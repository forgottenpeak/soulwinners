#!/bin/bash
# Deploy SoulWinners to VPS
# Usage: ./deploy_to_vps.sh

set -e

VPS_HOST="80.240.22.200"
VPS_USER="root"
APP_DIR="/root/soulwinners"
LOCAL_DIR="$(dirname "$0")/.."

echo "=========================================="
echo "Deploying SoulWinners to VPS"
echo "=========================================="
echo "VPS: ${VPS_USER}@${VPS_HOST}"
echo "Remote: $APP_DIR"
echo ""

# Step 1: Create tarball
echo "[1/5] Creating deployment package..."
cd "$LOCAL_DIR"
tar -czf /tmp/soulwinners.tar.gz \
    --exclude='*.pyc' \
    --exclude='__pycache__' \
    --exclude='.git' \
    --exclude='logs/*.log' \
    --exclude='venv' \
    --exclude='.DS_Store' \
    .

# Step 2: Copy to VPS
echo "[2/5] Copying files to VPS..."
scp /tmp/soulwinners.tar.gz ${VPS_USER}@${VPS_HOST}:/tmp/

# Step 3: Extract and setup
echo "[3/5] Setting up on VPS..."
ssh ${VPS_USER}@${VPS_HOST} << 'ENDSSH'
    set -e
    APP_DIR="/root/soulwinners"

    # Stop existing service if running
    systemctl stop soulwinners 2>/dev/null || true

    # Create and extract
    mkdir -p $APP_DIR
    cd $APP_DIR
    tar -xzf /tmp/soulwinners.tar.gz

    # Install system dependencies
    apt-get update -qq
    apt-get install -y -qq python3 python3-pip python3-venv

    # Setup virtual environment
    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi

    source venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt -q

    # Create directories
    mkdir -p data logs

    echo "Dependencies installed"
ENDSSH

# Step 4: Copy database with qualified wallets
echo "[4/5] Copying database..."
scp "$LOCAL_DIR/data/soulwinners.db" ${VPS_USER}@${VPS_HOST}:${APP_DIR}/data/

# Step 5: Setup systemd service and cron
echo "[5/5] Setting up service and cron..."
ssh ${VPS_USER}@${VPS_HOST} << 'ENDSSH'
    APP_DIR="/root/soulwinners"

    # Create systemd service
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

    # Enable and start service
    systemctl daemon-reload
    systemctl enable soulwinners
    systemctl start soulwinners

    # Setup cron for daily pipeline
    (crontab -l 2>/dev/null | grep -v 'soulwinners' || true; echo "0 0 * * * cd /root/soulwinners && ./venv/bin/python3 run_pipeline.py >> logs/cron.log 2>&1") | crontab -

    # Show status
    sleep 2
    systemctl status soulwinners --no-pager || true
    echo ""
    echo "Cron jobs:"
    crontab -l
ENDSSH

echo ""
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Commands:"
echo "  Status:  ssh ${VPS_USER}@${VPS_HOST} 'systemctl status soulwinners'"
echo "  Logs:    ssh ${VPS_USER}@${VPS_HOST} 'tail -f /root/soulwinners/logs/monitor.log'"
echo "  Restart: ssh ${VPS_USER}@${VPS_HOST} 'systemctl restart soulwinners'"
echo ""
