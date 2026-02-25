#!/usr/bin/env python3
"""
OpenClaw Auto-Trader Runner
Copy-trading bot that follows SoulWinners elite wallet signals

Usage:
    python3 run_openclaw.py             # Start the bot
    python3 run_openclaw.py --status    # Show current status
    python3 run_openclaw.py --balance   # Check balance only
"""
import asyncio
import argparse
import logging
import sys
import os

# Add project root to path
sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv()


def check_env():
    """Check required environment variables."""
    required = ['OPENCLAW_PRIVATE_KEY']
    missing = [k for k in required if not os.getenv(k)]

    if missing:
        print("ERROR: Missing required environment variables:")
        for k in missing:
            print(f"  - {k}")
        print("\nSet these in your .env file:")
        print("  OPENCLAW_PRIVATE_KEY=your_solana_private_key")
        print("  OPENCLAW_CHAT_ID=your_telegram_chat_id (optional)")
        sys.exit(1)


async def show_status():
    """Show current trading status."""
    from trader.position_manager import PositionManager

    pm = PositionManager()
    stats = pm.get_stats()
    positions = pm.get_open_positions()

    print("\n" + "=" * 50)
    print("OPENCLAW STATUS")
    print("=" * 50)

    print(f"\n💰 PORTFOLIO")
    print(f"├ Starting: {stats['starting_balance']:.4f} SOL")
    print(f"├ Current:  {stats['current_balance']:.4f} SOL")
    print(f"├ P&L:      {stats['total_pnl_sol']:+.4f} SOL ({stats['total_pnl_percent']:+.1f}%)")
    print(f"└ Progress: {stats['progress_percent']:.1f}% to $10k goal")

    print(f"\n📊 PERFORMANCE")
    print(f"├ Total Trades: {stats['total_trades']}")
    print(f"├ Winning:      {stats['winning_trades']}")
    print(f"└ Win Rate:     {stats['win_rate']:.1f}%")

    print(f"\n📍 OPEN POSITIONS ({len(positions)}/3)")
    if positions:
        for p in positions:
            emoji = "🟢" if p.pnl_percent >= 0 else "🔴"
            print(f"├ {emoji} {p.token_symbol}")
            print(f"│  Entry: {p.entry_sol:.4f} SOL | P&L: {p.pnl_percent:+.1f}%")
            print(f"│  TP1: {'✅' if p.tp1_hit else '⏳'} | TP2: {'✅' if p.tp2_hit else '⏳'}")
    else:
        print("└ No open positions")

    print("")


async def check_balance():
    """Check wallet balance."""
    from trader.solana_dex import JupiterDEX

    private_key = os.getenv('OPENCLAW_PRIVATE_KEY')
    if not private_key:
        print("ERROR: OPENCLAW_PRIVATE_KEY not set")
        return

    async with JupiterDEX(private_key) as dex:
        balance = await dex.get_sol_balance()
        sol_price = await dex.get_sol_price() or 78.0

        print("\n" + "=" * 50)
        print("OPENCLAW WALLET")
        print("=" * 50)
        print(f"\n💼 Address: {dex.wallet_address}")
        print(f"💰 Balance: {balance:.4f} SOL")
        print(f"💵 Value:   ${balance * sol_price:.2f}")
        print(f"📈 SOL Price: ${sol_price:.2f}")
        print("")


async def run_bot():
    """Run the trading bot."""
    from trader.openclaw import OpenClawTrader

    print("\n" + "=" * 60)
    print("OPENCLAW AUTO-TRADER")
    print("Copy-trading elite wallet signals from SoulWinners")
    print("=" * 60)
    print("\nStrategy:")
    print("├ Entry: 70% of balance per trade")
    print("├ Stop Loss: -20%")
    print("├ TP1: +50% (sell 50%)")
    print("├ TP2: +100% (sell 50%)")
    print("└ Max positions: 3")
    print("\nStarting bot... (Ctrl+C to stop)\n")

    trader = OpenClawTrader()

    try:
        await trader.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
        await trader.stop()


def main():
    parser = argparse.ArgumentParser(description='OpenClaw Auto-Trader')
    parser.add_argument('--status', action='store_true', help='Show current status')
    parser.add_argument('--balance', action='store_true', help='Check wallet balance')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Check environment
    if not args.status:  # Status doesn't need keys
        check_env()

    # Run appropriate command
    if args.status:
        asyncio.run(show_status())
    elif args.balance:
        asyncio.run(check_balance())
    else:
        asyncio.run(run_bot())


if __name__ == "__main__":
    main()
