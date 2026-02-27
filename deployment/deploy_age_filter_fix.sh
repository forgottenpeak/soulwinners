#!/bin/bash
# Deploy Age Filter Fix

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           AGE FILTER FIX - DEPLOYMENT                        ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Problem Fixed:${NC}"
echo "  ✗ DexScreener returns 30 tokens but age filter rejects all"
echo "  ✗ Found 0 fresh launches (should be 20-30)"
echo ""

echo -e "${GREEN}Solution:${NC}"
echo "  ✓ Fixed field name: 'pairCreatedAt' not 'createdAt'"
echo "  ✓ Added debug logging for age calculation"
echo "  ✓ Handle both ISO string and Unix timestamp formats"
echo "  ✓ Fixed age comparison logic"
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
echo -e "${YELLOW}Step 2: Verify fix${NC}"
echo "─────────────────────────────────────────"

# Verify pairCreatedAt field is used
if grep -q "pairCreatedAt" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Using 'pairCreatedAt' field"
else
    echo -e "${RED}✗${NC} 'pairCreatedAt' not found"
    exit 1
fi

# Verify debug logging added
if grep -q "created.*h ago" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Debug logging added"
else
    echo -e "${RED}✗${NC} Debug logging not found"
    exit 1
fi

# Verify age comparison fixed
if grep -q "age_hours > self.max_age_hours" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Age comparison logic fixed"
else
    echo -e "${RED}✗${NC} Age comparison not fixed"
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

echo "Waiting 15 seconds for pipeline to run..."
sleep 15

echo -e "\n${BLUE}Recent token discovery:${NC}"
ssh "$VPS_IP" "tail -n 100 $PROJECT_DIR/logs/pipeline.log | grep -E 'Token.*created.*h ago|Found.*fresh'" | tail -20 || echo "Waiting for pipeline cycle..."

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Age filter fix deployed!${NC}"
echo ""
echo "📊 What was fixed:"
echo "  1. Field name: 'pairCreatedAt' (not 'createdAt')"
echo "  2. Added debug logging: 'Token SYMBOL: created X.Xh ago'"
echo "  3. Handle both ISO string and Unix timestamp formats"
echo "  4. Fixed age comparison: age_hours > 24 (not launch_time <= cutoff)"
echo ""
echo "🔍 Monitor for tokens:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/pipeline.log | grep \"created.*h ago\"'"
echo ""
echo "Expected output:"
echo "  Token PEPE: created 2.3h ago"
echo "  Token DOGE: created 5.7h ago"
echo "  Found 35 fresh tokens via DexScreener"
echo ""
echo "📝 Debug if still 0 tokens:"
echo "  ssh $VPS_IP 'grep \"Token.*created\" $PROJECT_DIR/logs/pipeline.log | tail -20'"
echo "  # Check actual ages being reported"
echo ""
