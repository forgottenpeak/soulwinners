"""
Helius API Integration
Transaction history fetching and websocket monitoring
With API key rotation for 4x capacity (400 req/sec)

KEY POOLS:
- FREE keys: For background jobs (pipeline, insider detection, cluster analysis)
- PREMIUM key: For real-time monitoring only (60-sec polling, buy alerts)
"""
import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable
import logging
import websockets

from config.settings import (
    HELIUS_API_KEY,
    HELIUS_API_KEYS,
    HELIUS_FREE_KEYS,
    HELIUS_PREMIUM_KEY,
    HELIUS_RPC_URL,
    HELIUS_WS_URL,
)

logger = logging.getLogger(__name__)


class HeliusRotator:
    """
    Rotate between multiple Helius API keys to maximize throughput.

    Supports two modes:
    - FREE mode: Rotates between free keys (for background jobs)
    - PREMIUM mode: Uses single premium key (for real-time monitoring)
    """

    def __init__(self, api_keys: List[str] = None, use_premium: bool = False):
        """
        Initialize the rotator.

        Args:
            api_keys: List of API keys to rotate through
            use_premium: If True, use only the premium key (no rotation)
        """
        self.use_premium = use_premium

        if use_premium:
            self.api_keys = [HELIUS_PREMIUM_KEY]
            logger.info("HeliusRotator initialized with PREMIUM key (real-time mode)")
        else:
            self.api_keys = api_keys or HELIUS_FREE_KEYS
            logger.info(f"HeliusRotator initialized with {len(self.api_keys)} FREE keys")

        self.current_index = 0
        self.request_counts: Dict[str, int] = {key: 0 for key in self.api_keys}
        self.reset_times: Dict[str, float] = {key: time.time() for key in self.api_keys}
        self.max_requests_per_minute = 5500  # Stay under 6000 limit per key
        self._lock = asyncio.Lock()

    async def get_key(self) -> str:
        """Get next available API key with capacity."""
        async with self._lock:
            now = time.time()

            # Reset counters every 60 seconds
            for key in self.api_keys:
                if now - self.reset_times[key] > 60:
                    self.request_counts[key] = 0
                    self.reset_times[key] = now

            # Try each key to find one with capacity
            for _ in range(len(self.api_keys)):
                key = self.api_keys[self.current_index]

                # If this key has capacity
                if self.request_counts[key] < self.max_requests_per_minute:
                    self.request_counts[key] += 1
                    # Rotate to next key for load balancing
                    self.current_index = (self.current_index + 1) % len(self.api_keys)
                    return key

                # Try next key
                self.current_index = (self.current_index + 1) % len(self.api_keys)

            # All keys at limit - find the one that will reset soonest
            logger.warning("All API keys at limit, waiting for reset...")
            min_wait = min(60 - (now - self.reset_times[key]) for key in self.api_keys)
            await asyncio.sleep(max(1, min_wait))
            return await self.get_key()

    def get_key_sync(self) -> str:
        """Synchronous version for non-async contexts."""
        now = time.time()

        # Reset counters every 60 seconds
        for key in self.api_keys:
            if now - self.reset_times[key] > 60:
                self.request_counts[key] = 0
                self.reset_times[key] = now

        # Round-robin with capacity check
        for _ in range(len(self.api_keys)):
            key = self.api_keys[self.current_index]
            if self.request_counts[key] < self.max_requests_per_minute:
                self.request_counts[key] += 1
                self.current_index = (self.current_index + 1) % len(self.api_keys)
                return key
            self.current_index = (self.current_index + 1) % len(self.api_keys)

        # All at limit, wait
        time.sleep(1)
        return self.get_key_sync()

    def get_stats(self) -> Dict:
        """Get current usage stats for all keys."""
        return {
            'keys': len(self.api_keys),
            'usage': {key[:8]: count for key, count in self.request_counts.items()},
            'total_capacity': len(self.api_keys) * self.max_requests_per_minute,
        }


# Global rotator instances
# FREE rotator - for background jobs (pipeline, insider detection, cluster analysis)
helius_rotator = HeliusRotator(use_premium=False)

# PREMIUM rotator - for real-time monitoring only
helius_premium_rotator = HeliusRotator(use_premium=True)


class HeliusClient:
    """Client for Helius API interactions with key rotation."""

    def __init__(self):
        self.rotator = helius_rotator
        self.ws_url = HELIUS_WS_URL
        self.base_url = f"https://api.helius.xyz/v0"

    async def get_transaction_history(
        self,
        wallet: str,
        limit: int = 100,
        before: str = None
    ) -> List[Dict]:
        """Get parsed transaction history for a wallet using rotated API keys."""
        import aiohttp

        for attempt in range(3):
            # Get a fresh API key for each attempt
            api_key = await self.rotator.get_key()
            url = f"{self.base_url}/addresses/{wallet}/transactions"
            params = {
                "api-key": api_key,
                "limit": limit
            }
            if before:
                params["before"] = before

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params, timeout=15) as response:
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 429:
                            # Rate limited - the rotator will switch keys
                            logger.debug(f"Key {api_key[:8]}... rate limited, rotating...")
                            await asyncio.sleep(1)
                        else:
                            logger.debug(f"Helius API error: {response.status}")
                            return []
            except asyncio.TimeoutError:
                logger.debug(f"Helius timeout for {wallet[:15]}...")
                await asyncio.sleep(1)
            except Exception as e:
                logger.debug(f"Helius error: {e}")
                await asyncio.sleep(1)

        return []

    async def get_all_transactions(
        self,
        wallet: str,
        days: int = 30,
        max_transactions: int = 1000
    ) -> List[Dict]:
        """Get all transactions within a time period."""
        all_txs = []
        before = None
        cutoff_time = datetime.now() - timedelta(days=days)

        while len(all_txs) < max_transactions:
            txs = await self.get_transaction_history(wallet, limit=100, before=before)

            if not txs:
                break

            for tx in txs:
                tx_time = tx.get('timestamp', 0)
                if tx_time and tx_time < cutoff_time.timestamp():
                    return all_txs

                all_txs.append(tx)

            before = txs[-1].get('signature')
            await asyncio.sleep(0.1)  # Rate limiting

        return all_txs

    async def get_wallet_balances(self, wallet: str) -> Dict:
        """Get all token balances for a wallet using rotated API keys."""
        import aiohttp

        api_key = await self.rotator.get_key()
        url = f"{self.base_url}/addresses/{wallet}/balances"
        params = {"api-key": api_key}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:
                        # Retry with different key
                        api_key = await self.rotator.get_key()
                        params["api-key"] = api_key
                        async with session.get(url, params=params, timeout=10) as retry:
                            if retry.status == 200:
                                return await retry.json()
        except Exception as e:
            logger.debug(f"Balance fetch error: {e}")
        return {}

    async def get_token_metadata(self, token_address: str) -> Dict:
        """Get metadata for a token using rotated API keys."""
        import aiohttp

        api_key = await self.rotator.get_key()
        url = f"{self.base_url}/token-metadata"
        params = {"api-key": api_key}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    params=params,
                    json={"mintAccounts": [token_address]},
                    timeout=10
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        return result[0] if result else {}
        except Exception as e:
            logger.debug(f"Metadata fetch error: {e}")
        return {}

    def parse_swap_transaction(self, tx: Dict) -> Optional[Dict]:
        """Parse a swap transaction to extract trade details."""
        try:
            # Look for token transfers indicating a swap
            token_transfers = tx.get('tokenTransfers', [])
            native_transfers = tx.get('nativeTransfers', [])

            if len(token_transfers) < 1:
                return None

            # Identify the main token being traded (not SOL/USDC)
            main_transfer = None
            sol_amount = 0

            for transfer in token_transfers:
                mint = transfer.get('mint', '')
                # Skip stablecoins and wrapped SOL
                if mint not in [
                    'So11111111111111111111111111111111111111112',  # WSOL
                    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
                    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
                ]:
                    main_transfer = transfer
                    break

            if not main_transfer:
                return None

            # Calculate SOL value from native transfers
            fee_payer = tx.get('feePayer')
            for transfer in native_transfers:
                if transfer.get('fromUserAccount') == fee_payer:
                    sol_amount -= transfer.get('amount', 0) / 1e9
                elif transfer.get('toUserAccount') == fee_payer:
                    sol_amount += transfer.get('amount', 0) / 1e9

            # Determine trade type
            is_buy = main_transfer.get('toUserAccount') == fee_payer
            trade_type = 'buy' if is_buy else 'sell'

            return {
                'signature': tx.get('signature'),
                'wallet': fee_payer,
                'token_address': main_transfer.get('mint'),
                'token_symbol': main_transfer.get('tokenStandard'),
                'trade_type': trade_type,
                'token_amount': main_transfer.get('tokenAmount', 0),
                'sol_amount': abs(sol_amount),
                'timestamp': tx.get('timestamp'),
                'source': tx.get('source', 'unknown')
            }

        except Exception as e:
            logger.error(f"Error parsing transaction: {e}")
            return None


class HeliusWebsocket:
    """Websocket connection for real-time transaction monitoring."""

    def __init__(self, wallets: List[str], callback: Callable):
        self.wallets = wallets
        self.callback = callback
        self.rotator = helius_rotator
        self.running = False

    def _get_ws_url(self) -> str:
        """Get websocket URL with rotated API key."""
        api_key = self.rotator.get_key_sync()
        return f"wss://mainnet.helius-rpc.com/?api-key={api_key}"

    async def subscribe(self, websocket, wallets: List[str]):
        """Subscribe to account changes for wallets."""
        for wallet in wallets:
            subscribe_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "accountSubscribe",
                "params": [
                    wallet,
                    {"encoding": "jsonParsed", "commitment": "confirmed"}
                ]
            }
            await websocket.send(json.dumps(subscribe_msg))
            logger.debug(f"Subscribed to wallet: {wallet[:20]}...")

    async def start(self):
        """Start the websocket connection and listen for transactions."""
        self.running = True
        logger.info(f"Starting websocket monitor for {len(self.wallets)} wallets")

        while self.running:
            try:
                ws_url = self._get_ws_url()
                async with websockets.connect(ws_url) as websocket:
                    # Subscribe in batches to avoid rate limits
                    batch_size = 100
                    for i in range(0, len(self.wallets), batch_size):
                        batch = self.wallets[i:i + batch_size]
                        await self.subscribe(websocket, batch)
                        await asyncio.sleep(0.5)

                    logger.info("Websocket connected and subscribed")

                    # Listen for messages
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            if 'params' in data:
                                await self.callback(data['params'])
                        except json.JSONDecodeError:
                            continue

            except websockets.exceptions.ConnectionClosed:
                logger.warning("Websocket connection closed, reconnecting...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Websocket error: {e}")
                await asyncio.sleep(5)

    def stop(self):
        """Stop the websocket connection."""
        self.running = False


async def main():
    """Test the Helius client."""
    client = HeliusClient()

    # Test with a known active wallet
    test_wallet = "DYw8jCTfwHNRJhhmFcbXvVDTqWMEVFBX6ZKUmG5CNSKK"

    print("Fetching transaction history...")
    txs = await client.get_transaction_history(test_wallet, limit=5)
    print(f"Found {len(txs)} transactions")

    for tx in txs[:2]:
        parsed = client.parse_swap_transaction(tx)
        if parsed:
            print(f"\nTrade: {parsed['trade_type'].upper()}")
            print(f"  Token: {parsed['token_address'][:20]}...")
            print(f"  SOL: {parsed['sol_amount']:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
