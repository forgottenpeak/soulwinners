#!/bin/bash
# Setup ngrok for Trading API tunnel

set -e

echo "=========================================="
echo "NGROK TUNNEL SETUP"
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

echo -e "${YELLOW}1. Checking ngrok installation...${NC}"

# Check if ngrok is installed
if ! command -v ngrok &> /dev/null; then
    echo "ngrok not found. Installing..."

    # Download ngrok
    cd /tmp
    wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
    tar xvzf ngrok-v3-stable-linux-amd64.tgz -C /usr/local/bin
    chmod +x /usr/local/bin/ngrok

    echo -e "${GREEN}✓ ngrok installed${NC}"
else
    echo -e "${GREEN}✓ ngrok already installed${NC}"
fi

echo ""
echo -e "${YELLOW}2. Configuring ngrok...${NC}"

# Check for ngrok auth token
NGROK_TOKEN="${NGROK_AUTHTOKEN:-}"

if [ -z "$NGROK_TOKEN" ]; then
    echo -e "${YELLOW}You need an ngrok auth token.${NC}"
    echo ""
    echo "Get your token:"
    echo "  1. Visit: https://dashboard.ngrok.com/signup"
    echo "  2. Sign up (free)"
    echo "  3. Copy your auth token"
    echo ""
    echo -n "Enter your ngrok auth token: "
    read NGROK_TOKEN
fi

if [ -n "$NGROK_TOKEN" ]; then
    ngrok config add-authtoken "$NGROK_TOKEN"
    echo -e "${GREEN}✓ ngrok authenticated${NC}"
else
    echo -e "${RED}Error: No auth token provided${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}3. Creating ngrok systemd service...${NC}"

# Copy service file
if [ ! -f "/root/Soulwinners/deployment/ngrok.service" ]; then
    echo -e "${RED}Error: ngrok.service file not found${NC}"
    exit 1
fi

cp /root/Soulwinners/deployment/ngrok.service /etc/systemd/system/
systemctl daemon-reload

echo -e "${GREEN}✓ ngrok service installed${NC}"

echo ""
echo -e "${YELLOW}4. Starting ngrok tunnel...${NC}"

# Enable and start ngrok
systemctl enable ngrok
systemctl restart ngrok

# Wait for ngrok to start
sleep 3

# Check status
if systemctl is-active --quiet ngrok; then
    echo -e "${GREEN}✓ ngrok tunnel started${NC}"
else
    echo -e "${RED}✗ ngrok failed to start${NC}"
    echo "Check logs: journalctl -u ngrok -f"
    exit 1
fi

echo ""
echo -e "${YELLOW}5. Getting tunnel URL...${NC}"

# Get public URL from ngrok API
sleep 2
NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | grep -o '"public_url":"https://[^"]*' | cut -d'"' -f4 | head -n1)

if [ -n "$NGROK_URL" ]; then
    echo -e "${GREEN}✓ Tunnel established${NC}"
    echo ""
    echo "=========================================="
    echo "NGROK TUNNEL ACTIVE"
    echo "=========================================="
    echo ""
    echo -e "${GREEN}Public URL:${NC} $NGROK_URL"
    echo ""
    echo "Save this URL for OpenClaw configuration!"
    echo ""
    echo "API Endpoints:"
    echo "  $NGROK_URL/api/health"
    echo "  $NGROK_URL/api/status"
    echo "  $NGROK_URL/api/execute_buy"
    echo "  $NGROK_URL/api/execute_sell"
    echo ""
    echo "Test with:"
    echo "  curl $NGROK_URL/api/health"
    echo ""
else
    echo -e "${YELLOW}⚠ Could not retrieve tunnel URL${NC}"
    echo "Get it manually:"
    echo "  curl http://localhost:4040/api/tunnels"
    echo ""
fi

echo "Ngrok dashboard: http://localhost:4040"
echo ""
echo -e "${YELLOW}Management Commands:${NC}"
echo "  systemctl status ngrok"
echo "  systemctl restart ngrok"
echo "  journalctl -u ngrok -f"
echo ""
echo -e "${GREEN}Ngrok setup complete!${NC}"
