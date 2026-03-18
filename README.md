# Hedgehog v1.0

Personal AI agent using OpenClaw architecture patterns.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment
export OPENAI_API_KEY=your_key
export TELEGRAM_BOT_TOKEN=your_token  # optional

# Create test database
python run.py --setup-db

# Run in CLI mode (testing)
python run.py --cli

# Run Telegram bot
python run.py --telegram
```

## Architecture

```
hedgehog/
├── core/
│   ├── brain.py      # ReAct loop (THOUGHT->ACTION->OBSERVATION)
│   ├── gateway.py    # Telegram + CLI interfaces
│   ├── memory.py     # File-based JSON storage
│   └── router.py     # LLM routing (GPT-4o-mini/Claude)
├── skills/
│   ├── base.py       # Skill registry
│   ├── database.py   # SQL queries
│   └── system.py     # Service monitoring
├── memory/
│   └── system_state.json
├── config.py
└── run.py
```

## Skills

- `database_query(sql)` - Execute SELECT queries
- `get_wallet_count()` - Get total wallets
- `list_tables()` - List database tables
- `check_service(name)` - Check if service running
- `read_logs(service, lines)` - Read service logs
- `system_info()` - Get system information

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key (required) |
| `ANTHROPIC_API_KEY` | Anthropic key (optional, for complex queries) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `HEDGEHOG_DB_PATH` | Override database path |

## Cost Optimization

- 95% of queries use GPT-4o-mini (~$0.15/1M tokens)
- Complex reasoning falls back to Claude Sonnet
- Estimated monthly cost: $3-5 for typical usage
