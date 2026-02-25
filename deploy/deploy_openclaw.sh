#!/bin/bash
# OpenClaw Deployment Script
# Run this on the VPS: bash deploy_openclaw.sh

set -e

echo "================================================"
echo "OPENCLAW DEPLOYMENT"
echo "================================================"

cd /root/Soulwinners

# 1. Pull latest code
echo ""
echo "[1/6] Pulling latest code..."
git pull origin main

# 2. Install new dependencies
echo ""
echo "[2/6] Installing Solana dependencies..."
./venv/bin/pip install solana solders base58

# 3. Check if .env has OpenClaw config
echo ""
echo "[3/6] Checking .env configuration..."
if grep -q "OPENCLAW_PRIVATE_KEY" .env 2>/dev/null; then
    echo "✓ OPENCLAW_PRIVATE_KEY found in .env"
else
    echo "⚠ Adding OPENCLAW_PRIVATE_KEY placeholder to .env"
    echo "" >> .env
    echo "# OpenClaw Auto-Trader" >> .env
    echo "OPENCLAW_PRIVATE_KEY=YOUR_PRIVATE_KEY_HERE" >> .env
    echo "OPENCLAW_CHAT_ID=1153491543" >> .env
    echo ""
    echo ">>> IMPORTANT: Edit .env and add your Solana private key!"
    echo ">>> nano .env"
fi

# 4. Create logs directory
echo ""
echo "[4/6] Setting up directories..."
mkdir -p logs data

# 5. Install systemd service
echo ""
echo "[5/6] Installing systemd service..."
cp deploy/openclaw.service /etc/systemd/system/
systemctl daemon-reload

# 6. Test the installation
echo ""
echo "[6/6] Testing OpenClaw..."
./venv/bin/python3 -c "from trader import OpenClawTrader; print('✓ OpenClaw module loaded successfully')"

echo ""
echo "================================================"
echo "DEPLOYMENT COMPLETE"
echo "================================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Add your Solana private key to .env:"
echo "   nano .env"
echo "   OPENCLAW_PRIVATE_KEY=your_88_char_base58_key"
echo ""
echo "2. Test wallet connection:"
echo "   ./venv/bin/python3 run_openclaw.py --balance"
echo ""
echo "3. Start the service:"
echo "   systemctl enable openclaw"
echo "   systemctl start openclaw"
echo ""
echo "4. Check status:"
echo "   systemctl status openclaw"
echo "   tail -f logs/openclaw.log"
echo ""
