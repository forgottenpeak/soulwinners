# Trading API Bridge - Complete Guide

REST API bridge for remote trade execution from OpenClaw (Mac) to VPS trader.

## Architecture

```
┌──────────────────┐
│   Mac (Local)    │
│   OpenClaw       │
│   Decision Maker │
└────────┬─────────┘
         │ HTTPS/REST
         │ (via ngrok)
         ▼
┌──────────────────┐
│  VPS (Remote)    │
│  Trading API     │
│  Executor        │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  Jupiter DEX     │
│  Solana Mainnet  │
└──────────────────┘
```

## Features

### Secure REST API
- Bearer token authentication
- Rate limiting (60 req/min)
- CORS enabled
- Comprehensive logging

### Trade Execution
- Buy tokens with SOL
- Sell tokens (partial or full)
- Position management
- Strategy updates

### Monitoring
- Health checks
- Real-time status
- Position tracking
- Balance queries

## Quick Deploy

### 1. Deploy Trading API

```bash
ssh root@your-vps-ip
cd /root/Soulwinners
sudo bash deployment/deploy_trading_api.sh
```

### 2. Setup Ngrok Tunnel

```bash
sudo bash deployment/setup_ngrok.sh
```

You'll need an ngrok account (free):
- Visit: https://dashboard.ngrok.com/signup
- Get your auth token

### 3. Get API Credentials

```bash
# Get ngrok public URL
curl http://localhost:4040/api/tunnels | jq -r '.tunnels[0].public_url'

# Get API token
grep TRADING_API_TOKEN /root/Soulwinners/.env
# Or from logs:
tail -n 50 /root/Soulwinners/logs/trading_api.log | grep "Generated token"
```

## API Endpoints

Base URL: `https://your-ngrok-url.ngrok.io`

### Authentication

All endpoints (except `/api/health`) require Bearer token:

```bash
Authorization: Bearer your_api_token_here
```

### Endpoints

#### 1. Health Check
**No authentication required**

```bash
GET /api/health

Response:
{
  "status": "healthy",
  "timestamp": "2026-02-27T14:30:00",
  "dex_connected": true
}
```

#### 2. Get Status

```bash
GET /api/status
Authorization: Bearer <token>

Response:
{
  "success": true,
  "timestamp": "2026-02-27T14:30:00",
  "balance_sol": 0.185,
  "stats": {
    "current_balance": 0.185,
    "total_pnl_sol": 0.025,
    "total_pnl_percent": 12.5,
    "total_trades": 4,
    "win_rate": 75.0
  },
  "open_positions": 1,
  "positions": [...]
}
```

#### 3. Execute Buy

```bash
POST /api/execute_buy
Authorization: Bearer <token>
Content-Type: application/json

Body:
{
  "token_mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
  "token_symbol": "BONK",
  "sol_amount": 0.1,
  "source_wallet": "elite_wallet_address"
}

Response:
{
  "success": true,
  "signature": "5Kq...",
  "token_amount": 1234567.89,
  "entry_price": 0.000012,
  "position": {...},
  "timestamp": "2026-02-27T14:30:00"
}
```

#### 4. Execute Sell

```bash
POST /api/execute_sell
Authorization: Bearer <token>
Content-Type: application/json

Body:
{
  "token_mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
  "sell_percent": 50.0,
  "reason": "tp1"
}

Response:
{
  "success": true,
  "signature": "3Qw...",
  "sol_received": 0.125,
  "sell_percent": 50.0,
  "position": {...},
  "timestamp": "2026-02-27T14:30:00"
}
```

#### 5. Update Strategy

```bash
POST /api/update_strategy
Authorization: Bearer <token>
Content-Type: application/json

Body:
{
  "stop_loss_percent": -15.0,
  "tp1_percent": 40.0,
  "tp2_percent": 80.0,
  "position_size_percent": 80.0
}

Response:
{
  "success": true,
  "updated_fields": ["stop_loss_percent", "tp1_percent"],
  "current_config": {...},
  "timestamp": "2026-02-27T14:30:00"
}
```

#### 6. Get Positions

```bash
GET /api/positions
Authorization: Bearer <token>

Response:
{
  "success": true,
  "count": 2,
  "positions": [
    {
      "id": "DezXAZ8z_1709049600",
      "token_mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
      "token_symbol": "BONK",
      "entry_price": 0.000012,
      "entry_sol": 0.1,
      "current_price": 0.000015,
      "pnl_percent": 25.0,
      "pnl_sol": 0.025,
      "status": "open",
      "remaining_percent": 100.0,
      "entry_time": "2026-02-27T12:00:00"
    }
  ],
  "timestamp": "2026-02-27T14:30:00"
}
```

## Environment Configuration

Add to `/root/Soulwinners/.env`:

```bash
# Trading API
TRADING_API_TOKEN=your_generated_token_here
OPENCLAW_PRIVATE_KEY=your_solana_wallet_private_key
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
API_PORT=5000
```

## OpenClaw Integration

### Configure OpenClaw (Mac) to use VPS API

Update OpenClaw configuration:

```python
# openclaw_config.py
TRADING_API_URL = "https://your-ngrok-url.ngrok.io"
TRADING_API_TOKEN = "your_api_token"

# Use API for trade execution
USE_REMOTE_API = True
```

### Example: Execute Buy via API

```python
import requests

API_URL = "https://your-ngrok-url.ngrok.io"
API_TOKEN = "your_token"

headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

# Execute buy
response = requests.post(
    f"{API_URL}/api/execute_buy",
    headers=headers,
    json={
        "token_mint": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
        "token_symbol": "BONK",
        "sol_amount": 0.1,
        "source_wallet": "elite_wallet"
    }
)

result = response.json()
if result.get('success'):
    print(f"Buy executed: {result['signature']}")
else:
    print(f"Buy failed: {result.get('error')}")
```

## Service Management

### Trading API Service

```bash
# Start
sudo systemctl start trading_api

# Stop
sudo systemctl stop trading_api

# Restart
sudo systemctl restart trading_api

# Status
sudo systemctl status trading_api

# Logs
tail -f /root/Soulwinners/logs/trading_api.log
sudo journalctl -u trading_api -f
```

### Ngrok Service

```bash
# Start
sudo systemctl start ngrok

# Stop
sudo systemctl stop ngrok

# Restart
sudo systemctl restart ngrok

# Status
sudo systemctl status ngrok

# Get public URL
curl http://localhost:4040/api/tunnels | jq -r '.tunnels[0].public_url'

# Logs
tail -f /root/Soulwinners/logs/ngrok.log
```

## Security

### Bearer Token Authentication

Every API request requires a Bearer token:

```bash
Authorization: Bearer your_api_token_here
```

Without valid token → `401 Unauthorized` or `403 Forbidden`

### Rate Limiting

- Standard endpoints: 60 requests/minute
- Trading endpoints: 20 requests/minute
- Status endpoints: 120 requests/minute

Exceeding limit → `429 Rate Limit Exceeded`

### HTTPS Only (via ngrok)

Ngrok provides automatic HTTPS:
- TLS 1.2+ encryption
- Certificate management
- Man-in-the-middle protection

### Best Practices

1. **Keep token secret**
   - Never commit to git
   - Store in .env only
   - Rotate periodically

2. **Monitor access logs**
   ```bash
   tail -f /root/Soulwinners/logs/trading_api.log
   ```

3. **Use HTTPS only**
   - Never use `http://` for API calls
   - Always use ngrok HTTPS URL

4. **Firewall rules (optional)**
   ```bash
   # Only allow API on localhost
   ufw allow 5000/tcp
   ufw enable
   ```

## Testing

### Local Testing (VPS)

```bash
# Health check
curl http://localhost:5000/api/health

# Status (with auth)
curl -H "Authorization: Bearer your_token" \
     http://localhost:5000/api/status
```

### Remote Testing (Mac)

```bash
# Get ngrok URL
NGROK_URL="https://abc123.ngrok.io"
TOKEN="your_token"

# Health check
curl $NGROK_URL/api/health

# Status
curl -H "Authorization: Bearer $TOKEN" \
     $NGROK_URL/api/status

# Test buy (dry run)
curl -X POST \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "token_mint": "So11111111111111111111111111111111111111112",
       "token_symbol": "SOL",
       "sol_amount": 0.001,
       "source_wallet": "test"
     }' \
     $NGROK_URL/api/execute_buy
```

## Troubleshooting

### API Not Starting

```bash
# Check logs
tail -n 100 /root/Soulwinners/logs/trading_api.log

# Common issues:
# 1. Missing OPENCLAW_PRIVATE_KEY
grep OPENCLAW_PRIVATE_KEY /root/Soulwinners/.env

# 2. Port already in use
lsof -i :5000

# 3. Python dependencies
source /root/Soulwinners/venv/bin/activate
pip list | grep flask
```

### Ngrok Not Connecting

```bash
# Check ngrok status
systemctl status ngrok

# Test ngrok locally
ngrok http 5000

# Check auth token
cat ~/.config/ngrok/ngrok.yml

# Re-authenticate
ngrok config add-authtoken <your-token>
```

### Authentication Failing

```bash
# Verify token in .env
grep TRADING_API_TOKEN /root/Soulwinners/.env

# If not set, check logs for generated token
tail -n 50 /root/Soulwinners/logs/trading_api.log | grep "Generated token"

# Add to .env
echo "TRADING_API_TOKEN=your_token_here" >> /root/Soulwinners/.env

# Restart API
systemctl restart trading_api
```

### Buy/Sell Failing

```bash
# Check DEX connection
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:5000/api/status | jq '.dex_connected'

# Check wallet balance
grep OPENCLAW_PRIVATE_KEY /root/Soulwinners/.env

# Check RPC endpoint
grep SOLANA_RPC_URL /root/Soulwinners/.env

# View error logs
tail -f /root/Soulwinners/logs/trading_api.log
```

### Ngrok URL Changes

Ngrok free tier changes URL on restart. Solutions:

1. **Get new URL:**
   ```bash
   curl http://localhost:4040/api/tunnels | jq -r '.tunnels[0].public_url'
   ```

2. **Update OpenClaw config** with new URL

3. **Upgrade to ngrok Pro** for static URL:
   - Fixed domain
   - Reserved subdomain
   - $8/month

## Performance

### Benchmarks

- Health check: <10ms
- Status query: 50-100ms
- Buy execution: 2-5 seconds
- Sell execution: 2-5 seconds

### Optimization

1. **Use persistent connections:**
   ```python
   session = requests.Session()
   session.headers.update({"Authorization": f"Bearer {TOKEN}"})
   ```

2. **Cache status queries:**
   ```python
   # Don't query every second
   # Cache for 5-10 seconds
   ```

3. **Batch operations:**
   ```python
   # Execute multiple updates in single request
   ```

## Monitoring

### Health Check Endpoint

```bash
# Setup cron for health monitoring
*/5 * * * * curl -s http://localhost:5000/api/health || systemctl restart trading_api
```

### Log Rotation

```bash
# Rotate logs weekly
cat > /etc/logrotate.d/trading_api <<EOF
/root/Soulwinners/logs/trading_api.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    postrotate
        systemctl reload trading_api
    endscript
}
EOF
```

### Metrics

Track in your monitoring system:
- Request count per endpoint
- Response times
- Error rates
- Active positions
- Balance changes

## Production Checklist

- [ ] OPENCLAW_PRIVATE_KEY set in .env
- [ ] TRADING_API_TOKEN set in .env
- [ ] Trading API service running
- [ ] Ngrok tunnel active
- [ ] Public URL obtained
- [ ] Health check passing
- [ ] Authentication working
- [ ] Test buy executed successfully
- [ ] Test sell executed successfully
- [ ] Logs being written
- [ ] Services auto-restart on boot
- [ ] OpenClaw configured with API URL
- [ ] Monitoring setup
- [ ] Backup strategy in place

## Support

### Check Status

```bash
# All services
systemctl status trading_api ngrok

# Health
curl http://localhost:5000/api/health

# Ngrok URL
curl http://localhost:4040/api/tunnels
```

### Common Commands

```bash
# Restart everything
systemctl restart trading_api ngrok

# View logs
tail -f /root/Soulwinners/logs/trading_api.log
tail -f /root/Soulwinners/logs/ngrok.log

# Test API
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:5000/api/status
```

---

**Trading API Bridge Ready** 🚀

Next: Configure OpenClaw on your Mac to use the VPS API!
