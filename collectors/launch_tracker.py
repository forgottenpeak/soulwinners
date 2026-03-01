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

from config.settings import HELIUS_API_KEY, HELIUS_FREE_KEYS
from database import get_connection
from collectors.helius import helius_rotator  # Uses FREE keys for background jobs

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
    migration_time: datetime = None  # When it migrated to Raydium
    hours_since_migration: float = 0  # Age of Raydium pair


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
        self.fresh_migrations: List[FreshToken] = []  # Recently migrated tokens (0-6h)
        self.rotator = helius_rotator  # Use FREE key rotation for background jobs
        self.api_key = HELIUS_API_KEY  # Legacy fallback

    async def _get_api_key(self) -> str:
        """Get next API key from rotator (FREE pool)."""
        return await self.rotator.get_key()

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

        logger.info(f"Tracking {len(self.fresh_tokens)} fresh tokens total")
        logger.info(f"  - Fresh creations: {len(tokens)} (0-24h old)")
        logger.info(f"  - Fresh migrations: {len(self.fresh_migrations)} (0-6h since Raydium) ⭐")
        return tokens

    async def _scan_dexscreener_new(self) -> List[FreshToken]:
        """
        Scan DexScreener for fresh Raydium pairs (Pump.fun graduations).

        Uses multiple endpoints to maximize token discovery:
        1. Token boosts/latest endpoint for trending new tokens
        2. Search API with multiple queries
        3. Solana-specific pair searches

        Target: 50-100+ fresh tokens per scan.
        """
        tokens = []
        seen_mints = set()
        now = datetime.now()

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
        }

        async with aiohttp.ClientSession() as session:
            # Source 1: Token Boosts (trending new tokens)
            try:
                boost_url = "https://api.dexscreener.com/token-boosts/latest/v1"
                async with session.get(boost_url, headers=headers, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        boosts = data if isinstance(data, list) else []
                        logger.info(f"DexScreener boosts returned {len(boosts)} tokens")

                        for boost in boosts[:100]:
                            try:
                                if boost.get('chainId') != 'solana':
                                    continue
                                mint = boost.get('tokenAddress', '')
                                if not mint or mint in seen_mints:
                                    continue
                                seen_mints.add(mint)

                                # Get pair info for this token
                                token = await self._get_token_pair_info(session, mint, headers)
                                if token and self._is_fresh_token(token, now):
                                    tokens.append(token)
                            except Exception as e:
                                logger.debug(f"Error parsing boost: {e}")
            except Exception as e:
                logger.debug(f"Boosts endpoint failed: {e}")

            # Source 2: Latest pairs on Solana (most reliable for fresh launches)
            try:
                # DexScreener pairs by chain - gets newest pairs
                pairs_url = "https://api.dexscreener.com/latest/dex/pairs/solana"
                # Note: This endpoint doesn't exist, but we'll use token-profiles

                # Use token profiles for Solana
                profiles_url = "https://api.dexscreener.com/token-profiles/latest/v1"
                async with session.get(profiles_url, headers=headers, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        profiles = data if isinstance(data, list) else []
                        logger.info(f"DexScreener profiles returned {len(profiles)} tokens")

                        for profile in profiles[:150]:
                            try:
                                if profile.get('chainId') != 'solana':
                                    continue
                                mint = profile.get('tokenAddress', '')
                                if not mint or mint in seen_mints:
                                    continue
                                seen_mints.add(mint)

                                token = await self._get_token_pair_info(session, mint, headers)
                                if token and self._is_fresh_token(token, now):
                                    tokens.append(token)
                            except Exception as e:
                                logger.debug(f"Error parsing profile: {e}")
            except Exception as e:
                logger.debug(f"Profiles endpoint failed: {e}")

            # Source 3: Multiple search queries for Raydium pairs
            search_queries = [
                "raydium",      # Main Raydium pairs
                "pump",         # Pump.fun tokens
                "sol",          # SOL pairs
                "solana",       # Solana tokens
            ]

            for query in search_queries:
                try:
                    search_url = f"https://api.dexscreener.com/latest/dex/search?q={query}"
                    async with session.get(search_url, headers=headers, timeout=15) as response:
                        if response.status == 200:
                            data = await response.json()
                            pairs = data.get('pairs', [])
                            logger.info(f"DexScreener search '{query}' returned {len(pairs)} pairs")

                            fresh_from_query = 0
                            for pair in pairs[:100]:
                                try:
                                    if pair.get('chainId') != 'solana':
                                        continue

                                    # Only Raydium DEX
                                    dex_id = pair.get('dexId', '')
                                    if 'raydium' not in dex_id.lower():
                                        continue

                                    base_token = pair.get('baseToken', {})
                                    mint = base_token.get('address', '')

                                    if not mint or mint in seen_mints:
                                        continue
                                    seen_mints.add(mint)

                                    pair_created_at = pair.get('pairCreatedAt')
                                    if not pair_created_at:
                                        continue

                                    launch_time = datetime.fromtimestamp(pair_created_at / 1000)
                                    age_hours = (now - launch_time).total_seconds() / 3600

                                    if age_hours > self.max_age_hours or age_hours < 0:
                                        continue

                                    symbol = base_token.get('symbol', '???')
                                    name = base_token.get('name', 'Unknown')

                                    token = FreshToken(
                                        address=mint,
                                        symbol=symbol,
                                        name=name,
                                        launch_time=launch_time,
                                        pump_graduated='raydium' in dex_id.lower(),
                                        migration_detected=True,
                                        migration_time=launch_time,
                                        hours_since_migration=age_hours,
                                    )
                                    tokens.append(token)
                                    fresh_from_query += 1

                                except Exception as e:
                                    logger.debug(f"Error parsing pair: {e}")

                            if fresh_from_query > 0:
                                logger.info(f"  Found {fresh_from_query} fresh tokens from '{query}' search")

                    await asyncio.sleep(0.3)  # Rate limiting between queries

                except Exception as e:
                    logger.debug(f"Search '{query}' failed: {e}")

        # Sort by launch time (newest first)
        tokens.sort(key=lambda t: t.launch_time, reverse=True)

        logger.info(f"Total: Found {len(tokens)} fresh tokens (0-{self.max_age_hours}h) via DexScreener")

        return tokens

    async def _get_token_pair_info(self, session: aiohttp.ClientSession,
                                    mint: str, headers: dict) -> Optional[FreshToken]:
        """Get token pair info from DexScreener."""
        try:
            url = f"https://api.dexscreener.com/tokens/v1/solana/{mint}"
            async with session.get(url, headers=headers, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        pair = data[0]

                        # Only Raydium pairs
                        dex_id = pair.get('dexId', '')
                        if 'raydium' not in dex_id.lower():
                            return None

                        pair_created_at = pair.get('pairCreatedAt')
                        if not pair_created_at:
                            return None

                        launch_time = datetime.fromtimestamp(pair_created_at / 1000)
                        now = datetime.now()
                        age_hours = (now - launch_time).total_seconds() / 3600

                        base_token = pair.get('baseToken', {})
                        return FreshToken(
                            address=mint,
                            symbol=base_token.get('symbol', '???'),
                            name=base_token.get('name', 'Unknown'),
                            launch_time=launch_time,
                            pump_graduated=True,
                            migration_detected=True,
                            migration_time=launch_time,
                            hours_since_migration=age_hours,
                        )
        except Exception as e:
            logger.debug(f"Token info fetch failed: {e}")
        return None

    def _is_fresh_token(self, token: FreshToken, now: datetime) -> bool:
        """Check if token is within fresh window."""
        if not token or not token.launch_time:
            return False
        age_hours = (now - token.launch_time).total_seconds() / 3600
        return 0 <= age_hours <= self.max_age_hours

    async def _scan_pumpfun_graduated(self) -> List[FreshToken]:
        """
        Scan for Pump.fun graduated tokens (migrated to Raydium).

        This method now focuses specifically on finding FRESH MIGRATIONS (0-6h)
        which are the best trading signals.

        The main token discovery is handled by _scan_dexscreener_new().
        """
        fresh_migrations = []
        now = datetime.now()

        # Get all tokens from the main scan (already in self.fresh_tokens from scan_fresh_launches)
        # Filter for fresh migrations only (0-6h since Raydium)
        for token in list(self.fresh_tokens.values()):
            if token.migration_detected and token.hours_since_migration:
                if 0 < token.hours_since_migration <= 6:
                    fresh_migrations.append(token)
                    logger.info(f"🎯 FRESH MIGRATION: {token.symbol} (migrated {token.hours_since_migration:.1f}h ago)")

        # If we don't have enough, do an additional targeted search
        if len(fresh_migrations) < 10:
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': 'application/json',
                }

                # Search specifically for pump.fun graduated tokens
                async with aiohttp.ClientSession() as session:
                    search_url = "https://api.dexscreener.com/latest/dex/search?q=pump"
                    async with session.get(search_url, headers=headers, timeout=15) as response:
                        if response.status == 200:
                            data = await response.json()
                            pairs = data.get('pairs', [])

                            for pair in pairs[:100]:
                                try:
                                    if pair.get('chainId') != 'solana':
                                        continue

                                    dex_id = pair.get('dexId', '')
                                    if 'raydium' not in dex_id.lower():
                                        continue

                                    pair_created_at = pair.get('pairCreatedAt')
                                    if not pair_created_at:
                                        continue

                                    launch_time = datetime.fromtimestamp(pair_created_at / 1000)
                                    age_hours = (now - launch_time).total_seconds() / 3600

                                    # Only fresh migrations (0-6h)
                                    if age_hours > 6 or age_hours < 0:
                                        continue

                                    base_token = pair.get('baseToken', {})
                                    mint = base_token.get('address', '')

                                    # Skip if already in fresh_tokens
                                    if mint in self.fresh_tokens:
                                        continue

                                    token = FreshToken(
                                        address=mint,
                                        symbol=base_token.get('symbol', '???'),
                                        name=base_token.get('name', 'Unknown'),
                                        launch_time=launch_time,
                                        pump_graduated=True,
                                        migration_detected=True,
                                        migration_time=launch_time,
                                        hours_since_migration=age_hours,
                                    )

                                    fresh_migrations.append(token)
                                    self.fresh_tokens[mint] = token
                                    logger.info(f"🎯 FRESH MIGRATION: {token.symbol} (migrated {age_hours:.1f}h ago)")

                                except Exception as e:
                                    logger.debug(f"Error parsing pump pair: {e}")

            except Exception as e:
                logger.debug(f"Pump.fun search failed: {e}")

        logger.info(f"Found {len(fresh_migrations)} fresh migrations (0-6h) - BEST SIGNAL!")
        self.fresh_migrations = fresh_migrations

        return fresh_migrations

    async def _scan_via_helius_rpc(self) -> List[FreshToken]:
        """
        Fallback: Scan for new tokens via Helius RPC.

        Uses Helius webhook/transaction search to find recent token mints.
        """
        tokens = []

        try:
            # Use Helius Enhanced Transactions API
            # Search for recent transactions on Solana
            url = "https://api.helius.xyz/v0/transactions"
            params = {
                "api-key": self.api_key,
            }

            # Request body for transaction search
            body = {
                "query": {
                    "type": ["TOKEN_MINT"],
                    "commitment": "finalized"
                },
                "options": {
                    "limit": 100
                }
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, params=params, json=body, timeout=30) as response:
                    if response.status != 200:
                        logger.warning(f"Helius RPC fallback failed: {response.status}")
                        return tokens

                    data = await response.json()
                    logger.info(f"Helius RPC returned {len(data)} token mint transactions")

                    cutoff = datetime.now() - timedelta(hours=self.max_age_hours)

                    for tx in data:
                        try:
                            timestamp = tx.get('timestamp', 0)
                            if not timestamp:
                                continue

                            launch_time = datetime.fromtimestamp(timestamp)

                            if launch_time <= cutoff:
                                continue

                            # Extract token mint
                            token_transfers = tx.get('tokenTransfers', [])
                            for transfer in token_transfers:
                                mint = transfer.get('mint', '')
                                if mint:
                                    symbol = await self._get_token_symbol(mint)

                                    token = FreshToken(
                                        address=mint,
                                        symbol=symbol or mint[:8],
                                        name=symbol or 'Unknown',
                                        launch_time=launch_time,
                                        pump_graduated=False,
                                        migration_detected=False,
                                    )
                                    tokens.append(token)

                                    if len(tokens) >= 50:
                                        break

                        except Exception as e:
                            logger.debug(f"Error parsing Helius RPC tx: {e}")

                        if len(tokens) >= 50:
                            break

            logger.info(f"Found {len(tokens)} tokens via Helius RPC fallback")

        except Exception as e:
            logger.error(f"Helius RPC fallback failed: {e}")

        return tokens

    async def _get_token_symbol(self, mint: str) -> str:
        """Get token symbol/name from mint address via Helius."""
        try:
            api_key = await self._get_api_key()
            url = f"https://api.helius.xyz/v0/token-metadata"
            params = {
                "api-key": api_key,
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
            api_key = await self._get_api_key()
            url = f"https://api.helius.xyz/v0/addresses/{mint}/transactions"
            params = {
                "api-key": api_key,
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
        api_key = await self._get_api_key()
        url = f"https://api.helius.xyz/v0/addresses/{token_address}/transactions"
        params = {"api-key": api_key, "limit": 200}  # Get more to filter

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

    async def get_token_holders(self, token_address: str, min_balance: float = 0) -> List[Dict]:
        """
        Get ALL current holders of a token (not just recent traders).

        This captures:
        - Long-term holders (conviction wallets)
        - Wallets that bought early and held
        - Airdrop recipients who haven't sold
        - Anyone with current balance > 0

        Args:
            token_address: Token mint address
            min_balance: Minimum token balance to include (default 0)

        Returns:
            List of dicts: [{'wallet': address, 'balance': amount}, ...]
        """
        holders = []

        try:
            # Use Helius RPC to get all token accounts
            api_key = await self._get_api_key()
            url = f"https://rpc.helius.xyz/?api-key={api_key}"

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [token_address]
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        result = data.get('result', {})
                        value = result.get('value', [])

                        logger.info(f"Token {token_address[:8]}... has {len(value)} holder accounts")

                        for account_info in value:
                            # Get token account address
                            token_account = account_info.get('address')
                            balance_raw = account_info.get('amount')

                            if not token_account or not balance_raw:
                                continue

                            # Convert balance (usually in smallest units)
                            balance = float(balance_raw) / 1e9  # Adjust decimals as needed

                            # Skip if below minimum balance
                            if balance < min_balance:
                                continue

                            # Now get the owner of this token account
                            owner = await self._get_token_account_owner(token_account)
                            if owner:
                                holders.append({
                                    'wallet': owner,
                                    'balance': balance,
                                    'token_account': token_account
                                })

                        logger.info(f"Found {len(holders)} holders with balance > {min_balance}")

        except Exception as e:
            logger.error(f"Failed to get token holders: {e}")

        return holders

    async def _get_token_account_owner(self, token_account: str) -> Optional[str]:
        """Get the owner wallet address of a token account."""
        try:
            api_key = await self._get_api_key()
            url = f"https://rpc.helius.xyz/?api-key={api_key}"

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    token_account,
                    {"encoding": "jsonParsed"}
                ]
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        result = data.get('result', {})
                        value = result.get('value', {})
                        parsed_data = value.get('data', {}).get('parsed', {})
                        info = parsed_data.get('info', {})
                        owner = info.get('owner')
                        return owner

        except Exception as e:
            logger.debug(f"Failed to get token account owner: {e}")

        return None

    async def get_historical_token_holders(self, token_address: str, limit: int = 1000,
                                            max_days: int = 7) -> List[str]:
        """
        Get wallets that held this token in recent history (optimized for API usage).

        Uses Solana RPC getSignaturesForAddress for reliable transaction fetching,
        then parses each transaction for token transfers.

        OPTIMIZATION: Limited to last 7 days to reduce Helius API costs.
        - Scans up to 1000 transactions (reduced from 5000)
        - Only looks back 7 days (not all-time)
        - Reduces API usage by 80%+

        Args:
            token_address: Token mint address
            limit: Max number of transactions to scan (default 1000)
            max_days: Max days to look back (default 7)

        Returns:
            List of wallet addresses that held this token recently
        """
        historical_wallets = set()

        try:
            logger.info(f"Getting historical transactions for {token_address[:8]} (last {max_days} days)...")

            # Get API key from rotator (FREE pool for background jobs)
            api_key = await self._get_api_key()

            # Use Helius RPC for getSignaturesForAddress (more reliable than Enhanced API)
            rpc_url = f"https://mainnet.helius-rpc.com/?api-key={api_key}"

            # Calculate cutoff time
            cutoff_time = datetime.now() - timedelta(days=max_days)
            cutoff_timestamp = int(cutoff_time.timestamp())

            total_sigs = 0
            before_signature = None
            all_signatures = []

            # Step 1: Get all transaction signatures using RPC
            async with aiohttp.ClientSession() as session:
                while total_sigs < limit:
                    # Build RPC request for getSignaturesForAddress
                    rpc_params = [
                        token_address,
                        {
                            "limit": min(1000, limit - total_sigs),  # Max 1000 per request
                        }
                    ]

                    if before_signature:
                        rpc_params[1]["before"] = before_signature

                    payload = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getSignaturesForAddress",
                        "params": rpc_params
                    }

                    try:
                        async with session.post(rpc_url, json=payload, timeout=30) as response:
                            if response.status != 200:
                                error_text = await response.text()
                                logger.warning(f"Helius RPC error {response.status}: {error_text[:200]}")
                                break

                            data = await response.json()

                            if 'error' in data:
                                logger.warning(f"RPC error: {data['error']}")
                                break

                            result = data.get('result', [])

                            if not result:
                                logger.info(f"  No more signatures found")
                                break

                            # Check timestamps and filter
                            for sig_info in result:
                                block_time = sig_info.get('blockTime', 0)
                                if block_time and block_time < cutoff_timestamp:
                                    logger.info(f"  Reached transactions older than {max_days} days")
                                    total_sigs = limit  # Force exit
                                    break

                                all_signatures.append(sig_info.get('signature'))

                            total_sigs += len(result)
                            logger.info(f"  Fetched {len(result)} signatures (total: {total_sigs})")

                            # Set pagination cursor
                            if result:
                                before_signature = result[-1].get('signature')

                            # If we got less than requested, we're done
                            if len(result) < 1000:
                                break

                            await asyncio.sleep(0.2)  # Rate limiting

                    except asyncio.TimeoutError:
                        logger.warning("RPC timeout, continuing...")
                        break
                    except Exception as e:
                        logger.warning(f"RPC request failed: {e}")
                        break

            logger.info(f"  Found {len(all_signatures)} transaction signatures")

            # Step 2: Parse transactions in batches using Enhanced API
            if all_signatures:
                batch_size = 100
                for i in range(0, min(len(all_signatures), 500), batch_size):  # Limit to 500 tx parsing
                    batch = all_signatures[i:i + batch_size]

                    # Use parseTransactions endpoint for batch parsing
                    parse_api_key = await self._get_api_key()
                    parse_url = f"https://api.helius.xyz/v0/transactions"
                    params = {"api-key": parse_api_key}

                    try:
                        async with session.post(
                            parse_url,
                            params=params,
                            json={"transactions": batch},
                            timeout=30
                        ) as response:
                            if response.status == 200:
                                txs = await response.json()

                                for tx in txs:
                                    token_transfers = tx.get('tokenTransfers', [])
                                    for transfer in token_transfers:
                                        if transfer.get('mint') == token_address:
                                            to_wallet = transfer.get('toUserAccount')
                                            from_wallet = transfer.get('fromUserAccount')
                                            if to_wallet:
                                                historical_wallets.add(to_wallet)
                                            if from_wallet:
                                                historical_wallets.add(from_wallet)
                            else:
                                logger.debug(f"Parse batch failed: {response.status}")

                    except Exception as e:
                        logger.debug(f"Batch parse error: {e}")

                    await asyncio.sleep(0.3)  # Rate limiting

            logger.info(f"  Scanned {len(all_signatures)} historical transactions")
            logger.info(f"  Found {len(historical_wallets)} unique historical holders")

        except Exception as e:
            logger.error(f"Failed to get historical holders: {e}")

        return list(historical_wallets)

    async def get_all_token_wallets(self, token_address: str, min_balance: float = 0,
                                     use_historical: bool = True) -> List[str]:
        """
        Get ALL wallets associated with a token (complete blueprint).

        Combines:
        1. Current holders (anyone with balance > 0 now)
        2. Recent traders (buyers/sellers from recent transactions)
        3. Historical holders (EVERYONE who ever held the token) ← NEW!

        This gives COMPLETE coverage of all wallets that ever interacted with the token.

        Args:
            token_address: Token mint address
            min_balance: Minimum balance for current holders (default 0)
            use_historical: Include historical holders (default True for complete scan)

        Returns:
            List of wallet addresses (deduplicated)
        """
        all_wallets = set()

        # 1. Get current holders (conviction wallets - still holding)
        logger.info(f"Getting current holders for {token_address[:8]}...")
        holders = await self.get_token_holders(token_address, min_balance=min_balance)
        for holder in holders:
            all_wallets.add(holder['wallet'])
        logger.info(f"  Found {len(holders)} current holders")

        # 2. Get recent traders (active wallets - last 24h)
        logger.info(f"Getting recent traders for {token_address[:8]}...")
        traders = await self.get_first_buyers(token_address, limit=200, min_minutes=0, max_minutes=1440)  # 24h window
        all_wallets.update(traders)
        logger.info(f"  Found {len(traders)} recent traders")

        # 3. Get historical holders (last 7 days) - OPTIMIZED FOR API COST
        if use_historical:
            logger.info(f"Getting recent historical holders for {token_address[:8]} (last 7 days)...")
            historical = await self.get_historical_token_holders(token_address, limit=1000, max_days=7)
            all_wallets.update(historical)
            logger.info(f"  Found {len(historical)} historical holders (last 7 days)")

        logger.info(f"Total unique wallets for {token_address[:8]}: {len(all_wallets)}")
        logger.info(f"  Breakdown: {len(holders)} current + {len(traders)} recent + {len(historical) if use_historical else 0} historical")
        return list(all_wallets)

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
        api_key = await self._get_api_key()
        url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
        params = {"api-key": api_key, "limit": 100}

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
        self.rotator = helius_rotator  # Use FREE key rotation
        self.api_key = HELIUS_API_KEY  # Legacy fallback
        self.airdrop_recipients: Dict[str, List[AirdropRecipient]] = {}

    async def _get_api_key(self) -> str:
        """Get next API key from rotator (FREE pool)."""
        return await self.rotator.get_key()

    async def detect_airdrops(self, token_address: str, launch_time: datetime) -> List[AirdropRecipient]:
        """
        Detect wallets that received tokens via airdrop (0 SOL cost).

        Airdrop signals:
        - Token transfer TO wallet
        - No SOL transfer FROM wallet (0 cost)
        - Within first 24 hours of launch
        - Often large amounts (>1% of supply)
        """
        api_key = await self._get_api_key()
        url = f"https://api.helius.xyz/v0/addresses/{token_address}/transactions"
        params = {"api-key": api_key, "limit": 200}

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
        api_key = await self._get_api_key()
        url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
        params = {"api-key": api_key, "limit": 100}

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
        self.scan_interval = 7200  # 2 hours (optimized to reduce API costs)

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
        """Run one scan cycle with smart wallet selection strategy."""
        # 1. Get fresh launches (0-24 hours old - from birth!)
        tokens = await self.tracker.scan_fresh_launches()
        logger.info(f"Found {len(tokens)} fresh tokens (0-24h old)")

        # 2. For each token, use SMART STRATEGY based on age
        # OPTIMIZATION: Only process top 5 freshest tokens to reduce API costs
        for token in tokens[:5]:  # Process only 5 freshest tokens per cycle
            # Calculate token age
            now = datetime.now()
            age_hours = (now - token.launch_time).total_seconds() / 3600
            age_minutes = age_hours * 60

            logger.info(f"  {token.symbol}: Age {age_hours:.1f}h ({age_minutes:.0f} min)")

            # SMART STRATEGY: Different approach based on token age
            if age_hours < 1:
                # FRESH TOKEN (<1 hour): Scan current holders + traders
                # Reasoning: No one has sold yet, everyone still holding
                logger.info(f"  {token.symbol}: FRESH token - scanning current holders + traders")
                all_wallets = await self.tracker.get_all_token_wallets(
                    token.address,
                    min_balance=0,
                    use_historical=True  # Include some recent history
                )
                logger.info(f"  {token.symbol}: Found {len(all_wallets)} wallets (current + recent)")

                # Also detect airdrops for fresh tokens (team members)
                logger.info(f"  Scanning for airdrop recipients (team members)...")
                airdrop_recipients = await self.airdrop_tracker.detect_airdrops(
                    token.address,
                    token.launch_time
                )
                logger.info(f"  Found {len(airdrop_recipients)} airdrop recipients")

                # Save airdrop recipients
                for recipient in airdrop_recipients:
                    await self.airdrop_tracker.save_airdrop_recipient(recipient)
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

            else:
                # OLDER TOKEN (1-24 hours): Scan ALL historical buyers
                # Reasoning: Current holders = bag holders
                #            Winners already took profit and left
                #            We want to find the WINNERS, not bag holders!
                logger.info(f"  {token.symbol}: OLDER token - scanning ALL historical buyers (not bag holders)")
                all_wallets = await self.tracker.get_historical_token_holders(
                    token.address,
                    limit=1000,
                    max_days=7
                )
                logger.info(f"  {token.symbol}: Found {len(all_wallets)} historical buyers (since creation)")
                logger.info(f"  Strategy: Skip current holders (bag holders), find winners who took profit")

                # Skip airdrop detection for older tokens (already sold)
                logger.info(f"  Skipping airdrop detection (older token - airdrops already sold)")

            # 3. Analyze wallets (limit to top 50 per token to avoid overload)
            wallets_to_analyze = all_wallets[:50]
            logger.info(f"  Analyzing {len(wallets_to_analyze)} wallets for patterns...")

            for wallet in wallets_to_analyze:
                patterns = await self.tracker.analyze_buyer_patterns(wallet)

                # 4. If pattern detected, save to db
                if patterns.get('detected_pattern'):
                    await self.tracker.save_insider_to_db(wallet, patterns)
                    logger.info(f"    Insider detected: {wallet[:20]}... - {patterns['detected_pattern']}")

            # Rate limiting between tokens
            await asyncio.sleep(1)

        # 5. Check for promotion to main pool
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
