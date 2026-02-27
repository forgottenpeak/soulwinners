#!/bin/bash
# Deploy DexScreener Pairs Endpoint Fix

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║      DEXSCREENER PAIRS ENDPOINT FIX - DEPLOYMENT            ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Problem Fixed:${NC}"
echo "  ✗ token-profiles/latest/v1 has NO timestamps"
echo "  ✗ No pairCreatedAt field in response"
echo "  ✗ Can't filter by age → 0 fresh tokens found"
echo ""

echo -e "${GREEN}Solution:${NC}"
echo "  ✓ Changed to: latest/dex/pairs/solana endpoint"
echo "  ✓ Has pairCreatedAt field (millisecond timestamp)"
echo "  ✓ Has all pair data (volume, liquidity, dexId)"
echo "  ✓ Proper age filtering now works"
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
echo -e "${YELLOW}Step 2: Verify endpoint change${NC}"
echo "─────────────────────────────────────────"

# Verify old endpoint is gone
if grep -q "token-profiles/latest/v1" collectors/*.py; then
    echo -e "${RED}✗${NC} Old endpoint still found in collectors/"
    exit 1
else
    echo -e "${GREEN}✓${NC} Old endpoint removed (token-profiles/latest/v1)"
fi

# Verify new endpoint is used
if grep -q "latest/dex/pairs/solana" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} launch_tracker.py: Using new pairs endpoint"
else
    echo -e "${RED}✗${NC} launch_tracker.py: New endpoint not found"
    exit 1
fi

if grep -q "latest/dex/pairs/solana" collectors/pumpfun.py; then
    echo -e "${GREEN}✓${NC} pumpfun.py: Using new pairs endpoint"
else
    echo -e "${RED}✗${NC} pumpfun.py: New endpoint not found"
    exit 1
fi

# Verify proper parsing
if grep -q "pairs = data.get('pairs'" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} launch_tracker.py: Parsing 'pairs' array"
else
    echo -e "${RED}✗${NC} launch_tracker.py: Not parsing pairs correctly"
    exit 1
fi

if grep -q "base_token = pair.get('baseToken'" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} launch_tracker.py: Extracting baseToken data"
else
    echo -e "${RED}✗${NC} launch_tracker.py: Not extracting baseToken"
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
echo -e "${YELLOW}Step 5: Monitor token discovery${NC}"
echo "─────────────────────────────────────────"

echo "Waiting 20 seconds for pipeline to run..."
sleep 20

echo -e "\n${BLUE}Recent token discovery (should show tokens now):${NC}"
ssh "$VPS_IP" "tail -n 150 $PROJECT_DIR/logs/pipeline.log | grep -E 'DexScreener returned|Found fresh token|created.*h ago|Found.*fresh'" | tail -30 || echo "Waiting for pipeline cycle..."

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ DexScreener pairs endpoint deployed!${NC}"
echo ""
echo "📊 What changed:"
echo ""
echo "  OLD Endpoint (broken):"
echo "    https://api.dexscreener.com/token-profiles/latest/v1"
echo "    • No timestamps (pairCreatedAt missing)"
echo "    • Can't filter by age"
echo "    • Result: 0 tokens found"
echo ""
echo "  NEW Endpoint (working):"
echo "    https://api.dexscreener.com/latest/dex/pairs/solana"
echo "    • Has pairCreatedAt (milliseconds)"
echo "    • Proper age filtering"
echo "    • Returns pairs array with baseToken data"
echo ""
echo "  Response format change:"
echo "    OLD: [ {tokenAddress, symbol, name, ...} ]"
echo "    NEW: { pairs: [ {baseToken: {address, symbol, name}, pairCreatedAt, ...} ] }"
echo ""
echo "🔍 Monitor for tokens:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/pipeline.log | grep \"Found fresh\"'"
echo ""
echo "Expected output:"
echo "  DexScreener returned 50 pairs"
echo "  Token PEPE: created 2.3h ago (launch_time=...)"
echo "  Found fresh token: PEPE (created 2.3h ago, dex=raydium)"
echo "  Found 35 fresh tokens (0-24h) via DexScreener pairs"
echo "  Found 8 fresh migrations (0-6h) - BEST SIGNAL!"
echo ""
echo "📝 If still 0 tokens:"
echo "  ssh $VPS_IP 'tail -100 $PROJECT_DIR/logs/pipeline.log | grep -i dexscreener'"
echo "  # Check if API is responding and returning pairs"
echo ""
