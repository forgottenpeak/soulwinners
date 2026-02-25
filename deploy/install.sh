#!/bin/bash
# SoulWinners VPS Deployment Script
# Run on Ubuntu 24.04 VPS

set -e

echo "=========================================="
echo "SoulWinners VPS Installation"
echo "=========================================="

# Update system
echo "[1/7] Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Python 3.11+
echo "[2/7] Installing Python..."
sudo apt-get install -y python3.11 python3.11-venv python3-pip

# Install system dependencies
echo "[3/7] Installing system dependencies..."
sudo apt-get install -y git curl htop supervisor

# Create app directory
echo "[4/7] Creating application directory..."
sudo mkdir -p /opt/soulwinners
sudo chown $USER:$USER /opt/soulwinners

# Copy files (assumes files are in current directory)
echo "[5/7] Setting up application..."
cd /opt/soulwinners

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install Python dependencies
echo "[6/7] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create directories
mkdir -p data logs

# Initialize database
python -c "from database import init_database; init_database()"

# Setup supervisor for process management
echo "[7/7] Configuring supervisor..."
sudo tee /etc/supervisor/conf.d/soulwinners.conf << EOF
[program:soulwinners]
command=/opt/soulwinners/venv/bin/python /opt/soulwinners/main.py
directory=/opt/soulwinners
user=$USER
autostart=true
autorestart=true
stderr_logfile=/opt/soulwinners/logs/error.log
stdout_logfile=/opt/soulwinners/logs/output.log
environment=PYTHONPATH="/opt/soulwinners"
EOF

sudo supervisorctl reread
sudo supervisorctl update

echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Copy your project files to /opt/soulwinners/"
echo "2. Create .env file with your API keys"
echo "3. Start the service: sudo supervisorctl start soulwinners"
echo "4. Check logs: tail -f /opt/soulwinners/logs/output.log"
echo ""
