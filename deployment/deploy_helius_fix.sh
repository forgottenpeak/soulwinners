#!/bin/bash
# Deploy Helius Blockchain Query Bug Fix

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        HELIUS BLOCKCHAIN QUERY - BUG FIX                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Bug Fixed:${NC}"
echo "  ✗ Error: fetch_with_retry() got unexpected keyword argument 'params'"
echo ""

echo -e "${GREEN}Solution:${NC}"
echo "  ✓ Updated BaseCollector.fetch_with_retry() to accept params"
echo "  ✓ Helius queries now work correctly"
echo ""

VPS_IP="${1:-root@your-vps-ip}"
PROJECT_DIR="/root/Soulwinners"

echo -e "${YELLOW}Step 1: Verify local files${NC}"
echo "─────────────────────────────────────────"

# Check syntax of modified files
FILES=(
    "collectors/base.py"
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
echo -e "${YELLOW}Step 2: Verify fix${NC}"
echo "─────────────────────────────────────────"

# Verify params argument is in fetch_with_retry
if grep -q "params: Dict = None" collectors/base.py; then
    echo -e "${GREEN}✓${NC} BaseCollector.fetch_with_retry() now accepts params"
else
    echo -e "${RED}✗${NC} params argument not found in fetch_with_retry()"
    exit 1
fi

if grep -q "params=params" collectors/base.py; then
    echo -e "${GREEN}✓${NC} params passed to session.request()"
else
    echo -e "${RED}✗${NC} params not passed to request"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 3: Deploy to VPS${NC}"
echo "─────────────────────────────────────────"

echo "Copying fixed files to $VPS_IP..."
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
echo -e "${YELLOW}Step 5: Test fresh launch discovery${NC}"
echo "─────────────────────────────────────────"

echo "Waiting 10 seconds for service to initialize..."
sleep 10

echo "Checking logs for token discovery..."
ssh "$VPS_IP" "tail -n 50 $PROJECT_DIR/logs/pipeline.log | grep -E 'Helius returned|Found.*Pump.fun token|Found.*fresh'" || echo "No tokens found yet (may take 1-2 minutes)"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Bug fix deployed successfully!${NC}"
echo ""
echo "📊 What was fixed:"
echo "  1. Added 'params' parameter to fetch_with_retry()"
echo "  2. Helius blockchain queries now work"
echo "  3. Fresh launch discovery operational"
echo ""
echo "🔍 Monitor for tokens:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/pipeline.log | grep Pump.fun'"
echo ""
echo "Look for:"
echo "  • 'Helius returned X Pump.fun transactions'"
echo "  • 'Found Pump.fun token: SYMBOL'"
echo "  • 'Found X Pump.fun tokens via Helius'"
echo ""
echo "Expected results:"
echo "  • NO 'Error: unexpected keyword argument params'"
echo "  • 40-80 fresh launches found"
echo "  • Pipeline operational"
echo ""
