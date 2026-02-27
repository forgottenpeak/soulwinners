#!/bin/bash
# Deploy Telegram Command Format Fix

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║      TELEGRAM COMMAND FORMAT FIX - DEPLOYMENT                ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Problem:${NC}"
echo "  ✗ Error: \"Can't parse entities: can't find end of the entity\""
echo "  ✗ Commands /insiders, /clusters, /early_birds failing"
echo "  ✗ Invalid Telegram markdown formatting"
echo ""

echo -e "${GREEN}Solution:${NC}"
echo "  ✓ Convert from Markdown to HTML formatting"
echo "  ✓ Bold: ** → <b></b>"
echo "  ✓ Italic: _ → <i></i>"
echo "  ✓ ParseMode: MARKDOWN → HTML"
echo ""
echo "  HTML is more robust and doesn't require escaping"
echo ""

VPS_IP="${1:-root@your-vps-ip}"
PROJECT_DIR="/root/Soulwinners"

echo -e "${YELLOW}Step 1: Verify local files${NC}"
echo "─────────────────────────────────────────"

python3 -m py_compile bot/commands.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Syntax check passed: bot/commands.py"
else
    echo -e "${RED}✗${NC} Syntax errors in bot/commands.py"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 2: Verify format changes${NC}"
echo "─────────────────────────────────────────"

# Verify HTML formatting is used
if grep -q "ParseMode.HTML" bot/commands.py; then
    echo -e "${GREEN}✓${NC} Using ParseMode.HTML (not MARKDOWN)"
else
    echo -e "${RED}✗${NC} Still using ParseMode.MARKDOWN"
    exit 1
fi

# Verify bold tags
if grep -q "<b>INSIDER POOL" bot/commands.py; then
    echo -e "${GREEN}✓${NC} HTML bold tags in cmd_insiders()"
else
    echo -e "${RED}✗${NC} HTML bold tags not found"
    exit 1
fi

# Verify italic tags
if grep -q "<i>Fresh launch snipers" bot/commands.py; then
    echo -e "${GREEN}✓${NC} HTML italic tags in messages"
else
    echo -e "${RED}✗${NC} HTML italic tags not found"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 3: Deploy to VPS${NC}"
echo "─────────────────────────────────────────"

scp bot/commands.py "$VPS_IP:$PROJECT_DIR/bot/commands.py"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Deployed: bot/commands.py"
else
    echo -e "${RED}✗${NC} Failed to deploy bot/commands.py"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 4: Restart bot service${NC}"
echo "─────────────────────────────────────────"

ssh "$VPS_IP" "systemctl restart soulwinners-bot && sleep 2 && systemctl is-active soulwinners-bot"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Bot service restarted"
else
    echo -e "${RED}✗${NC} Bot restart failed"
    exit 1
fi

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Telegram format fix deployed!${NC}"
echo ""
echo "📊 Changes Made:"
echo ""
echo "  cmd_insiders():"
echo "    • ** → <b> (bold)"
echo "    • _ → <i> (italic)"
echo "    • ParseMode.MARKDOWN → ParseMode.HTML"
echo ""
echo "  cmd_clusters():"
echo "    • ** → <b> (bold)"
echo "    • _ → <i> (italic)"
echo "    • ParseMode.MARKDOWN → ParseMode.HTML"
echo ""
echo "  cmd_early_birds():"
echo "    • ** → <b> (bold)"
echo "    • _ → <i> (italic)"
echo "    • ParseMode.MARKDOWN → ParseMode.HTML"
echo ""
echo "🧪 Test Commands:"
echo ""
echo "  1. Test /insiders:"
echo "     Should show: Insider pool statistics"
echo "     Should NOT show: \"Can't parse entities\" error"
echo ""
echo "  2. Test /clusters:"
echo "     Should show: Wallet cluster analysis"
echo "     Should NOT show: \"Can't parse entities\" error"
echo ""
echo "  3. Test /early_birds:"
echo "     Should show: Fresh launch snipers"
echo "     Should NOT show: \"Can't parse entities\" error"
echo ""
echo "📝 HTML vs Markdown:"
echo ""
echo "  Markdown (OLD - problematic):"
echo "    • **bold** - requires escaping special chars"
echo "    • _italic_ - breaks with underscores in text"
echo "    • Very strict parsing"
echo ""
echo "  HTML (NEW - robust):"
echo "    • <b>bold</b> - no escaping needed"
echo "    • <i>italic</i> - works with any text"
echo "    • Forgiving parser"
echo ""
echo "🔍 Check bot logs:"
echo "  ssh $VPS_IP 'journalctl -u soulwinners-bot -n 50 -f'"
echo ""
echo "  Look for successful command responses (no parse errors)"
echo ""
