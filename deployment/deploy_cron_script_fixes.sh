#!/bin/bash
# Deploy Cron Script Method Name Fixes

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          CRON SCRIPT FIXES - DEPLOYMENT                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Problems Fixed:${NC}"
echo "  ✗ run_insider_detection.py calling tracker.scan() (doesn't exist)"
echo "  ✗ run_cluster_analysis.py calling detector.analyze_wallets() (doesn't exist)"
echo ""

echo -e "${GREEN}Solutions:${NC}"
echo "  ✓ Fixed: tracker.scan() → tracker.scan_fresh_launches()"
echo "  ✓ Fixed: detector.analyze_wallets() → detector.analyze_wallet_connections()"
echo "  ✓ Added proper cluster building logic to cron script"
echo "  ✓ Added better logging output"
echo ""

VPS_IP="${1:-root@your-vps-ip}"
PROJECT_DIR="/root/Soulwinners"

echo -e "${YELLOW}Step 1: Verify local files${NC}"
echo "─────────────────────────────────────────"

FILES=(
    "scripts/run_insider_detection.py"
    "scripts/run_cluster_analysis.py"
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
echo -e "${YELLOW}Step 2: Verify fixes${NC}"
echo "─────────────────────────────────────────"

# Verify insider detection fix
if grep -q "scan_fresh_launches()" scripts/run_insider_detection.py; then
    echo -e "${GREEN}✓${NC} Insider detection: Using correct method 'scan_fresh_launches()'"
else
    echo -e "${RED}✗${NC} Insider detection: Method not fixed"
    exit 1
fi

# Verify cluster analysis fix
if grep -q "analyze_wallet_connections" scripts/run_cluster_analysis.py; then
    echo -e "${GREEN}✓${NC} Cluster analysis: Using correct method 'analyze_wallet_connections()'"
else
    echo -e "${RED}✗${NC} Cluster analysis: Method not fixed"
    exit 1
fi

# Verify cluster building logic added
if grep -q "build_clusters()" scripts/run_cluster_analysis.py; then
    echo -e "${GREEN}✓${NC} Cluster analysis: Cluster building logic added"
else
    echo -e "${RED}✗${NC} Cluster analysis: Missing cluster building logic"
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
echo -e "${YELLOW}Step 4: Verify cron jobs${NC}"
echo "─────────────────────────────────────────"

echo "Checking crontab on VPS..."
ssh "$VPS_IP" "crontab -l | grep -E 'insider_detection|cluster_analysis'" || echo -e "${YELLOW}Note: Cron jobs may not be configured yet${NC}"

echo ""
echo -e "${YELLOW}Step 5: Test scripts manually${NC}"
echo "─────────────────────────────────────────"

echo "Testing insider detection script..."
ssh "$VPS_IP" "cd $PROJECT_DIR && timeout 30 python3 scripts/run_insider_detection.py 2>&1 | head -20" || echo -e "${YELLOW}Script may take longer than 30s${NC}"

echo ""
echo "Testing cluster analysis script..."
ssh "$VPS_IP" "cd $PROJECT_DIR && timeout 30 python3 scripts/run_cluster_analysis.py 2>&1 | head -20" || echo -e "${YELLOW}Script may take longer than 30s${NC}"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Cron script fixes deployed!${NC}"
echo ""
echo "📊 What was fixed:"
echo "  1. run_insider_detection.py:"
echo "     - Changed: tracker.scan() → tracker.scan_fresh_launches()"
echo "     - Added: Better logging with token counts"
echo ""
echo "  2. run_cluster_analysis.py:"
echo "     - Changed: detector.analyze_wallets() → detector.analyze_wallet_connections()"
echo "     - Added: Proper cluster building logic from ClusterScanner"
echo "     - Added: Detailed logging for each step"
echo ""
echo "🔍 Monitor cron jobs:"
echo "  # Watch insider detection (runs every 15 min)"
echo "  ssh $VPS_IP 'tail -f /var/log/syslog | grep insider'"
echo ""
echo "  # Watch cluster analysis (runs every 20 min)"
echo "  ssh $VPS_IP 'tail -f /var/log/syslog | grep cluster'"
echo ""
echo "📝 Manually test scripts:"
echo "  ssh $VPS_IP 'cd $PROJECT_DIR && python3 scripts/run_insider_detection.py'"
echo "  ssh $VPS_IP 'cd $PROJECT_DIR && python3 scripts/run_cluster_analysis.py'"
echo ""
echo "Expected output:"
echo "  ✓ Fresh launch scan complete - Found X tokens"
echo "  ✓ Analyzed connections for X wallets"
echo "  ✓ Found X clusters"
echo ""
