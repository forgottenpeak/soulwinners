#!/bin/bash
# Verify SoulWinners Deployment
# Checks all components are working correctly

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           SOULWINNERS VERIFICATION SCRIPT                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
NC='\033[0m'

PROJECT_DIR="/root/Soulwinners"
ALL_PASSED=true

echo -e "${BLUE}1. CHECKING CLOUDFLARE FIX${NC}"
echo "─────────────────────────────────────────"

if grep -q "CLOUDFLARE_BYPASS_HEADERS" "$PROJECT_DIR/collectors/pumpfun.py" && \
   grep -q "headers=CLOUDFLARE_BYPASS_HEADERS" "$PROJECT_DIR/collectors/pumpfun.py"; then
    echo -e "${GREEN}✓${NC} Pumpfun collector: Cloudflare fix applied"
else
    echo -e "${RED}✗${NC} Pumpfun collector: Cloudflare fix missing"
    ALL_PASSED=false
fi

if grep -q "CLOUDFLARE_BYPASS_HEADERS" "$PROJECT_DIR/collectors/dexscreener.py" && \
   grep -q "headers=CLOUDFLARE_BYPASS_HEADERS" "$PROJECT_DIR/collectors/dexscreener.py"; then
    echo -e "${GREEN}✓${NC} DexScreener collector: Cloudflare fix applied"
else
    echo -e "${RED}✗${NC} DexScreener collector: Cloudflare fix missing"
    ALL_PASSED=false
fi

echo ""
echo -e "${BLUE}2. CHECKING CRON JOBS${NC}"
echo "─────────────────────────────────────────"

if crontab -l 2>/dev/null | grep -q "run_insider_detection"; then
    echo -e "${GREEN}✓${NC} Insider detection cron: installed"
    INSIDER_SCHEDULE=$(crontab -l | grep "run_insider_detection" | awk '{print $1, $2, $3, $4, $5}')
    echo "  Schedule: $INSIDER_SCHEDULE (every 15 minutes)"
else
    echo -e "${RED}✗${NC} Insider detection cron: not installed"
    ALL_PASSED=false
fi

if crontab -l 2>/dev/null | grep -q "run_cluster_analysis"; then
    echo -e "${GREEN}✓${NC} Cluster analysis cron: installed"
    CLUSTER_SCHEDULE=$(crontab -l | grep "run_cluster_analysis" | awk '{print $1, $2, $3, $4, $5}')
    echo "  Schedule: $CLUSTER_SCHEDULE (every 20 minutes)"
else
    echo -e "${RED}✗${NC} Cluster analysis cron: not installed"
    ALL_PASSED=false
fi

echo ""
echo -e "${BLUE}3. CHECKING SCRIPTS${NC}"
echo "─────────────────────────────────────────"

if [ -f "$PROJECT_DIR/scripts/run_insider_detection.sh" ] && [ -x "$PROJECT_DIR/scripts/run_insider_detection.sh" ]; then
    echo -e "${GREEN}✓${NC} Insider detection script: exists and executable"
else
    echo -e "${RED}✗${NC} Insider detection script: missing or not executable"
    ALL_PASSED=false
fi

if [ -f "$PROJECT_DIR/scripts/run_cluster_analysis.sh" ] && [ -x "$PROJECT_DIR/scripts/run_cluster_analysis.sh" ]; then
    echo -e "${GREEN}✓${NC} Cluster analysis script: exists and executable"
else
    echo -e "${RED}✗${NC} Cluster analysis script: missing or not executable"
    ALL_PASSED=false
fi

if [ -f "$PROJECT_DIR/scripts/run_insider_detection.py" ]; then
    echo -e "${GREEN}✓${NC} Insider detection Python script: exists"
else
    echo -e "${RED}✗${NC} Insider detection Python script: missing"
    ALL_PASSED=false
fi

if [ -f "$PROJECT_DIR/scripts/run_cluster_analysis.py" ]; then
    echo -e "${GREEN}✓${NC} Cluster analysis Python script: exists"
else
    echo -e "${RED}✗${NC} Cluster analysis Python script: missing"
    ALL_PASSED=false
fi

echo ""
echo -e "${BLUE}4. CHECKING DATABASE${NC}"
echo "─────────────────────────────────────────"

DB_FILE="$PROJECT_DIR/data/soulwinners.db"

if [ -f "$DB_FILE" ]; then
    echo -e "${GREEN}✓${NC} Database: exists"

    FREQ=$(sqlite3 "$DB_FILE" "SELECT value FROM settings WHERE key='discovery_frequency_min'" 2>/dev/null)
    if [ "$FREQ" = "30" ]; then
        echo -e "${GREEN}✓${NC} Discovery frequency: ${FREQ} minutes (correct)"
    else
        echo -e "${YELLOW}⚠${NC} Discovery frequency: ${FREQ} minutes (expected 30)"
    fi

    # Check for required tables
    TABLES=$(sqlite3 "$DB_FILE" ".tables" 2>/dev/null)
    if echo "$TABLES" | grep -q "insider_pool"; then
        echo -e "${GREEN}✓${NC} Table insider_pool: exists"
    else
        echo -e "${YELLOW}⚠${NC} Table insider_pool: not found (will be created on first run)"
    fi

    if echo "$TABLES" | grep -q "wallet_clusters"; then
        echo -e "${GREEN}✓${NC} Table wallet_clusters: exists"
    else
        echo -e "${YELLOW}⚠${NC} Table wallet_clusters: not found (will be created on first run)"
    fi

else
    echo -e "${YELLOW}⚠${NC} Database: not found yet (will be created on first run)"
fi

echo ""
echo -e "${BLUE}5. CHECKING SERVICES${NC}"
echo "─────────────────────────────────────────"

if systemctl is-active --quiet soulwinners 2>/dev/null; then
    echo -e "${GREEN}✓${NC} SoulWinners service: running"
    UPTIME=$(systemctl show soulwinners -p ActiveEnterTimestamp | cut -d= -f2)
    echo "  Started: $UPTIME"
else
    echo -e "${RED}✗${NC} SoulWinners service: not running"
    ALL_PASSED=false
fi

if systemctl list-units --all 2>/dev/null | grep -q "insider.service"; then
    if systemctl is-active --quiet insider; then
        echo -e "${GREEN}✓${NC} Insider service: running"
    else
        echo -e "${YELLOW}⚠${NC} Insider service: exists but not running"
    fi
else
    echo -e "${YELLOW}⚠${NC} Insider service: not found (optional)"
fi

echo ""
echo -e "${BLUE}6. CHECKING LOG FILES${NC}"
echo "─────────────────────────────────────────"

LOGS=(
    "pipeline.log"
    "insider_cron.log"
    "cluster_cron.log"
)

for log in "${LOGS[@]}"; do
    LOG_PATH="$PROJECT_DIR/logs/$log"
    if [ -f "$LOG_PATH" ]; then
        SIZE=$(du -h "$LOG_PATH" | cut -f1)
        LINES=$(wc -l < "$LOG_PATH")
        echo -e "${GREEN}✓${NC} $log: exists (${SIZE}, ${LINES} lines)"
    else
        echo -e "${YELLOW}⚠${NC} $log: not found yet"
    fi
done

echo ""
echo -e "${BLUE}7. CHECKING RECENT ACTIVITY${NC}"
echo "─────────────────────────────────────────"

# Check main pipeline log
if [ -f "$PROJECT_DIR/logs/pipeline.log" ]; then
    RECENT=$(tail -n 5 "$PROJECT_DIR/logs/pipeline.log" | head -n 1)
    if [ -n "$RECENT" ]; then
        echo -e "${GREEN}✓${NC} Recent pipeline activity detected"
        echo "  Last log: $(echo $RECENT | cut -c1-80)..."
    else
        echo -e "${YELLOW}⚠${NC} Pipeline log is empty"
    fi

    # Check for token collection
    if grep -q "Found.*trending.*tokens" "$PROJECT_DIR/logs/pipeline.log" 2>/dev/null; then
        TOKENS=$(grep "Found.*trending.*tokens" "$PROJECT_DIR/logs/pipeline.log" | tail -1)
        echo -e "${GREEN}✓${NC} Token collection working"
        echo "  $(echo $TOKENS | cut -c1-80)..."
    else
        echo -e "${YELLOW}⚠${NC} No token collection detected yet"
    fi

    # Check for wallet collection
    if grep -q "Collected.*wallets" "$PROJECT_DIR/logs/pipeline.log" 2>/dev/null; then
        WALLETS=$(grep "Collected.*wallets" "$PROJECT_DIR/logs/pipeline.log" | tail -1)
        echo -e "${GREEN}✓${NC} Wallet collection working"
        echo "  $(echo $WALLETS | cut -c1-80)..."
    else
        echo -e "${YELLOW}⚠${NC} No wallet collection detected yet"
    fi
fi

# Check insider cron log
if [ -f "$PROJECT_DIR/logs/insider_cron.log" ]; then
    if [ -s "$PROJECT_DIR/logs/insider_cron.log" ]; then
        echo -e "${GREEN}✓${NC} Insider cron has executed"
        LAST_RUN=$(tail -n 1 "$PROJECT_DIR/logs/insider_cron.log")
        echo "  Last: $(echo $LAST_RUN | cut -c1-80)..."
    else
        echo -e "${YELLOW}⚠${NC} Insider cron hasn't run yet (wait 15 minutes)"
    fi
fi

# Check cluster cron log
if [ -f "$PROJECT_DIR/logs/cluster_cron.log" ]; then
    if [ -s "$PROJECT_DIR/logs/cluster_cron.log" ]; then
        echo -e "${GREEN}✓${NC} Cluster cron has executed"
        LAST_RUN=$(tail -n 1 "$PROJECT_DIR/logs/cluster_cron.log")
        echo "  Last: $(echo $LAST_RUN | cut -c1-80)..."
    else
        echo -e "${YELLOW}⚠${NC} Cluster cron hasn't run yet (wait 20 minutes)"
    fi
fi

echo ""
echo "══════════════════════════════════════════════════════════════"

if [ "$ALL_PASSED" = true ]; then
    echo -e "${GREEN}✅ ALL CRITICAL CHECKS PASSED${NC}"
    echo ""
    echo "SoulWinners is fully operational!"
    echo ""
    echo "📊 Monitor with:"
    echo "  tail -f $PROJECT_DIR/logs/pipeline.log"
    echo "  tail -f $PROJECT_DIR/logs/insider_cron.log"
    echo "  tail -f $PROJECT_DIR/logs/cluster_cron.log"
    echo ""
    exit 0
else
    echo -e "${RED}❌ SOME CHECKS FAILED${NC}"
    echo ""
    echo "Please review the errors above and re-run deployment."
    echo ""
    exit 1
fi
