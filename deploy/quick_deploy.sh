#!/bin/bash
# Quick VPS Deployment Script
# Copy-paste this entire script into your VPS terminal

set -e

echo "╔════════════════════════════════════════════════╗"
echo "║   SOULWINNERS DEPLOYMENT - STARTING NOW       ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# Navigate to project
cd /root/Soulwinners || { echo "Error: /root/Soulwinners not found"; exit 1; }

# Pull latest code
echo "[1/5] Pulling latest code from GitHub..."
git pull origin main

# Run deployment script
echo ""
echo "[2/5] Running automated deployment..."
bash deploy/deploy_all.sh

# Enable services
echo ""
echo "[3/5] Enabling services..."
systemctl enable soulwinners insider

# Start services
echo ""
echo "[4/5] Starting services..."
systemctl start soulwinners insider

# Wait a moment
sleep 3

# Verify
echo ""
echo "[5/5] Verifying deployment..."
echo ""

# Check service status
if systemctl is-active --quiet soulwinners; then
    echo "✅ soulwinners.service - RUNNING"
else
    echo "❌ soulwinners.service - FAILED"
fi

if systemctl is-active --quiet insider; then
    echo "✅ insider.service - RUNNING"
else
    echo "❌ insider.service - FAILED"
fi

# Check database
echo ""
./venv/bin/python3 << 'PYTHON_EOF'
from database import get_connection
conn = get_connection()

wallets = conn.execute('SELECT COUNT(*) FROM qualified_wallets').fetchone()[0]
print(f'✅ Qualified wallets: {wallets}')

try:
    insiders = conn.execute('SELECT COUNT(*) FROM insider_pool').fetchone()[0]
    print(f'✅ Insider pool: {insiders}')
except:
    print('⚠️  Insider pool: Table will be created on first scan')

try:
    clusters = conn.execute('SELECT COUNT(*) FROM wallet_clusters').fetchone()[0]
    print(f'✅ Wallet clusters: {clusters}')
except:
    print('⚠️  Wallet clusters: Table will be created on first scan')

# Check threshold setting
threshold = conn.execute('SELECT value FROM settings WHERE key="min_buy_amount"').fetchone()
if threshold:
    print(f'✅ MIN_BUY_AMOUNT: {threshold[0]} SOL')
else:
    print('⚠️  MIN_BUY_AMOUNT: Not set (using default)')

conn.close()
PYTHON_EOF

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║         DEPLOYMENT COMPLETE!                   ║"
echo "╚════════════════════════════════════════════════╝"
echo ""
echo "🎯 What's Running:"
echo "  • SoulWinners Monitor (1.0 SOL threshold)"
echo "  • Insider Detection Pipeline"
echo "  • Cluster Detection System"
echo ""
echo "📊 Next Steps:"
echo "  1. Check logs:"
echo "     tail -f logs/soulwinners.log"
echo "     tail -f logs/insider.log"
echo ""
echo "  2. Monitor services:"
echo "     systemctl status soulwinners"
echo "     systemctl status insider"
echo ""
echo "  3. Test Telegram commands:"
echo "     /cluster"
echo "     /insiders"
echo "     /status"
echo ""
echo "  4. View stats:"
echo "     ./venv/bin/python3 run_insider.py --stats"
echo ""
echo "⏰ Expected Timeline:"
echo "  • 5 min:  First alerts with 1.0 SOL threshold"
echo "  • 1 hour: 10-30 insiders detected"
echo "  • 1 day:  30-50+ insiders, 10-20 clusters"
echo ""
echo "📖 Full docs: cat DEPLOYMENT.md"
echo ""
