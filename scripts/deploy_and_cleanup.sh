#!/bin/bash
# Deploy IQR filtering + cleanup features and run immediately
# Usage: ./scripts/deploy_and_cleanup.sh

set -e

echo "========================================"
echo "DEPLOYING IQR FILTERING + WALLET CLEANUP"
echo "========================================"

# Configuration
REMOTE_USER="root"
REMOTE_HOST="147.79.68.86"  # Update if needed
REMOTE_PATH="/root/Soulwinners"
LOCAL_PATH="/Users/APPLE/Desktop/Soulwinners"

echo ""
echo "[1/5] Syncing files to server..."
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude 'venv' --exclude 'data/*.db' --exclude 'logs/*' \
    "$LOCAL_PATH/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH/"

echo ""
echo "[2/5] Ensuring logs directory exists..."
ssh "$REMOTE_USER@$REMOTE_HOST" "mkdir -p $REMOTE_PATH/logs"

echo ""
echo "[3/5] Installing/updating cron job..."
ssh "$REMOTE_USER@$REMOTE_HOST" "cat > /tmp/cleanup_cron.txt << 'EOF'
# Weekly wallet cleanup - Sundays at midnight
0 0 * * 0 $REMOTE_PATH/venv/bin/python3 $REMOTE_PATH/scripts/cleanup_wallets.py >> $REMOTE_PATH/logs/cleanup_cron.log 2>&1
EOF
crontab -l 2>/dev/null | grep -v 'cleanup_wallets.py' | cat - /tmp/cleanup_cron.txt | crontab -"

echo ""
echo "[4/5] Running immediate cleanup..."
ssh "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_PATH/venv/bin/python3 $REMOTE_PATH/scripts/cleanup_wallets.py --immediate"

echo ""
echo "[5/5] Restarting bot services..."
ssh "$REMOTE_USER@$REMOTE_HOST" "systemctl restart soulwinners-bot 2>/dev/null || echo 'Note: Manual restart may be needed'"

echo ""
echo "========================================"
echo "DEPLOYMENT COMPLETE"
echo "========================================"
echo ""
echo "New features active:"
echo "  - IQR filtering for robust averages"
echo "  - /stats now shows Raw vs Robust metrics"
echo "  - Weekly cleanup runs Sundays at midnight"
echo ""
echo "To check cleanup logs: ssh $REMOTE_USER@$REMOTE_HOST 'tail -f $REMOTE_PATH/logs/cleanup.log'"
