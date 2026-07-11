"""
Code Dojo Challenge Arena — curates coding challenges from recognized Gittensor repos.

Real coding tasks from real repos, scored by competition.
Challenges are shuffled for unpredictability — prevents overfitting.
"""

import re
from dataclasses import dataclass, field
from typing import Optional
import random

import requests

# Recognized repos with their emission weights (from gittensor.io, July 10 2026)
RECOGNIZED_REPOS = [
    {"name": "gittensor-ai-lab/sparkinfer", "weight": 0.35, "prs": 47},
    {"name": "JSONbored/metagraphed", "weight": 0.22, "prs": 1255},
    {"name": "JSONbored/gittensory", "weight": 0.10, "prs": 1003},
    {"name": "gittensor-vanguard/vanguarstew", "weight": 0.10, "prs": 398},
    {"name": "Autovara/kata", "weight": 0.08, "prs": 3},
    {"name": "entrius/gittensor", "weight": 0.05, "prs": 310},
    {"name": "vouchdev/vouch", "weight": 0.02, "prs": 101},
    {"name": "Geniepod/genie-claw", "weight": 0.02, "prs": 216},
    {"name": "phase-rs/phase", "weight": 0.01, "prs": 1499},
    {"name": "James-CUDA/Gittensor-TinyRouter", "weight": 0.01, "prs": 42},
]

GITHUB_API = "https://api.github.com"


@dataclass
class Battle:
    """A coding battle — a real issue from a recognized Gittensor repo."""
    id: int
    repo: str
    issue_number: int
    title: str
    url: str
    emission_weight: float
    difficulty: str  # white, yellow, black belt
    xp_reward: float
    body: str = ""
    labels: list = field(default_factory=list)
    battle_type: str = "solo"  # solo (vs threshold), duel (1v1), clan (team)


def fetch_open_issues(repo_full_name: str, github_pat: str, limit: int = 20) -> list[dict]:
    """Fetch open issues from a repo suitable for battles."""
    headers = {
        "Authorization": f"token {github_pat}",
        "Accept": "application/vnd.github+json",
    }
    url = f"{GITHUB_API}/repos/{repo_full_name}/issues"
    params = {"state": "open", "per_page": limit, "sort": "created", "direction": "desc"}
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    issues = resp.json()
    return [i for i in issues if "pull_request" not in i]


def classify_belt(issue: dict) -> tuple[str, float]:
    """Classify battle difficulty as belt color + XP reward."""
    labels = [l["name"].lower() for l in issue.get("labels", [])]
    body = issue.get("body") or ""
    body_len = len(body)

    # Explicit labels
    if any("good first issue" in l for l in labels):
        return "white", 10.0
    if any("help wanted" in l for l in labels):
        if body_len < 500:
            return "white", 10.0
        elif body_len < 2000:
            return "yellow", 25.0
        else:
            return "black", 50.0
    if any("enhancement" in l or "feature" in l for l in labels):
        return "black", 50.0
    if any("bug" in l for l in labels):
        return "yellow", 25.0

    # Body length heuristic
    if body_len < 200:
        return "white", 10.0
    elif body_len < 1000:
        return "yellow", 25.0
    else:
        return "black", 50.0


def curate_battles(github_pat: str, repos: list[dict] = None, per_repo: int = 5,
                   battle_type: str = "solo") -> list[Battle]:
    """Fetch issues from recognized repos and convert to battles.

    Shuffles order so battles are never predictable (anti-overfit, inspired by SN66).
    """
    repos = repos or RECOGNIZED_REPOS
    battles = []
    battle_id = 0

    for repo in repos:
        try:
            issues = fetch_open_issues(repo["name"], github_pat, limit=per_repo)
        except Exception:
            continue

        for issue in issues:
            body = issue.get("body") or ""
            if not body.strip():
                continue

            battle_id += 1
            belt, xp = classify_belt(issue)
            battles.append(Battle(
                id=battle_id,
                repo=repo["name"],
                issue_number=issue["number"],
                title=issue["title"],
                url=issue["html_url"],
                emission_weight=repo["weight"],
                difficulty=belt,
                xp_reward=xp,
                body=body[:500],
                labels=[l["name"] for l in issue.get("labels", [])],
                battle_type=battle_type,
            ))

    # Shuffle for unpredictability (SN66 principle: never reveal tasks in advance)
    random.shuffle(battles)
    # But sort by value within shuffled set for display
    battles.sort(key=lambda b: b.emission_weight * b.xp_reward, reverse=True)
    return battles


def score_battle_submission(submission: str, opponent_submission: str = None) -> tuple[bool, float, str]:
    """Score a battle submission.

    Solo mode: score against a quality threshold.
    Duel mode: score against opponent's submission (head-to-head).

    Returns: (won, score, feedback)

    In production this would use:
    - Changed-line similarity (like SN66)
    - LLM judge scoring
    - Test suite pass/fail
    """
    if not submission.strip():
        return False, 0.0, "Empty submission — no code provided."

    # Basic quality signals
    score = 0.0
    feedback_parts = []

    # Code presence
    if len(submission) > 50:
        score += 30
    else:
        feedback_parts.append("Submission too short to be meaningful.")

    # Structural indicators
    if any(kw in submission for kw in ["def ", "class ", "function ", "const ", "impl "]):
        score += 20
    else:
        feedback_parts.append("No structural code definitions found.")

    # Red flags
    red_flags = []
    if "TODO" in submission or "FIXME" in submission:
        red_flags.append("Contains TODO/FIXME")
    if "console.log" in submission or "print(" in submission:
        red_flags.append("Debug statements present")
    if "password" in submission.lower() or "secret" in submission.lower():
        red_flags.append("Potential secret leak")

    if red_flags:
        score -= 20
        feedback_parts.extend(red_flags)

    # Duel scoring (head-to-head)
    if opponent_submission:
        opponent_score = 30 if len(opponent_submission) > 50 else 0
        opponent_score += 20 if any(kw in opponent_submission for kw in ["def ", "class ", "function "]) else 0
        won = score > opponent_score
        feedback = f"Your score: {score:.0f} vs opponent: {opponent_score:.0f}"
        return won, score, feedback

    # Solo scoring (threshold)
    threshold = 40.0
    won = score >= threshold
    if won:
        feedback = f"Battle won! Score: {score:.0f}/{threshold:.0f}"
    else:
        feedback = f"Battle lost. Score: {score:.0f}/{threshold:.0f}. " + "; ".join(feedback_parts)

    return won, score, feedback


def format_battle_for_telegram(battle: Battle) -> str:
    """Format a battle for display in Telegram."""
    belt_emoji = {"white": "🥋", "yellow": "🟡", "black": "🥷"}
    emoji = belt_emoji.get(battle.difficulty, "⚔️")
    return (
        f"**Battle #{battle.id}** {emoji} {battle.difficulty.upper()} BELT\n"
        f"⚔️ {battle.title}\n"
        f"📦 {battle.repo}\n"
        f"⚡ XP: {battle.xp_reward} | Weight: {battle.emission_weight}\n"
        f"━━━━━━━━━━━━━━━━"
    )
