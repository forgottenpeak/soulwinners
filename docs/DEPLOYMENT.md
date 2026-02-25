# Deployment Guide

## Requirements

- **VPS**: Ubuntu 22.04+ (1GB RAM minimum)
- **Python**: 3.10+
- **APIs**: Helius (1-4 keys), Telegram Bot Token

## Quick Deploy

### 1. Server Setup

```bash
# Update system
apt update && apt upgrade -y

# Install Python
apt install python3 python3-pip python3-venv -y

# Create project directory
mkdir -p /root/Soulwinners
cd /root/Soulwinners
```

### 2. Clone Repository

```bash
git clone https://github.com/yourusername/soulwinners.git .
```

### 3. Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Configuration

```bash
# Copy example config
cp .env.example .env

# Edit with your keys
nano .env
```

Required environment variables:
```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHANNEL_ID=your_channel_id
HELIUS_API_KEYS=key1,key2,key3,key4
```

Or edit `config/settings.py` directly.

### 5. Initialize Database

```bash
python3 -c "from database import init_database; init_database()"
```

### 6. Create Systemd Service

```bash
cat > /etc/systemd/system/soulwinners.service << 'EOF'
[Unit]
Description=SoulWinners Bot (Monitor + Commands)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/Soulwinners
ExecStart=/root/Soulwinners/venv/bin/python3 run_bot.py
Restart=always
RestartSec=10
StandardOutput=append:/root/Soulwinners/logs/bot.log
StandardError=append:/root/Soulwinners/logs/bot.log

[Install]
WantedBy=multi-user.target
EOF
```

### 7. Enable Service

```bash
# Create logs directory
mkdir -p /root/Soulwinners/logs

# Reload systemd
systemctl daemon-reload

# Enable auto-start
systemctl enable soulwinners

# Start service
systemctl start soulwinners

# Check status
systemctl status soulwinners
```

### 8. Setup Cron Job

```bash
# Edit crontab
crontab -e

# Add this line (runs every 10 minutes)
*/10 * * * * cd /root/Soulwinners && /root/Soulwinners/venv/bin/python3 run_pipeline.py >> logs/cron.log 2>&1
```

### 9. Verify Deployment

```bash
# Check bot is running
systemctl status soulwinners

# Check cron is scheduled
crontab -l

# Watch logs
tail -f /root/Soulwinners/logs/bot.log

# Test Telegram commands
# Send /start to your bot
```

## Service Management

### Start/Stop/Restart

```bash
systemctl start soulwinners
systemctl stop soulwinners
systemctl restart soulwinners
```

### View Logs

```bash
# Bot logs
tail -f logs/bot.log

# Cron/pipeline logs
tail -f logs/cron.log

# Errors only
grep -i error logs/bot.log
```

### Manual Pipeline Run

```bash
cd /root/Soulwinners
./venv/bin/python3 run_pipeline.py
```

## Updating

```bash
# Stop service
systemctl stop soulwinners

# Pull latest code
git pull origin main

# Install any new dependencies
./venv/bin/pip install -r requirements.txt

# Start service
systemctl start soulwinners
```

## Troubleshooting

### Bot Not Responding

1. Check service status: `systemctl status soulwinners`
2. Check logs: `tail -100 logs/bot.log | grep -i error`
3. Restart: `systemctl restart soulwinners`

### Rate Limiting

If seeing many "Rate limited" warnings:
1. Add more Helius API keys to `config/settings.py`
2. Reduce `TARGET_WALLETS_DAILY` setting
3. Increase delay in `collectors/base.py`

### Database Issues

```bash
# Check database integrity
sqlite3 data/soulwinners.db "PRAGMA integrity_check"

# View qualified wallets
sqlite3 data/soulwinners.db "SELECT COUNT(*) FROM qualified_wallets"
```

### Telegram Conflicts

If seeing "409 Conflict" errors:
- Another bot instance is running
- Kill other instances: `pkill -f run_bot.py`
- Or check for local development instances

## Security

### Firewall

```bash
# Allow SSH only
ufw allow 22
ufw enable
```

### API Keys

- Never commit `.env` or keys to git
- Use environment variables in production
- Rotate keys if compromised

## Monitoring

### Health Check Script

```bash
#!/bin/bash
# health_check.sh

# Check service
if ! systemctl is-active --quiet soulwinners; then
    echo "Service down, restarting..."
    systemctl restart soulwinners
fi

# Check pool size
POOL=$(sqlite3 /root/Soulwinners/data/soulwinners.db "SELECT COUNT(*) FROM qualified_wallets")
echo "Pool size: $POOL wallets"
```

### Uptime Monitoring

Consider using:
- UptimeRobot
- Healthchecks.io
- Custom webhook to Telegram
