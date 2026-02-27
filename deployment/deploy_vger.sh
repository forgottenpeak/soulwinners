#!/bin/bash
# V'ger Bot Deployment Script for VPS
# Deploys the V'ger Telegram control bot to manage OpenClaw trader

set -e

echo "=========================================="
echo "V'GER BOT DEPLOYMENT"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: Please run as root${NC}"
    exit 1
fi

# Configuration
PROJECT_DIR="/root/Soulwinners"
VENV_DIR="$PROJECT_DIR/venv"
LOG_DIR="$PROJECT_DIR/logs"
SERVICE_NAME="vger"

echo -e "${YELLOW}1. Checking prerequisites...${NC}"

# Check if project directory exists
if [ ! -d "$PROJECT_DIR" ]; then
    echo -e "${RED}Error: Project directory not found: $PROJECT_DIR${NC}"
    exit 1
fi

# Check if OpenClaw is installed
if [ ! -f "$PROJECT_DIR/trader/openclaw.py" ]; then
    echo -e "${RED}Error: OpenClaw trader not found. Deploy OpenClaw first.${NC}"
    exit 1
fi

# Check if .env exists
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo -e "${RED}Error: .env file not found${NC}"
    exit 1
fi

# Check for required env vars
source "$PROJECT_DIR/.env"
if [ -z "$VGER_BOT_TOKEN" ]; then
    echo -e "${RED}Error: VGER_BOT_TOKEN not set in .env${NC}"
    exit 1
fi

if [ -z "$VGER_ADMIN_ID" ]; then
    echo -e "${RED}Error: VGER_ADMIN_ID not set in .env${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Prerequisites OK${NC}"

echo ""
echo -e "${YELLOW}2. Creating log directory...${NC}"
mkdir -p "$LOG_DIR"
echo -e "${GREEN}✓ Log directory ready${NC}"

echo ""
echo -e "${YELLOW}3. Installing Python dependencies...${NC}"
cd "$PROJECT_DIR"

# Check if venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate venv and install
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install python-telegram-bot python-dotenv
echo -e "${GREEN}✓ Dependencies installed${NC}"

echo ""
echo -e "${YELLOW}4. Installing systemd service...${NC}"

# Copy service file
if [ ! -f "$PROJECT_DIR/deployment/vger.service" ]; then
    echo -e "${RED}Error: vger.service file not found in deployment/${NC}"
    exit 1
fi

cp "$PROJECT_DIR/deployment/vger.service" /etc/systemd/system/vger.service
systemctl daemon-reload
echo -e "${GREEN}✓ Service file installed${NC}"

echo ""
echo -e "${YELLOW}5. Starting V'ger service...${NC}"

# Stop if running
systemctl stop vger 2>/dev/null || true

# Enable and start
systemctl enable vger
systemctl start vger

# Check status
sleep 2
if systemctl is-active --quiet vger; then
    echo -e "${GREEN}✓ V'ger service started successfully${NC}"
else
    echo -e "${RED}✗ V'ger service failed to start${NC}"
    echo "Check logs with: journalctl -u vger -f"
    exit 1
fi

echo ""
echo "=========================================="
echo -e "${GREEN}V'GER DEPLOYMENT COMPLETE${NC}"
echo "=========================================="
echo ""
echo "Service status:"
systemctl status vger --no-pager | head -n 10
echo ""
echo -e "${YELLOW}Useful commands:${NC}"
echo "  systemctl status vger    - Check service status"
echo "  systemctl stop vger      - Stop service"
echo "  systemctl start vger     - Start service"
echo "  systemctl restart vger   - Restart service"
echo "  journalctl -u vger -f    - View live logs"
echo "  tail -f $LOG_DIR/vger.log - View application logs"
echo ""
echo -e "${YELLOW}Test V'ger:${NC}"
echo "  1. Open Telegram"
echo "  2. Find @vgerr_bot"
echo "  3. Send /start"
echo "  4. Send /status to see OpenClaw status"
echo ""
echo -e "${GREEN}🖖 V'ger is online and awaiting commands.${NC}"
echo ""
