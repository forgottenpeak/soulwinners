#!/bin/bash
# Deploy Insider Detection Cron Fix

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       INSIDER DETECTION CRON FIX - DEPLOYMENT                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Problems Fixed:${NC}"
echo "  ✗ Error: 'LaunchTracker' object has no attribute 'scan'"
echo "  ✗ Error: 'InsiderDetector' object has no attribute 'detect'"
echo "  ✗ Error: run_insider_detection.sh not found"
echo ""

echo -e "${GREEN}Solutions:${NC}"
echo "  ✓ Use InsiderScanner._scan_cycle() method"
echo "  ✓ Remove calls to non-existent methods"
echo "  ✓ Create missing .sh wrapper script"
echo "  ✓ Proper logging to insider_detection.log"
echo ""

VPS_IP="${1:-root@your-vps-ip}"
PROJECT_DIR="/root/Soulwinners"

echo -e "${YELLOW}Step 1: Verify local files${NC}"
echo "─────────────────────────────────────────"

python3 -m py_compile scripts/run_insider_detection.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Syntax check passed: run_insider_detection.py"
else
    echo -e "${RED}✗${NC} Syntax errors in run_insider_detection.py"
    exit 1
fi

if [ -f "scripts/run_insider_detection.sh" ]; then
    echo -e "${GREEN}✓${NC} Wrapper script exists: run_insider_detection.sh"
else
    echo -e "${RED}✗${NC} Wrapper script not found"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 2: Verify fixes${NC}"
echo "─────────────────────────────────────────"

# Verify InsiderScanner is used
if grep -q "InsiderScanner" scripts/run_insider_detection.py; then
    echo -e "${GREEN}✓${NC} Using InsiderScanner (correct)"
else
    echo -e "${RED}✗${NC} Not using InsiderScanner"
    exit 1
fi

# Verify _scan_cycle is called
if grep -q "_scan_cycle" scripts/run_insider_detection.py; then
    echo -e "${GREEN}✓${NC} Calling _scan_cycle() method"
else
    echo -e "${RED}✗${NC} Not calling _scan_cycle()"
    exit 1
fi

# Verify no calls to .scan() or .detect()
if grep -q "tracker.scan()" scripts/run_insider_detection.py; then
    echo -e "${RED}✗${NC} Still calling tracker.scan() (wrong!)"
    exit 1
else
    echo -e "${GREEN}✓${NC} No calls to tracker.scan()"
fi

if grep -q "detector.detect()" scripts/run_insider_detection.py; then
    echo -e "${RED}✗${NC} Still calling detector.detect() (wrong!)"
    exit 1
else
    echo -e "${GREEN}✓${NC} No calls to detector.detect()"
fi

echo ""
echo -e "${YELLOW}Step 3: Deploy to VPS${NC}"
echo "─────────────────────────────────────────"

scp scripts/run_insider_detection.py "$VPS_IP:$PROJECT_DIR/scripts/run_insider_detection.py"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Deployed: run_insider_detection.py"
else
    echo -e "${RED}✗${NC} Failed to deploy .py file"
    exit 1
fi

scp scripts/run_insider_detection.sh "$VPS_IP:$PROJECT_DIR/scripts/run_insider_detection.sh"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Deployed: run_insider_detection.sh"
else
    echo -e "${RED}✗${NC} Failed to deploy .sh file"
    exit 1
fi

# Make wrapper executable
ssh "$VPS_IP" "chmod +x $PROJECT_DIR/scripts/run_insider_detection.sh"
echo -e "${GREEN}✓${NC} Made wrapper executable"

echo ""
echo -e "${YELLOW}Step 4: Check crontab${NC}"
echo "─────────────────────────────────────────"

echo "Current crontab entries for insider detection:"
ssh "$VPS_IP" "crontab -l 2>/dev/null | grep insider || echo 'No insider cron jobs found'"

echo ""
echo -e "${BLUE}If cron job doesn't exist, add it:${NC}"
echo "  */15 * * * * /root/Soulwinners/scripts/run_insider_detection.sh"

echo ""
echo -e "${YELLOW}Step 5: Test manual run${NC}"
echo "─────────────────────────────────────────"

echo "Running insider detection manually..."
ssh "$VPS_IP" "cd $PROJECT_DIR && timeout 60 python3 scripts/run_insider_detection.py 2>&1" || echo -e "${YELLOW}⚠${NC}  Test run timed out or failed (check logs)"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Insider detection cron fix deployed!${NC}"
echo ""
echo "📊 What was fixed:"
echo ""
echo "  run_insider_detection.py:"
echo "    • OLD: from collectors.launch_tracker import LaunchTracker"
echo "    • NEW: from collectors.launch_tracker import InsiderScanner"
echo ""
echo "    • OLD: tracker = LaunchTracker()"
echo "    •      tokens = await tracker.scan()  ← AttributeError!"
echo "    • NEW: scanner = InsiderScanner()"
echo "    •      await scanner._scan_cycle()   ← Correct!"
echo ""
echo "    • REMOVED: detector.detect()  ← Method doesn't exist"
echo ""
echo "  run_insider_detection.sh (NEW):"
echo "    • Bash wrapper for cron job"
echo "    • Changes to project directory"
echo "    • Activates venv if exists"
echo "    • Runs Python script"
echo "    • Logs to insider_detection.log"
echo ""
echo "🔍 Monitor insider detection:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/insider_detection.log'"
echo ""
echo "Expected output:"
echo "  ============================================================"
echo "  INSIDER DETECTION - Starting"
echo "  ============================================================"
echo "  Found 35 fresh tokens (0-24h old)"
echo "  Process only 5 freshest tokens per cycle"
echo "  PEPE: Scanning all token wallets (holders + traders)..."
echo "  Found 163 unique wallets"
echo "  Analyzing 50 wallets for patterns..."
echo "  Insider detected: HN7cAB... - Long-term Holder"
echo "  ============================================================"
echo "  INSIDER DETECTION - Complete"
echo "  ============================================================"
echo ""
echo "🧪 Test cron manually:"
echo "  ssh $VPS_IP '/root/Soulwinners/scripts/run_insider_detection.sh'"
echo ""
echo "📝 Add to crontab if not present:"
echo "  ssh $VPS_IP"
echo "  crontab -e"
echo "  # Add this line:"
echo "  */15 * * * * /root/Soulwinners/scripts/run_insider_detection.sh"
echo ""
