# Hedgehog - SoulWinners AI Brain v2.0

**Codename:** Hedgehog 🦔

Full autonomous AI agent with hybrid model routing, Telegram command interface, and self-healing capabilities.

## Hybrid AI Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     HEDGEHOG AI BRAIN                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────┐     ┌──────────────┐     ┌─────────────┐ │
│   │   Telegram  │────▶│   Router     │────▶│  GPT-4o-mini│ │
│   │   Commands  │     │  (Routing)   │     │  (95% calls)│ │
│   └─────────────┘     └──────────────┘     └─────────────┘ │
│                              │                              │
│                              ▼                              │
│                       ┌──────────────┐                      │
│                       │Claude Sonnet │                      │
│                       │  (5% calls)  │                      │
│                       │  Critical    │                      │
│                       └──────────────┘                      │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  Tools │ Memory │ Safety │ Monitoring │ Self-Healing       │
└─────────────────────────────────────────────────────────────┘
```

## Cost Optimization

| Model | Use Case | Cost |
|-------|----------|------|
| GPT-4o-mini | 95% of calls: monitoring, status, simple queries | ~$0.15/1M tokens |
| Claude Sonnet 4 | 5% of calls: trading decisions, self-healing, strategy | ~$15/1M tokens |

**Target: $3-5/month**

## Directory Structure

```
hedgehog/
├── __init__.py              # Package entry
├── __main__.py              # Module entry point
├── brain.py                 # Core AI brain (full autonomy)
├── config.py                # Hybrid API configuration
├── router.py                # Intelligent model routing
├── run_hedgehog.py          # CLI entry point
├── README.md                # This file
│
├── tools/                   # Tool system
│   ├── base.py              # Base classes + safety levels
│   ├── database_tools.py    # Database query/write
│   ├── system_tools.py      # System status, restart, logs
│   ├── trading_tools.py     # Positions, wallets, tokens
│   └── telegram_tools.py    # Send/edit messages
│
├── memory/                  # Persistent memory
│   ├── store.py             # SQLite-backed storage
│   ├── hedgehog_memory.db   # Decision/error database
│   └── actions.json         # Action audit log
│
├── safety/                  # Safety classification
│   └── classifier.py        # SAFE/MODERATE/RISKY/DESTRUCTIVE
│
├── monitoring/              # Event detection & health
│   ├── events.py            # Event types & detection
│   └── health.py            # Service health & self-healing
│
└── integrations/            # System integrations
    ├── webhook_handler.py   # Flask routes for webhooks
    ├── telegram_handler.py  # Telegram bot interface
    └── cron_handler.py      # Scheduled tasks
```

## Quick Start

### Run Telegram Bot (Main Mode)

```bash
python -m hedgehog bot
```

### Other Modes

```bash
# Show status
python -m hedgehog status

# Interactive mode
python -m hedgehog interactive

# Process events (for cron)
python -m hedgehog process

# Health check
python -m hedgehog health

# Send daily report
python -m hedgehog report
```

## Telegram Commands

### Status & Monitoring

| Command | Description |
|---------|-------------|
| `/status` | Full system overview |
| `/health` | Detailed health check |
| `/positions` | Open trading positions |
| `/wallets` | Wallet statistics |
| `/cost` | AI cost tracking |
| `/logs [service]` | Recent error logs |

### Actions

| Command | Description |
|---------|-------------|
| `/fix <issue>` | Auto-diagnose and fix |
| `/restart <service>` | Restart service |
| `/trade_decision <token>` | Trade analysis (uses Claude) |

### Configuration (Requires Approval)

| Command | Description |
|---------|-------------|
| `/update_key <svc> <key>` | Update API key |
| `/set_threshold <param> <val>` | Change setting |

### Approvals

| Command | Description |
|---------|-------------|
| `/pending` | Show pending approvals |
| `/approve <id>` | Approve action |
| `/reject <id>` | Reject action |

### Other

| Command | Description |
|---------|-------------|
| `/hedgehog <question>` | Ask AI anything |
| `/history` | Action history |
| `/undo <id>` | Mark action undone |
| `/pause` | Pause autonomy |
| `/resume` | Resume autonomy |
| `/help` | Show all commands |

## Natural Language Examples

```
"Change min buy to 1.0 SOL"
→ Creates approval request to update threshold

"Why did webhook stop?"
→ Diagnoses issue and attempts fix

"Fix the UNKNOWN tokens"
→ Auto-fixes token symbol issues

"What's the top wallet today?"
→ Shows top performing wallets

"Show positions"
→ Lists open trading positions
```

## Model Routing Logic

GPT-4o-mini is used for:
- Log analysis
- Status checks
- Simple queries
- Telegram responses
- Event monitoring
- Safety classification

Claude Sonnet 4 is used for:
- Trading decisions > 5 SOL
- Self-healing operations
- Strategic analysis
- System failure diagnosis
- Complex reasoning
- When GPT confidence < 80%

## Safety Levels

| Level | Auto-Execute | Examples |
|-------|--------------|----------|
| SAFE | ✓ | Status checks, log analysis, monitoring |
| MODERATE | ✓ (logged) | Restart services, fix tokens, rotate keys |
| RISKY | Needs approval | Update config, change thresholds |
| DESTRUCTIVE | Blocked | Delete database, drop tables |

## Cron Integration

```cron
# Process events every 5 minutes
*/5 * * * * cd /root/Soulwinners && python -m hedgehog.integrations.cron_handler events

# Health check and self-heal
*/5 * * * * cd /root/Soulwinners && python -m hedgehog.integrations.cron_handler heal

# Daily report at midnight
0 0 * * * cd /root/Soulwinners && python -m hedgehog.integrations.cron_handler report

# Cleanup old data weekly
0 3 * * 0 cd /root/Soulwinners && python -m hedgehog.integrations.cron_handler cleanup
```

## Self-Healing Capabilities

Hedgehog automatically handles:
- **Service crashes** → Restart up to 3x, then alert
- **Rate limits** → Rotate API keys
- **High error rate** → Diagnose and fix
- **Database issues** → Reconnect
- **Unknown tokens** → Fetch metadata

## Configuration

Environment variables (optional overrides):
```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
```

Default API keys are configured in `config.py`.

## Requirements

```
openai>=1.0.0
anthropic>=0.25.0
aiohttp>=3.9.0
python-telegram-bot>=20.0
```

## Version History

- **v2.0.0** - Hybrid AI (GPT-4o-mini + Claude), full Telegram autonomy
- **v1.0.0** - Initial release (Claude only)
