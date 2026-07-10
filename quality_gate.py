"""
GitQuest Quality Gate — code review before promoting a submission upstream.

This is the pool's credibility shield. Every submission from a contributor
is reviewed here before it gets opened as a PR on the upstream repo.

Gate strictness scales with contributor level:
  - Level 1-3 (new): strict — full diff review, must pass all checks
  - Level 4-9 (mid): moderate — spot checks + CI must pass
  - Level 10+ (veteran): light — CI must pass, spot review only

Rejected submissions die at the fork. They never reach upstream and
never poison the pool's credibility ratio.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ReviewResult:
    approved: bool
    notes: str
    confidence: float  # 0.0 to 1.0


def review_submission(
    code_diff: str,
    quest_body: str,
    contributor_level: int,
    repo_full_name: str,
    fork_branch: str,
) -> ReviewResult:
    """Review a code submission before promoting it upstream.

    In production this would:
    1. Run the repo's test suite against the fork branch
    2. Use an LLM to review the diff against the issue requirements
    3. Check for common red flags (secrets, debug code, unrelated changes)

    For now this is a stub that returns a placeholder result.
    """
    # Basic checks anyone can do
    red_flags = []
    if "TODO" in code_diff or "FIXME" in code_diff:
        red_flags.append("Contains TODO/FIXME — resolve before submitting")
    if "console.log" in code_diff or "print(" in code_diff:
        red_flags.append("Contains debug print statements")
    if "password" in code_diff.lower() or "secret" in code_diff.lower():
        red_flags.append("Potential secret in diff — security review needed")

    if red_flags:
        return ReviewResult(
            approved=False,
            notes="; ".join(red_flags),
            confidence=0.9,
        )

    # Gate strictness based on contributor level
    if contributor_level <= 3:
        # New contributors: strict
        return ReviewResult(
            approved=False,
            notes="New contributor submission — requires manual review. "
                  "This stub would trigger a full LLM code review + test run.",
            confidence=0.0,
        )
    elif contributor_level <= 9:
        # Mid-level: moderate
        return ReviewResult(
            approved=False,
            notes="Mid-level contributor — requires CI pass + spot review. "
                  "This stub would run tests and do a lighter LLM review.",
            confidence=0.0,
        )
    else:
        # Veteran: light
        return ReviewResult(
            approved=True,
            notes="Veteran contributor — auto-approved pending CI. "
                  "In production, CI must still pass before upstream PR opens.",
            confidence=0.7,
        )
