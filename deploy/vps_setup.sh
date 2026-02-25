#!/bin/bash
# VPS Setup Script for SoulWinners
# Run this on the VPS after copying files

set -e

PROJECT_DIR="/root/soulwinners"
PYTHON="/usr/bin/python3"

echo "=========================================="
echo "SoulWinners VPS Setup"
echo "=========================================="

# Install Python dependencies
echo "Installing Python dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv

cd $PROJECT_DIR

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install requirements
pip install --upgrade pip
pip install -r requirements.txt

# Create logs directory
mkdir -p logs

# Create systemd service for monitor
echo "Creating systemd service..."
cat > /etc/systemd/system/soulwinners.service << 'EOF'
[Unit]
Description=SoulWinners Real-Time Monitor
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/soulwinners
ExecStart=/root/soulwinners/venv/bin/python3 run_monitor.py
Restart=always
RestartSec=10
StandardOutput=append:/root/soulwinners/logs/monitor.log
StandardError=append:/root/soulwinners/logs/monitor.log

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
systemctl daemon-reload
systemctl enable soulwinners.service

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "Commands:"
echo "  Start:   systemctl start soulwinners"
echo "  Stop:    systemctl stop soulwinners"
echo "  Status:  systemctl status soulwinners"
echo "  Logs:    journalctl -u soulwinners -f"
echo "           tail -f /root/soulwinners/logs/monitor.log"
echo ""
echo "Cron job for daily pipeline:"
echo "  0 0 * * * cd /root/soulwinners && ./venv/bin/python3 run_pipeline.py >> logs/cron.log 2>&1"
