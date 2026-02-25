# Architecture

## System Overview

SoulWinners is a multi-component system designed for autonomous operation with zero human intervention once deployed.

## Components

### 1. Data Collection Layer

```
collectors/
├── base.py           # Base collector with rate limiting
├── helius.py         # Helius API client + key rotation
├── dexscreener.py    # DexScreener collector
└── pumpfun.py        # Pump.fun collector
```

**HeliusRotator**: Manages 4 API keys for 400 req/sec capacity
- Round-robin key selection
- Per-key request counting
- Automatic rate limit detection
- Retry with fresh keys on 429

### 2. Pipeline Layer

```
pipeline/
├── orchestrator.py   # Main pipeline coordinator
├── metrics.py        # Performance calculations
├── clustering.py     # K-means ML clustering
└── ranking.py        # Priority scoring + tiers
```

**Pipeline Flow**:
1. Collect wallets from Pump.fun + DexScreener
2. Merge and deduplicate
3. Calculate performance metrics
4. Run K-means clustering (5 archetypes)
5. Calculate priority scores
6. Apply quality filters
7. Save to database (ADD only, never remove)

### 3. Bot Layer

```
bot/
├── commands.py       # Telegram command handlers
└── realtime_bot.py   # Transaction monitor + alerts
```

**Two concurrent processes**:
- **CommandBot**: Handles user commands via polling
- **RealTimeBot**: Monitors wallets, posts alerts

### 4. Database Layer

```
database/
├── __init__.py       # Connection management
└── schema.sql        # Table definitions
```

**Tables**:
- `qualified_wallets` - Active monitoring pool
- `wallet_metrics` - All analyzed wallets
- `alerts` - Sent alert history
- `pipeline_runs` - Job execution logs
- `settings` - Runtime configuration

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                     DISCOVERY (Every 10 min)                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  DexScreener API ──┐                                        │
│                    ├──▶ Trending Tokens ──▶ Token Traders   │
│  Pump.fun API ─────┘                                        │
│                                                             │
│  For each wallet:                                           │
│    ├── Fetch transaction history (Helius)                   │
│    ├── Fetch balances (Helius)                              │
│    └── Calculate metrics                                    │
│                                                             │
│  Metrics:                                                   │
│    ├── ROI per trade                                        │
│    ├── Win rate (profit_token_ratio)                        │
│    ├── Trade frequency                                      │
│    ├── Multi-bagger ratios (10x, 20x, 50x, 100x)           │
│    └── Hold time patterns                                   │
│                                                             │
│  K-Means Clustering (5 clusters):                           │
│    ├── Core Alpha (Active)                                  │
│    ├── Moonshot Hunters                                     │
│    ├── Low-frequency Snipers                                │
│    ├── Conviction Holders                                   │
│    └── Dormant/Legacy                                       │
│                                                             │
│  Quality Filter:                                            │
│    ├── SOL balance >= 10                                    │
│    ├── Trades >= 15                                         │
│    ├── Win rate >= 60%                                      │
│    └── ROI >= 50%                                           │
│                                                             │
│  Save to qualified_wallets (ADD only, never remove)         │
│                                                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   MONITORING (Every 30 sec)                  │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  For each qualified wallet:                                 │
│    ├── Fetch recent transactions (Helius)                   │
│    ├── Detect new buys                                      │
│    └── Check if buy >= 2 SOL                                │
│                                                             │
│  Alert Filter:                                              │
│    ├── Transaction < 5 min old                              │
│    ├── Buy amount >= 2 SOL                                  │
│    └── Last 5 closed trades >= 60% win rate                 │
│                                                             │
│  If passes:                                                 │
│    ├── Fetch token metadata                                 │
│    ├── Format alert message                                 │
│    └── Post to Telegram channel                             │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Scheduling

| Task | Frequency | Managed By |
|------|-----------|------------|
| Wallet Discovery | Every 10 min | Cron |
| Transaction Monitoring | Every 30 sec | Bot process |
| Command Handling | Real-time | Bot polling |

## Persistence

- **SQLite**: Single file database, no external dependencies
- **systemd**: Auto-restart on crash, start on boot
- **Cron**: Survives reboots, runs independently

## Scalability

Current capacity with 4 Helius keys:
- **400 req/sec** = 24,000 req/min
- **~200 wallets** analyzed per 10-min run
- **56+ wallets** monitored every 30 sec

To scale:
1. Add more Helius API keys
2. Increase collection targets
3. Reduce poll interval (with rate limit headroom)

## Error Handling

- **API Rate Limits**: Retry with fresh key, exponential backoff
- **Network Timeouts**: 3 retries with delay
- **Bot Conflicts**: Skip command bot if another instance running
- **Database Locks**: SQLite WAL mode for concurrent access
