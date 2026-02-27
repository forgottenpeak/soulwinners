#!/bin/bash
# Trading API Bridge Deployment Script

set -e

echo "=========================================="
echo "TRADING API BRIDGE DEPLOYMENT"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: Please run as root${NC}"
    exit 1
fi

# Configuration
PROJECT_DIR="/root/Soulwinners"
VENV_DIR="$PROJECT_DIR/venv"
LOG_DIR="$PROJECT_DIR/logs"

echo -e "${YELLOW}1. Checking prerequisites...${NC}"

# Check project directory
if [ ! -d "$PROJECT_DIR" ]; then
    echo -e "${RED}Error: Project directory not found: $PROJECT_DIR${NC}"
    exit 1
fi

# Check .env
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo -e "${RED}Error: .env file not found${NC}"
    exit 1
fi

# Source .env
source "$PROJECT_DIR/.env"

# Check for private key
if [ -z "$OPENCLAW_PRIVATE_KEY" ]; then
    echo -e "${RED}Error: OPENCLAW_PRIVATE_KEY not set in .env${NC}"
    echo "The trading API requires a wallet private key to execute trades."
    exit 1
fi

# Check for API token
if [ -z "$TRADING_API_TOKEN" ]; then
    echo -e "${YELLOW}Warning: TRADING_API_TOKEN not set${NC}"
    echo "A secure token will be generated on first run."
    echo "You'll need to add it to your .env file."
fi

echo -e "${GREEN}✓ Prerequisites OK${NC}"

echo ""
echo -e "${YELLOW}2. Creating log directory...${NC}"
mkdir -p "$LOG_DIR"
echo -e "${GREEN}✓ Log directory ready${NC}"

echo ""
echo -e "${YELLOW}3. Installing Python dependencies...${NC}"
cd "$PROJECT_DIR"

# Check venv
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate and install
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install flask flask-cors python-dotenv
echo -e "${GREEN}✓ Dependencies installed${NC}"

echo ""
echo -e "${YELLOW}4. Installing Trading API service...${NC}"

# Copy service file
if [ ! -f "$PROJECT_DIR/deployment/trading_api.service" ]; then
    echo -e "${RED}Error: trading_api.service not found${NC}"
    exit 1
fi

cp "$PROJECT_DIR/deployment/trading_api.service" /etc/systemd/system/
systemctl daemon-reload
echo -e "${GREEN}✓ Service file installed${NC}"

echo ""
echo -e "${YELLOW}5. Starting Trading API...${NC}"

# Stop if running
systemctl stop trading_api 2>/dev/null || true

# Enable and start
systemctl enable trading_api
systemctl start trading_api

# Check status
sleep 2
if systemctl is-active --quiet trading_api; then
    echo -e "${GREEN}✓ Trading API started successfully${NC}"
else
    echo -e "${RED}✗ Trading API failed to start${NC}"
    echo "Check logs: journalctl -u trading_api -f"
    exit 1
fi

echo ""
echo -e "${YELLOW}6. Checking API health...${NC}"

# Wait for API to be ready
sleep 3

# Test health endpoint
HEALTH_CHECK=$(curl -s http://localhost:5000/api/health || echo "failed")

if echo "$HEALTH_CHECK" | grep -q "healthy"; then
    echo -e "${GREEN}✓ API health check passed${NC}"
else
    echo -e "${RED}✗ API health check failed${NC}"
    echo "Response: $HEALTH_CHECK"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}TRADING API DEPLOYMENT COMPLETE${NC}"
echo "=========================================="
echo ""

# Show API token if generated
if [ -z "$TRADING_API_TOKEN" ]; then
    echo -e "${YELLOW}⚠ IMPORTANT: API Token${NC}"
    echo ""
    echo "Check the API logs for your generated token:"
    echo "  tail -n 50 $LOG_DIR/trading_api.log | grep 'Generated token'"
    echo ""
    echo "Add it to your .env file:"
    echo "  TRADING_API_TOKEN=<your-token>"
    echo ""
fi

echo "Service status:"
systemctl status trading_api --no-pager | head -n 10

echo ""
echo -e "${YELLOW}Local API URL:${NC} http://localhost:5000"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "  1. Setup ngrok tunnel (for remote access):"
echo "     sudo bash deployment/setup_ngrok.sh"
echo ""
echo "  2. Test API locally:"
echo "     curl http://localhost:5000/api/health"
echo ""
echo "  3. Get API token from logs:"
echo "     tail -f $LOG_DIR/trading_api.log"
echo ""
echo -e "${YELLOW}Useful Commands:${NC}"
echo "  systemctl status trading_api"
echo "  systemctl restart trading_api"
echo "  journalctl -u trading_api -f"
echo "  tail -f $LOG_DIR/trading_api.log"
echo ""
echo -e "${GREEN}Trading API is ready to accept connections!${NC}"
echo ""
