# OpenClaw Auto-Trader

Copy-trading bot that follows SoulWinners elite wallet signals.

**Goal:** Turn $15 → $10k by copy-trading elite wallet buys

## Architecture

```
┌─────────────────┐
│  SoulWinners    │ Detects elite wallet buys
│  (Tracker)      │ Posts to internal queue
└────────┬────────┘
         ↓
┌─────────────────┐
│  OpenClaw       │ Receives buy signals
│  (Trader)       │ Executes trades on Jupiter
└─────────────────┘
```

## Trading Strategy

### Entry Rules
- Copy elite wallet buys (BES > 1000)
- Token liquidity >= $50k
- Wallet's last 5 trades >= 80% win rate
- Use 70% of balance per trade
- Max 3 simultaneous positions

### Exit Rules
1. **Stop Loss:** -20% → Sell 100% immediately
2. **Take Profit 1:** +50% → Sell 50%
3. **Take Profit 2:** +100% → Sell 50% of remaining
4. **Momentum:** If surging past 120%, hold runner
5. **Stagnation:** If flat for 10 min after TP2, sell remaining

### Position Sizing
- Start: ~$15 (0.2 SOL)
- Per trade: 70% of current balance
- Keep 30% as buffer for fees

## Setup

### 1. Create Solana Wallet

```bash
# Install Solana CLI
sh -c "$(curl -sSfL https://release.solana.com/stable/install)"

# Generate new wallet
solana-keygen new --outfile ~/.config/solana/openclaw.json

# Get address
solana address -k ~/.config/solana/openclaw.json

# Get private key (base58)
cat ~/.config/solana/openclaw.json
# Copy the array, convert to base58
```

Or use Phantom/Solflare to create wallet and export private key.

### 2. Fund Wallet

Transfer ~$15 worth of SOL to your OpenClaw wallet address.

### 3. Configure Environment

```bash
# Add to .env
OPENCLAW_PRIVATE_KEY=your_base58_private_key
OPENCLAW_CHAT_ID=your_telegram_chat_id  # For trade notifications
```

### 4. Install Dependencies

```bash
pip install solana solders base58
```

### 5. Start Bot

```bash
# Check balance first
python3 run_openclaw.py --balance

# Start trading
python3 run_openclaw.py

# Or as systemd service
sudo cp deploy/openclaw.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable openclaw
sudo systemctl start openclaw
```

## Commands

```bash
# Start bot
python3 run_openclaw.py

# Check status
python3 run_openclaw.py --status

# Check wallet balance
python3 run_openclaw.py --balance

# Debug mode
python3 run_openclaw.py --debug
```

## Monitoring

### Status Dashboard

The `--status` command shows:
- Current balance and P&L
- Win rate and trade count
- Open positions with P&L
- Progress toward $10k goal

### Telegram Notifications

OpenClaw sends notifications for:
- Trade entries (with source wallet info)
- Trade exits (with P&L)
- Stop loss triggers
- Take profit hits

### Logs

```bash
# View logs
tail -f /root/Soulwinners/logs/openclaw.log

# Filter for trades
grep "TRADE" logs/openclaw.log

# Filter for errors
grep -i error logs/openclaw.log
```

## Database

OpenClaw stores data in `data/openclaw.db`:

- **positions:** Open and historical positions
- **trade_history:** All trades with P&L
- **daily_pnl:** Daily performance tracking
- **stats:** Overall statistics
- **signal_queue:** Pending signals from SoulWinners

## Safety Features

1. **Entry Filters:**
   - Only copies elite wallets (BES > 1000)
   - Requires 80%+ win rate
   - Minimum $50k liquidity

2. **Position Limits:**
   - Max 3 simultaneous positions
   - Won't buy same token twice
   - 30% balance buffer

3. **Exit Protection:**
   - Automatic stop loss at -20%
   - Partial exits lock in profits
   - Momentum detection for runners

4. **Error Handling:**
   - Automatic retry on failed transactions
   - Graceful shutdown on errors
   - All trades logged for review

## Risk Warning

**This is real money trading. Risks include:**
- Total loss of capital
- Slippage on volatile tokens
- Failed transactions losing gas
- Smart contract risks
- API downtime

**Only trade what you can afford to lose.**

## Performance Tracking

### Goal Progress

```
Starting: $15 (0.2 SOL)
Target:   $10,000 (128 SOL)
Required: 640x return
```

### Expected Win Rate

Based on copying elite wallets with 80%+ win rate:
- Conservative estimate: 60% win rate after slippage
- Average win: +30% (TP1 hits)
- Average loss: -20% (stop loss)
- Expected edge: +8% per trade

### Path to $10k

At 8% edge per trade with 70% position sizing:
- Trade 1: $15 → $15.84
- Trade 10: $15 → $22
- Trade 50: $15 → $70
- Trade 100: $15 → $330
- Trade 150: $15 → $1,500
- Trade 200: $15 → $7,000
- Trade 220: $15 → $10,000+

*Theoretical only. Actual results may vary significantly.*
