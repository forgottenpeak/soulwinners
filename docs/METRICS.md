# Metrics & Scoring Guide

## Buy Efficiency Score (BES)

The BES is our proprietary metric for measuring capital efficiency - how well a trader converts capital into returns.

### Formula

```
BES = (ROI per Trade × Win Rate × Trade Frequency) / Average Buy Size
```

### Why BES Matters

**Traditional ROI is misleading.** Consider:

| Wallet | Total ROI | Avg Buy Size |
|--------|-----------|--------------|
| A | 1000% | 10 SOL |
| B | 200% | 0.5 SOL |

Wallet A looks better by ROI, but:
- Wallet A risked 10 SOL to make 100 SOL profit
- Wallet B risked 0.5 SOL to make 1 SOL profit

**BES reveals the truth:**
- Wallet A: BES = 100 (10x return per SOL risked)
- Wallet B: BES = 400 (40x return per SOL risked)

**Wallet B is 4x more capital efficient.**

### Components

| Component | Description | Higher = |
|-----------|-------------|----------|
| ROI per Trade | Average return on each position | Better |
| Win Rate | % of profitable trades | Better |
| Trade Frequency | Trades per day | More opportunities |
| Average Buy Size | Typical position size | Lower = more efficient |

---

## Quality Filter Thresholds

### Pool Qualification

| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| SOL Balance | >= 10 | Serious capital |
| Trades (30d) | >= 15 | Active trader |
| Win Rate | >= 60% | Consistently profitable |
| ROI | >= 50% | Meaningful returns |

### Alert Qualification

| Metric | Threshold | Rationale |
|--------|-----------|-----------|
| Buy Amount | >= 2 SOL | Significant position |
| Transaction Age | < 5 min | Timely alerts |
| Last 5 Win Rate | >= 60% | Recent performance |

---

## Tier Assignment

Based on priority score percentiles:

| Tier | Percentile | Description |
|------|------------|-------------|
| **Elite** | Top 15% | Best performers |
| **High-Quality** | 60-85% | Strong performers |
| **Mid-Tier** | 20-60% | Average performers |
| **Watchlist** | Bottom 20% | Underperformers |

### Priority Score Formula

```python
priority_score = (
    roi_pct * 0.25 +
    profit_token_ratio * 0.20 +
    roi_per_trade * 0.20 +
    trade_frequency * 0.15 +
    x10_ratio * 0.10 +
    x20_ratio * 0.05 +
    x50_ratio * 0.05
)
```

All values normalized to 0-1 range before weighting.

---

## Multi-Bagger Ratios

Tracks how often a wallet hits big wins:

| Metric | Definition | Elite Benchmark |
|--------|------------|-----------------|
| 10x Ratio | % of trades with 10x+ return | > 5% |
| 20x Ratio | % of trades with 20x+ return | > 2% |
| 50x Ratio | % of trades with 50x+ return | > 0.5% |
| 100x Ratio | % of trades with 100x+ return | > 0.1% |

---

## K-Means Clustering

### Features Used

```python
KMEANS_FEATURES = [
    "trade_frequency",    # Trades per day
    "roi_per_trade",      # Average ROI
    "median_hold_time",   # Position duration
    "x10_ratio",          # Multi-bagger hits
    "profit_token_ratio", # Win rate
]
```

### Cluster Archetypes

| Cluster | Name | Characteristics |
|---------|------|-----------------|
| 0 | **Core Alpha (Active)** | High frequency, consistent returns |
| 1 | **Low-frequency Snipers** | Few trades, high accuracy |
| 2 | **Moonshot Hunters** | High risk, chasing multi-baggers |
| 3 | **Conviction Holders** | Long hold times, patient |
| 4 | **Dormant/Legacy** | Previously active, now quiet |

---

## Metric Calculations

### Win Rate (profit_token_ratio)

```python
def calculate_win_rate(trades: List[Dict]) -> float:
    closed_positions = [t for t in trades if t['sold']]
    profitable = [t for t in closed_positions if t['profit'] > 0]
    return len(profitable) / len(closed_positions)
```

### ROI per Trade

```python
def calculate_roi_per_trade(trades: List[Dict]) -> float:
    rois = []
    for trade in trades:
        if trade['sol_spent'] > 0 and trade['sol_earned'] > 0:
            roi = (trade['sol_earned'] / trade['sol_spent'] - 1) * 100
            rois.append(roi)
    return sum(rois) / len(rois) if rois else 0
```

### Trade Frequency

```python
def calculate_trade_frequency(trades: List[Dict], days: int) -> float:
    return len(trades) / days  # Trades per day
```

### Median Hold Time

```python
def calculate_median_hold_time(trades: List[Dict]) -> float:
    hold_times = []
    for trade in trades:
        if trade['buy_time'] and trade['sell_time']:
            duration = trade['sell_time'] - trade['buy_time']
            hold_times.append(duration)
    hold_times.sort()
    return hold_times[len(hold_times) // 2] if hold_times else 0
```

---

## Real-time Alert Scoring

When a wallet makes a buy, we check:

```python
async def should_alert(wallet: str, buy_amount: float) -> bool:
    # Check minimum buy size
    if buy_amount < MIN_BUY_AMOUNT:
        return False

    # Check recent performance
    last_5_trades = await get_last_closed_trades(wallet, limit=5)
    wins = sum(1 for t in last_5_trades if t['profitable'])
    recent_win_rate = wins / len(last_5_trades)

    return recent_win_rate >= 0.60
```

---

## Interpreting the Data

### High BES, Low ROI
- Efficient with small positions
- Good for copying with limited capital

### High ROI, Low BES
- Big positions, big returns
- Requires significant capital to replicate

### High Win Rate, Low Multi-bagger
- Consistent small gains
- Lower risk profile

### Low Win Rate, High Multi-bagger
- Lottery ticket strategy
- High variance, occasional huge wins

---

## Dashboard Metrics

### /pool Command Shows:

```
#1 | BES: 2,450 | Core Alpha
├─ ROI/Trade: 156% | Win: 73%
├─ Avg Buy: 2.3 SOL | Trades: 847
├─ Balance: 45.2 SOL (LIVE)
├─ Last Buy: 12m ago | $TOKEN +24%
└─ 7xR2...wK9p
```

### /stats Command Shows:

```
Overview:
├ Total Wallets: 56
├ Total SOL Tracked: 1,234 SOL
├ Avg ROI: 234%
├ Avg Win Rate: 68%
└ Avg Balance: 22.03 SOL

Tier Breakdown:
🔥 Elite: 54 wallets (Avg ROI: 312%)
🟢 High-Quality: 2 wallets (Avg ROI: 156%)
```
