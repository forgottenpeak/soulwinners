# Trading API Bridge - Quick Start

Remote trade execution from Mac → VPS

## One-Command Deploy

```bash
# 1. Deploy Trading API
ssh root@your-vps-ip
cd /root/Soulwinners
sudo bash deployment/deploy_trading_api.sh

# 2. Setup ngrok tunnel
sudo bash deployment/setup_ngrok.sh
```

## Get Credentials

```bash
# 1. Get ngrok public URL
curl http://localhost:4040/api/tunnels | jq -r '.tunnels[0].public_url'
# Output: https://abc123.ngrok.io

# 2. Get API token
grep TRADING_API_TOKEN .env
# Or: tail -f logs/trading_api.log | grep "Generated token"
```

## Configure OpenClaw (Mac)

Add to OpenClaw configuration:

```python
# Remote trading via VPS API
TRADING_API_URL = "https://abc123.ngrok.io"
TRADING_API_TOKEN = "your_token_here"
USE_REMOTE_API = True
```

## Test API

### From VPS (local)

```bash
# Health check
curl http://localhost:5000/api/health

# Status (with auth)
TOKEN="your_token"
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:5000/api/status
```

### From Mac (remote)

```bash
# Set variables
export API_URL="https://abc123.ngrok.io"
export TOKEN="your_token"

# Health check
curl $API_URL/api/health

# Get status
curl -H "Authorization: Bearer $TOKEN" \
     $API_URL/api/status | jq
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/health` | GET | Health check (no auth) |
| `/api/status` | GET | Trading status |
| `/api/positions` | GET | Open positions |
| `/api/execute_buy` | POST | Execute buy order |
| `/api/execute_sell` | POST | Execute sell order |
| `/api/update_strategy` | POST | Update strategy |

## Python Client Example

```python
import requests

class TradingAPIClient:
    def __init__(self, api_url, api_token):
        self.api_url = api_url
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }

    def get_status(self):
        """Get trading status."""
        response = requests.get(
            f"{self.api_url}/api/status",
            headers=self.headers
        )
        return response.json()

    def execute_buy(self, token_mint, token_symbol, sol_amount):
        """Execute buy order."""
        response = requests.post(
            f"{self.api_url}/api/execute_buy",
            headers=self.headers,
            json={
                "token_mint": token_mint,
                "token_symbol": token_symbol,
                "sol_amount": sol_amount,
                "source_wallet": "openclaw"
            }
        )
        return response.json()

    def execute_sell(self, token_mint, sell_percent, reason="manual"):
        """Execute sell order."""
        response = requests.post(
            f"{self.api_url}/api/execute_sell",
            headers=self.headers,
            json={
                "token_mint": token_mint,
                "sell_percent": sell_percent,
                "reason": reason
            }
        )
        return response.json()

# Usage
client = TradingAPIClient(
    api_url="https://abc123.ngrok.io",
    api_token="your_token"
)

# Get status
status = client.get_status()
print(f"Balance: {status['balance_sol']} SOL")

# Execute buy
result = client.execute_buy(
    token_mint="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    token_symbol="BONK",
    sol_amount=0.1
)
print(f"Buy signature: {result['signature']}")

# Execute sell
result = client.execute_sell(
    token_mint="DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    sell_percent=50.0,
    reason="tp1"
)
print(f"Sell signature: {result['signature']}")
```

## Service Management

```bash
# Check status
systemctl status trading_api ngrok

# Restart
systemctl restart trading_api ngrok

# Logs
tail -f /root/Soulwinners/logs/trading_api.log
tail -f /root/Soulwinners/logs/ngrok.log

# Get ngrok URL anytime
curl http://localhost:4040/api/tunnels | jq -r '.tunnels[0].public_url'
```

## Troubleshooting

### API Not Responding

```bash
# Check if running
systemctl status trading_api

# Restart
systemctl restart trading_api

# Check logs
tail -n 50 /root/Soulwinners/logs/trading_api.log
```

### Ngrok URL Changed

Free tier changes URL on restart:

```bash
# Get new URL
curl http://localhost:4040/api/tunnels | jq -r '.tunnels[0].public_url'

# Update OpenClaw with new URL
```

### Authentication Failed

```bash
# Check token
grep TRADING_API_TOKEN /root/Soulwinners/.env

# If missing, check logs
tail -f /root/Soulwinners/logs/trading_api.log | grep "token"

# Add to .env
echo "TRADING_API_TOKEN=your_token" >> /root/Soulwinners/.env
systemctl restart trading_api
```

## Architecture

```
Mac (OpenClaw)
    ↓ HTTPS REST API
Ngrok Tunnel
    ↓
VPS (Trading API)
    ↓
Jupiter DEX
    ↓
Solana Mainnet
```

## Security

- ✅ Bearer token authentication
- ✅ HTTPS encryption (ngrok)
- ✅ Rate limiting (60/min)
- ✅ Request logging
- ✅ CORS enabled

## Next Steps

1. ✅ Deploy API to VPS
2. ✅ Setup ngrok tunnel
3. ✅ Get credentials (URL + Token)
4. ⬜ Update OpenClaw config
5. ⬜ Test buy/sell
6. ⬜ Monitor logs

---

**API URL:** `https://your-ngrok-url.ngrok.io`
**Status:** 🟢 Ready
