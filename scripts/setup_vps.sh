#!/bin/bash
# =============================================================================
# VPS SETUP SCRIPT - Run after git pull
# Sets up environment variables and API keys
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

echo "=========================================="
echo "SoulWinners VPS Setup"
echo "=========================================="

# Create .env file if it doesn't exist
if [ ! -f "$ENV_FILE" ]; then
    echo "Creating .env file..."
    touch "$ENV_FILE"
fi

# Function to set env variable
set_env() {
    local key=$1
    local value=$2
    local file=$3

    if grep -q "^${key}=" "$file" 2>/dev/null; then
        # Update existing
        sed -i "s|^${key}=.*|${key}=${value}|" "$file"
    else
        # Add new
        echo "${key}=${value}" >> "$file"
    fi
}

echo ""
echo "Setting up Helius API Keys..."
echo "================================"

# MONITORING KEYS (3 keys) - For real-time buy alert monitoring
set_env "HELIUS_MONITOR_KEY_1" "9081e779-6108-4699-8937-26eae13d0963" "$ENV_FILE"
set_env "HELIUS_MONITOR_KEY_2" "f3669c59-b5e5-48b1-baf1-13f67b3fa342" "$ENV_FILE"
set_env "HELIUS_MONITOR_KEY_3" "0e524dfe-ff4a-4fea-bf8c-cb455dd82707" "$ENV_FILE"

# CRON KEYS (10 keys) - For background pipeline/cron jobs
set_env "HELIUS_CRON_KEY_1" "21656a17-a0c0-4c9d-99a1-68ee607b644c" "$ENV_FILE"
set_env "HELIUS_CRON_KEY_2" "58591b72-7973-4668-bebd-361e170f1748" "$ENV_FILE"
set_env "HELIUS_CRON_KEY_3" "6dd6522d-b292-4ab5-85e9-567d973beaa5" "$ENV_FILE"
set_env "HELIUS_CRON_KEY_4" "28afc29b-5ef0-4edf-add2-52dea80854f4" "$ENV_FILE"
set_env "HELIUS_CRON_KEY_5" "b1a8feb3-bbd3-4ae0-81dc-67aff11b1338" "$ENV_FILE"
set_env "HELIUS_CRON_KEY_6" "5023062c-f4cd-411f-a462-49df6fa9d5ae" "$ENV_FILE"
set_env "HELIUS_CRON_KEY_7" "59bf3ee7-582f-415e-8631-c6cc6e9d3bde" "$ENV_FILE"
set_env "HELIUS_CRON_KEY_8" "4cf897ed-a81f-4aa2-9e66-ce735a010e6c" "$ENV_FILE"
set_env "HELIUS_CRON_KEY_9" "c9fd3f13-bcc3-4829-aa8e-b74427ef3381" "$ENV_FILE"
set_env "HELIUS_CRON_KEY_10" "59648c8b-a691-451b-b1ee-3542ad7afd36" "$ENV_FILE"

echo ""
echo "Setting up Telegram Config..."
echo "================================"
set_env "TELEGRAM_BOT_TOKEN" "8483614914:AAFjwtH2pct_OdZgi4zrcPNKq6zWdb62ypQ" "$ENV_FILE"
set_env "TELEGRAM_CHANNEL_ID" "-1003534177506" "$ENV_FILE"
set_env "TELEGRAM_USER_ID" "1153491543" "$ENV_FILE"

echo ""
echo "Setting up OpenClaw Auto-Trader..."
echo "================================"
# OpenClaw settings - USER MUST SET PRIVATE KEY MANUALLY
set_env "OPENCLAW_CHAT_ID" "1153491543" "$ENV_FILE"
# set_env "OPENCLAW_PRIVATE_KEY" "" "$ENV_FILE"  # SET MANUALLY - NEVER COMMIT

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "IMPORTANT: You must manually set the following in .env:"
echo "  - OPENCLAW_PRIVATE_KEY (trading wallet private key)"
echo ""
echo "To add Kimi AI API key:"
echo "  echo 'KIMI_API_KEY=your-key-here' >> .env"
echo ""
echo "Next steps:"
echo "  1. Edit .env to add private keys"
echo "  2. Run: python3 -m pytest tests/ (if tests exist)"
echo "  3. Restart services: systemctl restart soulwinners-bot"
echo ""
