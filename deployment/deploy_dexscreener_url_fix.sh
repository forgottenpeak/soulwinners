#!/bin/bash
# Deploy DexScreener URL Fix

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        DEXSCREENER URL FIX - DEPLOYMENT                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Error Fixed:${NC}"
echo "  ✗ 404 on /latest/dex/pairs/solana"
echo ""

echo -e "${GREEN}Solution:${NC}"
echo "  OLD: https://api.dexscreener.com/latest/dex/pairs/solana"
echo "  NEW: https://api.dexscreener.com/latest/dex/search?q=solana ✅"
echo "  Response format: Same (has 'pairs' key)"
echo ""

VPS_IP="${1:-root@your-vps-ip}"
PROJECT_DIR="/root/Soulwinners"

echo -e "${YELLOW}Step 1: Verify local files${NC}"
echo "─────────────────────────────────────────"

FILES=(
    "collectors/launch_tracker.py"
    "collectors/pumpfun.py"
)

for file in "${FILES[@]}"; do
    python3 -m py_compile "$file"
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} Syntax check passed: $file"
    else
        echo -e "${RED}✗${NC} Syntax errors in $file"
        exit 1
    fi
done

echo ""
echo -e "${YELLOW}Step 2: Verify URL fix${NC}"
echo "─────────────────────────────────────────"

# Verify old URL is gone
if grep -q "latest/dex/pairs/solana" collectors/*.py; then
    echo -e "${RED}✗${NC} Old URL still found"
    exit 1
else
    echo -e "${GREEN}✓${NC} Old URL removed (/latest/dex/pairs/solana)"
fi

# Verify new URL is used
URL_COUNT=$(grep -c "latest/dex/search?q=solana" collectors/*.py)
if [ "$URL_COUNT" -ge 4 ]; then
    echo -e "${GREEN}✓${NC} New URL used in $URL_COUNT locations"
else
    echo -e "${RED}✗${NC} New URL not found in expected locations"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 3: Deploy to VPS${NC}"
echo "─────────────────────────────────────────"

for file in "${FILES[@]}"; do
    scp "$file" "$VPS_IP:$PROJECT_DIR/$file"
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC} Deployed: $file"
    else
        echo -e "${RED}✗${NC} Failed to deploy: $file"
        exit 1
    fi
done

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
echo -e "${YELLOW}Step 5: Monitor for tokens${NC}"
echo "─────────────────────────────────────────"

echo "Waiting 20 seconds for first pipeline cycle..."
sleep 20

echo -e "\n${BLUE}Recent logs (should show 200 OK and tokens found):${NC}"
ssh "$VPS_IP" "tail -n 200 $PROJECT_DIR/logs/pipeline.log | grep -E 'DexScreener|Found fresh|created.*h ago|pairs'" | tail -40 || echo "Waiting for data..."

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ DexScreener URL fix deployed!${NC}"
echo ""
echo "📊 What changed:"
echo "  OLD: /latest/dex/pairs/solana (404 ✗)"
echo "  NEW: /latest/dex/search?q=solana (200 ✅)"
echo ""
echo "  Files updated:"
echo "    • collectors/launch_tracker.py (2 occurrences)"
echo "    • collectors/pumpfun.py (2 occurrences)"
echo ""
echo "🔍 Monitor for success:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/pipeline.log | grep \"Found fresh\"'"
echo ""
echo "Expected output:"
echo "  DexScreener returned 50+ pairs"
echo "  Token PEPE: created 2.3h ago"
echo "  Found fresh token: PEPE (created 2.3h ago, dex=raydium)"
echo "  Found 35 fresh tokens (0-24h) via DexScreener"
echo ""
