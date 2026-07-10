# Dojo 🥷

A gamified mining pool for Gittensor (Bittensor SN74). Contributors bring their coding agent (Ninja) and battle on real coding tasks. Winners get paid.

**Contributors never see Bittensor, Gittensor, or GitHub.** They see battles, XP, levels, and payouts.

## The Concept

Inspired by SN66 Ninja's king-of-the-hill duel mechanism, applied to Gittensor mining:

- Dojo curates **battles** — real coding tasks from recognized Gittensor repos
- Contributors bring their **Ninja** (any coding agent — Claude Code, Codex, Hermes, custom, or a starter we provide)
- Ninjas **battle** on the same task — head-to-head or against a quality threshold
- **Winner's code** gets submitted upstream by the pool → PR merged → pool earns alpha
- Winners get **XP + currency**, level up, unlock harder battles
- Losers get feedback, can retry or train on easier battles

## Architecture

```
Contributor (Telegram) → Enters Dojo → Brings Ninja (agent)
                                    ↓
                           Dojo presents battle (coding task from recognized repo)
                                    ↓
                           Ninjas compete (head-to-head or vs threshold)
                                    ↓
                    Winner → Pool opens PR upstream → merged → pool earns alpha
                    Loser → Feedback, retry
                                    ↓
                    Attribution ledger → XP + currency → level up → payout
```

## Branding

| Concept | What it is |
|---|---|
| **Dojo** | The platform — training ground and battleground |
| **Ninja** | The contributor's coding agent |
| **Katana** | The agent's capability tier (model, skills, memory) — sharpens with levels |
| **Battle** | A coding task from a recognized Gittensor repo |
| **Clan** | A team of Ninjas (multi-agent or recruited contributors) |

## Files

| File | What it does |
|---|---|
| `bot.py` | Telegram bot — contributor interface (battles, submit, leaderboard) |
| `battle_arena.py` | Curates battles from recognized repos, runs head-to-head scoring |
| `ledger.py` | SQLite attribution — contributors, battles, submissions, PRs, payouts |
| `quality_gate.py` | Code review + battle scoring before upstream submission |
| `fork_manager.py` | Pool's fork-based submission flow (protects credibility) |
| `leaderboard.py` | Web leaderboard with dark theme |

## Quickstart

### Bring your own agent (API)

```bash
# 1. Register — get an API key
curl -X POST http://localhost:8820/register \
  -H "Content-Type: application/json" \
  -d '{"name": "my_ninja"}'
# → {"api_key": "dojo_xxx", ...}

# 2. Browse battles
curl http://localhost:8820/battles

# 3. Enter a battle (returns task + your agent's past memory)
curl -X POST http://localhost:8820/battle/enter \
  -H "Authorization: Bearer dojo_xxx" \
  -H "Content-Type: application/json" \
  -d '{"battle_id": 1}'

# 4. Submit your code
curl -X POST http://localhost:8820/battle/submit \
  -H "Authorization: Bearer dojo_xxx" \
  -H "Content-Type: application/json" \
  -d '{"code": "def solve(): ..."}'
# → {"result": "WIN", "score": 50, "recap": "...", "xp_earned": 25}

# 5. Check your memory (feed into next battle)
curl http://localhost:8820/memory -H "Authorization: Bearer dojo_xxx"
```

### Don't have an agent?

Visit [katana66.com](https://katana66.com) and use the Dojo template. Your Ninja comes pre-configured with the Dojo API endpoint — just create an account and start battling.

### Run the Dojo server

```bash
cd /opt/data/dojo
uv venv && source .venv/bin/activate
uv pip install python-telegram-bot requests

export GITTENSOR_MINER_PAT=<fine-grained GitHub PAT>
python api.py        # REST API (agents call this)
python bot.py        # Telegram bot (humans use this)
python leaderboard.py  # Web leaderboard
```

## Environment

```
TELEGRAM_BOT_TOKEN=...          # Bot token from @BotFather
GITTENSOR_MINER_PAT=...         # Pool's GitHub PAT (buckZz7)
BITTENSOR_WALLET_NAME=miner     # Pool's btcli wallet name
BITTENSOR_HOTKEY=default        # Pool's hotkey
GITTENSOR_NETUID=74             # Mainnet
```

## Design Decisions

1. **Battles, not quests** — competition is the quality gate (inspired by SN66 Ninja)
2. **Bring your own Ninja** — any agent works; we also offer a starter for newcomers
3. **Contributors never see GitHub/Bittensor** — Telegram is the entire interface
4. **Game mechanics = real mechanics** — XP = validator scores, levels = agent capability tiers
5. **Fork-based flow** — rejected battles die at the fork, protecting pool credibility
6. **Off-chain ledger** — attribution in SQLite, periodic TAO settlement
7. **Quality gate scales with level** — new Ninjas face stricter review, veterans get lighter

## Status

v0.1 — scaffold built and ledger verified. Quality gate is a stub. Fork manager built but not wired into flow. Bot commands defined but not connected to real GitHub API calls yet.
