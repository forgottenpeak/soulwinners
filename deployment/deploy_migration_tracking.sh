#!/bin/bash
# Deploy Migration Tracking

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        MIGRATION TRACKING - DEPLOYMENT                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}What's Being Added:${NC}"
echo "  ✓ Track token creation age (0-24h) - GOOD"
echo "  ✓ Track migration age (0-6h) - BEST! ⭐"
echo "  ✓ Fresh migrations = proven success tokens"
echo ""

echo -e "${BLUE}Why Migration Tracking Matters:${NC}"
echo "  🎯 Migration = Token graduated from Pump.fun to Raydium"
echo "  🎯 Only successful tokens migrate"
echo "  🎯 Fresh migrations (0-6h) = BEST entry signal"
echo "  🎯 These tokens have proven demand"
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
echo -e "${YELLOW}Step 2: Verify changes${NC}"
echo "─────────────────────────────────────────"

# Verify migration time tracking
if grep -q "migration_time" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Migration time tracking added"
else
    echo -e "${RED}✗${NC} Migration time not found"
    exit 1
fi

# Verify fresh migrations list
if grep -q "fresh_migrations" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Fresh migrations list added"
else
    echo -e "${RED}✗${NC} Fresh migrations list not found"
    exit 1
fi

# Verify 6-hour check
if grep -q "hours_since_migration <= 6" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} 6-hour migration window check added"
else
    echo -e "${RED}✗${NC} Migration window check not found"
    exit 1
fi

# Verify logging
if grep -q "FRESH MIGRATION" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Migration logging added"
else
    echo -e "${RED}✗${NC} Migration logging not found"
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
echo -e "${YELLOW}Step 5: Monitor for migrations${NC}"
echo "─────────────────────────────────────────"

echo "Waiting 15 seconds for pipeline..."
sleep 15

echo -e "\n${BLUE}Recent migrations:${NC}"
ssh "$VPS_IP" "tail -n 100 $PROJECT_DIR/logs/pipeline.log | grep 'FRESH MIGRATION'" || echo "No fresh migrations yet (wait 2-3 minutes)"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Migration tracking deployed!${NC}"
echo ""
echo "📊 What was added:"
echo "  1. Migration time tracking (when token migrated to Raydium)"
echo "  2. Hours since migration calculation"
echo "  3. Fresh migrations list (0-6h window)"
echo "  4. Separate logging for migrations"
echo ""
echo "🔍 Monitor for migrations:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/pipeline.log | grep MIGRATION'"
echo ""
echo "Expected output:"
echo "  🎯 FRESH MIGRATION: PEPE (migrated 2.3h ago)"
echo "  🎯 FRESH MIGRATION: DOGE (migrated 4.7h ago)"
echo "  Found 5 fresh migrations (0-6h since Raydium) ⭐"
echo ""
echo "📝 Why this matters:"
echo "  • Fresh creations (0-24h) = early stage tokens"
echo "  • Fresh migrations (0-6h) = PROVEN successful tokens"
echo "  • Migration = graduated from Pump.fun to Raydium"
echo "  • Only tokens with strong demand migrate"
echo "  • Best entry timing = just after migration"
echo ""
