# V'ger Quick Start Guide

## One-Command Deploy (VPS)

```bash
ssh root@your-vps-ip
cd /root/Soulwinners
sudo bash deployment/deploy_vger.sh
```

## Test V'ger

1. Open Telegram
2. Search for `@vgerr_bot`
3. Send `/start`
4. Send `/status`

## Essential Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/status` | Current status | `/status` |
| `/portfolio` | All positions | `/portfolio` |
| `/exit <token>` | Close position | `/exit BONK` |
| `/settings` | View settings | `/settings` |
| `/set <param> <val>` | Change setting | `/set stop_loss 15` |
| `/balance` | SOL balance | `/balance` |
| `/report` | Today's P&L | `/report` |
| `/history` | Last 10 trades | `/history` |

## Quick Operations

### Check Balance
```
/balance
```

### Close Position
```
/exit BONK
```
(Confirm with button)

### Change Stop Loss to -15%
```
/set stop_loss 15
```

### View Today's Trades
```
/report
```

## Service Commands (VPS)

```bash
# Status
sudo systemctl status vger

# Restart
sudo systemctl restart vger

# Logs
tail -f /root/Soulwinners/logs/vger.log

# Live system logs
sudo journalctl -u vger -f
```

## Troubleshooting

### Bot not responding?
```bash
sudo systemctl restart vger
sudo systemctl status vger
```

### Check logs
```bash
tail -n 100 /root/Soulwinners/logs/vger.log
```

### Verify it's running
```bash
ps aux | grep v_ger_bot
```

## Security

- **Only YOU can use V'ger** (User ID: 1153491543)
- All commands require confirmation
- Every action is logged
- No one else can access your trader

---

**Bot:** @vgerr_bot
**Admin:** 1153491543
**Status:** 🟢 Online
