#!/usr/bin/env python3
"""
Historical Dataset Builder for ML Training

Scans all 656+ wallets (qualified + insiders) for 90 days of transaction history.
Uses 7 dedicated API keys for backfill operations.

Target: 1M+ trade events

Usage:
    python scripts/build_historical_dataset.py [--days 90] [--batch-size 50] [--resume]

Estimated time: ~4-6 hours for full backfill (rate limited)
"""
import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
import aiohttp
import sqlite3

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection
from config.settings import DATABASE_PATH

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Dedicated API keys for historical backfill (7 keys)
AUTOTRADER_HELIUS_KEYS = [
    "b4566281-3a52-4088-9002-d95a4ce14e8b",
    "9df159d5-f5dd-4aa5-940e-c9803b1c3bcf",
    "dd77546c-6814-46af-9bb4-1479d29c41b2",
    "b7e626fb-1007-42c4-879f-fe53554d516f",
    "a69cebc8-ef5c-4d1a-b76d-f76b5b12d9c4",
    "2ccf5c1a-7e14-40da-9bb8-8d57889ef44e",
    "76c6d5d5-35ad-4429-a06e-719056140feb",
]

# Skip tokens (stablecoins, wrapped SOL)
SKIP_TOKENS = {
    'So11111111111111111111111111111111111111112',  # WSOL
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
    'USDH1SM1ojwWUga67PGrgFWUHibbjqMvuMaDkRJTgkX',   # USDH
    '7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj', # stSOL
}


class KeyRotator:
    """Rotate through API keys to maximize throughput."""

    def __init__(self, keys: List[str]):
        self.keys = keys
        self.current_idx = 0
        self.request_counts = {key: 0 for key in keys}
        self.last_reset = time.time()
        self.lock = asyncio.Lock()

    async def get_key(self) -> str:
        """Get next API key with round-robin rotation."""
        async with self.lock:
            # Reset counts every minute
            if time.time() - self.last_reset > 60:
                self.request_counts = {key: 0 for key in self.keys}
                self.last_reset = time.time()

            # Find key with lowest request count
            min_count = min(self.request_counts.values())
            for key in self.keys:
                if self.request_counts[key] == min_count:
                    self.request_counts[key] += 1
                    return key

            # Fallback to round-robin
            key = self.keys[self.current_idx]
            self.current_idx = (self.current_idx + 1) % len(self.keys)
            return key


class HistoricalScanner:
    """
    Scan wallets for historical transaction data.

    Features:
    - Scans 90 days of history per wallet
    - Uses 7 dedicated API keys for high throughput
    - Tracks progress for resume capability
    - Fetches token metadata from DexScreener
    """

    def __init__(self, days: int = 90):
        self.days = days
        self.cutoff_timestamp = int((datetime.now() - timedelta(days=days)).timestamp())
        self.rotator = KeyRotator(AUTOTRADER_HELIUS_KEYS)
        self.base_url = "https://api.helius.xyz/v0"

        # Statistics
        self.stats = {
            "wallets_scanned": 0,
            "wallets_skipped": 0,
            "events_collected": 0,
            "buys_collected": 0,
            "sells_collected": 0,
            "errors": 0,
            "api_calls": 0,
        }

        # Token info cache
        self.token_cache: Dict[str, Dict] = {}

        # Progress tracking
        self.scanned_wallets: Set[str] = set()

    def get_all_wallets(self) -> List[Dict]:
        """Get all wallets to scan (qualified + insiders)."""
        conn = get_connection()
        cursor = conn.cursor()

        wallets = []

        # Get qualified wallets
        cursor.execute("""
            SELECT wallet_address, tier, 'qualified' as wallet_type
            FROM qualified_wallets
        """)
        for row in cursor.fetchall():
            wallets.append({
                "address": row[0],
                "tier": row[1],
                "type": row[2],
            })

        # Get insider wallets (not already in qualified)
        try:
            cursor.execute("""
                SELECT wallet_address, 'Insider' as tier, 'insider' as wallet_type
                FROM insider_pool
                WHERE wallet_address NOT IN (SELECT wallet_address FROM qualified_wallets)
            """)
            for row in cursor.fetchall():
                wallets.append({
                    "address": row[0],
                    "tier": row[1],
                    "type": row[2],
                })
        except Exception as e:
            logger.warning(f"Could not fetch insider wallets: {e}")

        conn.close()
        logger.info(f"Found {len(wallets)} total wallets to scan")

        return wallets

    def load_progress(self) -> Set[str]:
        """Load list of already scanned wallets for resume."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT DISTINCT wallet_address
                FROM trade_events
                WHERE timestamp >= ?
            """, (self.cutoff_timestamp,))

            scanned = {row[0] for row in cursor.fetchall()}
            logger.info(f"Resuming: {len(scanned)} wallets already scanned")
            return scanned
        except Exception as e:
            logger.warning(f"Could not load progress: {e}")
            return set()
        finally:
            conn.close()

    async def fetch_transactions(
        self,
        wallet: str,
        session: aiohttp.ClientSession,
        before_sig: Optional[str] = None,
    ) -> List[Dict]:
        """Fetch transactions from Helius API."""
        api_key = await self.rotator.get_key()
        url = f"{self.base_url}/addresses/{wallet}/transactions"

        params = {
            "api-key": api_key,
            "limit": 100,
        }
        if before_sig:
            params["before"] = before_sig

        try:
            async with session.get(url, params=params, timeout=30) as response:
                self.stats["api_calls"] += 1

                if response.status == 429:
                    logger.warning(f"Rate limited, waiting 5s...")
                    await asyncio.sleep(5)
                    return await self.fetch_transactions(wallet, session, before_sig)

                if response.status != 200:
                    logger.debug(f"API error {response.status} for {wallet[:12]}...")
                    return []

                return await response.json()

        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching {wallet[:12]}...")
            return []
        except Exception as e:
            logger.debug(f"Fetch error for {wallet[:12]}...: {e}")
            self.stats["errors"] += 1
            return []

    async def fetch_token_info(
        self,
        token_address: str,
        session: aiohttp.ClientSession,
    ) -> Dict:
        """Fetch token info from DexScreener (with caching)."""
        if token_address in self.token_cache:
            return self.token_cache[token_address]

        try:
            url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        pair = data[0]

                        # Calculate token age
                        pair_created_at = pair.get('pairCreatedAt', 0)
                        token_age_hours = 0
                        if pair_created_at:
                            age_ms = datetime.now().timestamp() * 1000 - pair_created_at
                            token_age_hours = max(0, age_ms / (1000 * 3600))

                        info = {
                            "symbol": pair.get("baseToken", {}).get("symbol", "???"),
                            "name": pair.get("baseToken", {}).get("name", "Unknown"),
                            "market_cap": float(pair.get("marketCap", 0) or 0),
                            "liquidity": float(pair.get("liquidity", {}).get("usd", 0) or 0),
                            "volume_24h": float(pair.get("volume", {}).get("h24", 0) or 0),
                            "token_age_hours": token_age_hours,
                            "holders": pair.get("info", {}).get("holders", 0),
                        }

                        self.token_cache[token_address] = info
                        return info

        except Exception as e:
            logger.debug(f"Token info error for {token_address[:12]}...: {e}")

        # Return defaults
        return {
            "symbol": "???",
            "name": "Unknown",
            "market_cap": 0,
            "liquidity": 0,
            "volume_24h": 0,
            "token_age_hours": 0,
            "holders": 0,
        }

    def parse_swap(self, tx: Dict, wallet: str) -> Optional[Dict]:
        """Parse a swap transaction from Helius format."""
        try:
            token_transfers = tx.get('tokenTransfers', [])
            native_transfers = tx.get('nativeTransfers', [])

            if not token_transfers:
                return None

            # Find the main token (not SOL/stables)
            main_transfer = None
            for transfer in token_transfers:
                mint = transfer.get('mint', '')
                if mint not in SKIP_TOKENS:
                    main_transfer = transfer
                    break

            if not main_transfer:
                return None

            # Calculate SOL amount
            sol_amount = 0
            for nt in native_transfers:
                amount = abs(nt.get('amount', 0)) / 1e9
                if nt.get('fromUserAccount') == wallet:
                    sol_amount += amount  # SOL out = buying
                elif nt.get('toUserAccount') == wallet:
                    sol_amount -= amount  # SOL in = selling

            # Determine buy or sell
            is_buy = main_transfer.get('toUserAccount') == wallet
            tx_type = 'buy' if is_buy else 'sell'

            # Get token amount
            token_amount = float(main_transfer.get('tokenAmount', 0) or 0)

            return {
                'signature': tx.get('signature'),
                'type': tx_type,
                'token_address': main_transfer.get('mint'),
                'sol_amount': abs(sol_amount),
                'token_amount': token_amount,
                'timestamp': tx.get('timestamp', 0),
            }

        except Exception as e:
            logger.debug(f"Parse error: {e}")
            return None

    async def scan_wallet(
        self,
        wallet: Dict,
        session: aiohttp.ClientSession,
    ) -> int:
        """
        Scan a single wallet for historical transactions.

        Returns number of events collected.
        """
        address = wallet["address"]
        tier = wallet["tier"]
        wallet_type = wallet["type"]

        events_collected = 0
        before_sig = None
        page = 0
        reached_cutoff = False

        while not reached_cutoff and page < 100:  # Max 100 pages (~10K txs)
            txs = await self.fetch_transactions(address, session, before_sig)

            if not txs:
                break

            page += 1

            for tx in txs:
                timestamp = tx.get('timestamp', 0)

                # Check if we've gone past our time window
                if timestamp < self.cutoff_timestamp:
                    reached_cutoff = True
                    break

                # Parse the transaction
                parsed = self.parse_swap(tx, address)
                if not parsed:
                    continue

                # Get token info
                token_info = await self.fetch_token_info(parsed['token_address'], session)

                # Calculate token age at trade time
                # (current age minus time since trade)
                current_age = token_info['token_age_hours']
                hours_since_trade = (datetime.now().timestamp() - timestamp) / 3600
                age_at_trade = max(0, current_age - hours_since_trade)

                # Save to database
                self._save_trade_event(
                    wallet_address=address,
                    wallet_type=wallet_type,
                    wallet_tier=tier,
                    parsed=parsed,
                    token_info=token_info,
                    token_age_at_trade=age_at_trade,
                )

                events_collected += 1
                if parsed['type'] == 'buy':
                    self.stats["buys_collected"] += 1
                else:
                    self.stats["sells_collected"] += 1

            # Get signature for pagination
            if txs:
                before_sig = txs[-1].get('signature')

            # Rate limit
            await asyncio.sleep(0.5)

        return events_collected

    def _save_trade_event(
        self,
        wallet_address: str,
        wallet_type: str,
        wallet_tier: str,
        parsed: Dict,
        token_info: Dict,
        token_age_at_trade: float,
    ):
        """Save trade event to database."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO trade_events
                (wallet_address, wallet_type, wallet_tier, token_address, token_symbol,
                 token_name, timestamp, trade_type, sol_amount, token_amount,
                 token_age_hours, marketcap_at_trade, liquidity_at_trade,
                 volume_24h_at_trade, holder_count_at_trade, tx_signature)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                wallet_address,
                wallet_type,
                wallet_tier,
                parsed['token_address'],
                token_info['symbol'],
                token_info['name'],
                parsed['timestamp'],
                parsed['type'],
                parsed['sol_amount'],
                parsed['token_amount'],
                token_age_at_trade,
                token_info['market_cap'],
                token_info['liquidity'],
                token_info['volume_24h'],
                token_info['holders'],
                parsed['signature'],
            ))
            conn.commit()

        except Exception as e:
            logger.debug(f"Save error: {e}")
        finally:
            conn.close()

    async def run(self, batch_size: int = 50, resume: bool = True):
        """
        Run the historical scan for all wallets.

        Args:
            batch_size: Number of wallets to scan in parallel
            resume: Resume from previous progress
        """
        start_time = time.time()

        # Get wallets
        wallets = self.get_all_wallets()

        # Load progress if resuming
        if resume:
            self.scanned_wallets = self.load_progress()

        # Filter out already scanned wallets
        wallets_to_scan = [
            w for w in wallets
            if w["address"] not in self.scanned_wallets
        ]

        logger.info(f"Scanning {len(wallets_to_scan)} wallets "
                   f"(skipping {len(wallets) - len(wallets_to_scan)} already scanned)")
        logger.info(f"Time window: last {self.days} days")
        logger.info(f"Using {len(AUTOTRADER_HELIUS_KEYS)} API keys")

        # Process in batches
        connector = aiohttp.TCPConnector(limit=20)
        async with aiohttp.ClientSession(connector=connector) as session:
            for i in range(0, len(wallets_to_scan), batch_size):
                batch = wallets_to_scan[i:i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(wallets_to_scan) + batch_size - 1) // batch_size

                logger.info(f"\n{'='*60}")
                logger.info(f"BATCH {batch_num}/{total_batches} "
                           f"({len(batch)} wallets)")
                logger.info(f"{'='*60}")

                # Scan batch in parallel
                tasks = [
                    self.scan_wallet(wallet, session)
                    for wallet in batch
                ]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Count results
                batch_events = 0
                for j, result in enumerate(results):
                    if isinstance(result, Exception):
                        logger.error(f"Error scanning {batch[j]['address'][:12]}...: {result}")
                        self.stats["errors"] += 1
                    else:
                        batch_events += result
                        self.stats["wallets_scanned"] += 1

                self.stats["events_collected"] += batch_events

                # Log progress
                elapsed = time.time() - start_time
                rate = self.stats["events_collected"] / (elapsed / 3600) if elapsed > 0 else 0

                logger.info(f"Batch complete: {batch_events} events")
                logger.info(f"Total progress: {self.stats['events_collected']} events "
                           f"| {self.stats['wallets_scanned']} wallets "
                           f"| {rate:.0f} events/hour")
                logger.info(f"API calls: {self.stats['api_calls']} | Errors: {self.stats['errors']}")

                # Rate limit between batches
                await asyncio.sleep(2)

        # Final summary
        elapsed = time.time() - start_time
        logger.info("\n" + "=" * 60)
        logger.info("SCAN COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Wallets scanned: {self.stats['wallets_scanned']}")
        logger.info(f"Events collected: {self.stats['events_collected']}")
        logger.info(f"  - Buys: {self.stats['buys_collected']}")
        logger.info(f"  - Sells: {self.stats['sells_collected']}")
        logger.info(f"API calls: {self.stats['api_calls']}")
        logger.info(f"Errors: {self.stats['errors']}")
        logger.info(f"Time elapsed: {elapsed/3600:.1f} hours")
        logger.info(f"Rate: {self.stats['events_collected'] / (elapsed/3600):.0f} events/hour")


def get_dataset_stats() -> Dict:
    """Get statistics about the current dataset."""
    conn = get_connection()
    cursor = conn.cursor()

    stats = {}

    try:
        # Total events
        cursor.execute("SELECT COUNT(*) FROM trade_events")
        stats["total_events"] = cursor.fetchone()[0]

        # By trade type
        cursor.execute("""
            SELECT trade_type, COUNT(*)
            FROM trade_events
            GROUP BY trade_type
        """)
        stats["by_type"] = dict(cursor.fetchall())

        # By wallet tier
        cursor.execute("""
            SELECT wallet_tier, COUNT(*)
            FROM trade_events
            GROUP BY wallet_tier
        """)
        stats["by_tier"] = dict(cursor.fetchall())

        # Unique wallets
        cursor.execute("SELECT COUNT(DISTINCT wallet_address) FROM trade_events")
        stats["unique_wallets"] = cursor.fetchone()[0]

        # Unique tokens
        cursor.execute("SELECT COUNT(DISTINCT token_address) FROM trade_events")
        stats["unique_tokens"] = cursor.fetchone()[0]

        # Date range
        cursor.execute("""
            SELECT MIN(timestamp), MAX(timestamp)
            FROM trade_events
        """)
        min_ts, max_ts = cursor.fetchone()
        if min_ts and max_ts:
            stats["date_range"] = {
                "start": datetime.fromtimestamp(min_ts).isoformat(),
                "end": datetime.fromtimestamp(max_ts).isoformat(),
                "days": (max_ts - min_ts) / 86400,
            }

        # Events with outcomes
        cursor.execute("""
            SELECT COUNT(*)
            FROM trade_events
            WHERE outcome IS NOT NULL
        """)
        stats["events_with_outcomes"] = cursor.fetchone()[0]

    except Exception as e:
        logger.error(f"Error getting stats: {e}")

    finally:
        conn.close()

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Build historical dataset for ML training"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days to look back (default: 90)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Number of wallets to scan in parallel (default: 50)"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume from previous progress (default: true)"
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Start fresh, don't resume"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Just show current dataset statistics"
    )

    args = parser.parse_args()

    if args.stats:
        stats = get_dataset_stats()
        print("\n" + "=" * 60)
        print("DATASET STATISTICS")
        print("=" * 60)
        print(f"Total events: {stats.get('total_events', 0):,}")
        print(f"Unique wallets: {stats.get('unique_wallets', 0)}")
        print(f"Unique tokens: {stats.get('unique_tokens', 0)}")
        print(f"\nBy trade type:")
        for t, c in stats.get('by_type', {}).items():
            print(f"  {t}: {c:,}")
        print(f"\nBy wallet tier:")
        for t, c in stats.get('by_tier', {}).items():
            print(f"  {t}: {c:,}")
        if 'date_range' in stats:
            print(f"\nDate range: {stats['date_range']['start'][:10]} to {stats['date_range']['end'][:10]}")
            print(f"Days covered: {stats['date_range']['days']:.1f}")
        print(f"\nEvents with outcomes: {stats.get('events_with_outcomes', 0):,}")
        return

    logger.info("=" * 60)
    logger.info("SoulWinners: Historical Dataset Builder")
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    scanner = HistoricalScanner(days=args.days)
    resume = not args.no_resume

    asyncio.run(scanner.run(
        batch_size=args.batch_size,
        resume=resume,
    ))


if __name__ == "__main__":
    main()
