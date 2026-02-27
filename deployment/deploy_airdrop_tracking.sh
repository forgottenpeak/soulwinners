#!/bin/bash
# Deploy Airdrop Tracking to VPS

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║        AIRDROP TRACKING - DEPLOYMENT                         ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
NC='\033[0m'

echo -e "${BLUE}What's being added:${NC}"
echo "  • Track airdrop recipients (team/insiders)"
echo "  • Detect token transfers with 0 SOL cost"
echo "  • Monitor insider sell behavior"
echo "  • Generate alerts when insiders dump"
echo "  • Auto-add airdrop wallets to pool (no screening)"
echo ""

VPS_IP="${1:-root@your-vps-ip}"
PROJECT_DIR="/root/Soulwinners"

echo -e "${YELLOW}Step 1: Verify local files${NC}"
echo "─────────────────────────────────────────"

# Check syntax of modified files
FILES=(
    "collectors/launch_tracker.py"
    "pipeline/insider_detector.py"
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
if grep -q "class AirdropTracker" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} AirdropTracker class added"
else
    echo "✗ AirdropTracker class not found"
    exit 1
fi

if grep -q "class AirdropRecipient" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} AirdropRecipient dataclass added"
else
    echo "✗ AirdropRecipient dataclass not found"
    exit 1
fi

if grep -q "airdrop_insiders" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} airdrop_insiders table schema added"
else
    echo "✗ airdrop_insiders table not found"
    exit 1
fi

if grep -q "detect_airdrops" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Airdrop detection method added"
else
    echo "✗ Airdrop detection method not found"
    exit 1
fi

if grep -q "generate_sell_alert" collectors/launch_tracker.py; then
    echo -e "${GREEN}✓${NC} Sell alert generation added"
else
    echo "✗ Sell alert generation not found"
    exit 1
fi

if grep -q "_check_airdrop_history" pipeline/insider_detector.py; then
    echo -e "${GREEN}✓${NC} Airdrop history check added to insider detector"
else
    echo "✗ Airdrop history check not found"
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
echo -e "${YELLOW}Step 4: Create database tables${NC}"
echo "─────────────────────────────────────────"

echo "Creating airdrop_insiders table on VPS..."
ssh "$VPS_IP" "sqlite3 $PROJECT_DIR/data/soulwinners.db \"
CREATE TABLE IF NOT EXISTS airdrop_insiders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    token_address TEXT NOT NULL,
    token_symbol TEXT,
    received_time TIMESTAMP,
    time_since_launch_min INTEGER,
    token_amount REAL,
    token_value_sol REAL DEFAULT 0,
    percent_of_supply REAL DEFAULT 0,
    has_sold INTEGER DEFAULT 0,
    sold_amount REAL DEFAULT 0,
    sold_at TIMESTAMP,
    hold_duration_min INTEGER DEFAULT 0,
    pattern TEXT DEFAULT 'Airdrop Insider',
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(wallet_address, token_address)
);
\""

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Database table created"
else
    echo "✗ Database table creation failed"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 5: Restart SoulWinners service${NC}"
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
echo -e "${YELLOW}Step 6: Verify deployment${NC}"
echo "─────────────────────────────────────────"

echo "Checking if changes are present on VPS..."
ssh "$VPS_IP" "grep -q 'class AirdropTracker' $PROJECT_DIR/collectors/launch_tracker.py && echo 'Found AirdropTracker' || echo 'Missing AirdropTracker'"
ssh "$VPS_IP" "grep -q 'airdrop_insiders' $PROJECT_DIR/collectors/launch_tracker.py && echo 'Found airdrop_insiders table' || echo 'Missing airdrop_insiders table'"
ssh "$VPS_IP" "grep -q 'detect_airdrops' $PROJECT_DIR/collectors/launch_tracker.py && echo 'Found airdrop detection' || echo 'Missing airdrop detection'"

# Verify database table
ssh "$VPS_IP" "sqlite3 $PROJECT_DIR/data/soulwinners.db \"SELECT name FROM sqlite_master WHERE type='table' AND name='airdrop_insiders'\" && echo 'airdrop_insiders table exists' || echo 'Table not found'"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Airdrop tracking deployed successfully!${NC}"
echo ""
echo "📊 What was added:"
echo "  1. AirdropTracker class (detect airdrop recipients)"
echo "  2. AirdropRecipient dataclass (track airdrop data)"
echo "  3. airdrop_insiders database table"
echo "  4. Airdrop detection in insider scanner"
echo "  5. Sell tracking and alerts"
echo "  6. Auto-add airdrop wallets to pool"
echo ""
echo "🔍 Monitor airdrop detection:"
echo "  ssh $VPS_IP 'tail -f $PROJECT_DIR/logs/pipeline.log'"
echo ""
echo "Look for:"
echo "  • 'Airdrop detected: <wallet>'"
echo "  • 'Found X airdrop recipients'"
echo "  • 'Added airdrop wallet to pool'"
echo "  • '🚨 INSIDER SELL DETECTED' (when they dump)"
echo ""
echo "📝 Check airdrop insiders:"
echo "  ssh $VPS_IP 'sqlite3 $PROJECT_DIR/data/soulwinners.db \"SELECT * FROM airdrop_insiders LIMIT 10\"'"
echo ""
echo "📈 Expected results:"
echo "  • Detect team members via airdrops"
echo "  • Track insider sell behavior"
echo "  • Alert when insiders dump"
echo "  • Auto-add valuable insider wallets to pool"
echo ""
