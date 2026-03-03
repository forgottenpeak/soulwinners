#!/bin/bash
# Deploy fixes + restore wallets + run cleanup safely
# Usage: ./scripts/deploy_and_cleanup.sh

set -e

echo "========================================"
echo "DEPLOYING FIXES + WALLET RESTORATION"
echo "========================================"

# Configuration
REMOTE_USER="root"
REMOTE_HOST="80.240.22.200"
REMOTE_PATH="/root/Soulwinners"
LOCAL_PATH="/Users/APPLE/Desktop/Soulwinners"

echo ""
echo "[1/6] Syncing files to server..."
rsync -avz --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude 'venv' --exclude 'data/*.db' --exclude 'logs/*' \
    "$LOCAL_PATH/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH/"

echo ""
echo "[2/6] Ensuring directories exist..."
ssh "$REMOTE_USER@$REMOTE_HOST" "mkdir -p $REMOTE_PATH/logs $REMOTE_PATH/utils"

echo ""
echo "[3/6] Listing removed wallets..."
ssh "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_PATH/venv/bin/python3 $REMOTE_PATH/scripts/restore_wallets.py --list" || echo "No cleanup log found yet"

echo ""
echo "[4/6] Restoring all recently removed wallets..."
ssh "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_PATH/venv/bin/python3 $REMOTE_PATH/scripts/restore_wallets.py --restore-all --hours 168" || echo "No wallets to restore"

echo ""
echo "[5/6] Running cleanup with FIXED detection (dry-run first)..."
ssh "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_PATH/venv/bin/python3 $REMOTE_PATH/scripts/cleanup_wallets.py --dry-run"

echo ""
echo "[6/6] Installing cron job for weekly cleanup..."
ssh "$REMOTE_USER@$REMOTE_HOST" "cat > /tmp/cleanup_cron.txt << 'EOF'
# Weekly wallet cleanup - Sundays at midnight
0 0 * * 0 $REMOTE_PATH/venv/bin/python3 $REMOTE_PATH/scripts/cleanup_wallets.py --immediate >> $REMOTE_PATH/logs/cleanup_cron.log 2>&1
EOF
crontab -l 2>/dev/null | grep -v 'cleanup_wallets.py' | cat - /tmp/cleanup_cron.txt | crontab -"

echo ""
echo "========================================"
echo "DEPLOYMENT COMPLETE"
echo "========================================"
echo ""
echo "FIXES APPLIED:"
echo "  1. Cleanup script now uses proper key rotation"
echo "  2. Conservative removal (assumes active if uncertain)"
echo "  3. Alerts now fetch LIVE balance from Helius"
echo "  4. Restore script available for wrongly removed wallets"
echo ""
echo "COMMANDS:"
echo "  Restore specific wallet:"
echo "    ssh $REMOTE_USER@$REMOTE_HOST '$REMOTE_PATH/venv/bin/python3 $REMOTE_PATH/scripts/restore_wallets.py --wallet ADDRESS --add-watchlist'"
echo ""
echo "  Run actual cleanup (not dry-run):"
echo "    ssh $REMOTE_USER@$REMOTE_HOST '$REMOTE_PATH/venv/bin/python3 $REMOTE_PATH/scripts/cleanup_wallets.py --immediate'"
echo ""
echo "  View cleanup logs:"
echo "    ssh $REMOTE_USER@$REMOTE_HOST 'tail -f $REMOTE_PATH/logs/cleanup.log'"
