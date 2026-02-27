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


@dataclass
class AirdropRecipient:
    """A wallet that received tokens via airdrop (0 SOL cost)"""
    wallet_address: str
    token_address: str
    token_symbol: str
    received_time: datetime
    time_since_launch_min: int
    token_amount: float
    token_value_sol: float = 0
    percent_of_supply: float = 0
    has_sold: bool = False
    sold_amount: float = 0
    sold_at: datetime = None
    hold_duration_min: int = 0
    pattern: str = "Airdrop Insider"  # Team member, insider, partner


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

                            # Scan from birth (0 min) to 24 hours - get insiders & dev wallets!
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
        """
        Scan Pump.fun tokens via Helius blockchain queries (bypasses Cloudflare).

        Query Solana blockchain directly to find:
        1. New token mints (last 24h)
        2. Pump.fun program tokens
        3. Raydium migrations
        """
        tokens = []

        # Pump.fun program ID (bonding curve program)
        PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

        # Raydium AMM program (for detecting migrations)
        RAYDIUM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

        try:
            # Get recent signatures for Pump.fun program
            url = f"https://api.helius.xyz/v0/addresses/{PUMPFUN_PROGRAM}/transactions"
            params = {
                "api-key": self.api_key,
                "limit": 1000,  # Get more transactions to find token mints
                "type": "TOKEN_MINT"  # Filter for mint events
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=30) as response:
                    if response.status != 200:
                        logger.error(f"Helius API error: {response.status}")
                        return tokens

                    data = await response.json()
                    logger.info(f"Helius returned {len(data)} Pump.fun transactions")

                    cutoff = datetime.now() - timedelta(hours=self.max_age_hours)
                    seen_mints = set()

                    for tx in data:
                        try:
                            # Get timestamp
                            timestamp = tx.get('timestamp', 0)
                            if not timestamp:
                                continue

                            launch_time = datetime.fromtimestamp(timestamp)

                            # Filter by age (0-24 hours)
                            if launch_time <= cutoff:
                                continue

                            # Extract token mint from transaction
                            token_transfers = tx.get('tokenTransfers', [])
                            if not token_transfers:
                                continue

                            for transfer in token_transfers:
                                mint = transfer.get('mint', '')

                                # Skip if already seen
                                if mint in seen_mints or not mint:
                                    continue

                                seen_mints.add(mint)

                                # Check if this is a new mint (creation)
                                # New mints have large initial transfers TO the bonding curve
                                to_user = transfer.get('toUserAccount', '')
                                amount = transfer.get('tokenAmount', 0)

                                if amount > 0:  # Significant initial mint
                                    # Try to get token metadata
                                    symbol = await self._get_token_symbol(mint)

                                    # Check for Raydium migration
                                    migration_detected = await self._check_raydium_migration(mint)

                                    token = FreshToken(
                                        address=mint,
                                        symbol=symbol or mint[:8],
                                        name=symbol or 'Unknown',
                                        launch_time=launch_time,
                                        pump_graduated=migration_detected,
                                        migration_detected=migration_detected,
                                    )
                                    tokens.append(token)

                                    logger.info(f"Found Pump.fun token: {symbol or mint[:8]} (age: {(datetime.now() - launch_time).total_seconds() / 60:.1f} min)")

                                    # Limit results
                                    if len(tokens) >= 100:
                                        break

                        except Exception as e:
                            logger.debug(f"Error parsing transaction: {e}")
                            continue

                        if len(tokens) >= 100:
                            break

            logger.info(f"Found {len(tokens)} Pump.fun tokens via Helius blockchain query")

        except Exception as e:
            logger.error(f"Helius blockchain query failed: {e}")

        return tokens

    async def _get_token_symbol(self, mint: str) -> str:
        """Get token symbol/name from mint address via Helius."""
        try:
            url = f"https://api.helius.xyz/v0/token-metadata"
            params = {
                "api-key": self.api_key,
                "mint": mint
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('symbol', mint[:8])
        except:
            pass

        return mint[:8]

    async def _check_raydium_migration(self, mint: str) -> bool:
        """
        Check if token has migrated to Raydium via blockchain query.

        Migration = Raydium pool creation for this token
        """
        try:
            # Get recent transactions for this token mint
            url = f"https://api.helius.xyz/v0/addresses/{mint}/transactions"
            params = {
                "api-key": self.api_key,
                "limit": 50
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()

                        # Look for Raydium program interactions
                        RAYDIUM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

                        for tx in data:
                            account_data = tx.get('accountData', [])
                            for account in account_data:
                                if account.get('account') == RAYDIUM_PROGRAM:
                                    return True

                            # Also check instructions
                            instructions = tx.get('instructions', [])
                            for instr in instructions:
                                if instr.get('programId') == RAYDIUM_PROGRAM:
                                    return True
        except:
            pass

        return False

    async def get_first_buyers(self, token_address: str, limit: int = 100,
                               min_minutes: int = 0, max_minutes: int = 30) -> List[str]:
        """
        Get the first N buyers of a token within time window.

        Args:
            token_address: Token mint address
            limit: Max number of buyers (default 100)
            min_minutes: Minimum time after launch (default 0 - get insiders!)
            max_minutes: Maximum time after launch (default 30)
        """
        url = f"https://api.helius.xyz/v0/addresses/{token_address}/transactions"
        params = {"api-key": self.api_key, "limit": 200}  # Get more to filter

        buyers = []

        # Get token launch time
        token = self.fresh_tokens.get(token_address)
        if not token:
            logger.warning(f"Token {token_address} not in fresh_tokens")
            return buyers

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        txs = await response.json()

                        # Parse transactions to find buyers within time window
                        for tx in txs:
                            tx_time = datetime.fromtimestamp(tx.get('timestamp', 0))
                            time_since_launch = (tx_time - token.launch_time).total_seconds() / 60

                            # Filter by time window (default 0-30 min = insiders + early buyers)
                            if min_minutes <= time_since_launch <= max_minutes:
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


class AirdropTracker:
    """
    Tracks airdrop recipients (team members, insiders).

    Airdrop = token transfer with 0 SOL cost
    These wallets are insiders/team = valuable signal!
    """

    def __init__(self):
        self.api_key = HELIUS_API_KEY
        self.airdrop_recipients: Dict[str, List[AirdropRecipient]] = {}

    async def detect_airdrops(self, token_address: str, launch_time: datetime) -> List[AirdropRecipient]:
        """
        Detect wallets that received tokens via airdrop (0 SOL cost).

        Airdrop signals:
        - Token transfer TO wallet
        - No SOL transfer FROM wallet (0 cost)
        - Within first 24 hours of launch
        - Often large amounts (>1% of supply)
        """
        url = f"https://api.helius.xyz/v0/addresses/{token_address}/transactions"
        params = {"api-key": self.api_key, "limit": 200}

        recipients = []

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        txs = await response.json()

                        for tx in txs:
                            tx_time = datetime.fromtimestamp(tx.get('timestamp', 0))
                            time_since_launch = (tx_time - launch_time).total_seconds() / 60

                            # Only check first 24 hours
                            if time_since_launch > 1440:  # 24 hours
                                continue

                            # Look for airdrop transfers (token IN, no SOL OUT)
                            recipient = self._extract_airdrop_recipient(tx, token_address, tx_time, time_since_launch)
                            if recipient:
                                recipients.append(recipient)
                                logger.info(f"Airdrop detected: {recipient.wallet_address[:20]}... received {recipient.token_amount:.0f} tokens at {time_since_launch:.1f} min")

        except Exception as e:
            logger.error(f"Failed to detect airdrops: {e}")

        return recipients

    def _extract_airdrop_recipient(self, tx: Dict, token_address: str,
                                   tx_time: datetime, time_since_launch: float) -> Optional[AirdropRecipient]:
        """
        Extract airdrop recipient from transaction.

        Airdrop characteristics:
        - Token transfer TO wallet
        - No corresponding SOL transfer FROM that wallet
        - Often large amounts
        """
        try:
            token_transfers = tx.get('tokenTransfers', [])
            native_transfers = tx.get('nativeTransfers', [])

            # Find token transfers for this token
            for transfer in token_transfers:
                if transfer.get('mint') != token_address:
                    continue

                to_wallet = transfer.get('toUserAccount')
                token_amount = transfer.get('tokenAmount', 0)

                if not to_wallet or token_amount == 0:
                    continue

                # Check if this wallet paid SOL for the tokens
                sol_paid = 0
                for nt in native_transfers:
                    if nt.get('fromUserAccount') == to_wallet:
                        sol_paid += abs(nt.get('amount', 0)) / 1e9

                # If no SOL paid, it's an airdrop!
                if sol_paid < 0.001:  # Less than 0.001 SOL (accounting for fees)
                    return AirdropRecipient(
                        wallet_address=to_wallet,
                        token_address=token_address,
                        token_symbol=tx.get('tokenTransfers', [{}])[0].get('mint', '???')[:8],
                        received_time=tx_time,
                        time_since_launch_min=int(time_since_launch),
                        token_amount=token_amount,
                        token_value_sol=0,  # Will be calculated later
                        percent_of_supply=0,  # Will be calculated if supply data available
                    )

        except Exception as e:
            logger.debug(f"Failed to extract airdrop recipient: {e}")

        return None

    async def track_airdrop_sells(self, wallet: str, token_address: str) -> Dict:
        """
        Track when airdrop recipient sells their tokens.

        This is a key signal: Team/insiders dumping = exit signal for others!
        """
        url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
        params = {"api-key": self.api_key, "limit": 100}

        sell_data = {
            'has_sold': False,
            'sold_amount': 0,
            'sold_at': None,
            'hold_duration_min': 0,
            'sell_pattern': None,  # 'immediate', 'gradual', 'long_hold'
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        txs = await response.json()

                        for tx in txs:
                            token_transfers = tx.get('tokenTransfers', [])

                            for transfer in token_transfers:
                                if transfer.get('mint') != token_address:
                                    continue

                                from_wallet = transfer.get('fromUserAccount')

                                # Check if this wallet is selling
                                if from_wallet == wallet:
                                    sell_data['has_sold'] = True
                                    sell_data['sold_amount'] += transfer.get('tokenAmount', 0)

                                    if not sell_data['sold_at']:
                                        sell_data['sold_at'] = datetime.fromtimestamp(tx.get('timestamp', 0))

        except Exception as e:
            logger.error(f"Failed to track airdrop sells: {e}")

        return sell_data

    async def save_airdrop_recipient(self, recipient: AirdropRecipient):
        """Save airdrop recipient to database."""
        conn = get_connection()
        cursor = conn.cursor()

        # Create table if not exists
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS airdrop_insiders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wallet_address TEXT NOT NULL,
                token_address TEXT NOT NULL,
                token_symbol TEXT,
                received_time TIMESTAMP,
                time_since_launch_min INTEGER,
                token_amount REAL,
                token_value_sol REAL DEFAULT 0,
                percent_of_supply REAL DEFAULT 0,
                has_sold INTEGER DEFAULT 0,
                sold_amount REAL DEFAULT 0,
                sold_at TIMESTAMP,
                hold_duration_min INTEGER DEFAULT 0,
                pattern TEXT DEFAULT 'Airdrop Insider',
                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(wallet_address, token_address)
            )
        """)

        cursor.execute("""
            INSERT OR REPLACE INTO airdrop_insiders (
                wallet_address, token_address, token_symbol, received_time,
                time_since_launch_min, token_amount, token_value_sol,
                percent_of_supply, has_sold, sold_amount, sold_at,
                hold_duration_min, pattern, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            recipient.wallet_address,
            recipient.token_address,
            recipient.token_symbol,
            recipient.received_time.isoformat() if recipient.received_time else None,
            recipient.time_since_launch_min,
            recipient.token_amount,
            recipient.token_value_sol,
            recipient.percent_of_supply,
            1 if recipient.has_sold else 0,
            recipient.sold_amount,
            recipient.sold_at.isoformat() if recipient.sold_at else None,
            recipient.hold_duration_min,
            recipient.pattern,
            datetime.now().isoformat(),
        ))

        conn.commit()
        conn.close()

        logger.info(f"Saved airdrop insider: {recipient.wallet_address[:20]}...")

    async def generate_sell_alert(self, recipient: AirdropRecipient, token_symbol: str) -> str:
        """
        Generate alert when airdrop insider sells.

        Format:
        🚨 INSIDER SELL DETECTED
        💰 Team wallet dumped 40% supply
        🪙 $TOKEN (launched 2h ago)
        ⚠️ Caution: Insiders taking profit
        """
        if not recipient.has_sold:
            return ""

        alert = f"""🚨 INSIDER SELL DETECTED
💰 Airdrop wallet dumped {recipient.sold_amount:.0f} tokens
🪙 ${token_symbol}
⏰ Hold duration: {recipient.hold_duration_min} minutes
👤 Wallet: {recipient.wallet_address[:20]}...
⚠️ Caution: Insiders taking profit"""

        return alert


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
        self.airdrop_tracker = AirdropTracker()
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
        # 1. Get fresh launches (0-24 hours old - from birth!)
        tokens = await self.tracker.scan_fresh_launches()
        logger.info(f"Found {len(tokens)} fresh tokens (0-24h old)")

        # 2. For each token, get first 100 buyers (0-30 min window = insiders + early)
        for token in tokens[:20]:  # Process 20 tokens per cycle
            buyers = await self.tracker.get_first_buyers(
                token.address,
                limit=100,  # Get first 100 buyers
                min_minutes=0,   # From birth - get insiders & dev team!
                max_minutes=30   # Ultra-early window
            )
            logger.info(f"  {token.symbol}: Found {len(buyers)} buyers (0-30min window)")

            # 3. Analyze each buyer
            for buyer in buyers[:20]:  # Analyze top 20 buyers per token
                patterns = await self.tracker.analyze_buyer_patterns(buyer)

                # 4. If pattern detected, save to db
                if patterns.get('detected_pattern'):
                    await self.tracker.save_insider_to_db(buyer, patterns)
                    logger.info(f"    Insider detected: {buyer[:20]}... - {patterns['detected_pattern']}")

            # 5. DETECT AIRDROPS (team members, insiders)
            logger.info(f"  Scanning for airdrop recipients...")
            airdrop_recipients = await self.airdrop_tracker.detect_airdrops(
                token.address,
                token.launch_time
            )

            logger.info(f"  Found {len(airdrop_recipients)} airdrop recipients")

            # 6. Save airdrop recipients and add to pool immediately (no screening)
            for recipient in airdrop_recipients:
                await self.airdrop_tracker.save_airdrop_recipient(recipient)

                # Add to insider pool immediately (airdrop = insider)
                await self._add_airdrop_wallet_to_pool(recipient.wallet_address)

                # Track their sells
                sell_data = await self.airdrop_tracker.track_airdrop_sells(
                    recipient.wallet_address,
                    token.address
                )

                if sell_data['has_sold']:
                    recipient.has_sold = True
                    recipient.sold_amount = sell_data['sold_amount']
                    recipient.sold_at = sell_data['sold_at']

                    if recipient.received_time and sell_data['sold_at']:
                        recipient.hold_duration_min = int(
                            (sell_data['sold_at'] - recipient.received_time).total_seconds() / 60
                        )

                    # Generate alert
                    alert = await self.airdrop_tracker.generate_sell_alert(recipient, token.symbol)
                    if alert:
                        logger.warning(alert)

                    # Update in database
                    await self.airdrop_tracker.save_airdrop_recipient(recipient)

            await asyncio.sleep(1)  # Rate limiting

        # 7. Check for promotion to main pool
        await self._check_promotions()

    async def _add_airdrop_wallet_to_pool(self, wallet: str):
        """
        Add airdrop recipient to insider pool immediately (no screening).

        Airdrop = insider/team member = automatically qualifies.
        """
        conn = get_connection()
        cursor = conn.cursor()

        # Create insider_pool table if not exists
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
            INSERT OR IGNORE INTO insider_pool (
                wallet_address, pattern, last_active
            ) VALUES (?, 'Airdrop Insider', ?)
        """, (
            wallet,
            datetime.now().isoformat(),
        ))

        # Also add to qualified_wallets immediately
        cursor.execute("""
            INSERT OR IGNORE INTO qualified_wallets (
                wallet_address, source, tier, cluster_name, qualified_at
            ) VALUES (?, 'airdrop_insider', 'Elite', 'Team/Insider', ?)
        """, (
            wallet,
            datetime.now().isoformat(),
        ))

        conn.commit()
        conn.close()

        logger.info(f"Added airdrop wallet to pool: {wallet[:20]}...")

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
    tracker = LaunchTracker(max_age_hours=24)

    print("Scanning for fresh launches from birth (0-24h old)...")
    tokens = await tracker.scan_fresh_launches()

    print(f"\nFound {len(tokens)} fresh tokens:")
    for token in tokens[:5]:
        age_minutes = (datetime.now() - token.launch_time).total_seconds() / 60
        print(f"  {token.symbol}: {token.address[:30]}...")
        print(f"    Launched: {token.launch_time} ({age_minutes:.0f} min ago)")

        # Get first 100 buyers from birth (0-30 min = insiders + early)
        buyers = await tracker.get_first_buyers(
            token.address,
            limit=100,
            min_minutes=0,   # From birth - get insiders!
            max_minutes=30   # Ultra-early window
        )
        print(f"    First buyers (0-30min window): {len(buyers)}")

        for buyer in buyers[:3]:
            patterns = await tracker.analyze_buyer_patterns(buyer)
            if patterns.get('detected_pattern'):
                print(f"      {buyer[:15]}... - {patterns['detected_pattern']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
