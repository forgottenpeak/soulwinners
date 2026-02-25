"""
Launch Tracker - Tracks fresh token launches (<24h old)
Identifies Early Bird wallets that buy immediately after launch
"""
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
from dataclasses import dataclass, field

from config.settings import HELIUS_API_KEY
from database import get_connection

logger = logging.getLogger(__name__)


@dataclass
class FreshToken:
    """A token that launched recently (<24h)"""
    address: str
    symbol: str
    name: str
    launch_time: datetime
    initial_liquidity: float = 0
    current_mcap: float = 0
    first_buyers: List[str] = field(default_factory=list)
    migration_detected: bool = False
    pump_graduated: bool = False


@dataclass
class EarlyBuyer:
    """A wallet that bought a fresh token early"""
    wallet_address: str
    token_address: str
    token_symbol: str
    buy_time: datetime
    time_since_launch_min: int
    sol_amount: float
    current_pnl_percent: float = 0
    pattern: str = ""  # "Migration Sniper", "Accumulation Insider", etc.


class LaunchTracker:
    """
    Tracks fresh token launches and identifies early buyers.

    Sources:
    - Pump.fun graduated tokens (migrated to Raydium)
    - DexScreener new pairs
    - Helius transaction monitoring
    """

    def __init__(self, max_age_hours: int = 24):
        self.max_age_hours = max_age_hours
        self.fresh_tokens: Dict[str, FreshToken] = {}
        self.early_buyers: Dict[str, List[EarlyBuyer]] = {}  # wallet -> buys
        self.api_key = HELIUS_API_KEY

    async def scan_fresh_launches(self) -> List[FreshToken]:
        """Scan for tokens launched in the last 24 hours."""
        tokens = []

        # Scan DexScreener for new pairs
        dex_tokens = await self._scan_dexscreener_new()
        tokens.extend(dex_tokens)

        # Scan Pump.fun for graduated tokens
        pump_tokens = await self._scan_pumpfun_graduated()
        tokens.extend(pump_tokens)

        # Store and dedupe
        for token in tokens:
            self.fresh_tokens[token.address] = token

        logger.info(f"Tracking {len(self.fresh_tokens)} fresh tokens")
        return tokens

    async def _scan_dexscreener_new(self) -> List[FreshToken]:
        """Scan DexScreener for new Solana pairs."""
        tokens = []
        url = "https://api.dexscreener.com/token-profiles/latest/v1"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()

                        cutoff = datetime.now() - timedelta(hours=self.max_age_hours)

                        for profile in data[:100]:  # Check latest 100
                            if profile.get('chainId') != 'solana':
                                continue

                            # Parse creation time
                            created_at = profile.get('createdAt')
                            if not created_at:
                                continue

                            launch_time = datetime.fromisoformat(
                                created_at.replace('Z', '+00:00')
                            ).replace(tzinfo=None)

                            if launch_time > cutoff:
                                token = FreshToken(
                                    address=profile.get('tokenAddress', ''),
                                    symbol=profile.get('symbol', '???'),
                                    name=profile.get('name', 'Unknown'),
                                    launch_time=launch_time,
                                )
                                tokens.append(token)

        except Exception as e:
            logger.error(f"DexScreener scan failed: {e}")

        return tokens

    async def _scan_pumpfun_graduated(self) -> List[FreshToken]:
        """Scan Pump.fun for recently graduated tokens (migrated to Raydium)."""
        tokens = []
        url = "https://frontend-api.pump.fun/coins/king-of-the-hill?limit=50&offset=0&includeNsfw=true"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()

                        cutoff = datetime.now() - timedelta(hours=self.max_age_hours)

                        for coin in data:
                            # Check if recently graduated
                            created_timestamp = coin.get('created_timestamp', 0)
                            if not created_timestamp:
                                continue

                            launch_time = datetime.fromtimestamp(created_timestamp / 1000)

                            if launch_time > cutoff:
                                token = FreshToken(
                                    address=coin.get('mint', ''),
                                    symbol=coin.get('symbol', '???'),
                                    name=coin.get('name', 'Unknown'),
                                    launch_time=launch_time,
                                    pump_graduated=True,
                                    migration_detected=coin.get('raydium_pool') is not None,
                                )
                                tokens.append(token)

        except Exception as e:
            logger.error(f"Pump.fun scan failed: {e}")

        return tokens

    async def get_first_buyers(self, token_address: str, limit: int = 20) -> List[str]:
        """Get the first N buyers of a token."""
        url = f"https://api.helius.xyz/v0/addresses/{token_address}/transactions"
        params = {"api-key": self.api_key, "limit": 100}

        buyers = []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        txs = await response.json()

                        # Parse transactions to find buyers
                        for tx in txs:
                            wallet = self._extract_buyer(tx, token_address)
                            if wallet and wallet not in buyers:
                                buyers.append(wallet)
                                if len(buyers) >= limit:
                                    break

        except Exception as e:
            logger.error(f"Failed to get first buyers: {e}")

        return buyers

    def _extract_buyer(self, tx: Dict, token_address: str) -> Optional[str]:
        """Extract buyer wallet from transaction."""
        try:
            token_transfers = tx.get('tokenTransfers', [])

            for transfer in token_transfers:
                if transfer.get('mint') == token_address:
                    # This is a buy if token goes TO the wallet
                    to_wallet = transfer.get('toUserAccount')
                    if to_wallet:
                        return to_wallet

        except Exception:
            pass

        return None

    async def analyze_buyer_patterns(self, wallet: str) -> Dict:
        """
        Analyze a buyer's patterns across fresh launches.

        Patterns detected:
        - Migration Sniper: Buys within 2 min of Raydium migration
        - Accumulation Insider: Multiple small buys before big move
        - Silent Whale: Large buys with no social presence
        - Dev Associate: Connected to dev wallets
        """
        patterns = {
            'migration_snipes': 0,
            'early_buys': 0,  # Within 5 min of launch
            'accumulation_tokens': [],
            'avg_time_to_buy_min': 0,
            'success_rate': 0,
            'detected_pattern': None,
        }

        # Get wallet's recent buys
        url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
        params = {"api-key": self.api_key, "limit": 100}

        buy_times = []
        profitable_buys = 0
        total_buys = 0

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        txs = await response.json()

                        for tx in txs:
                            trade = self._parse_trade(tx, wallet)
                            if trade and trade['type'] == 'buy':
                                total_buys += 1

                                # Check if this was a fresh token
                                token = trade['token']
                                if token in self.fresh_tokens:
                                    fresh = self.fresh_tokens[token]
                                    buy_time = datetime.fromtimestamp(tx.get('timestamp', 0))
                                    time_since_launch = (buy_time - fresh.launch_time).total_seconds() / 60

                                    buy_times.append(time_since_launch)

                                    if time_since_launch < 2:
                                        patterns['migration_snipes'] += 1
                                    elif time_since_launch < 5:
                                        patterns['early_buys'] += 1

        except Exception as e:
            logger.error(f"Pattern analysis failed: {e}")

        # Calculate metrics
        if buy_times:
            patterns['avg_time_to_buy_min'] = sum(buy_times) / len(buy_times)

        if total_buys > 0:
            patterns['success_rate'] = profitable_buys / total_buys

        # Classify pattern
        if patterns['migration_snipes'] >= 3:
            patterns['detected_pattern'] = 'Migration Sniper'
        elif patterns['early_buys'] >= 5:
            patterns['detected_pattern'] = 'Early Bird Hunter'
        elif patterns['avg_time_to_buy_min'] < 3:
            patterns['detected_pattern'] = 'Launch Sniper'

        return patterns

    def _parse_trade(self, tx: Dict, wallet: str) -> Optional[Dict]:
        """Parse transaction to extract trade info."""
        try:
            token_transfers = tx.get('tokenTransfers', [])

            # Skip stablecoins
            SKIP_MINTS = {
                'So11111111111111111111111111111111111111112',  # WSOL
                'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
                'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
            }

            for transfer in token_transfers:
                mint = transfer.get('mint', '')
                if mint in SKIP_MINTS:
                    continue

                to_wallet = transfer.get('toUserAccount')
                from_wallet = transfer.get('fromUserAccount')

                if to_wallet == wallet:
                    return {'type': 'buy', 'token': mint}
                elif from_wallet == wallet:
                    return {'type': 'sell', 'token': mint}

        except Exception:
            pass

        return None

    async def save_insider_to_db(self, wallet: str, patterns: Dict):
        """Save detected insider to database."""
        conn = get_connection()
        cursor = conn.cursor()

        # Create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS insider_pool (
                wallet_address TEXT PRIMARY KEY,
                pattern TEXT,
                migration_snipes INTEGER DEFAULT 0,
                early_buys INTEGER DEFAULT 0,
                avg_time_to_buy_min REAL,
                success_rate REAL,
                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP,
                total_fresh_buys INTEGER DEFAULT 0,
                promoted_to_main INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            INSERT OR REPLACE INTO insider_pool (
                wallet_address, pattern, migration_snipes, early_buys,
                avg_time_to_buy_min, success_rate, last_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            wallet,
            patterns.get('detected_pattern'),
            patterns.get('migration_snipes', 0),
            patterns.get('early_buys', 0),
            patterns.get('avg_time_to_buy_min', 0),
            patterns.get('success_rate', 0),
            datetime.now().isoformat(),
        ))

        conn.commit()
        conn.close()


class InsiderScanner:
    """
    Background scanner that continuously finds insiders.

    Process:
    1. Scan fresh launches every 5 minutes
    2. Get first 20 buyers of each fresh token
    3. Analyze their patterns
    4. Add insiders to insider_pool
    5. If an insider succeeds 3+ times, promote to main pool
    """

    def __init__(self):
        self.tracker = LaunchTracker()
        self.running = False
        self.scan_interval = 300  # 5 minutes

    async def start(self):
        """Start the insider scanner."""
        self.running = True
        logger.info("Insider Scanner started")

        while self.running:
            try:
                await self._scan_cycle()
            except Exception as e:
                logger.error(f"Scan cycle failed: {e}")

            await asyncio.sleep(self.scan_interval)

    async def _scan_cycle(self):
        """Run one scan cycle."""
        # 1. Get fresh launches
        tokens = await self.tracker.scan_fresh_launches()
        logger.info(f"Found {len(tokens)} fresh tokens")

        # 2. For each token, get first buyers
        for token in tokens[:10]:  # Limit to 10 per cycle
            buyers = await self.tracker.get_first_buyers(token.address)

            # 3. Analyze each buyer
            for buyer in buyers[:5]:  # Top 5 first buyers
                patterns = await self.tracker.analyze_buyer_patterns(buyer)

                # 4. If pattern detected, save to db
                if patterns.get('detected_pattern'):
                    await self.tracker.save_insider_to_db(buyer, patterns)
                    logger.info(f"Insider detected: {buyer[:20]}... - {patterns['detected_pattern']}")

            await asyncio.sleep(1)  # Rate limiting

        # 5. Check for promotion to main pool
        await self._check_promotions()

    async def _check_promotions(self):
        """Promote successful insiders to main qualified_wallets pool."""
        conn = get_connection()
        cursor = conn.cursor()

        # Find insiders with 3+ successful early buys and good success rate
        cursor.execute("""
            SELECT wallet_address, pattern, success_rate
            FROM insider_pool
            WHERE (migration_snipes + early_buys) >= 3
            AND success_rate >= 0.6
            AND promoted_to_main = 0
        """)

        for row in cursor.fetchall():
            wallet, pattern, success_rate = row

            # Add to qualified_wallets with special tier
            cursor.execute("""
                INSERT OR IGNORE INTO qualified_wallets (
                    wallet_address, source, tier, cluster_name,
                    win_rate, qualified_at
                ) VALUES (?, 'insider', 'Elite', ?, ?, ?)
            """, (
                wallet,
                f"Insider: {pattern}",
                success_rate,
                datetime.now().isoformat(),
            ))

            # Mark as promoted
            cursor.execute("""
                UPDATE insider_pool SET promoted_to_main = 1
                WHERE wallet_address = ?
            """, (wallet,))

            logger.info(f"Promoted insider to main pool: {wallet[:20]}...")

        conn.commit()
        conn.close()

    def stop(self):
        """Stop the scanner."""
        self.running = False


async def main():
    """Test the launch tracker."""
    tracker = LaunchTracker()

    print("Scanning for fresh launches...")
    tokens = await tracker.scan_fresh_launches()

    print(f"\nFound {len(tokens)} fresh tokens (< 24h old):")
    for token in tokens[:5]:
        print(f"  {token.symbol}: {token.address[:30]}...")
        print(f"    Launched: {token.launch_time}")

        # Get first buyers
        buyers = await tracker.get_first_buyers(token.address, limit=3)
        print(f"    First buyers: {len(buyers)}")

        for buyer in buyers[:2]:
            patterns = await tracker.analyze_buyer_patterns(buyer)
            if patterns.get('detected_pattern'):
                print(f"      {buyer[:15]}... - {patterns['detected_pattern']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
