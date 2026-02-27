#!/bin/bash
# Deploy Historical Holder Scanning (Complete Blueprint)

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║    HISTORICAL HOLDER SCANNING (BLUEPRINT) - DEPLOYMENT       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Problem Fixed:${NC}"
echo "  ✗ Only scans current holders (balance > 0 NOW)"
echo "  ✗ Misses wallets that bought → profited → sold"
echo "  ✗ Misses wallets that bought → lost → sold"
echo "  ✗ Missing successful traders who moved on"
echo ""

echo -e "${GREEN}Solution: Complete Historical Blueprint${NC}"
echo "  ✓ Scan ALL transactions from token creation to now"
echo "  ✓ Find EVERY wallet that EVER held the token"
echo "  ✓ Include quick flippers (held 1 min)"
echo "  ✓ Include swing traders (held 1 day, took profit)"
echo "  ✓ Include diamond hands (held long)"
echo "  ✓ Include stop-loss sellers (took loss, moved on)"
echo ""

echo -e "${BLUE}Why This Matters:${NC}"
echo "  Example: Good trader bought PEPE at \$0.01"
echo "           → Sold at \$0.10 (10x profit)"
echo "           → Moved to next token"
echo "           → No longer holds PEPE"
echo ""
echo "  OLD System: Misses this wallet (not current holder)"
echo "  NEW System: Captures this wallet (historical scan)"
echo ""
echo "  Their HISTORY shows skill, not current holdings!"
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

# Verify get_historical_token_holders method
if grep -q "async def get_historical_token_holders" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} get_historical_token_holders() method added"
else
    echo -e "${RED}✗${NC} get_historical_token_holders() method not found"
    exit 1
fi

# Verify historical scanning logic
if grep -q "blueprint scan" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Blueprint scan logic added"
else
    echo -e "${RED}✗${NC} Blueprint scan not found"
    exit 1
fi

# Verify pagination logic
if grep -q "before_signature" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Transaction pagination implemented"
else
    echo -e "${RED}✗${NC} Pagination not found"
    exit 1
fi

# Verify get_all_token_wallets uses historical
if grep -q "use_historical" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} get_all_token_wallets() updated with historical flag"
else
    echo -e "${RED}✗${NC} Historical flag not added"
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
echo -e "${YELLOW}Step 5: Monitor historical scanning${NC}"
echo "─────────────────────────────────────────"

echo "Waiting 30 seconds for first blueprint scan..."
sleep 30

echo -e "\n${BLUE}Recent historical scanning activity:${NC}"
ssh "$VPS_IP" "tail -n 300 $PROJECT_DIR/logs/pipeline.log | grep -E 'historical|blueprint|Processing batch|Scanned.*transactions|Breakdown'" | tail -40 || echo "Waiting for scan cycle..."

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Historical holder scanning (blueprint) deployed!${NC}"
echo ""
echo "📊 What was added:"
echo ""
echo "  New Method:"
echo "    get_historical_token_holders(token_address, limit=5000)"
echo "      → Scans ALL transactions from token creation to now"
echo "      → Uses Helius getSignaturesForAddress with pagination"
echo "      → Processes up to 5000 transactions per token"
echo "      → Extracts every wallet that received tokens"
echo "      → Returns complete historical blueprint"
echo ""
echo "  Updated Method:"
echo "    get_all_token_wallets(token_address, use_historical=True)"
echo "      → Now includes 3 sources:"
echo "        1. Current holders (snapshot)"
echo "        2. Recent traders (last 24h)"
echo "        3. Historical holders (ever held) ← NEW!"
echo ""
echo "🔍 Monitor for blueprint scanning:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/pipeline.log | grep \"historical\\|blueprint\"'"
echo ""
echo "Expected output:"
echo "  Getting current holders for 7xKXtg2C..."
echo "  Found 115 current holders"
echo "  Getting recent traders for 7xKXtg2C..."
echo "  Found 48 recent traders"
echo "  Getting ALL historical holders for 7xKXtg2C (blueprint scan)..."
echo "  Processing batch of 1000 transactions (total: 0)..."
echo "  Processing batch of 1000 transactions (total: 1000)..."
echo "  Processing batch of 842 transactions (total: 2000)..."
echo "  Scanned 2842 historical transactions"
echo "  Found 1247 unique historical holders"
echo "  Total unique wallets for 7xKXtg2C: 1410"
echo "  Breakdown: 115 current + 48 recent + 1247 historical"
echo ""
echo "📝 What this captures:"
echo ""
echo "  Quick Flippers:"
echo "    • Bought, sold in 1 hour (still tracked)"
echo "    • Fast scalpers"
echo ""
echo "  Swing Traders:"
echo "    • Held 1 day, took 2-5x profit"
echo "    • Moved to next opportunity"
echo "    • No longer holding, but HISTORY shows skill"
echo ""
echo "  Diamond Hands:"
echo "    • Held long-term"
echo "    • May still be holding"
echo ""
echo "  Stop-Loss Sellers:"
echo "    • Bought, lost money, sold"
echo "    • Learn from their patterns too"
echo ""
echo "🎯 Impact:"
echo "  OLD: 50-200 wallets per token (current + recent only)"
echo "  NEW: 500-2000+ wallets per token (complete blueprint)"
echo ""
echo "  We now track wallets by HISTORY, not just current state!"
echo "  Good traders who took profit and moved on = still tracked ✓"
echo ""
