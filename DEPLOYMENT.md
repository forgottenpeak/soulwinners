# SoulWinners VPS Deployment Guide

## Quick Deployment (Recommended)

SSH into your VPS and run these commands:

```bash
# 1. Navigate to project directory
cd /root/Soulwinners

# 2. Pull latest code from GitHub
git pull origin main

# 3. Run automated deployment
bash deploy/deploy_all.sh

# 4. Start services
systemctl enable soulwinners insider
systemctl start soulwinners insider

# 5. Verify deployment
systemctl status soulwinners
systemctl status insider
```

That's it! The system is now running.

---

## What Was Deployed

### Core Updates
- **Threshold Fixed**: MIN_BUY_AMOUNT changed from 2.0 → 1.0 SOL
- **Alert Format**: Now shows aggregate stats (Avg ROI, Win Rate, BES)
- **Accumulation Detection**: Alerts when multiple buys occur in 30 minutes

### New Features

#### 1. Insider Detection Pipeline
- **InsiderScanner**: Scans fresh launches every 5 minutes
- **ClusterDetector**: Maps wallet connections every 10 minutes
- **Auto-promotion**: High-confidence wallets (≥0.7, win rate ≥60%) auto-added to qualified_wallets

#### 2. OpenClaw Auto-Trader (Optional)
- **Strategy**: Follow elite wallet buys with strict entry criteria
- **Risk Management**: -20% stop loss, +50%/+100% take profits
- **Position Sizing**: 70% per trade, max 3 concurrent positions
- **Requires**: OPENCLAW_PRIVATE_KEY in .env file

---

## Verification Steps

### 1. Check Services Are Running
```bash
systemctl status soulwinners  # Main monitoring + alerts
systemctl status insider      # Insider detection pipeline
```

Expected: Both showing "active (running)" in green

### 2. Check Logs
```bash
# Main monitor
tail -f /root/Soulwinners/logs/soulwinners.log

# Should see:
# - "MIN_BUY_AMOUNT = 1.0" (NOT 2.0)
# - "Monitoring XX Elite wallets"
# - WebSocket connection messages

# Insider detector
tail -f /root/Soulwinners/logs/insider.log

# Should see:
# - "InsiderScanner starting..."
# - "ClusterDetector starting..."
# - "Scanning fresh launches..."
# - "Building wallet clusters..."
```

### 3. Verify Database Tables
```bash
cd /root/Soulwinners
./venv/bin/python3 << 'EOF'
from database import get_connection
conn = get_connection()

# Check qualified wallets
wallets = conn.execute('SELECT COUNT(*) FROM qualified_wallets').fetchone()[0]
print(f'✓ Qualified wallets: {wallets}')

# Check insider pool (should grow over time)
insiders = conn.execute('SELECT COUNT(*) FROM insider_pool').fetchone()[0]
print(f'✓ Insider pool: {insiders}')

# Check clusters (should grow over time)
clusters = conn.execute('SELECT COUNT(*) FROM wallet_clusters').fetchone()[0]
print(f'✓ Wallet clusters: {clusters}')

conn.close()
EOF
```

### 4. Test Telegram Commands
In your Telegram bot chat:
```
/cluster      - Show active wallet clusters
/insiders     - Show insider pool stats
/early_birds  - Show fresh launch snipers
/status       - Overall system status
```

---

## Optional: Enable OpenClaw Auto-Trader

### Prerequisites
1. **Wallet Setup**: Create a new Solana wallet with 0.2+ SOL
2. **Get Private Key**: Export the base58-encoded private key (88 characters)
3. **Update .env**: Add OPENCLAW_PRIVATE_KEY and OPENCLAW_CHAT_ID

### Steps
```bash
# 1. Edit .env file
nano /root/Soulwinners/.env

# Add these lines:
OPENCLAW_PRIVATE_KEY=<your-88-char-base58-key>
OPENCLAW_CHAT_ID=1153491543

# 2. Enable and start service
systemctl enable openclaw
systemctl start openclaw

# 3. Check status
systemctl status openclaw
tail -f /root/Soulwinners/logs/openclaw.log

# 4. Test balance
./venv/bin/python3 run_openclaw.py --balance
```

---

## Expected Behavior

### Within 5 Minutes
- SoulWinners monitoring active
- InsiderScanner starts scanning fresh launches
- ClusterScanner starts analyzing wallet connections
- Alerts sent for buys ≥ 1.0 SOL (not 2.0)

### Within 1 Hour
- 10-30 insiders detected in insider_pool
- 5-10 wallet clusters identified
- Alerts show "Avg ROI" and "Win Rate" (not "Last 5 Trades")
- Accumulation alerts for wallets making multiple buys

### Within 24 Hours
- 30-50+ insiders in pool
- 10-20+ wallet clusters mapped
- High-confidence insiders (≥0.7) promoted to qualified_wallets
- OpenClaw (if enabled): 1-3 positions taken

---

## Monitoring Commands

### View Service Logs
```bash
# Real-time logs
journalctl -u soulwinners -f
journalctl -u insider -f
journalctl -u openclaw -f  # If enabled

# Last 100 lines
journalctl -u soulwinners -n 100
journalctl -u insider -n 100
```

### Check Database Stats
```bash
cd /root/Soulwinners
./venv/bin/python3 run_insider.py --insiders
./venv/bin/python3 run_insider.py --clusters
./venv/bin/python3 run_insider.py --stats
```

### OpenClaw Status (If Enabled)
```bash
./venv/bin/python3 run_openclaw.py --status
./venv/bin/python3 run_openclaw.py --balance
./venv/bin/python3 run_openclaw.py --positions
./venv/bin/python3 run_openclaw.py --pnl
```

---

## Service Management

### Restart Services
```bash
systemctl restart soulwinners
systemctl restart insider
systemctl restart openclaw  # If enabled
```

### Stop Services
```bash
systemctl stop soulwinners
systemctl stop insider
systemctl stop openclaw  # If enabled
```

### View Service Configuration
```bash
cat /etc/systemd/system/soulwinners.service
cat /etc/systemd/system/insider.service
cat /etc/systemd/system/openclaw.service
```

---

## Troubleshooting

### No Alerts Received
1. Check if qualified_wallets has entries:
   ```bash
   ./venv/bin/python3 -c "from database import get_connection; conn = get_connection(); print(conn.execute('SELECT COUNT(*) FROM qualified_wallets').fetchone()[0])"
   ```

2. Check MIN_BUY_AMOUNT setting:
   ```bash
   ./venv/bin/python3 -c "from database import get_connection; conn = get_connection(); print(conn.execute('SELECT value FROM settings WHERE key=\"min_buy_amount\"').fetchone()[0])"
   ```
   Should return "1.0"

3. Check service logs for errors:
   ```bash
   journalctl -u soulwinners --since "10 minutes ago"
   ```

### Insider Detection Not Working
1. Check if service is running:
   ```bash
   systemctl status insider
   ```

2. Check logs for scanning activity:
   ```bash
   tail -50 logs/insider.log
   ```
   Should see "Scanning fresh launches..." every 5 minutes

3. Manually trigger a scan:
   ```bash
   ./venv/bin/python3 run_insider.py --scan
   ```

### OpenClaw Not Trading
1. Verify private key is set:
   ```bash
   grep OPENCLAW_PRIVATE_KEY /root/Soulwinners/.env
   ```

2. Check wallet balance:
   ```bash
   ./venv/bin/python3 run_openclaw.py --balance
   ```
   Should have at least 0.2 SOL

3. Check signal queue:
   ```bash
   ./venv/bin/python3 -c "from database import get_connection; conn = get_connection(); signals = conn.execute('SELECT COUNT(*) FROM signal_queue WHERE processed = 0').fetchone()[0]; print(f'Pending signals: {signals}')"
   ```

---

## Rollback Plan

If issues occur:

```bash
# 1. Stop new services
systemctl stop insider openclaw

# 2. Check previous commit
cd /root/Soulwinners
git log --oneline -5

# 3. Revert if needed
git reset --hard <previous-commit-hash>
systemctl restart soulwinners

# 4. Check logs
tail -100 logs/soulwinners.log
```

---

## Performance Metrics

### Expected Resource Usage
- **CPU**: 5-15% average (spikes to 30-40% during scans)
- **Memory**: 200-400 MB
- **Disk**: ~10 MB/day for logs and database
- **Network**: Minimal (API calls only)

### Database Growth
- **insider_pool**: ~5-10 rows/day
- **wallet_clusters**: ~2-5 rows/day
- **trade_history**: ~10-20 rows/day (if OpenClaw enabled)
- **Total size**: ~50 MB after 30 days

---

## Success Indicators

After 7 days, you should see:

| Metric | Expected Value |
|--------|---------------|
| Qualified Wallets | 70-100 |
| Insider Pool | 50-80 |
| Wallet Clusters | 15-25 |
| Daily Alerts | 20-50 |
| OpenClaw Positions (if enabled) | 10-15 total |
| OpenClaw Win Rate (if enabled) | 40-60% |

---

## Next Steps

1. Monitor Telegram channel for alerts (should arrive within 1-2 minutes of on-chain buys)
2. Watch insider pool grow in `/insiders` command
3. Review wallet clusters in `/cluster` command
4. If OpenClaw enabled, monitor positions with `run_openclaw.py --status`
5. Adjust thresholds if needed (insider confidence, cluster size, etc.)

---

## Support

For issues or questions:
1. Check logs first: `tail -100 logs/insider.log`
2. Review systemd status: `systemctl status insider`
3. Test modules manually: `./venv/bin/python3 run_insider.py --scan`
4. Check database state: `./venv/bin/python3 run_insider.py --stats`
