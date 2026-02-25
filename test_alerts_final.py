#!/usr/bin/env python3
"""
Final test - Send both BUY and SELL alerts with real token data
"""
import asyncio
import sys
import aiohttp
sys.path.insert(0, '.')

from telegram import Bot
from telegram.constants import ParseMode
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID


async def get_trending_tokens(count: int = 2):
    """Fetch trending Solana tokens from DexScreener."""
    url = "https://api.dexscreener.com/token-boosts/top/v1"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                solana_tokens = [t for t in data if t.get('chainId') == 'solana']
                return solana_tokens[:count]
    return []


async def get_token_details(token_address: str):
    """Get detailed token info including logo."""
    url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                if data and len(data) > 0:
                    pair = data[0]
                    return {
                        'name': pair.get('baseToken', {}).get('name', 'Unknown'),
                        'symbol': pair.get('baseToken', {}).get('symbol', '???'),
                        'address': token_address,
                        'image_url': pair.get('info', {}).get('imageUrl', ''),
                        'price_usd': pair.get('priceUsd', '0'),
                    }
    return None


def format_wallet(address: str) -> str:
    """Format as first7...last4"""
    return f"{address[:7]}...{address[-4:]}"


async def send_final_tests():
    """Send BUY and SELL alerts with different real tokens."""
    print("=" * 60)
    print("FINAL ALERT TESTS")
    print("=" * 60)

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # Get 2 trending tokens
    print("\n[1/4] Fetching trending tokens...")
    tokens = await get_trending_tokens(2)

    if len(tokens) < 2:
        print("  ❌ Not enough tokens found")
        return

    # Get details for both
    token1_addr = tokens[0].get('tokenAddress')
    token2_addr = tokens[1].get('tokenAddress')

    print(f"  Token 1: {token1_addr[:20]}...")
    print(f"  Token 2: {token2_addr[:20]}...")

    print("\n[2/4] Fetching token details...")
    token1 = await get_token_details(token1_addr)
    token2 = await get_token_details(token2_addr)

    if not token1 or not token2:
        print("  ❌ Failed to get token details")
        return

    print(f"  Token 1: {token1['symbol']} ({token1['name']})")
    print(f"  Token 2: {token2['symbol']} ({token2['name']})")

    # Sample wallet
    wallet = "DYw8jCTfwHNRJhhmFcbXvVDTqWMEVFBX6ZKUmG5CNSKK"
    wallet_short = format_wallet(wallet)

    # ===== BUY ALERT =====
    print("\n[3/4] Sending ELITE BUY alert...")
    buy_alert = f"""
🔥 **ELITE WALLET BUY ALERT** 🔥

🪙 **Token:** {token1['symbol']} ({token1['name']})
📍 **CA:** `{token1['address']}`
💰 **Amount:** 8.5000 SOL (~$1,200)

📊 **Wallet Stats:**
├ Strategy: Core Alpha (Active)
├ Win Rate: 82.5%
├ ROI: 312.8%
├ 10x+ Rate: 15.2%
└ SOL Balance: 245.30

🔗 **Links:**
[DexScreener](https://dexscreener.com/solana/{token1['address']}) | [Birdeye](https://birdeye.so/token/{token1['address']}?chain=solana) | [Solscan](https://solscan.io/token/{token1['address']}) | [Jupiter](https://jup.ag/swap/SOL-{token1['address']})

👛 **Wallet:** `{wallet_short}`
[View on Solscan](https://solscan.io/account/{wallet}) | [View on Birdeye](https://birdeye.so/profile/{wallet}?chain=solana)

📈 **Last 5 Trades:**
🟢 BONK: +245.8%
🟢 WIF: +128.3%
🟢 POPCAT: +89.5%
🔴 MYRO: -15.2%
🟢 JTO: +67.4%
"""

    try:
        if token1.get('image_url'):
            msg = await bot.send_photo(
                chat_id=TELEGRAM_CHANNEL_ID,
                photo=token1['image_url'],
                caption=buy_alert,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            msg = await bot.send_message(
                chat_id=TELEGRAM_CHANNEL_ID,
                text=buy_alert,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False
            )
        print(f"  ✅ BUY alert sent (ID: {msg.message_id})")
    except Exception as e:
        print(f"  ❌ BUY alert failed: {e}")

    await asyncio.sleep(2)

    # ===== SELL ALERT =====
    print("\n[4/4] Sending HIGH-QUALITY SELL alert...")
    sell_alert = f"""
🟢 **HIGH-QUALITY WALLET SELL** 🟢

🪙 **Token:** {token2['symbol']} ({token2['name']})
📍 **CA:** `{token2['address']}`
💰 **Sold:** 12.3500 SOL
📊 **PnL:** +185.2%

🔗 [DexScreener](https://dexscreener.com/solana/{token2['address']}) | [Birdeye](https://birdeye.so/token/{token2['address']}?chain=solana) | [Solscan](https://solscan.io/token/{token2['address']})

👛 `{wallet_short}` | [Solscan](https://solscan.io/account/{wallet})
"""

    try:
        msg = await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=sell_alert,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False
        )
        print(f"  ✅ SELL alert sent (ID: {msg.message_id})")
    except Exception as e:
        print(f"  ❌ SELL alert failed: {e}")

    print("\n" + "=" * 60)
    print("✅ ALL TESTS COMPLETE!")
    print("=" * 60)
    print("\nCheck @TopwhaleTracker for:")
    print("  1. ELITE BUY alert with token image")
    print("  2. HIGH-QUALITY SELL alert")
    print("\nAll links should be clickable!")


if __name__ == "__main__":
    asyncio.run(send_final_tests())
