"""
Code Dojo Leaderboard — lightweight web endpoint for the leaderboard.

Serves a simple HTML page at http://localhost:PORT/ showing
top contributors ranked by XP, earnings, and level.
"""

import os
from http.server import HTTPServer, BaseHTTPRequestHandler

import ledger

PORT = int(os.environ.get("LEADERBOARD_PORT", "8819"))


class LeaderboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return

        rows = ledger.get_leaderboard(limit=50)

        row_html = ""
        medals = ["🥇", "🥈", "🥉"]
        for i, row in enumerate(rows):
            medal = medals[i] if i < 3 else f"#{i+1}"
            row_html += f"""
            <tr>
                <td>{medal}</td>
                <td>{row['telegram_handle']}</td>
                <td>{row['level']}</td>
                <td>{row['xp']:.0f}</td>
                <td>{row['currency']:.2f}</td>
                <td>{row['reputation']:.2f}</td>
                <td>{row['total_quests_completed']}</td>
                <td>{row['total_quests_failed']}</td>
            </tr>"""

        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Dojo Arena — Leaderboard</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; max-width: 800px; margin: 40px auto; }}
        h1 {{ color: #58a6ff; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #21262d; }}
        th {{ color: #8b949e; font-size: 12px; text-transform: uppercase; }}
        tr:hover {{ background: #161b22; }}
        a {{ color: #58a6ff; text-decoration: none; }}
    </style>
</head>
<body>
    <h1>🥷 Dojo Arena</h1>
    <p>Battleground for <a href="https://gittensor.io">Gittensor</a> (Bittensor SN74)</p>
    <table>
        <tr><th>Rank</th><th>Contributor</th><th>Level</th><th>XP</th><th>Currency</th><th>Reputation</th><th>Completed</th><th>Failed</th></tr>
        {row_html}
    </table>
    <p style="color: #484f58; margin-top: 40px;">Dojo Mining Pool — Train. Battle. Earn.</p>
</body>
</html>"""

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass  # quiet


def main():
    ledger.init_db()
    server = HTTPServer(("0.0.0.0", PORT), LeaderboardHandler)
    print(f"Dojo Arena running at http://localhost:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
