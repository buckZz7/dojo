"""
GitQuest Ledger — SQLite attribution tracking.

Tracks: contributors, quests, submissions, PRs, scores, payouts.
This is the off-chain accounting that maps pool earnings to individual contributors.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "gitquest.db"


def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS contributors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        telegram_handle TEXT NOT NULL,
        github_username TEXT,  -- their personal GitHub if they have one (optional)
        level INTEGER DEFAULT 1,
        xp REAL DEFAULT 0,
        currency REAL DEFAULT 0,  -- in-game currency backed by TAO
        reputation REAL DEFAULT 1.0,  -- multiplier, grows with good submissions
        joined_at TEXT NOT NULL,
        total_quests_completed INTEGER DEFAULT 0,
        total_quests_failed INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS quests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        repo_full_name TEXT NOT NULL,  -- e.g. "JSONbored/metagraphed"
        issue_number INTEGER NOT NULL,
        issue_title TEXT NOT NULL,
        issue_url TEXT NOT NULL,
        emission_weight REAL,  -- from gittensor.io repo ranking
        difficulty TEXT,  -- easy, medium, hard (heuristic from issue labels/body)
        xp_reward REAL,  -- how much XP this quest is worth
        status TEXT DEFAULT 'open',  -- open, claimed, in_review, submitted, merged, rejected, closed
        claimed_by INTEGER,  -- contributor id
        claimed_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (claimed_by) REFERENCES contributors(id)
    );

    CREATE TABLE IF NOT EXISTS submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        quest_id INTEGER NOT NULL,
        contributor_id INTEGER NOT NULL,
        code_diff TEXT,  -- the actual code submitted
        fork_branch TEXT,  -- branch name on pool's fork
        quality_gate_result TEXT,  -- approved, rejected, pending
        quality_gate_notes TEXT,  -- review feedback
        reviewed_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (quest_id) REFERENCES quests(id),
        FOREIGN KEY (contributor_id) REFERENCES contributors(id)
    );

    CREATE TABLE IF NOT EXISTS pull_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id INTEGER NOT NULL,
        upstream_repo TEXT NOT NULL,
        upstream_pr_number INTEGER,
        upstream_pr_url TEXT,
        pr_state TEXT,  -- open, merged, closed
        validator_score REAL,  -- score from Gittensor validators
        scored_at TEXT,
        merged_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (submission_id) REFERENCES submissions(id)
    );

    CREATE TABLE IF NOT EXISTS payouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contributor_id INTEGER NOT NULL,
        amount_tao REAL NOT NULL,
        amount_currency REAL NOT NULL,
        quest_id INTEGER,
        status TEXT DEFAULT 'pending',  -- pending, settled, failed
        settled_at TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (contributor_id) REFERENCES contributors(id),
        FOREIGN KEY (quest_id) REFERENCES quests(id)
    );

    CREATE TABLE IF NOT EXISTS pool_earnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scoring_round TEXT NOT NULL,  -- ISO timestamp of validator round
        total_alpha REAL NOT NULL,
        pool_fee REAL NOT NULL,  -- pool's cut
        contributor_share REAL NOT NULL,  -- what was distributed
        created_at TEXT NOT NULL
    );
    """)
    db.commit()
    db.close()


# --- Contributors ---

def register_contributor(telegram_id: int, telegram_handle: str):
    db = get_db()
    try:
        db.execute(
            "INSERT INTO contributors (telegram_id, telegram_handle, joined_at) VALUES (?, ?, ?)",
            (telegram_id, telegram_handle, datetime.now().isoformat())
        )
        db.commit()
    except sqlite3.IntegrityError:
        pass  # already exists
    finally:
        db.close()


def get_contributor(telegram_id: int):
    db = get_db()
    row = db.execute(
        "SELECT * FROM contributors WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    db.close()
    return row


def add_xp(contributor_id: int, amount: float):
    db = get_db()
    db.execute(
        "UPDATE contributors SET xp = xp + ?, currency = currency + ? WHERE id = ?",
        (amount, amount, contributor_id)
    )
    # Level up: every 100 XP = 1 level
    db.execute(
        """UPDATE contributors SET level = MAX(1, CAST(xp / 100 AS INTEGER) + 1)
           WHERE id = ?""",
        (contributor_id,)
    )
    db.commit()
    db.close()


def update_reputation(contributor_id: int, success: bool):
    """Reputation goes up on success, down on failure. Clamped to [0.1, 5.0]."""
    db = get_db()
    delta = 0.05 if success else -0.15
    db.execute(
        """UPDATE contributors
           SET reputation = MAX(0.1, MIN(5.0, reputation + ?)),
               total_quests_completed = total_quests_completed + ?,
               total_quests_failed = total_quests_failed + ?
           WHERE id = ?""",
        (delta, 1 if success else 0, 0 if success else 1, contributor_id)
    )
    db.commit()
    db.close()


# --- Quests ---

def add_quest(repo_full_name: str, issue_number: int, issue_title: str,
              issue_url: str, emission_weight: float = 0, difficulty: str = None,
              xp_reward: float = 10.0):
    db = get_db()
    db.execute(
        """INSERT INTO quests (repo_full_name, issue_number, issue_title, issue_url,
                               emission_weight, difficulty, xp_reward, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (repo_full_name, issue_number, issue_title, issue_url,
         emission_weight, difficulty, xp_reward, datetime.now().isoformat())
    )
    db.commit()
    db.close()


def get_open_quests(limit: int = 10):
    db = get_db()
    rows = db.execute(
        """SELECT * FROM quests WHERE status = 'open'
           ORDER BY emission_weight DESC, xp_reward DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    db.close()
    return rows


def claim_quest(quest_id: int, contributor_id: int):
    db = get_db()
    db.execute(
        """UPDATE quests SET status = 'claimed', claimed_by = ?, claimed_at = ?
           WHERE id = ? AND status = 'open'""",
        (contributor_id, datetime.now().isoformat(), quest_id)
    )
    db.commit()
    db.close()


# --- Submissions & PRs ---

def record_submission(quest_id: int, contributor_id: int, code_diff: str, fork_branch: str):
    db = get_db()
    db.execute(
        """INSERT INTO submissions (quest_id, contributor_id, code_diff, fork_branch,
                                     quality_gate_result, created_at)
           VALUES (?, ?, ?, ?, 'pending', ?)""",
        (quest_id, contributor_id, code_diff, fork_branch, datetime.now().isoformat())
    )
    db.commit()
    db.close()


def record_pr(submission_id: int, upstream_repo: str, pr_number: int = None, pr_url: str = None):
    db = get_db()
    db.execute(
        """INSERT INTO pull_requests (submission_id, upstream_repo, upstream_pr_number,
                                       upstream_pr_url, pr_state, created_at)
           VALUES (?, ?, ?, ?, 'open', ?)""",
        (submission_id, upstream_repo, pr_number, pr_url, datetime.now().isoformat())
    )
    db.commit()
    db.close()


def record_pr_merge(pr_id: int, validator_score: float):
    db = get_db()
    db.execute(
        """UPDATE pull_requests SET pr_state = 'merged', validator_score = ?,
                                     merged_at = ?, scored_at = ?
           WHERE id = ?""",
        (validator_score, datetime.now().isoformat(), datetime.now().isoformat(), pr_id)
    )
    db.commit()
    db.close()


# --- Leaderboard ---

def get_leaderboard(limit: int = 10):
    db = get_db()
    rows = db.execute(
        """SELECT telegram_handle, level, xp, currency, reputation,
                  total_quests_completed, total_quests_failed
           FROM contributors ORDER BY xp DESC LIMIT ?""",
        (limit,)
    ).fetchall()
    db.close()
    return rows


# --- Payouts ---

def create_payout(contributor_id: int, amount_tao: float, amount_currency: float, quest_id: int = None):
    db = get_db()
    db.execute(
        """INSERT INTO payouts (contributor_id, amount_tao, amount_currency, quest_id, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (contributor_id, amount_tao, amount_currency, quest_id, datetime.now().isoformat())
    )
    db.commit()
    db.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized at", DB_PATH)
