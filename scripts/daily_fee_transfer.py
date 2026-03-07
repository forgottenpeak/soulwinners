#!/usr/bin/env python3
"""
Daily Fee Transfer Script
Run via cron to batch transfer collected fees to owner wallet

Cron example (daily at midnight):
0 0 * * * cd /path/to/Soulwinners && python scripts/daily_fee_transfer.py
"""

import asyncio
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from trader.fee_collector import send_to_owner, get_total_fees, get_pending_fees


async def main():
    print("=" * 50)
    print("DAILY FEE TRANSFER")
    print("=" * 50)

    # Get current stats
    stats = get_total_fees()
    pending = get_pending_fees()

    print(f"\nFee Statistics:")
    print(f"  Total collected: {stats['total_collected_sol']:.4f} SOL")
    print(f"  Total transferred: {stats['total_transferred_sol']:.4f} SOL")
    print(f"  Pending transfer: {pending:.4f} SOL")
    print(f"  Unique users: {stats['unique_users']}")
    print(f"  Total trades: {stats['total_trades']}")

    if pending < 0.01:
        print(f"\nSkipping transfer - pending amount too small ({pending:.4f} SOL)")
        return

    print(f"\nTransferring {pending:.4f} SOL to owner...")

    result = await send_to_owner()

    if result['success']:
        print(f"\nTransfer successful!")
        print(f"  Amount: {result['amount_sol']:.4f} SOL")
        print(f"  Signature: {result['signature']}")
        print(f"  Owner: {result['owner_wallet']}")
    else:
        print(f"\nTransfer failed: {result.get('error')}")


if __name__ == "__main__":
    asyncio.run(main())
