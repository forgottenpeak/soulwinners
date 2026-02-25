"""
Real-time Transaction Monitor
Uses Helius websocket to monitor qualified wallet transactions
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Set, Callable, Optional
import aiohttp
import websockets

from config.settings import HELIUS_API_KEY, HELIUS_WS_URL
from collectors.helius import HeliusClient

logger = logging.getLogger(__name__)


class TransactionMonitor:
    """
    Monitor qualified wallets for real-time transactions.
    Uses Helius enhanced websocket API.
    """

    def __init__(
        self,
        wallets: List[str],
        on_buy_callback: Callable,
        on_sell_callback: Callable
    ):
        self.wallets = set(wallets)
        self.on_buy = on_buy_callback
        self.on_sell = on_sell_callback
        self.api_key = HELIUS_API_KEY
        self.ws_url = f"wss://atlas-mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
        self.running = False
        self.helius = HeliusClient()
        self.reconnect_delay = 5
        self.subscription_ids = {}

    def add_wallet(self, wallet: str):
        """Add a wallet to monitor."""
        self.wallets.add(wallet)
        logger.info(f"Added wallet to monitor: {wallet[:20]}...")

    def remove_wallet(self, wallet: str):
        """Remove a wallet from monitoring."""
        self.wallets.discard(wallet)
        logger.info(f"Removed wallet from monitor: {wallet[:20]}...")

    def update_wallets(self, wallets: List[str]):
        """Update the full wallet list."""
        self.wallets = set(wallets)
        logger.info(f"Updated wallet list: {len(self.wallets)} wallets")

    async def start(self):
        """Start the transaction monitor."""
        self.running = True
        logger.info(f"Starting transaction monitor for {len(self.wallets)} wallets")

        while self.running:
            try:
                await self._connect_and_monitor()
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket connection closed: {e}")
                if self.running:
                    logger.info(f"Reconnecting in {self.reconnect_delay}s...")
                    await asyncio.sleep(self.reconnect_delay)
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                if self.running:
                    await asyncio.sleep(self.reconnect_delay)

    async def _connect_and_monitor(self):
        """Connect to websocket and start monitoring."""
        async with websockets.connect(self.ws_url) as ws:
            logger.info("WebSocket connected")

            # Subscribe to all wallets
            await self._subscribe_wallets(ws)

            # Listen for messages
            async for message in ws:
                if not self.running:
                    break

                try:
                    await self._handle_message(json.loads(message))
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.error(f"Error handling message: {e}")

    async def _subscribe_wallets(self, ws):
        """Subscribe to account updates for all wallets."""
        logger.info(f"Subscribing to {len(self.wallets)} wallets...")

        for i, wallet in enumerate(self.wallets):
            subscribe_msg = {
                "jsonrpc": "2.0",
                "id": i + 1,
                "method": "accountSubscribe",
                "params": [
                    wallet,
                    {
                        "encoding": "jsonParsed",
                        "commitment": "confirmed"
                    }
                ]
            }
            await ws.send(json.dumps(subscribe_msg))

            # Rate limit subscriptions
            if (i + 1) % 50 == 0:
                await asyncio.sleep(1)
                logger.info(f"Subscribed to {i + 1} wallets...")

        logger.info(f"Subscribed to all {len(self.wallets)} wallets")

    async def _handle_message(self, data: Dict):
        """Handle incoming websocket message."""
        # Check if it's a subscription confirmation
        if 'result' in data and isinstance(data['result'], int):
            sub_id = data['result']
            req_id = data.get('id')
            logger.debug(f"Subscription confirmed: {sub_id}")
            return

        # Check if it's an account notification
        if 'method' not in data or data['method'] != 'accountNotification':
            return

        params = data.get('params', {})
        result = params.get('result', {})
        context = result.get('context', {})
        value = result.get('value', {})

        if not value:
            return

        # Get the account (wallet) that changed
        # We need to identify which wallet this is for
        subscription = params.get('subscription')

        # Fetch recent transactions for this account to understand the change
        # This is a simplified approach - in production you'd want more efficient tracking
        await self._process_account_change(value, subscription)

    async def _process_account_change(self, value: Dict, subscription: int):
        """Process an account change notification."""
        # Get parsed account data
        data = value.get('data', {})

        if isinstance(data, dict) and 'parsed' in data:
            parsed = data['parsed']
            # Check for token account changes
            if parsed.get('type') == 'account':
                info = parsed.get('info', {})
                owner = info.get('owner')
                mint = info.get('mint')
                amount = info.get('tokenAmount', {}).get('uiAmount', 0)

                if owner in self.wallets and mint:
                    logger.info(f"Token change detected: {owner[:20]}... | {mint[:20]}...")
                    await self._analyze_transaction(owner, mint, amount)

    async def _analyze_transaction(self, wallet: str, token: str, amount: float):
        """Analyze a detected transaction and trigger appropriate callback."""
        # Fetch recent transactions to determine buy/sell
        txs = await self.helius.get_transaction_history(wallet, limit=5)

        for tx in txs:
            parsed = self.helius.parse_swap_transaction(tx)
            if parsed and parsed.get('token_address') == token:
                trade_type = parsed.get('trade_type')

                # Get token info
                token_info = {
                    'address': token,
                    'symbol': parsed.get('token_symbol', '???'),
                    'name': '',
                }

                trade_info = {
                    'signature': parsed.get('signature'),
                    'sol_amount': parsed.get('sol_amount', 0),
                    'token_amount': parsed.get('token_amount', 0),
                    'timestamp': parsed.get('timestamp'),
                }

                if trade_type == 'buy':
                    await self.on_buy(wallet, token_info, trade_info)
                elif trade_type == 'sell':
                    await self.on_sell(wallet, token_info, trade_info)

                break

    def stop(self):
        """Stop the transaction monitor."""
        self.running = False
        logger.info("Transaction monitor stopped")


class EnhancedMonitor:
    """
    Enhanced transaction monitor using Helius Enhanced Transactions API.
    More reliable than raw websocket for detecting swaps.
    """

    def __init__(
        self,
        wallets: List[str],
        on_transaction: Callable,
        poll_interval: float = 10.0  # Increased to avoid rate limits
    ):
        self.wallets = set(wallets)
        self.on_transaction = on_transaction
        self.poll_interval = poll_interval
        self.helius = HeliusClient()
        self.running = False
        self.last_signatures: Dict[str, str] = {}  # Track last seen tx per wallet

    def update_wallets(self, wallets: List[str]):
        """Update wallet list."""
        self.wallets = set(wallets)

    async def start(self):
        """Start polling for transactions."""
        self.running = True
        logger.info(f"Starting enhanced monitor for {len(self.wallets)} wallets")

        while self.running:
            try:
                await self._poll_transactions()
                await asyncio.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"Polling error: {e}")
                await asyncio.sleep(self.poll_interval * 2)

    async def _poll_transactions(self):
        """Poll for new transactions across all wallets."""
        # Process wallets one at a time with delays
        wallet_list = list(self.wallets)

        for wallet in wallet_list:
            try:
                await self._check_wallet(wallet)
            except Exception as e:
                logger.debug(f"Error checking {wallet[:15]}...: {e}")
            await asyncio.sleep(2)  # 2 second delay between each wallet

    async def _check_wallet(self, wallet: str):
        """Check a single wallet for new transactions."""
        txs = await self.helius.get_transaction_history(wallet, limit=3)

        if not txs:
            return

        latest_sig = txs[0].get('signature')
        last_seen = self.last_signatures.get(wallet)

        if last_seen and latest_sig != last_seen:
            # New transaction detected
            for tx in txs:
                if tx.get('signature') == last_seen:
                    break

                parsed = self.helius.parse_swap_transaction(tx)
                if parsed:
                    await self.on_transaction(wallet, parsed)

        self.last_signatures[wallet] = latest_sig

    def stop(self):
        """Stop the monitor."""
        self.running = False


async def main():
    """Test the monitor."""
    async def on_buy(wallet, token, trade):
        print(f"BUY: {wallet[:20]}... bought {token.get('symbol', '???')}")

    async def on_sell(wallet, token, trade):
        print(f"SELL: {wallet[:20]}... sold {token.get('symbol', '???')}")

    # Test with a known active wallet
    test_wallets = ["DYw8jCTfwHNRJhhmFcbXvVDTqWMEVFBX6ZKUmG5CNSKK"]

    monitor = TransactionMonitor(
        wallets=test_wallets,
        on_buy_callback=on_buy,
        on_sell_callback=on_sell
    )

    print("Starting monitor (press Ctrl+C to stop)...")
    try:
        await monitor.start()
    except KeyboardInterrupt:
        monitor.stop()


if __name__ == "__main__":
    asyncio.run(main())
