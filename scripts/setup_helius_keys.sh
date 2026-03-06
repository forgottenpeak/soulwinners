#!/bin/bash
# =============================================================================
# HELIUS API KEY SETUP SCRIPT
# Run this on VPS after pulling code to configure API keys
# =============================================================================

# Configuration file
CONFIG_FILE="/root/Soulwinners/config/settings.py"

echo "=============================================="
echo "HELIUS API KEY CONFIGURATION"
echo "=============================================="
echo ""
echo "This script will update settings.py with your actual API keys."
echo "Make sure you have the keys ready before proceeding."
echo ""

# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: Config file not found at $CONFIG_FILE"
    exit 1
fi

# Backup original
cp "$CONFIG_FILE" "${CONFIG_FILE}.backup"
echo "Backup created: ${CONFIG_FILE}.backup"
echo ""

# =============================================================================
# MONITORING KEYS (3 keys for real-time buy alerts)
# =============================================================================
echo "Setting MONITORING KEYS (3 keys for real-time alerts)..."

sed -i 's/PLACEHOLDER_MONITOR_KEY_1/9081e779-6108-4699-8937-26eae13d0963/g' "$CONFIG_FILE"
sed -i 's/PLACEHOLDER_MONITOR_KEY_2/f3669c59-b5e5-48b1-baf1-13f67b3fa342/g' "$CONFIG_FILE"
sed -i 's/PLACEHOLDER_MONITOR_KEY_3/0e524dfe-ff4a-4fea-bf8c-cb455dd82707/g' "$CONFIG_FILE"

echo "  - Monitor Key 1: 9081e779..."
echo "  - Monitor Key 2: f3669c59..."
echo "  - Monitor Key 3: 0e524dfe..."

# =============================================================================
# CRON KEYS (10 keys for background pipeline jobs)
# =============================================================================
echo ""
echo "Setting CRON KEYS (10 keys for background jobs)..."

sed -i 's/PLACEHOLDER_CRON_KEY_1/21656a17-a0c0-4c9d-99a1-68ee607b644c/g' "$CONFIG_FILE"
sed -i 's/PLACEHOLDER_CRON_KEY_2/58591b72-7973-4668-bebd-361e170f1748/g' "$CONFIG_FILE"
sed -i 's/PLACEHOLDER_CRON_KEY_3/6dd6522d-b292-4ab5-85e9-567d973beaa5/g' "$CONFIG_FILE"
sed -i 's/PLACEHOLDER_CRON_KEY_4/28afc29b-5ef0-4edf-add2-52dea80854f4/g' "$CONFIG_FILE"
sed -i 's/PLACEHOLDER_CRON_KEY_5/b1a8feb3-bbd3-4ae0-81dc-67aff11b1338/g' "$CONFIG_FILE"
sed -i 's/PLACEHOLDER_CRON_KEY_6/5023062c-f4cd-411f-a462-49df6fa9d5ae/g' "$CONFIG_FILE"
sed -i 's/PLACEHOLDER_CRON_KEY_7/59bf3ee7-582f-415e-8631-c6cc6e9d3bde/g' "$CONFIG_FILE"
sed -i 's/PLACEHOLDER_CRON_KEY_8/4cf897ed-a81f-4aa2-9e66-ce735a010e6c/g' "$CONFIG_FILE"
sed -i 's/PLACEHOLDER_CRON_KEY_9/c9fd3f13-bcc3-4829-aa8e-b74427ef3381/g' "$CONFIG_FILE"
sed -i 's/PLACEHOLDER_CRON_KEY_10/59648c8b-a691-451b-b1ee-3542ad7afd36/g' "$CONFIG_FILE"

echo "  - Cron Key 1: 21656a17..."
echo "  - Cron Key 2: 58591b72..."
echo "  - Cron Key 3: 6dd6522d..."
echo "  - Cron Key 4: 28afc29b..."
echo "  - Cron Key 5: b1a8feb3..."
echo "  - Cron Key 6: 5023062c..."
echo "  - Cron Key 7: 59bf3ee7..."
echo "  - Cron Key 8: 4cf897ed..."
echo "  - Cron Key 9: c9fd3f13..."
echo "  - Cron Key 10: 59648c8b..."

echo ""
echo "=============================================="
echo "CONFIGURATION COMPLETE"
echo "=============================================="
echo ""
echo "Key pools configured:"
echo "  - MONITORING: 3 keys (real-time buy alerts)"
echo "  - CRON: 10 keys (pipeline/insider/cluster jobs)"
echo ""
echo "Total capacity: 13 keys = ~1300 req/sec"
echo ""
echo "Now restart services:"
echo "  systemctl restart soulwinners-bot"
echo "  systemctl restart soulwinners-collector"
echo ""
