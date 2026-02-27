#!/bin/bash
# Deploy Database Schema Migration

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║         DATABASE SCHEMA MIGRATION - DEPLOYMENT               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${RED}Problem:${NC}"
echo "  ✗ /insiders command: 'no such column: early_entry_count'"
echo "  ✗ /clusters command: 'no such column: cluster_size'"
echo "  ✗ Tables exist but schema doesn't match bot expectations"
echo ""

echo -e "${GREEN}Solution:${NC}"
echo "  ✓ Add missing columns to insider_pool table"
echo "  ✓ Add missing columns to wallet_clusters table"
echo "  ✓ Update cluster sizes from member counts"
echo "  ✓ Migration is safe (checks before adding)"
echo ""

VPS_IP="${1:-root@your-vps-ip}"
PROJECT_DIR="/root/Soulwinners"

echo -e "${YELLOW}Step 1: Verify local migration script${NC}"
echo "─────────────────────────────────────────"

python3 -m py_compile scripts/migrate_database_schemas.py
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Syntax check passed: migrate_database_schemas.py"
else
    echo -e "${RED}✗${NC} Syntax errors in migration script"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 2: Check current database schema on VPS${NC}"
echo "─────────────────────────────────────────"

echo "Checking insider_pool table..."
ssh "$VPS_IP" "cd $PROJECT_DIR && sqlite3 data/soulwinners.db '.schema insider_pool'" || echo "Table may not exist yet"

echo ""
echo "Checking wallet_clusters table..."
ssh "$VPS_IP" "cd $PROJECT_DIR && sqlite3 data/soulwinners.db '.schema wallet_clusters'" || echo "Table may not exist yet"

echo ""
echo -e "${YELLOW}Step 3: Backup database${NC}"
echo "─────────────────────────────────────────"

echo "Creating database backup..."
ssh "$VPS_IP" "cd $PROJECT_DIR && cp data/soulwinners.db data/soulwinners.db.backup_$(date +%Y%m%d_%H%M%S)"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Database backed up"
else
    echo -e "${RED}✗${NC} Backup failed"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 4: Deploy migration script${NC}"
echo "─────────────────────────────────────────"

scp scripts/migrate_database_schemas.py "$VPS_IP:$PROJECT_DIR/scripts/migrate_database_schemas.py"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Deployed: migrate_database_schemas.py"
else
    echo -e "${RED}✗${NC} Failed to deploy migration script"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 5: Run database migration${NC}"
echo "─────────────────────────────────────────"

echo "Running migration on VPS..."
ssh "$VPS_IP" "cd $PROJECT_DIR && python3 scripts/migrate_database_schemas.py"

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} Migration completed successfully"
else
    echo -e "${RED}✗${NC} Migration failed"
    echo ""
    echo "To restore backup:"
    echo "  ssh $VPS_IP 'cd $PROJECT_DIR && cp data/soulwinners.db.backup_* data/soulwinners.db'"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 6: Verify updated schema${NC}"
echo "─────────────────────────────────────────"

echo "Verifying insider_pool columns..."
ssh "$VPS_IP" "cd $PROJECT_DIR && sqlite3 data/soulwinners.db 'PRAGMA table_info(insider_pool)' | grep -E 'early_entry_count|win_rate|tier'"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} insider_pool columns verified"
else
    echo -e "${YELLOW}⚠${NC}  Could not verify insider_pool columns"
fi

echo ""
echo "Verifying wallet_clusters columns..."
ssh "$VPS_IP" "cd $PROJECT_DIR && sqlite3 data/soulwinners.db 'PRAGMA table_info(wallet_clusters)' | grep -E 'cluster_size|cluster_type|connection_strength'"
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC} wallet_clusters columns verified"
else
    echo -e "${YELLOW}⚠${NC}  Could not verify wallet_clusters columns"
fi

echo ""
echo -e "${YELLOW}Step 7: Restart bot service${NC}"
echo "─────────────────────────────────────────"

ssh "$VPS_IP" "systemctl restart soulwinners-bot 2>/dev/null || echo 'Bot service not found (may need manual restart)'"

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║              DEPLOYMENT COMPLETE                             ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo -e "${GREEN}✅ Database schema migration deployed!${NC}"
echo ""
echo "📊 Columns Added:"
echo ""
echo "  insider_pool table:"
echo "    • early_entry_count (INTEGER DEFAULT 0)"
echo "    • win_rate (REAL DEFAULT 0.0)"
echo "    • avg_hold_minutes (REAL DEFAULT 0.0)"
echo "    • tier (TEXT DEFAULT 'Bronze')"
echo "    • discovered_at (TIMESTAMP)"
echo ""
echo "  wallet_clusters table:"
echo "    • cluster_size (INTEGER DEFAULT 0)"
echo "    • cluster_type (TEXT DEFAULT 'Unknown')"
echo "    • connection_strength (REAL DEFAULT 0.0)"
echo "    • shared_tokens (TEXT DEFAULT '')"
echo ""
echo "🧪 Test Telegram Commands:"
echo ""
echo "  1. Test insider pool:"
echo "     Send: /insiders"
echo "     Expected: List of insider wallets with stats"
echo "     Should NOT show: 'no such column: early_entry_count'"
echo ""
echo "  2. Test cluster detection:"
echo "     Send: /clusters"
echo "     Expected: List of wallet clusters with sizes"
echo "     Should NOT show: 'no such column: cluster_size'"
echo ""
echo "📝 If commands still fail:"
echo ""
echo "  Check bot logs:"
echo "    ssh $VPS_IP 'journalctl -u soulwinners-bot -n 50'"
echo ""
echo "  Verify schema manually:"
echo "    ssh $VPS_IP 'cd $PROJECT_DIR && sqlite3 data/soulwinners.db'"
echo "    sqlite> PRAGMA table_info(insider_pool);"
echo "    sqlite> PRAGMA table_info(wallet_clusters);"
echo ""
echo "  Restore backup if needed:"
echo "    ssh $VPS_IP 'cd $PROJECT_DIR && cp data/soulwinners.db.backup_* data/soulwinners.db'"
echo ""
