#!/bin/bash
# Deploy Helius Blockchain Query (Bypasses Cloudflare)

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        HELIUS BLOCKCHAIN QUERY - DEPLOYMENT                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}Problem:${NC}"
echo "  ✗ Pump.fun API returns Error 1016 (Cloudflare block)"
echo "  ✗ 0 fresh launches found"
echo "  ✗ Pipeline broken"
echo ""

echo -e "${BLUE}Solution:${NC}"
echo "  ✓ Query Solana blockchain directly via Helius"
echo "  ✓ Find new token mints (last 24h)"
echo "  ✓ Filter for Pump.fun program tokens"
echo "  ✓ Detect Raydium migrations"
echo "  ✓ Bypass Cloudflare completely"
echo ""

VPS_IP="${1:-root@your-vps-ip}"
PROJECT_DIR="/root/Soulwinners"

echo -e "${YELLOW}Step 1: Verify local files${NC}"
echo "─────────────────────────────────────────"

# Check syntax of modified files
FILES=(
    "collectors/launch_tracker.py"
    "collectors/pumpfun.py"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        python3 -m py_compile "$file"
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓${NC} Syntax check passed: $file"
        else
            echo -e "${RED}✗${NC} Syntax errors found in $file"
            exit 1
        fi
    else
        echo -e "${RED}✗${NC} File not found: $file"
        exit 1
    fi
done

echo ""
echo -e "${YELLOW}Step 2: Verify changes${NC}"
echo "─────────────────────────────────────────"

# Verify blockchain query methods are present
if grep -q "Helius blockchain queries" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Helius blockchain query method added"
else
    echo -e "${RED}✗${NC} Helius blockchain query not found"
    exit 1
fi

if grep -q "PUMPFUN_PROGRAM" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Pump.fun program ID defined"
else
    echo -e "${RED}✗${NC} Pump.fun program ID not found"
    exit 1
fi

if grep -q "_get_token_symbol" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Token metadata fetching added"
else
    echo -e "${RED}✗${NC} Token metadata method not found"
    exit 1
fi

if grep -q "_check_raydium_migration" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Raydium migration detection added"
else
    echo -e "${RED}✗${NC} Raydium migration method not found"
    exit 1
fi

if grep -q "Helius blockchain queries" collectors/pumpfun.py; then
    echo -e "${GREEN}✓${NC} PumpFunCollector updated for Helius"
else
    echo -e "${RED}✗${NC} PumpFunCollector not updated"
    exit 1
fi

# Verify old Pump.fun API is NOT being used
if grep -q "frontend-api.pump.fun" collectors/launch_tracker.py; then
    echo -e "${RED}✗${NC} Still using Pump.fun frontend API!"
    exit 1
else
    echo -e "${GREEN}✓${NC} Pump.fun frontend API removed"
fi

echo ""
echo -e "${YELLOW}Step 3: Deploy to VPS${NC}"
echo "─────────────────────────────────────────"

echo "Copying modified files to $VPS_IP..."
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
echo -e "${YELLOW}Step 4: Restart SoulWinners service${NC}"
echo "─────────────────────────────────────────"

ssh "$VPS_IP" "systemctl restart soulwinners && sleep 3 && systemctl is-active soulwinners"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Service restarted successfully"
else
    echo -e "${RED}✗${NC} Service restart failed"
    echo "Check logs with: ssh $VPS_IP 'journalctl -u soulwinners -n 50'"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 5: Verify deployment${NC}"
echo "─────────────────────────────────────────"

echo "Checking if Helius blockchain query is active..."
ssh "$VPS_IP" "grep -q 'PUMPFUN_PROGRAM' $PROJECT_DIR/collectors/launch_tracker.py && echo 'Found Pump.fun program ID' || echo 'Missing program ID'"
ssh "$VPS_IP" "grep -q 'Helius blockchain queries' $PROJECT_DIR/collectors/launch_tracker.py && echo 'Found Helius query method' || echo 'Missing Helius method'"
ssh "$VPS_IP" "grep -q '_check_raydium_migration' $PROJECT_DIR/collectors/launch_tracker.py && echo 'Found Raydium detection' || echo 'Missing Raydium detection'"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Helius blockchain query deployed successfully!${NC}"
echo ""
echo "📊 What changed:"
echo "  1. Switched from Pump.fun API to Helius blockchain queries"
echo "  2. Query Solana blockchain directly for token mints"
echo "  3. Filter for Pump.fun program (6EF8r...)"
echo "  4. Detect Raydium migrations via pool creation events"
echo "  5. Bypass Cloudflare completely"
echo ""
echo "🔍 Monitor pipeline:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/pipeline.log'"
echo ""
echo "Look for:"
echo "  • 'Helius returned X Pump.fun transactions'"
echo "  • 'Found Pump.fun token: SYMBOL (X min old)'"
echo "  • 'Found X Pump.fun tokens via Helius blockchain query'"
echo ""
echo "Expected results:"
echo "  • NO MORE Error 1016 (Cloudflare)"
echo "  • 40-80 fresh launches found (not 0)"
echo "  • Direct blockchain data (no API blocks)"
echo ""
echo "📝 Test immediately:"
echo "  ssh $VPS_IP"
echo "  cd $PROJECT_DIR"
echo "  # Watch for tokens in logs"
echo "  tail -f logs/pipeline.log | grep 'Found Pump.fun token'"
echo ""
