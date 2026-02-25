# SoulWinners - Solana Smart Money Tracker

**Autonomous AI-powered system that discovers and monitors elite Solana wallet traders, posting real-time buy alerts when they make moves.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-blue?logo=telegram)](https://t.me/TopwhaleTracker)

---

## Features

- **Smart Discovery** - Scans Pump.fun + DexScreener every 10 minutes for profitable traders
- **ML Classification** - K-means clustering identifies 5 distinct trading archetypes
- **BES Ranking** - Buy Efficiency Score measures capital efficiency, not just raw ROI
- **Real-time Alerts** - Sub-30 second latency on whale buys >= 2 SOL
- **Quality Filters** - Only alerts from wallets with 60%+ win rate on last 5 trades
- **Never Shrinks** - Pool only grows; underperformers drop in ranking but stay monitored
- **Telegram Bot** - Full command interface for stats, leaderboards, and controls
- **4-Key Rotation** - Helius API key rotation for 400 req/sec capacity

---

## What It Tracks

| Metric | Description |
|--------|-------------|
| **ROI per Trade** | Average return on each position |
| **Win Rate** | Percentage of profitable trades |
| **10x/20x/50x/100x Ratios** | Multi-bagger hit rates |
| **Trade Frequency** | Trades per day |
| **Median Hold Time** | Typical position duration |
| **BES Score** | (ROI/Trade x Win Rate x Frequency) / Avg Buy Size |

---

## Current Stats

```
Pool Size:        56 elite wallets
Strategies:       5 archetypes identified
Alert Latency:    <30 seconds
Discovery:        Every 10 minutes
Uptime:           99.9%
```

### Wallet Archetypes (K-Means Clustering)

| Cluster | Description | Characteristics |
|---------|-------------|-----------------|
| **Core Alpha** | Active, consistent traders | High frequency, steady ROI |
| **Moonshot Hunters** | High-risk multi-bagger chasers | Lower win rate, higher upside |
| **Low-frequency Snipers** | Selective, high-conviction | Few trades, high accuracy |
| **Conviction Holders** | Long-term position holders | Extended hold times |
| **Dormant/Legacy** | Previously active wallets | Historical performance data |

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| **Language** | Python 3.10+ |
| **Blockchain Data** | Helius API (4-key rotation) |
| **Database** | SQLite |
| **Telegram** | python-telegram-bot |
| **ML/Analytics** | scikit-learn, pandas, numpy |
| **Deployment** | Ubuntu VPS, systemd, cron |

---

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/pool` | BES leaderboard with live balances |
| `/wallets` | Full wallet addresses with links |
| `/leaderboard` | Top 10 by ROI |
| `/stats` | Pool statistics and tier breakdown |
| `/settings` | Interactive control panel |
| `/cron` | Discovery job status |
| `/logs` | View system logs |
| `/help` | Comprehensive metrics guide |

---

## Alert Format

When an elite wallet buys >= 2 SOL of a token:

```
WHALE BUY ALERT

Wallet: Core Alpha (Active)
Tier: Elite
Recent Win Rate: 73%

Token: $EXAMPLE
Amount: 5.2 SOL ($780)
Market Cap: $1.2M

Wallet Stats:
- ROI/Trade: 156%
- Total Trades: 847
- 10x Rate: 12%

[Birdeye] [Solscan] [DexScreener]
```

---

## Architecture

```
                    +------------------+
                    |   DexScreener    |
                    |    Pump.fun      |
                    +--------+---------+
                             |
                    +--------v---------+
                    |  Wallet Discovery |
                    |   (Every 10 min)  |
                    +--------+---------+
                             |
              +--------------+--------------+
              |                             |
     +--------v--------+          +--------v--------+
     | Metrics Engine  |          | K-Means Cluster |
     | ROI, Win Rate,  |          | 5 Archetypes    |
     | Multi-baggers   |          |                 |
     +--------+--------+          +--------+--------+
              |                             |
              +--------------+--------------+
                             |
                    +--------v---------+
                    |  Quality Filter  |
                    | SOL>=10, WR>=60% |
                    | Trades>=15       |
                    +--------+---------+
                             |
                    +--------v---------+
                    |  Qualified Pool  |
                    |   (56 wallets)   |
                    +--------+---------+
                             |
         +-------------------+-------------------+
         |                                       |
+--------v--------+                    +--------v--------+
| Real-time Monitor|                    | Telegram Bot   |
| Poll every 30s   |                    | Commands + UI  |
+--------+--------+                    +-----------------+
         |
+--------v--------+
|  Alert Engine   |
| Buy >= 2 SOL    |
| Last 5 WR >= 60%|
+--------+--------+
         |
+--------v--------+
| @TopwhaleTracker|
|  Telegram Channel|
+-----------------+
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- Helius API key(s)
- Telegram Bot Token

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/soulwinners.git
cd soulwinners

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Initialize database
python3 -c "from database import init_database; init_database()"

# Run bot
python3 run_bot.py
```

### VPS Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for full production setup guide.

---

## Configuration

### Quality Thresholds

```python
MIN_SOL_BALANCE = 10    # Minimum SOL balance
MIN_TRADES_30D = 15     # Minimum trades in 30 days
MIN_WIN_RATE = 0.60     # 60% win rate
MIN_ROI = 0.50          # 50% total ROI
```

### Alert Filters

```python
MIN_BUY_AMOUNT = 2.0    # Minimum SOL per buy
MAX_TX_AGE = 300        # 5 minutes max
LAST_5_WIN_RATE = 0.60  # 60% on recent trades
```

---

## API Keys

SoulWinners uses 4-key rotation for Helius API to achieve 400 req/sec capacity:

```python
HELIUS_API_KEYS = [
    "key-1",  # 100 req/sec
    "key-2",  # 100 req/sec
    "key-3",  # 100 req/sec
    "key-4",  # 100 req/sec
]
# Total: 400 req/sec = 24,000 req/min
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design and data flow |
| [DEPLOYMENT.md](docs/DEPLOYMENT.md) | VPS setup and production guide |
| [API.md](docs/API.md) | Helius and Telegram integration |
| [METRICS.md](docs/METRICS.md) | BES formula and scoring explained |

---

## Roadmap

- [ ] Web dashboard with real-time updates
- [ ] REST API for external integrations
- [ ] Historical performance tracking
- [ ] Portfolio simulation mode
- [ ] Multi-chain support (Base, Arbitrum)
- [ ] Discord bot integration

---

## Contributing

Contributions are welcome! Please read our contributing guidelines before submitting PRs.

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Disclaimer

This software is for educational and research purposes only. Cryptocurrency trading involves substantial risk. Past performance of tracked wallets does not guarantee future results. Always do your own research before making investment decisions.

---

**Built with intelligence. Powered by data.**
