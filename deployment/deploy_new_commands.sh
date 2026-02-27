#!/bin/bash
# Deploy Updated Telegram Bot Commands to VPS

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        TELEGRAM BOT COMMANDS - DEPLOYMENT                    ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
NC='\033[0m'

echo -e "${BLUE}New Commands Added:${NC}"
echo "  • /insiders    - Insider pool statistics"
echo "  • /clusters    - Detected wallet clusters"
echo "  • /early_birds - Fresh launch snipers"
echo ""

VPS_IP="${1:-root@your-vps-ip}"
PROJECT_DIR="/root/Soulwinners"

echo -e "${YELLOW}Step 1: Verify local file${NC}"
echo "─────────────────────────────────────────"

# Check syntax
python3 -m py_compile bot/commands.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Syntax check passed"
else
    echo "✗ Syntax errors found"
    exit 1
fi

# Verify commands exist
COMMANDS_FOUND=0
for cmd in "cmd_insiders" "cmd_clusters" "cmd_early_birds"; do
    if grep -q "async def $cmd" bot/commands.py; then
        echo -e "${GREEN}✓${NC} Found method: $cmd"
        COMMANDS_FOUND=$((COMMANDS_FOUND + 1))
    fi
done

if [ $COMMANDS_FOUND -eq 3 ]; then
    echo -e "${GREEN}✓${NC} All 3 command methods present"
else
    echo "✗ Missing command methods"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 2: Deploy to VPS${NC}"
echo "─────────────────────────────────────────"

echo "Copying bot/commands.py to $VPS_IP..."
scp bot/commands.py "$VPS_IP:$PROJECT_DIR/bot/commands.py"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} File deployed successfully"
else
    echo "✗ Deployment failed"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 3: Restart SoulWinners service${NC}"
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
echo -e "${YELLOW}Step 4: Verify deployment${NC}"
echo "─────────────────────────────────────────"

echo "Checking if commands are present on VPS..."
ssh "$VPS_IP" "grep -q 'async def cmd_insiders' $PROJECT_DIR/bot/commands.py && echo 'Found cmd_insiders' || echo 'Missing cmd_insiders'"
ssh "$VPS_IP" "grep -q 'async def cmd_clusters' $PROJECT_DIR/bot/commands.py && echo 'Found cmd_clusters' || echo 'Missing cmd_clusters'"
ssh "$VPS_IP" "grep -q 'async def cmd_early_birds' $PROJECT_DIR/bot/commands.py && echo 'Found cmd_early_birds' || echo 'Missing cmd_early_birds'"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ New commands deployed successfully!${NC}"
echo ""
echo "📱 Test in Telegram:"
echo "  1. Open your bot"
echo "  2. Send: /insiders"
echo "  3. Send: /clusters"
echo "  4. Send: /early_birds"
echo "  5. Send: /help (verify new commands listed)"
echo ""
echo "📊 Also test existing commands:"
echo "  /pool, /stats, /cron, /settings, /leaderboard"
echo ""
echo "📝 Monitor logs:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/bot.log'"
echo ""
