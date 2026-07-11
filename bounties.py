"""
Code Dojo Bounty System — pool posts bounties, agents compete, Code Dojo evaluates and picks winner.

Bounty lifecycle:
  open → accepting submissions → closed (winner selected) → paid

Rules (v0.1):
- Pool funds bounties from own pocket (fixed amount)
- Code Dojo's evaluation agent picks the winner (not the pool)
- Multiple agents can submit on the same bounty
- All submissions are timestamped and publicly visible (fraud prevention)
- Winner gets paid on selection, not on upstream merge
- Pool controls close trigger: hours, submission count, or manual
"""

import sqlite3
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

DB_PATH = Path(__file__).parent / "dojo.db"


@dataclass
class Bounty:
    id: int
    title: str
    description: str
    repo: str  # target Gittensor repo
    issue_url: str  # GitHub issue being solved
    amount: float  # bounty payout in USD (pool's pocket)
    close_trigger: str  # "manual", "hours", "submissions"
    close_value: Optional[int]  # hours count or submission count
    created_at: str
    closed_at: Optional[str] = None
    winner_id: Optional[int] = None
    status: str = "open"  # open, closed


@dataclass
class Submission:
    id: int
    bounty_id: int
    contributor_id: int
    code: str
    created_at: str
    is_winner: bool = False


def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_bounties():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS bounties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        repo TEXT NOT NULL,
        issue_url TEXT,
        amount REAL NOT NULL,
        close_trigger TEXT DEFAULT 'manual',
        close_value INTEGER,
        status TEXT DEFAULT 'open',
        winner_id INTEGER,
        created_at TEXT NOT NULL,
        closed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS bounty_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bounty_id INTEGER NOT NULL,
        contributor_id INTEGER NOT NULL,
        code TEXT NOT NULL,
        is_winner INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (bounty_id) REFERENCES bounties(id),
        FOREIGN KEY (contributor_id) REFERENCES contributors(id)
    );
    """)
    db.commit()
    db.close()


# --- Pool operations ---

def post_bounty(
    title: str,
    description: str,
    repo: str,
    amount: float,
    issue_url: str = "",
    close_trigger: str = "manual",
    close_value: int = None,
) -> int:
    """Pool posts a new bounty. Returns bounty ID."""
    db = get_db()
    cursor = db.execute(
        """INSERT INTO bounties (title, description, repo, issue_url, amount,
                                  close_trigger, close_value, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (title, description, repo, issue_url, amount,
         close_trigger, close_value, datetime.now().isoformat())
    )
    bounty_id = cursor.lastrowid
    db.commit()
    db.close()
    return bounty_id


def get_open_bounties() -> list[dict]:
    """Get all open bounties."""
    db = get_db()
    rows = db.execute(
        """SELECT b.*,
                  (SELECT COUNT(*) FROM bounty_submissions bs WHERE bs.bounty_id = b.id) as submission_count
           FROM bounties b WHERE b.status = 'open'
           ORDER BY b.amount DESC"""
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_bounty(bounty_id: int) -> Optional[dict]:
    db = get_db()
    row = db.execute("SELECT * FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
    db.close()
    return dict(row) if row else None


def close_bounty(bounty_id: int, winner_submission_id: int) -> dict:
    """Pool closes a bounty and selects the winning submission.

    No "no winner" option — pool must always pick.
    """
    db = get_db()

    # Mark the winning submission
    db.execute(
        "UPDATE bounty_submissions SET is_winner = 1 WHERE id = ?",
        (winner_submission_id,)
    )

    # Get the contributor who won
    sub = db.execute(
        "SELECT contributor_id FROM bounty_submissions WHERE id = ?",
        (winner_submission_id,)
    ).fetchone()
    winner_id = sub["contributor_id"] if sub else None

    # Close the bounty
    db.execute(
        """UPDATE bounties SET status = 'closed', winner_id = ?,
                               closed_at = ?
           WHERE id = ?""",
        (winner_id, datetime.now().isoformat(), bounty_id)
    )
    db.commit()
    db.close()

    return {"bounty_id": bounty_id, "winner_id": winner_id, "winner_submission_id": winner_submission_id}


# --- Contributor operations ---

def submit_to_bounty(bounty_id: int, contributor_id: int, code: str) -> int:
    """An agent submits code for a bounty. Returns submission ID.

    All submissions are timestamped — this is the fraud prevention layer.
    """
    db = get_db()
    cursor = db.execute(
        """INSERT INTO bounty_submissions (bounty_id, contributor_id, code, created_at)
           VALUES (?, ?, ?, ?)""",
        (bounty_id, contributor_id, code, datetime.now().isoformat())
    )
    submission_id = cursor.lastrowid
    db.commit()
    db.close()

    # Check if this triggers auto-close
    _check_auto_close(bounty_id)
    return submission_id


def get_submissions(bounty_id: int) -> list[dict]:
    """Get all submissions for a bounty — publicly visible (fraud prevention)."""
    db = get_db()
    rows = db.execute(
        """SELECT bs.*, c.telegram_handle
           FROM bounty_submissions bs
           JOIN contributors c ON bs.contributor_id = c.id
           WHERE bs.bounty_id = ?
           ORDER BY bs.created_at ASC""",
        (bounty_id,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_my_submissions(contributor_id: int) -> list[dict]:
    """Get a contributor's submissions across all bounties."""
    db = get_db()
    rows = db.execute(
        """SELECT bs.*, b.title, b.amount, b.status as bounty_status
           FROM bounty_submissions bs
           JOIN bounties b ON bs.bounty_id = b.id
           WHERE bs.contributor_id = ?
           ORDER BY bs.created_at DESC""",
        (contributor_id,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


# --- Auto-close logic ---

def _check_auto_close(bounty_id: int):
    """Check if a bounty should auto-close based on its trigger."""
    bounty = get_bounty(bounty_id)
    if not bounty or bounty["status"] != "open":
        return

    if bounty["close_trigger"] == "submissions":
        subs = get_submissions(bounty_id)
        if len(subs) >= bounty["close_value"]:
            # Auto-close after N submissions — but pool still needs to pick winner
            # Just mark as "pending_selection" so pool knows to review
            db = get_db()
            db.execute(
                "UPDATE bounties SET status = 'pending_selection' WHERE id = ?",
                (bounty_id,)
            )
            db.commit()
            db.close()

    elif bounty["close_trigger"] == "hours":
        created = datetime.fromisoformat(bounty["created_at"])
        if datetime.now() > created + timedelta(hours=bounty["close_value"]):
            db = get_db()
            db.execute(
                "UPDATE bounties SET status = 'pending_selection' WHERE id = ?",
                (bounty_id,)
            )
            db.commit()
            db.close()


def get_pending_selection() -> list[dict]:
    """Get bounties waiting for pool to pick a winner."""
    db = get_db()
    rows = db.execute(
        """SELECT b.*,
                  (SELECT COUNT(*) FROM bounty_submissions bs WHERE bs.bounty_id = b.id) as submission_count
           FROM bounties b WHERE b.status = 'pending_selection'
           ORDER BY b.closed_at DESC"""
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


# --- Payout ---

def get_bounty_payouts(contributor_id: int) -> list[dict]:
    """Get bounties a contributor has won."""
    db = get_db()
    rows = db.execute(
        """SELECT b.title, b.amount, b.closed_at, b.repo
           FROM bounties b WHERE b.winner_id = ?
           ORDER BY b.closed_at DESC""",
        (contributor_id,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_total_earned(contributor_id: int) -> float:
    """Total bounty earnings for a contributor."""
    db = get_db()
    row = db.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM bounties WHERE winner_id = ?",
        (contributor_id,)
    ).fetchone()
    db.close()
    return row["total"]


if __name__ == "__main__":
    init_bounties()
    print("Bounty system initialized at", DB_PATH)
