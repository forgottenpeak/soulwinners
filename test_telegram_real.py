#!/usr/bin/env python3
"""
Test Telegram bot with REAL token data from DexScreener
"""
import asyncio
import sys
import aiohttp
sys.path.insert(0, '.')

from telegram import Bot
from telegram.constants import ParseMode
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID


async def get_real_token_data():
    """Fetch real trending token from DexScreener."""
    url = "https://api.dexscreener.com/token-boosts/top/v1"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                # Find first Solana token
                for token in data:
                    if token.get('chainId') == 'solana':
                        return token
    return None


async def get_token_details(token_address: str):
    """Get detailed token info including logo."""
    url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data and len(data) > 0:
                    return data[0]
    return None


def format_wallet_address(address: str) -> str:
    """Format wallet address as first7...last4"""
    if len(address) > 11:
        return f"{address[:7]}...{address[-4:]}"
    return address


async def test_real_alert():
    """Send test alert with REAL token data."""
    print("=" * 60)
    print("REAL TOKEN ALERT TEST")
    print("=" * 60)

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # Step 1: Get real token from DexScreener
    print("\n[1/3] Fetching real token from DexScreener...")
    token_boost = await get_real_token_data()

    if not token_boost:
        print("  ❌ Failed to fetch trending token")
        return

    token_address = token_boost.get('tokenAddress')
    print(f"  ✅ Found token: {token_address[:20]}...")

    # Step 2: Get token details (name, symbol, logo)
    print("\n[2/3] Fetching token details...")
    token_info = await get_token_details(token_address)

    if token_info:
        token_name = token_info.get('baseToken', {}).get('name', 'Unknown')
        token_symbol = token_info.get('baseToken', {}).get('symbol', '???')
        token_logo = token_info.get('info', {}).get('imageUrl', '')
        price_usd = token_info.get('priceUsd', '0')
        liquidity = token_info.get('liquidity', {}).get('usd', 0)
        print(f"  ✅ Token: {token_symbol} ({token_name})")
        print(f"     Logo: {token_logo[:50] if token_logo else 'None'}...")
        print(f"     Price: ${price_usd}")
    else:
        token_name = token_boost.get('name', 'Unknown')
        token_symbol = token_boost.get('symbol', '???')
        token_logo = token_boost.get('icon', '')
        price_usd = '0'
        liquidity = 0
        print(f"  ⚠️ Using boost data: {token_symbol}")

    # Sample wallet address (use a real one)
    wallet_address = "DYw8jCTfwHNRJhhmFcbXvVDTqWMEVFBX6ZKUmG5CNSKK"
    wallet_short = format_wallet_address(wallet_address)

    # Step 3: Build and send alert
    print("\n[3/3] Sending real alert...")

    # Build alert message with clickable links
    alert_message = f"""
🔥 **ELITE WALLET BUY ALERT** 🔥

🪙 **Token:** {token_symbol} ({token_name})
📍 **CA:** `{token_address}`
💰 **Amount:** 5.2500 SOL (~$750)

📊 **Wallet Stats:**
├ Strategy: Core Alpha (Active)
├ Win Rate: 78.5%
├ ROI: 245.5%
├ 10x+ Rate: 12.0%
└ SOL Balance: 125.50

🔗 **Links:**
[DexScreener](https://dexscreener.com/solana/{token_address}) | [Birdeye](https://birdeye.so/token/{token_address}?chain=solana) | [Solscan](https://solscan.io/token/{token_address}) | [Jupiter](https://jup.ag/swap/SOL-{token_address})

👛 **Wallet:** `{wallet_short}`
[View on Solscan](https://solscan.io/account/{wallet_address}) | [View on Birdeye](https://birdeye.so/profile/{wallet_address}?chain=solana)

📈 **Last 5 Trades:**
🟢 BONK: +150.2%
🟢 WIF: +85.3%
🔴 POPCAT: -12.5%
🟢 MYRO: +220.0%
🟢 JTO: +45.8%
"""

    try:
        # Send with photo if logo available
        if token_logo:
            msg = await bot.send_photo(
                chat_id=TELEGRAM_CHANNEL_ID,
                photo=token_logo,
                caption=alert_message,
                parse_mode=ParseMode.MARKDOWN
            )
            print(f"  ✅ Photo alert sent (ID: {msg.message_id})")
        else:
            # Send text only, Telegram will auto-preview DexScreener link
            msg = await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=alert_message,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False  # Enable link preview
            )
            print(f"  ✅ Text alert sent (ID: {msg.message_id})")

    except Exception as e:
        print(f"  ❌ Alert failed: {e}")
        # Try without photo
        try:
            msg = await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=alert_message,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False
            )
            print(f"  ✅ Fallback text alert sent (ID: {msg.message_id})")
        except Exception as e2:
            print(f"  ❌ Fallback also failed: {e2}")

    print("\n" + "=" * 60)
    print("CHECK @TopwhaleTracker FOR THE ALERT!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_real_alert())
