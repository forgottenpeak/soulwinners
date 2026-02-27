# V'ger Control Bot - Deployment Guide

V'ger is a Telegram bot that provides remote control and monitoring for your OpenClaw auto-trader.

## Bot Information

- **Bot:** @vgerr_bot
- **Token:** `8402301699:AAFUXJ2kNtQGupo4Qe4JBSY2gGMxs0OZMNQ`
- **Admin User ID:** `1153491543`

## Features

### 📊 Monitoring Commands

- `/status` - Current positions, P&L, and balance
- `/portfolio` - Detailed view of all open positions
- `/balance` - Wallet SOL balance and goal progress
- `/report` - Today's trade summary and P&L
- `/history` - Last 10 trades with results

### ⚙️ Settings Commands

- `/settings` - View current strategy parameters
- `/set <param> <value>` - Change strategy settings
  - Example: `/set stop_loss 15` (sets stop loss to -15%)
  - Example: `/set tp1_percent 40` (sets TP1 to +40%)
  - Example: `/set position_size 80` (use 80% of balance)

### 📈 Trading Commands

- `/exit <token>` - Force close a position with confirmation
  - Example: `/exit BONK`
- `/buy <token> <amount>` - Manual buy order (requires confirmation)
  - Example: `/buy BONK 0.1`

### ❓ Help

- `/help` - Show all available commands
- `/start` - Initialize bot

## Deployment to VPS

### Prerequisites

1. **OpenClaw trader must be deployed first**
   - See `deployment/DEPLOY.md` for OpenClaw setup
   - V'ger reads from OpenClaw's database at `data/openclaw.db`

2. **Environment variables set in `.env`:**
   ```bash
   VGER_BOT_TOKEN=8402301699:AAFUXJ2kNtQGupo4Qe4JBSY2gGMxs0OZMNQ
   VGER_ADMIN_ID=1153491543
   ```

### Quick Deploy

```bash
# SSH to your VPS
ssh root@your-vps-ip

# Navigate to project
cd /root/Soulwinners

# Run deployment script
sudo bash deployment/deploy_vger.sh
```

### Manual Deploy

If you prefer manual deployment:

```bash
# 1. Install dependencies
cd /root/Soulwinners
source venv/bin/activate
pip install python-telegram-bot python-dotenv

# 2. Create logs directory
mkdir -p logs

# 3. Install systemd service
sudo cp deployment/vger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable vger
sudo systemctl start vger

# 4. Check status
sudo systemctl status vger
```

## Service Management

### Start/Stop Service

```bash
# Start
sudo systemctl start vger

# Stop
sudo systemctl stop vger

# Restart
sudo systemctl restart vger

# Status
sudo systemctl status vger
```

### View Logs

```bash
# Live system logs
sudo journalctl -u vger -f

# Application logs
tail -f /root/Soulwinners/logs/vger.log

# Last 100 lines
tail -n 100 /root/Soulwinners/logs/vger.log
```

## Usage Examples

### Check Status

**Command:** `/status`

**Response:**
```
🟢 OPENCLAW STATUS

💰 Balance: 0.185 SOL ($15.20)
📊 Open Positions: 1/3
📈 Total P&L: +0.025 SOL (+12.5%)

🎯 Goal Progress: 0.2% to $10k
📊 Stats: 3/4 wins (75.0%)

📋 POSITIONS:

🟢 1. $BONK
├ Entry: 0.05 SOL @ $0.000012
├ Current: $0.000015 (+25.0%)
├ Value: 0.0625 SOL
├ P&L: +0.0125 SOL
├ Remaining: 100%
└ Duration: 2h 15m
```

### View Settings

**Command:** `/settings`

**Response:**
```
⚙️ STRATEGY SETTINGS

📊 Position Sizing:
├ Position Size: 70% of balance
└ Max Positions: 3

🚪 Exit Rules:
├ Stop Loss: -20%
├ TP1: +50% (sell 50%)
└ TP2: +100% (sell 50%)

🎯 Entry Filters:
├ Min BES: 1000
├ Min Win Rate: 80%
└ Min Liquidity: $50,000
```

### Change Settings

**Command:** `/set stop_loss 15`

**Response:**
```
✅ Updated stop_loss to -15.0

Use /settings to view all settings.
```

### Force Exit Position

**Command:** `/exit BONK`

**Response:** (with confirmation buttons)
```
⚠️ CONFIRM EXIT

Position: $BONK
Entry: 0.05 SOL ($4.10)
Current: 0.0625 SOL ($5.13)
P&L: +0.0125 SOL (+25.0%)
Remaining: 100%

⚠️ This will close the entire position immediately.

[✅ CONFIRM EXIT] [❌ CANCEL]
```

### Today's Report

**Command:** `/report`

**Response:**
```
📊 DAILY REPORT - February 27, 2026

🟢 Summary:
├ Total Trades: 4
├ Wins: 3/4 (75%)
└ P&L: +0.025 SOL

Trades Today:
🟢 14:30 - $BONK: +0.012 SOL (+24.0%)
🟢 12:15 - $WIF: +0.008 SOL (+16.0%)
🔴 10:45 - $PEPE: -0.010 SOL (-20.0%)
🟢 08:20 - $SAMO: +0.015 SOL (+30.0%)
```

## Security Features

### Access Control

- **Only responds to admin user ID** (1153491543)
- All unauthorized commands are rejected
- Every command is logged with timestamp

### Confirmation Required

- Trades over 1 SOL require confirmation
- Exit commands show preview before execution
- Buttons prevent accidental commands

### Logging

All actions are logged to:
- System journal: `journalctl -u vger`
- Application log: `logs/vger.log`

Log format:
```
2026-02-27 14:30:15 - INFO - Status command from user 1153491543
2026-02-27 14:31:22 - WARNING - Manual exit requested for BONK
```

## Integration with OpenClaw

V'ger reads directly from OpenClaw's database:

```python
# Database: data/openclaw.db

# Tables used:
- positions       # Open/closed positions
- trade_history   # All trades
- stats          # Balance, P&L, stats
- signal_queue   # Pending signals
```

### Data Flow

```
SoulWinners → Signal → OpenClaw Trader
                           ↓
                    data/openclaw.db
                           ↓
                      V'ger Bot ← Telegram Commands
```

## Troubleshooting

### Bot Not Responding

1. **Check service status:**
   ```bash
   sudo systemctl status vger
   ```

2. **Check logs for errors:**
   ```bash
   tail -f logs/vger.log
   ```

3. **Verify bot token:**
   ```bash
   grep VGER_BOT_TOKEN .env
   ```

4. **Test bot token with curl:**
   ```bash
   curl "https://api.telegram.org/bot8402301699:AAFUXJ2kNtQGupo4Qe4JBSY2gGMxs0OZMNQ/getMe"
   ```

### Database Errors

If you see "database locked" errors:

```bash
# Check if OpenClaw is running
sudo systemctl status openclaw

# Restart V'ger
sudo systemctl restart vger
```

### Unauthorized Access

If someone else tries to use the bot:
- They'll get: "⛔️ Unauthorized. V'ger responds only to Commander."
- All attempts are logged

### Service Won't Start

```bash
# Check logs
sudo journalctl -u vger -n 50

# Verify Python environment
cd /root/Soulwinners
source venv/bin/activate
python3 -c "import telegram; print('OK')"

# Test script directly
python3 v_ger_bot.py
```

## Updating V'ger

```bash
# Pull latest code
cd /root/Soulwinners
git pull

# Restart service
sudo systemctl restart vger

# Verify
sudo systemctl status vger
```

## Monitoring

### Health Check

Create a cron job to check if V'ger is running:

```bash
# Add to crontab
*/5 * * * * systemctl is-active --quiet vger || systemctl start vger
```

### Log Rotation

Logs are automatically rotated by systemd. To manually clean:

```bash
# Clear old logs
sudo journalctl --vacuum-time=7d

# Rotate application log
mv logs/vger.log logs/vger.log.old
sudo systemctl restart vger
```

## Advanced Configuration

### Custom Admin ID

To change the admin user:

1. Get your Telegram user ID
2. Update `.env`:
   ```bash
   VGER_ADMIN_ID=your_telegram_user_id
   ```
3. Restart service:
   ```bash
   sudo systemctl restart vger
   ```

### Multiple Admins

To allow multiple admins, modify `v_ger_bot.py`:

```python
# Change this:
VGER_ADMIN_ID = int(os.getenv('VGER_ADMIN_ID', '1153491543'))

# To this:
VGER_ADMIN_IDS = [
    1153491543,
    123456789,  # Add more IDs
]

def is_admin(user_id: int) -> bool:
    return user_id in VGER_ADMIN_IDS
```

## Support

### Common Issues

1. **"Position not found"** - Use `/portfolio` to see exact token symbols
2. **"Insufficient balance"** - Check with `/balance`
3. **"Max positions reached"** - Close a position first with `/exit`

### Getting Help

- Check logs: `tail -f logs/vger.log`
- Check OpenClaw status: `sudo systemctl status openclaw`
- Verify database: `sqlite3 data/openclaw.db "SELECT COUNT(*) FROM positions;"`

---

🖖 **Live long and profit.**
