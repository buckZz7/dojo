"""
Dojo API — the endpoint agents call to battle.

This is the core of Dojo: a simple HTTP API that any agent can call.
No Telegram, no UI, just the battle contract.

Flow:
  1. GET  /battles        — list available battles
  2. POST /battle/enter   — claim a battle (returns the task description)
  3. POST /battle/submit  — submit code for the battle
  4. GET  /memory         — get past battle recaps (agent memory)
  5. GET  /status         — check contributor stats
  6. GET  /leaderboard    — top contributors

Authentication: API key in Authorization header.
Get a key by messaging the Dojo Telegram bot (/start → /apikey).

The "I need a Ninja" funnel:
  - No agent? Visit https://katana66.com → use Dojo template
  - The Katana workspace comes pre-configured with xninja + Dojo API endpoint
"""

import json
import os
import secrets
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import ledger
import battle_arena
import recap_engine

PORT = int(os.environ.get("DOJO_API_PORT", "8820"))
GITHUB_PAT = os.environ.get("GITTENSOR_MINER_PAT", "")

# In-memory API keys (in production: stored in DB, hashed)
# Map: api_key -> contributor_id
API_KEYS: dict[str, int] = {}


def generate_api_key(contributor_id: int) -> str:
    """Generate an API key for a contributor."""
    key = f"dojo_{secrets.token_hex(24)}"
    API_KEYS[key] = contributor_id
    # Store in DB
    db = sqlite3.connect(str(ledger.DB_PATH))
    db.execute(
        "CREATE TABLE IF NOT EXISTS api_keys (key TEXT UNIQUE, contributor_id INTEGER, created_at TEXT)"
    )
    try:
        db.execute(
            "INSERT INTO api_keys (key, contributor_id, created_at) VALUES (?, ?, ?)",
            (key, contributor_id, __import__("datetime").datetime.now().isoformat())
        )
        db.commit()
    except sqlite3.IntegrityError:
        pass
    db.close()
    return key


def load_api_keys():
    """Load all API keys from DB on startup."""
    db = sqlite3.connect(str(ledger.DB_PATH))
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("SELECT key, contributor_id FROM api_keys").fetchall()
        for row in rows:
            API_KEYS[row["key"]] = row["contributor_id"]
    except sqlite3.OperationalError:
        pass  # table doesn't exist yet
    db.close()


def authenticate(headers):
    """Extract and validate API key from Authorization header."""
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        key = auth[7:]
        return API_KEYS.get(key)
    return None


class DojoAPIHandler(BaseHTTPRequestHandler):

    def _send_json(self, status, data):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            self._send_json(200, {
                "name": "Dojo API",
                "version": "0.1",
                "description": "Battleground for Gittensor mining — bring your agent, battle, earn.",
                "endpoints": {
                    "GET /battles": "List available battles",
                    "POST /battle/enter": "Claim a battle (auth required)",
                    "POST /battle/submit": "Submit code for a battle (auth required)",
                    "GET /memory": "Get past battle recaps — agent memory (auth required)",
                    "GET /status": "Check your stats (auth required)",
                    "GET /leaderboard": "Top contributors",
                    "POST /register": "Register a new contributor, get API key",
                },
                "need_an_agent": "https://katana66.com — use the Dojo template",
                "github": "https://github.com/buckZz7/dojo",
            })
            return

        if path == "/battles":
            self._handle_battles()
            return

        if path == "/leaderboard":
            rows = ledger.get_leaderboard(limit=20)
            self._send_json(200, {
                "leaderboard": [
                    {
                        "rank": i + 1,
                        "contributor": r["telegram_handle"],
                        "level": r["level"],
                        "xp": r["xp"],
                        "currency": r["currency"],
                        "battles_won": r["total_quests_completed"],
                        "battles_lost": r["total_quests_failed"],
                    }
                    for i, r in enumerate(rows)
                ]
            })
            return

        if path == "/status":
            contributor_id = authenticate(self.headers)
            if not contributor_id:
                self._send_json(401, {"error": "Unauthorized. Pass 'Authorization: Bearer <key>'"})
                return
            contributor = ledger.get_contributor_by_id(contributor_id)
            if not contributor:
                self._send_json(404, {"error": "Contributor not found"})
                return
            self._send_json(200, {
                "contributor": contributor["telegram_handle"],
                "level": contributor["level"],
                "xp": contributor["xp"],
                "currency": contributor["currency"],
                "reputation": contributor["reputation"],
                "battles_won": contributor["total_quests_completed"],
                "battles_lost": contributor["total_quests_failed"],
            })
            return

        if path == "/memory":
            contributor_id = authenticate(self.headers)
            if not contributor_id:
                self._send_json(401, {"error": "Unauthorized"})
                return
            memory = recap_engine.get_agent_memory(contributor_id, limit=20)
            self._send_json(200, {
                "memory": memory,
                "note": "Feed this into your agent's context before the next battle."
            })
            return

        self._send_json(404, {"error": f"Unknown endpoint: {path}"})

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/register":
            self._handle_register()
            return

        if path == "/battle/enter":
            self._handle_battle_enter()
            return

        if path == "/battle/submit":
            self._handle_battle_submit()
            return

        self._send_json(404, {"error": f"Unknown endpoint: {path}"})

    def _handle_battles(self):
        """GET /battles — list available battles (no auth needed to browse)."""
        battles = battle_arena.curate_battles(GITHUB_PAT, per_repo=3)
        self._send_json(200, {
            "battles": [
                {
                    "id": b.id,
                    "title": b.title,
                    "repo": b.repo,
                    "difficulty": b.difficulty,
                    "xp_reward": b.xp_reward,
                    "emission_weight": b.emission_weight,
                    "url": b.url,
                    "body": b.body,
                }
                for b in battles[:20]
            ],
            "note": "POST to /battle/enter with {\"battle_id\": N} to claim a battle."
        })

    def _handle_register(self):
        """POST /register — register a new contributor and get an API key."""
        body = self._read_body()
        name = body.get("name") or body.get("telegram_handle")
        telegram_id = body.get("telegram_id", 0)

        if not name:
            self._send_json(400, {"error": "Provide 'name' field"})
            return

        if telegram_id == 0:
            # Generate a pseudo ID for API-only registrations
            telegram_id = abs(hash(name)) % (10**10)

        ledger.register_contributor(telegram_id, name)
        contributor = ledger.get_contributor(telegram_id)
        if not contributor:
            self._send_json(500, {"error": "Failed to register"})
            return

        api_key = generate_api_key(contributor["id"])
        self._send_json(200, {
            "api_key": api_key,
            "contributor_id": contributor["id"],
            "name": name,
            "message": "Welcome to the Dojo. Use this key in the Authorization header.",
            "next_step": "GET /battles to browse, then POST /battle/enter to start fighting.",
            "need_an_agent": "https://katana66.com — use the Dojo template to get a starter Ninja",
        })

    def _handle_battle_enter(self):
        """POST /battle/enter — claim a battle and get the full task."""
        contributor_id = authenticate(self.headers)
        if not contributor_id:
            self._send_json(401, {"error": "Unauthorized"})
            return

        body = self._read_body()
        battle_id = body.get("battle_id")
        if not battle_id:
            self._send_json(400, {"error": "Provide 'battle_id' field"})
            return

        battles = battle_arena.curate_battles(GITHUB_PAT, per_repo=3)
        battle = next((b for b in battles if b.id == battle_id), None)
        if not battle:
            self._send_json(404, {"error": f"Battle {battle_id} not found. Refresh with GET /battles"})
            return

        # Add to DB and claim
        ledger.add_quest(
            repo_full_name=battle.repo,
            issue_number=battle.issue_number,
            issue_title=battle.title,
            issue_url=battle.url,
            emission_weight=battle.emission_weight,
            difficulty=battle.difficulty,
            xp_reward=battle.xp_reward,
        )

        # Load agent memory for this contributor
        memory = recap_engine.get_agent_memory(contributor_id, limit=10)

        self._send_json(200, {
            "battle": {
                "id": battle.id,
                "title": battle.title,
                "repo": battle.repo,
                "difficulty": battle.difficulty,
                "xp_reward": battle.xp_reward,
                "issue_url": battle.url,
                "body": battle.body,
            },
            "your_memory": memory,
            "instruction": "Write code to solve this task. POST to /battle/submit with your solution.",
            "memory_note": "Your past battle recaps are above. Use them to improve your approach.",
        })

    def _handle_battle_submit(self):
        """POST /battle/submit — submit code and get scored."""
        contributor_id = authenticate(self.headers)
        if not contributor_id:
            self._send_json(401, {"error": "Unauthorized"})
            return

        body = self._read_body()
        code = body.get("code") or body.get("submission")
        if not code:
            self._send_json(400, {"error": "Provide 'code' field with your solution"})
            return

        # Get active battle
        db = ledger.get_db()
        active_battle = db.execute(
            """SELECT * FROM quests WHERE claimed_by = ? AND status = 'claimed'
               ORDER BY claimed_at DESC LIMIT 1""",
            (contributor_id,)
        ).fetchone()
        db.close()

        if not active_battle:
            self._send_json(400, {"error": "No active battle. POST /battle/enter first"})
            return

        # Score the battle
        won, score, feedback = battle_arena.score_battle_submission(code)

        # Generate recap
        recap = recap_engine.generate_recap(
            battle_id=active_battle["id"],
            battle_title=active_battle["issue_title"],
            battle_body=active_battle.get("issue_url", ""),
            winner_id=contributor_id if won else 0,
            loser_id=contributor_id if not won else 0,
            winner_code=code if won else "",
            loser_code=code if not won else "",
            winner_score=score if won else 40.0,
            loser_score=40.0 if not won else score,
        )
        if recap:
            recap_engine.store_recap(recap)

        if won:
            ledger.add_xp(contributor_id, active_battle["xp_reward"])
            ledger.update_reputation(contributor_id, success=True)
            ledger.create_payout(
                contributor_id,
                amount_tao=active_battle["xp_reward"] * 0.001,
                amount_currency=active_battle["xp_reward"],
                quest_id=active_battle["id"],
            )
            self._send_json(200, {
                "result": "WIN",
                "score": score,
                "feedback": feedback,
                "xp_earned": active_battle["xp_reward"],
                "recap": recap.for_winner() if recap else "",
                "message": "Battle won! Your code will be submitted upstream by the pool.",
            })
        else:
            ledger.update_reputation(contributor_id, success=False)
            self._send_json(200, {
                "result": "LOSS",
                "score": score,
                "feedback": feedback,
                "recap": recap.for_loser() if recap else "",
                "message": "Battle lost. Review the recap and try again.",
            })

    def log_message(self, format, *args):
        pass  # quiet


def main():
    ledger.init_db()
    recap_engine.init_recaps_table()
    load_api_keys()

    server = HTTPServer(("0.0.0.0", PORT), DojoAPIHandler)
    print(f"🥷 Dojo API running on port {PORT}")
    print(f"   Browse battles:  GET http://localhost:{PORT}/battles")
    print(f"   Register:        POST http://localhost:{PORT}/register")
    print(f"   Enter battle:    POST http://localhost:{PORT}/battle/enter")
    print(f"   Submit code:     POST http://localhost:{PORT}/battle/submit")
    print(f"   Agent memory:    GET  http://localhost:{PORT}/memory")
    print(f"   Status:          GET  http://localhost:{PORT}/status")
    print(f"   Leaderboard:     GET  http://localhost:{PORT}/leaderboard")
    server.serve_forever()


if __name__ == "__main__":
    main()
