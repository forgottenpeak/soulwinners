#!/bin/bash
# Deploy Smart Holder Scanning Strategy

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║      SMART HOLDER STRATEGY - DEPLOYMENT                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Current Problem:${NC}"
echo "  ✗ Scanning current holders of 11-23h old tokens"
echo "  ✗ Finds bag holders (down money, still holding)"
echo "  ✗ Misses winners (took profit, moved on)"
echo ""

echo -e "${GREEN}Solution: Age-Based Strategy${NC}"
echo ""
echo "  For tokens < 1 hour old:"
echo "    ✓ Scan current holders (no one sold yet)"
echo "    ✓ Detect airdrops (team members)"
echo "    ✓ Everyone still holding = valid targets"
echo ""
echo "  For tokens 1-24 hours old:"
echo "    ✓ Scan ALL historical buyers (since creation)"
echo "    ✓ Skip current holders (bag holders)"
echo "    ✓ Skip airdrop detection (already sold)"
echo "    ✓ Find winners who took profit and left"
echo ""
echo -e "${BLUE}Why This Works:${NC}"
echo "  • Fresh tokens: No profit-taking yet"
echo "  • Older tokens: Smart traders already exited"
echo "  • We want winners, not bag holders!"
echo ""

VPS_IP="${1:-root@your-vps-ip}"
PROJECT_DIR="/root/Soulwinners"

echo -e "${YELLOW}Step 1: Verify local files${NC}"
echo "─────────────────────────────────────────"

python3 -m py_compile collectors/launch_tracker.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Syntax check passed: launch_tracker.py"
else
    echo -e "${RED}✗${NC} Syntax errors in launch_tracker.py"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 2: Verify strategy logic${NC}"
echo "─────────────────────────────────────────"

# Verify age-based logic
if grep -q "if age_hours < 1:" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Age-based strategy implemented"
else
    echo -e "${RED}✗${NC} Age-based logic not found"
    exit 1
fi

# Verify fresh token handling
if grep -q "FRESH token - scanning current holders" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Fresh token strategy (<1h)"
else
    echo -e "${RED}✗${NC} Fresh token strategy not found"
    exit 1
fi

# Verify older token handling
if grep -q "OLDER token - scanning ALL historical buyers" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Older token strategy (1-24h)"
else
    echo -e "${RED}✗${NC} Older token strategy not found"
    exit 1
fi

# Verify bag holder skip
if grep -q "not bag holders" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Bag holder logic (skip current holders for old tokens)"
else
    echo -e "${RED}✗${NC} Bag holder skip not found"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 3: Deploy to VPS${NC}"
echo "─────────────────────────────────────────"

scp collectors/launch_tracker.py "$VPS_IP:$PROJECT_DIR/collectors/launch_tracker.py"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Deployed: launch_tracker.py"
else
    echo -e "${RED}✗${NC} Failed to deploy launch_tracker.py"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 4: Restart service${NC}"
echo "─────────────────────────────────────────"

ssh "$VPS_IP" "systemctl restart soulwinners && sleep 3 && systemctl is-active soulwinners"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Service restarted"
else
    echo -e "${RED}✗${NC} Service restart failed"
    exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Smart holder strategy deployed!${NC}"
echo ""
echo "📊 Strategy Logic:"
echo ""
echo "  Token Age < 1 Hour (Fresh):"
echo "    1. Calculate age from launch_time"
echo "    2. If age < 1h:"
echo "       - Scan current holders (no one sold yet)"
echo "       - Scan recent traders"
echo "       - Detect airdrops (team members)"
echo "       - Save all findings"
echo ""
echo "  Token Age 1-24 Hours (Older):"
echo "    1. Calculate age from launch_time"
echo "    2. If age >= 1h:"
echo "       - Scan ALL historical buyers (since creation)"
echo "       - Skip current holders (bag holders)"
echo "       - Skip airdrop detection (pointless)"
echo "       - Find winners who took profit"
echo ""
echo "🔍 Monitor for strategy in action:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/pipeline.log | grep -E \"Age|FRESH|OLDER|bag holders\"'"
echo ""
echo "Expected output (Fresh token):"
echo "  PEPE: Age 0.3h (18 min)"
echo "  PEPE: FRESH token - scanning current holders + traders"
echo "  Found 163 wallets (current + recent)"
echo "  Scanning for airdrop recipients (team members)..."
echo "  Found 12 airdrop recipients"
echo ""
echo "Expected output (Older token):"
echo "  DOGE: Age 5.7h (342 min)"
echo "  DOGE: OLDER token - scanning ALL historical buyers (not bag holders)"
echo "  Found 847 historical buyers (since creation)"
echo "  Strategy: Skip current holders (bag holders), find winners who took profit"
echo "  Skipping airdrop detection (older token - airdrops already sold)"
echo ""
echo "📝 Why this strategy is correct:"
echo ""
echo "  Fresh Tokens (<1h):"
echo "    • No one has taken profit yet"
echo "    • Everyone still holding = valid"
echo "    • Airdrops still detectable"
echo "    • Current holders = potential winners"
echo ""
echo "  Older Tokens (1-24h):"
echo "    • Smart traders already exited with profit"
echo "    • Current holders = bag holders (losing money)"
echo "    • Historical buyers = includes the winners"
echo "    • We want to track the WINNERS, not losers!"
echo ""
echo "💡 Example:"
echo "  Token launched 12 hours ago:"
echo "    • Wallet A: Bought at \$0.01, sold at \$0.10 (10x profit) ← WINNER!"
echo "    • Wallet B: Bought at \$0.05, still holding at \$0.02 (down 60%) ← Bag holder"
echo ""
echo "  OLD Strategy: Would find Wallet B (current holder)"
echo "  NEW Strategy: Finds Wallet A (historical buyer)"
echo ""
echo "  We want Wallet A's future trades, not Wallet B's!"
echo ""
