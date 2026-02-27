#!/bin/bash
# Deploy Fresh Launch Pipeline Fix to VPS

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        FRESH LAUNCH PIPELINE FIX - DEPLOYMENT                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
NC='\033[0m'

echo -e "${BLUE}What's being fixed:${NC}"
echo "  • Scan tokens FROM BIRTH (0-24 hours old, not trending)"
echo "  • Use Pump.fun /coins/latest API endpoint"
echo "  • Get first 100 buyers within 0-30 min window"
echo "  • INCLUDES insiders & dev wallets (0-5 min = highest alpha)"
echo ""

VPS_IP="${1:-root@your-vps-ip}"
PROJECT_DIR="/root/Soulwinners"

echo -e "${YELLOW}Step 1: Verify local files${NC}"
echo "─────────────────────────────────────────"

# Check syntax of modified files
FILES=(
    "collectors/launch_tracker.py"
    "collectors/pumpfun.py"
    "pipeline/orchestrator.py"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        python3 -m py_compile "$file"
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓${NC} Syntax check passed: $file"
        else
            echo "✗ Syntax errors found in $file"
            exit 1
        fi
    else
        echo "✗ File not found: $file"
        exit 1
    fi
done

echo ""
echo -e "${YELLOW}Step 2: Verify changes${NC}"
echo "─────────────────────────────────────────"

# Verify key changes are present
if grep -q "min_minutes: int = 0" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} launch_tracker.py: Scanning from birth (0 min)"
else
    echo "✗ launch_tracker.py: Not scanning from birth"
    exit 1
fi

if grep -q "get_fresh_pumpfun_launches" collectors/pumpfun.py; then
    echo -e "${GREEN}✓${NC} pumpfun.py: Fresh launch method added"
else
    echo "✗ pumpfun.py: Missing fresh launch method"
    exit 1
fi

if grep -q "use_fresh_launches=True" pipeline/orchestrator.py; then
    echo -e "${GREEN}✓${NC} orchestrator.py: Fresh launch mode enabled"
else
    echo "✗ orchestrator.py: Fresh launch mode not enabled"
    exit 1
fi

if grep -q "coins/latest" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} launch_tracker.py: Using /coins/latest endpoint"
else
    echo "✗ launch_tracker.py: Not using /coins/latest endpoint"
    exit 1
fi

if grep -q "Scan from birth" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} launch_tracker.py: Scanning from birth (includes insiders)"
else
    echo "✗ launch_tracker.py: Not scanning from birth"
    exit 1
fi

if grep -q "limit: int = 100" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} launch_tracker.py: Increased buyer limit to 100"
else
    echo "✗ launch_tracker.py: Buyer limit not updated"
    exit 1
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
        echo "✗ Failed to deploy: $file"
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
    echo "✗ Service restart failed"
    echo "Check logs with: ssh $VPS_IP 'journalctl -u soulwinners -n 50'"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 5: Verify deployment${NC}"
echo "─────────────────────────────────────────"

echo "Checking if changes are present on VPS..."
ssh "$VPS_IP" "grep -q 'min_minutes: int = 0' $PROJECT_DIR/collectors/launch_tracker.py && echo 'Found scan from birth (0 min)' || echo 'Missing scan from birth'"
ssh "$VPS_IP" "grep -q 'Scan from birth' $PROJECT_DIR/collectors/launch_tracker.py && echo 'Found birth scanning comments' || echo 'Missing birth scanning'"
ssh "$VPS_IP" "grep -q 'get_fresh_pumpfun_launches' $PROJECT_DIR/collectors/pumpfun.py && echo 'Found fresh launch method' || echo 'Missing fresh launch method'"
ssh "$VPS_IP" "grep -q 'use_fresh_launches=True' $PROJECT_DIR/pipeline/orchestrator.py && echo 'Found fresh launch mode' || echo 'Missing fresh launch mode'"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Fresh launch pipeline fix deployed successfully!${NC}"
echo ""
echo "📊 What changed:"
echo "  1. Scan tokens FROM BIRTH (0-24 hours, not trending)"
echo "  2. Use Pump.fun /coins/latest API"
echo "  3. Get first 100 buyers (0-30 min window)"
echo "  4. INCLUDES insiders & dev wallets (0-5 min = highest alpha)"
echo ""
echo "🔍 Monitor pipeline:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/pipeline.log'"
echo ""
echo "Look for:"
echo "  • 'Found X fresh tokens (0-24h old)'"
echo "  • 'Found X fresh Pump.fun launches (0-24h from birth)'"
echo "  • 'Found X buyers (0-30min window)'"
echo "  • 'Collected X pump.fun wallets from fresh launches'"
echo ""
echo "📝 Expected results:"
echo "  • More wallets: Scanning from birth = maximum capture"
echo "  • Highest alpha: Insiders (0-5 min) + fast snipers (5-15 min)"
echo "  • Filter by performance later, not by time"
echo "  • Dev connections & insider knowledge captured"
echo ""
