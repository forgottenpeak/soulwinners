#!/usr/bin/env python3
"""
Test Telegram bot functionality
Sends test alerts to verify everything works
"""
import asyncio
import sys
sys.path.insert(0, '.')

from telegram import Bot
from telegram.constants import ParseMode
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID


async def test_telegram_bot():
    """Test the Telegram bot connection and message sending."""
    print("=" * 60)
    print("TELEGRAM BOT TEST")
    print("=" * 60)

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    # Test 1: Get bot info
    print("\n[1/4] Testing bot connection...")
    try:
        me = await bot.get_me()
        print(f"  ✅ Bot connected: @{me.username}")
        print(f"     Name: {me.first_name}")
    except Exception as e:
        print(f"  ❌ Bot connection failed: {e}")
        return

    # Test 2: Send a simple message
    print("\n[2/4] Sending test message...")
    try:
        msg = await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text="🔧 **SoulWinners Test Message**\n\nBot is connected and working!",
            parse_mode=ParseMode.MARKDOWN
        )
        print(f"  ✅ Message sent (ID: {msg.message_id})")
    except Exception as e:
        print(f"  ❌ Send message failed: {e}")
        print(f"     Make sure the bot is admin in channel {TELEGRAM_CHANNEL_ID}")
        return

    # Test 3: Send formatted alert
    print("\n[3/4] Sending test buy alert...")
    test_alert = """
🔥 **ELITE WALLET BUY ALERT** 🔥

🪙 **Token:** TESTCOIN (Test Token)
💰 **Amount:** 5.5000 SOL

📊 **Wallet Stats:**
├ Strategy: Core Alpha (Active)
├ Win Rate: 78.0%
├ ROI: 245.5%
├ 10x+ Rate: 12.0%
└ SOL Balance: 125.50

🔗 **Token Links:**
[DexScreener](https://dexscreener.com/solana/test) | [Birdeye](https://birdeye.so/token/test) | [Solscan](https://solscan.io/token/test)

👛 **Wallet:** `DYw8jCTfwHNRJhhmFcbX...`
[View Wallet](https://solscan.io/account/DYw8jCTfwHNRJhhmFcbXvVDTqWMEVFBX6ZKUmG5CNSKK)

📈 **Last 5 Trades:**
🟢 BONK: +150.2%
🟢 WIF: +85.3%
🔴 POPCAT: -12.5%
🟢 MYRO: +220.0%
🟢 JTO: +45.8%

⏰ 2026-02-24 01:45:00 UTC

_This is a test alert - Real alerts will be sent when monitoring starts_
"""
    try:
        msg = await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=test_alert,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        print(f"  ✅ Buy alert sent (ID: {msg.message_id})")
    except Exception as e:
        print(f"  ❌ Buy alert failed: {e}")

    # Test 4: Send with photo (token image)
    print("\n[4/4] Sending alert with image...")
    try:
        # Use SOL logo as test image
        image_url = "https://raw.githubusercontent.com/solana-labs/token-list/main/assets/mainnet/So11111111111111111111111111111111111111112/logo.png"
        caption = """
🟢 **HIGH-QUALITY WALLET BUY** 🟢

🪙 **Token:** SOL (Solana)
💰 **Amount:** 10.0000 SOL

📊 Win Rate: 72.0% | ROI: 180.5%

_Test alert with token image_
"""
        msg = await bot.send_photo(
            chat_id=TELEGRAM_CHANNEL_ID,
            photo=image_url,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN
        )
        print(f"  ✅ Photo alert sent (ID: {msg.message_id})")
    except Exception as e:
        print(f"  ⚠️ Photo alert failed (this is optional): {e}")

    print("\n" + "=" * 60)
    print("TELEGRAM TEST COMPLETE")
    print("=" * 60)
    print("\nCheck your channel @TopwhaleTracker for the test messages!")


if __name__ == "__main__":
    asyncio.run(test_telegram_bot())
