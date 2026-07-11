"""
Code Dojo Telegram Bot — the contributor interface.

Contributors connect via Telegram. This is their account, settings, and
notification channel. Their AI agent communicates with Code Dojo via the
HTTP API (see api.py and llms.txt).

Commands:
  /start     — Register your account
  /bounties  — Browse available challenges
  /bounty <N> — Enter a challenge
  /submit    — Submit your code
  /status    — Check your rank, XP, level
  /arena     — Live leaderboard
  /cashout   — Withdraw earnings for TAO
"""

import os
import logging
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import ledger
import battle_arena
import recap_engine
from quality_gate import review_submission

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GITHUB_PAT = os.environ.get("GITTENSOR_MINER_PAT", "")

# In-memory cache of current battles
current_battles: list[battle_arena.Battle] = []


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enter the Dojo."""
    user = update.effective_user
    ledger.init_db()
    ledger.register_contributor(user.id, user.username or user.first_name)
    contributor = ledger.get_contributor(user.id)

    await update.message.reply_text(
        f"🥷 **Welcome to the Dojo**\n\n"
        f"Your AI is registered: **{user.username or user.first_name}**\n"
        f"Rank: {contributor['level']} | XP: {contributor['xp']} | 💰: {contributor['currency']}\n\n"
        f"**How it works:**\n"
        f"1. Browse battles with /battles\n"
        f"2. Enter a battle with /battle <N>\n"
        f"3. Your AI writes code to solve it\n"
        f"4. Submit with /submit\n"
        f"5. Win → earn XP + currency → level up\n\n"
        f"⚔️ **Commands:**\n"
        f"/battles — Available battles\n"
        f"/battle <N> — Enter battle\n"
        f"/submit — Submit your solution\n"
        f"/status — Your agent's stats\n"
        f"/arena — Leaderboard\n"
        f"/cashout — Withdraw earnings\n\n"
        f"Train well. The battles are real."
    )


async def battles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available battles."""
    global current_battles

    await update.message.reply_text("⚔️ Scanning for battles...")

    try:
        current_battles = battle_arena.curate_battles(GITHUB_PAT, per_repo=3)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to fetch battles: {e}")
        return

    if not current_battles:
        await update.message.reply_text("No battles available right now. Check back later.")
        return

    lines = ["🥋 **Available Battles**\n"]
    for b in current_battles[:10]:
        lines.append(battle_arena.format_battle_for_telegram(b))
        lines.append("")

    lines.append("Enter a battle: /battle <N> (e.g. /battle 3)")
    await update.message.reply_text("\n".join(lines))


async def battle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Enter a battle by number."""
    if not context.args:
        await update.message.reply_text("Usage: /battle <number> (e.g. /battle 3)")
        return

    try:
        battle_num = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Battle number must be a number. E.g. /battle 3")
        return

    if not current_battles or battle_num < 1 or battle_num > len(current_battles):
        await update.message.reply_text("Invalid battle number. Run /battles first.")
        return

    b = current_battles[battle_num - 1]
    user = update.effective_user
    contributor = ledger.get_contributor(user.id)

    if not contributor:
        await update.message.reply_text("Run /start first to enter the Dojo.")
        return

    ledger.add_quest(
        repo_full_name=b.repo,
        issue_number=b.issue_number,
        issue_title=b.title,
        issue_url=b.url,
        emission_weight=b.emission_weight,
        difficulty=b.difficulty,
        xp_reward=b.xp_reward,
    )

    belt_emoji = {"white": "🥋", "yellow": "🟡", "black": "🥷"}
    emoji = belt_emoji.get(b.difficulty, "⚔️")

    await update.message.reply_text(
        f"{emoji} **Battle Entered!**\n\n"
        f"⚔️ {b.title}\n"
        f"📦 {b.repo}\n"
        f"🎯 {b.difficulty.upper()} belt | ⚡ {b.xp_reward} XP\n\n"
        f"**The Challenge:**\n{b.body}\n\n"
        f"Send your AI to solve it. Use /submit when ready.\n"
        f"Win → earn XP + currency. Lose → train and retry."
    )


async def submit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Submit code for a battle."""
    user = update.effective_user
    contributor = ledger.get_contributor(user.id)

    if not contributor:
        await update.message.reply_text("Run /start first.")
        return

    db = ledger.get_db()
    active_battle = db.execute(
        """SELECT * FROM quests WHERE claimed_by = ? AND status = 'claimed'
           ORDER BY claimed_at DESC LIMIT 1""",
        (contributor["id"],)
    ).fetchone()
    db.close()

    if not active_battle:
        await update.message.reply_text("You're not in a battle. Run /battles and /battle <N> first.")
        return

    code = " ".join(context.args) if context.args else ""
    if not code and update.message.reply_to_message:
        code = update.message.reply_to_message.text or ""

    if not code:
        await update.message.reply_text(
            "Submit your code: /submit <code or diff>\n"
            "Or reply to a message containing your code with /submit"
        )
        return

    # Score the battle
    won, score, feedback = battle_arena.score_battle_submission(code)

    if won:
        # Award XP and update reputation
        ledger.add_xp(contributor["id"], active_battle["xp_reward"])
        ledger.update_reputation(contributor["id"], success=True)
        ledger.create_payout(
            contributor["id"],
            amount_tao=active_battle["xp_reward"] * 0.001,  # placeholder conversion
            amount_currency=active_battle["xp_reward"],
            quest_id=active_battle["id"],
        )

        updated = ledger.get_contributor(user.id)
        await update.message.reply_text(
            f"🏆 **BATTLE WON!**\n\n"
            f"Score: {score:.0f}\n"
            f"+{active_battle['xp_reward']} XP\n"
            f"+{active_battle['xp_reward']} 💰\n\n"
            f"Level: {updated['level']} | Total XP: {updated['xp']}\n"
            f"Reputation: {updated['reputation']:.2f}\n\n"
            f"Your code is being submitted upstream. "
            f"You'll be notified when the PR merges and earnings settle."
        )

        # Generate battle recap for learning
        recap = recap_engine.generate_recap(
            battle_id=active_battle["id"],
            battle_title=active_battle["issue_title"],
            battle_body=active_battle.get("issue_url", ""),
            winner_id=contributor["id"],
            loser_id=0,  # solo battle — no opponent
            winner_code=code,
            loser_code="",
            winner_score=score,
            loser_score=0,
        )
        if recap:
            recap_engine.store_recap(recap)
            # Notify the contributor with their recap
            await update.message.reply_text(
                f"📝 **Battle Recap**\n\n"
                f"{recap.for_winner()}\n"
                f"Your agent has learned from this challenge. "
                f"These insights will inform your next fight."
            )
    else:
        ledger.update_reputation(contributor["id"], success=False)

        # Generate battle recap — losses are where the most learning happens
        recap = recap_engine.generate_recap(
            battle_id=active_battle["id"],
            battle_title=active_battle["issue_title"],
            battle_body=active_battle.get("issue_url", ""),
            winner_id=0,  # solo — no opponent won
            loser_id=contributor["id"],
            winner_code="",
            loser_code=code,
            winner_score=40.0,  # threshold
            loser_score=score,
        )
        if recap:
            recap_engine.store_recap(recap)

        await update.message.reply_text(
            f"💀 **BATTLE LOST**\n\n"
            f"Score: {score:.0f}\n"
            f"Feedback: {feedback}\n\n"
            f"{'📝 **Battle Recap:**\\n' + recap.for_loser() + '\\n' if recap else ''}"
            f"No XP lost, but your reputation took a small hit.\n"
            f"Your agent has learned from this defeat. Train and try again: /submit"
        )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show agent stats."""
    user = update.effective_user
    contributor = ledger.get_contributor(user.id)

    if not contributor:
        await update.message.reply_text("Run /start first.")
        return

    belt = "🥋 White" if contributor["level"] < 4 else "🟡 Yellow" if contributor["level"] < 10 else "🥷 Black"

    await update.message.reply_text(
        f"🥷 **Your Agent**\n\n"
        f"Name: {contributor['telegram_handle']}\n"
        f"Belt: {belt} (Level {contributor['level']})\n"
        f"XP: {contributor['xp']} ⚡\n"
        f"Currency: {contributor['currency']} 💰\n"
        f"Reputation: {contributor['reputation']:.2f} ⭐\n"
        f"Battles won: {contributor['total_quests_completed']} 🏆\n"
        f"Battles lost: {contributor['total_quests_failed']} 💀\n\n"
        f"{'🔥 Black belt — respect.' if contributor['level'] >= 10 else 'Keep winning battles to level up!'}"
    )


async def arena(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the arena leaderboard."""
    rows = ledger.get_leaderboard(limit=10)

    if not rows:
        await update.message.reply_text("The Dojo is empty. Be the first to enter!")
        return

    lines = ["⚔️ **Dojo Arena — Leaderboard**\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(
            f"{medal} {row['telegram_handle']} — "
            f"Lv{row['level']} | {row['xp']:.0f} XP | "
            f"{row['total_quests_completed']}🏆"
        )

    await update.message.reply_text("\n".join(lines))


async def cashout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Withdraw currency for TAO."""
    user = update.effective_user
    contributor = ledger.get_contributor(user.id)

    if not contributor:
        await update.message.reply_text("Run /start first.")
        return

    if contributor["currency"] <= 0:
        await update.message.reply_text("You have no earnings. Win some battles first! ⚔️")
        return

    await update.message.reply_text(
        f"💰 **Cash Out**\n\n"
        f"Your balance: {contributor['currency']} Dojo currency\n"
        f"≈ {contributor['currency'] * 0.8:.4f} TAO (after 20% Dojo fee)\n\n"
        f"Provide your Bittensor coldkey address to receive TAO.\n"
        f"(In production, this triggers an on-chain transfer.)"
    )


def main():
    if not BOT_TOKEN:
        print("ERROR: Set TELEGRAM_BOT_TOKEN environment variable")
        return

    ledger.init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("battles", battles))
    app.add_handler(CommandHandler("battle", battle))
    app.add_handler(CommandHandler("submit", submit))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("arena", arena))
    app.add_handler(CommandHandler("cashout", cashout))

    logger.info("🥷 Dojo bot starting...")
    app.run_polling(allow_updates=True)


if __name__ == "__main__":
    main()
