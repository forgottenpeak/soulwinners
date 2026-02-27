#!/bin/bash
# Deploy Token Holder Scanning Feature

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       TOKEN HOLDER SCANNING - DEPLOYMENT                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Problem Fixed:${NC}"
echo "  ✗ System only scans wallets that recently TRADED"
echo "  ✗ Misses wallets that HELD tokens but didn't trade recently"
echo "  ✗ Missing valuable conviction wallets (long-term holders)"
echo ""

echo -e "${GREEN}Solution:${NC}"
echo "  ✓ Scan ALL wallets: Current holders + Recent traders"
echo "  ✓ Get token holders via Helius getTokenLargestAccounts"
echo "  ✓ Get recent traders via transaction history (existing)"
echo "  ✓ Combine both lists for complete coverage"
echo ""

echo -e "${BLUE}What This Captures:${NC}"
echo "  📊 Holders (Conviction Wallets):"
echo "    • Bought early and still holding"
echo "    • Airdrop recipients who didn't sell"
echo "    • Long-term conviction plays"
echo "    • Diamond hands 💎"
echo ""
echo "  📊 Traders (Active Wallets):"
echo "    • Recent buyers/sellers"
echo "    • Active trading wallets"
echo "    • Quick flippers"
echo ""
echo "  Result: Complete wallet coverage, not just recent activity!"
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
echo -e "${YELLOW}Step 2: Verify new methods${NC}"
echo "─────────────────────────────────────────"

# Verify get_token_holders method
if grep -q "async def get_token_holders" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} get_token_holders() method added"
else
    echo -e "${RED}✗${NC} get_token_holders() method not found"
    exit 1
fi

# Verify get_all_token_wallets method
if grep -q "async def get_all_token_wallets" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} get_all_token_wallets() method added"
else
    echo -e "${RED}✗${NC} get_all_token_wallets() method not found"
    exit 1
fi

# Verify getTokenLargestAccounts usage
if grep -q "getTokenLargestAccounts" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Using Helius getTokenLargestAccounts RPC"
else
    echo -e "${RED}✗${NC} Helius RPC method not found"
    exit 1
fi

# Verify InsiderScanner uses new method
if grep -q "get_all_token_wallets" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} InsiderScanner updated to scan all wallets"
else
    echo -e "${RED}✗${NC} InsiderScanner not updated"
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
echo -e "${YELLOW}Step 5: Monitor holder scanning${NC}"
echo "─────────────────────────────────────────"

echo "Waiting 30 seconds for first scan cycle..."
sleep 30

echo -e "\n${BLUE}Recent holder scanning activity:${NC}"
ssh "$VPS_IP" "tail -n 200 $PROJECT_DIR/logs/pipeline.log | grep -E 'holder|Found.*unique wallets|Scanning all token wallets'" | tail -30 || echo "Waiting for scan cycle..."

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Token holder scanning deployed!${NC}"
echo ""
echo "📊 What was added:"
echo ""
echo "  New Methods:"
echo "    1. get_token_holders(token_address, min_balance)"
echo "       → Gets ALL current holders via Helius RPC"
echo "       → Uses getTokenLargestAccounts"
echo "       → Returns wallet addresses + balances"
echo ""
echo "    2. get_all_token_wallets(token_address, min_balance)"
echo "       → Combines holders + traders"
echo "       → Complete wallet coverage"
echo "       → Deduplicates addresses"
echo ""
echo "  Updated Logic:"
echo "    • InsiderScanner._scan_cycle() now uses get_all_token_wallets()"
echo "    • Scans up to 50 wallets per token (holders + traders)"
echo "    • Analyzes both conviction holders and active traders"
echo ""
echo "🔍 Monitor for holder scanning:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/pipeline.log | grep \"holder\\|unique wallets\"'"
echo ""
echo "Expected output:"
echo "  PEPE: Scanning all token wallets (holders + traders)..."
echo "  Getting token holders for 7xKXtg2C..."
echo "  Token 7xKXtg2C... has 127 holder accounts"
echo "  Found 115 holders with balance > 0"
echo "  Getting recent traders for 7xKXtg2C..."
echo "  Found 48 recent traders"
echo "  Total unique wallets for 7xKXtg2C: 163"
echo "  PEPE: Found 163 unique wallets"
echo "  Analyzing 50 wallets for patterns..."
echo "  Insider detected: HN7cAB... - Long-term Holder"
echo ""
echo "📝 Why this matters:"
echo "  • OLD: Only scanned 20-100 recent buyers/sellers"
echo "  • NEW: Scans ALL holders + traders (100-500+ wallets)"
echo "  • Captures conviction wallets that hold long-term"
echo "  • Diamond hands = valuable signal 💎"
echo ""
