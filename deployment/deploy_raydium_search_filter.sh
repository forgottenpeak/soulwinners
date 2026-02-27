#!/bin/bash
# Deploy Raydium Search Filter for Fresh Pump.fun Tokens

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║      RAYDIUM SEARCH FILTER - DEPLOYMENT                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Problem Fixed:${NC}"
echo "  ✗ Search q=solana returns ALL Solana tokens (years old)"
echo "  ✗ Gets established tokens, not fresh Pump.fun launches"
echo ""

echo -e "${GREEN}Solution:${NC}"
echo "  OLD: /search?q=solana (returns ALL Solana tokens)"
echo "  NEW: /search?q=raydium (returns only Raydium pairs)"
echo ""
echo "  Additional filters:"
echo "    ✓ chainId == 'solana'"
echo "    ✓ dexId contains 'raydium'"
echo "    ✓ pairCreatedAt < 24h"
echo ""
echo "  Result: Only fresh Raydium pairs (Pump.fun graduations)"
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
echo -e "${YELLOW}Step 2: Verify search filter change${NC}"
echo "─────────────────────────────────────────"

# Verify old search is gone
if grep -q "search?q=solana" collectors/*.py; then
    echo -e "${RED}✗${NC} Old search query still found (q=solana)"
    exit 1
else
    echo -e "${GREEN}✓${NC} Old query removed (q=solana)"
fi

# Verify new search is used
RAYDIUM_COUNT=$(grep -c "search?q=raydium" collectors/*.py)
if [ "$RAYDIUM_COUNT" -ge 4 ]; then
    echo -e "${GREEN}✓${NC} New query used (q=raydium) in $RAYDIUM_COUNT locations"
else
    echo -e "${RED}✗${NC} New query not found in expected locations"
    exit 1
fi

# Verify chainId filter
if grep -q "chainId.*!=.*'solana'" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} chainId filter added"
else
    echo -e "${RED}✗${NC} chainId filter not found"
    exit 1
fi

# Verify dexId filter
if grep -q "dexId.*raydium" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} dexId filter added (raydium)"
else
    echo -e "${RED}✗${NC} dexId filter not found"
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
echo -e "${YELLOW}Step 5: Monitor for fresh Raydium pairs${NC}"
echo "─────────────────────────────────────────"

echo "Waiting 20 seconds for first pipeline cycle..."
sleep 20

echo -e "\n${BLUE}Recent discoveries (should show fresh Raydium pairs):${NC}"
ssh "$VPS_IP" "tail -n 200 $PROJECT_DIR/logs/pipeline.log | grep -E 'DexScreener.*returned|Fresh Raydium|Found fresh|dex=raydium'" | tail -40 || echo "Waiting for pipeline..."

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Raydium search filter deployed!${NC}"
echo ""
echo "📊 What changed:"
echo ""
echo "  Search Query:"
echo "    OLD: /search?q=solana → Returns ALL Solana tokens (years old)"
echo "    NEW: /search?q=raydium → Returns only Raydium pairs"
echo ""
echo "  Filters Applied:"
echo "    1. chainId == 'solana' (only Solana chain)"
echo "    2. dexId contains 'raydium' (only Raydium DEX)"
echo "    3. pairCreatedAt < 24h (only fresh pairs)"
echo ""
echo "  Result:"
echo "    • Fresh Raydium pairs created in last 24 hours"
echo "    • These are typically Pump.fun tokens that graduated"
echo "    • No old/established tokens anymore"
echo ""
echo "🔍 Monitor for fresh tokens:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/pipeline.log | grep \"Fresh Raydium\"'"
echo ""
echo "Expected output:"
echo "  DexScreener search returned 150 Raydium pairs"
echo "  Fresh Raydium pair: PEPE (created 2.3h ago)"
echo "  Fresh Raydium pair: DOGE (created 5.7h ago)"
echo "  Found fresh token: PEPE (created 2.3h ago, dex=raydium)"
echo "  Found 25 fresh tokens (0-24h) via DexScreener"
echo "  Found 8 fresh migrations (0-6h) - BEST SIGNAL! ⭐"
echo ""
echo "📝 These are fresh Pump.fun graduations to Raydium!"
echo ""
