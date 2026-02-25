# API Integration Guide

## Helius API

### Overview

SoulWinners uses Helius for all Solana blockchain data:
- Transaction history
- Wallet balances
- Token metadata
- Parsed transaction data

### Endpoints Used

| Endpoint | Purpose | Rate Limit |
|----------|---------|------------|
| `/v0/addresses/{address}/transactions` | Transaction history | 100/sec |
| `/v0/addresses/{address}/balances` | Wallet balances | 100/sec |
| `/v0/token-metadata` | Token info | 100/sec |

### Key Rotation

SoulWinners implements 4-key rotation for 400 req/sec capacity:

```python
class HeliusRotator:
    def __init__(self, api_keys: List[str]):
        self.api_keys = api_keys
        self.current_index = 0
        self.request_counts = {key: 0 for key in api_keys}
        self.max_requests_per_minute = 5500  # Per key limit

    async def get_key(self) -> str:
        """Get next available API key with capacity."""
        # Round-robin with capacity check
        for _ in range(len(self.api_keys)):
            key = self.api_keys[self.current_index]
            if self.request_counts[key] < self.max_requests_per_minute:
                self.request_counts[key] += 1
                self.current_index = (self.current_index + 1) % len(self.api_keys)
                return key
            self.current_index = (self.current_index + 1) % len(self.api_keys)

        # All keys at limit, wait for reset
        await asyncio.sleep(1)
        return await self.get_key()
```

### Transaction Parsing

Helius returns parsed transaction data. We extract:

```python
def parse_swap_transaction(tx: Dict) -> Optional[Dict]:
    token_transfers = tx.get('tokenTransfers', [])
    native_transfers = tx.get('nativeTransfers', [])

    # Identify main token (not SOL/USDC/USDT)
    for transfer in token_transfers:
        mint = transfer.get('mint')
        if mint not in SKIP_TOKENS:
            # Determine buy vs sell
            is_buy = transfer.get('toUserAccount') == fee_payer

            return {
                'token_address': mint,
                'trade_type': 'buy' if is_buy else 'sell',
                'sol_amount': calculate_sol_amount(native_transfers),
                'timestamp': tx.get('timestamp'),
            }
```

### Getting API Keys

1. Go to [helius.dev](https://helius.dev)
2. Sign up for free account
3. Create API key in dashboard
4. For higher limits, upgrade plan or create multiple accounts

---

## DexScreener API

### Overview

Used for discovering trending tokens and their traders.

### Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `/token-boosts/top/v1` | Top trending tokens |
| `/token-profiles/latest/v1` | Latest token profiles |
| `/tokens/v1/solana/{address}` | Token price data |

### Example Usage

```python
async def get_trending_tokens() -> List[Dict]:
    url = "https://api.dexscreener.com/token-boosts/top/v1"
    response = await fetch(url)
    return [t for t in response if t.get('chainId') == 'solana']
```

### Rate Limits

- Free tier: ~300 req/min
- No authentication required
- Returns parsed JSON

---

## Telegram Bot API

### Setup

1. Create bot via [@BotFather](https://t.me/BotFather)
2. Get bot token
3. Create channel, add bot as admin
4. Get channel ID (use [@userinfobot](https://t.me/userinfobot))

### Configuration

```python
TELEGRAM_BOT_TOKEN = "123456789:ABCdefGHI..."
TELEGRAM_CHANNEL_ID = "-1001234567890"
```

### Command Handlers

```python
from telegram.ext import Application, CommandHandler

app = Application.builder().token(TOKEN).build()

# Register handlers
app.add_handler(CommandHandler("start", cmd_start))
app.add_handler(CommandHandler("pool", cmd_pool))
app.add_handler(CommandHandler("stats", cmd_stats))

# Callback handler for inline buttons
app.add_handler(CallbackQueryHandler(handle_callback))
```

### Sending Alerts

```python
from telegram import Bot
from telegram.constants import ParseMode

bot = Bot(token=TELEGRAM_BOT_TOKEN)

async def send_alert(message: str):
    await bot.send_message(
        chat_id=TELEGRAM_CHANNEL_ID,
        text=message,
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True
    )
```

### Inline Keyboards

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

keyboard = [
    [
        InlineKeyboardButton("Toggle Alerts", callback_data="toggle_alerts"),
        InlineKeyboardButton("Run Now", callback_data="run_pipeline"),
    ],
]
reply_markup = InlineKeyboardMarkup(keyboard)

await update.message.reply_text(
    "Settings:",
    reply_markup=reply_markup
)
```

---

## Solana RPC (Fallback)

For balance fetching when Helius is rate limited:

```python
async def get_balance_fallback(wallet: str) -> float:
    url = "https://api.mainnet-beta.solana.com"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [wallet]
    }
    response = await fetch(url, method="POST", json=payload)
    lamports = response['result']['value']
    return lamports / 1e9  # Convert to SOL
```

---

## Error Handling

### Rate Limit Response

```python
async def fetch_with_retry(url: str, max_retries: int = 3):
    for attempt in range(max_retries):
        response = await fetch(url)

        if response.status == 200:
            return response.json()

        if response.status == 429:  # Rate limited
            wait_time = 2 ** (attempt + 1)
            await asyncio.sleep(wait_time)
            continue

        if response.status >= 500:  # Server error
            await asyncio.sleep(2)
            continue

        return None
    return None
```

### Timeout Handling

```python
import asyncio
import aiohttp

async def fetch(url: str, timeout: int = 30):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as response:
                return await response.json()
    except asyncio.TimeoutError:
        logger.warning(f"Timeout: {url}")
        return None
```
