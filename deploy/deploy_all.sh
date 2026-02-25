#!/bin/bash
# Full SoulWinners Deployment Script
# Includes: SoulWinners + OpenClaw + Insider Detection
# Run this on the VPS: bash deploy/deploy_all.sh

set -e

echo "================================================"
echo "SOULWINNERS FULL DEPLOYMENT"
echo "================================================"

cd /root/Soulwinners

# 1. Pull latest code
echo ""
echo "[1/8] Pulling latest code..."
git pull origin main

# 2. Install dependencies
echo ""
echo "[2/8] Installing dependencies..."
./venv/bin/pip install solana solders base58 websockets aiohttp --quiet

# 3. Initialize database
echo ""
echo "[3/8] Initializing database..."
./venv/bin/python3 -c "from database import init_database; init_database()"

# 4. Update min_buy_amount to 1.0 SOL
echo ""
echo "[4/8] Updating settings..."
./venv/bin/python3 -c "
from database import get_connection
conn = get_connection()
conn.execute(\"UPDATE settings SET value = '1.0' WHERE key = 'min_buy_amount'\")
conn.commit()
conn.close()
print('✓ MIN_BUY_AMOUNT set to 1.0 SOL')
"

# 5. Create logs directory
echo ""
echo "[5/8] Setting up directories..."
mkdir -p logs data

# 6. Install systemd services
echo ""
echo "[6/8] Installing systemd services..."
cp deploy/soulwinners.service /etc/systemd/system/ 2>/dev/null || true
cp deploy/openclaw.service /etc/systemd/system/ 2>/dev/null || true
cp deploy/insider.service /etc/systemd/system/
systemctl daemon-reload

# 7. Test modules
echo ""
echo "[7/8] Testing modules..."
./venv/bin/python3 -c "from bot.realtime_monitor import RealTimeMonitor; print('✓ Realtime Monitor loaded')"
./venv/bin/python3 -c "from pipeline.insider_detector import InsiderDetector; print('✓ Insider Detector loaded')"
./venv/bin/python3 -c "from pipeline.cluster_detector import ClusterDetector; print('✓ Cluster Detector loaded')"
./venv/bin/python3 -c "from collectors.launch_tracker import LaunchTracker; print('✓ Launch Tracker loaded')"

# 8. Show status
echo ""
echo "[8/8] Checking service status..."
echo ""

echo "================================================"
echo "DEPLOYMENT COMPLETE"
echo "================================================"
echo ""
echo "Services installed:"
echo "  • soulwinners.service - Main tracker + alerts"
echo "  • openclaw.service    - Auto-trader (optional)"
echo "  • insider.service     - Insider detection"
echo ""
echo "Commands:"
echo ""
echo "  # Start all services:"
echo "  systemctl enable soulwinners insider"
echo "  systemctl start soulwinners insider"
echo ""
echo "  # Check status:"
echo "  systemctl status soulwinners"
echo "  systemctl status insider"
echo ""
echo "  # View logs:"
echo "  tail -f logs/soulwinners.log"
echo "  tail -f logs/insider.log"
echo ""
echo "  # Test insider detection:"
echo "  ./venv/bin/python3 run_insider.py --scan"
echo "  ./venv/bin/python3 run_insider.py --insiders"
echo "  ./venv/bin/python3 run_insider.py --clusters"
echo ""
echo "Updates deployed:"
echo "  ✓ MIN_BUY_AMOUNT = 1.0 SOL"
echo "  ✓ Accumulation detection (multiple buys in 30 min)"
echo "  ✓ Aggregate stats in alerts (replaces Last 5 Trades)"
echo "  ✓ Insider Detection Pipeline"
echo "  ✓ Cluster Detection / Bubble Map"
echo ""
