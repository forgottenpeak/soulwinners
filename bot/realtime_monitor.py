"""
Real-Time Transaction Monitor
- Helius websocket for live transactions
- Only monitors qualified wallets
- Posts alerts within 30 seconds
- Gets actual trade data from blockchain
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Set, Optional
import aiohttp
import websockets

from config.settings import HELIUS_API_KEY, DATABASE_PATH
from database import get_connection

# OpenClaw integration (optional)
try:
    from trader.strategy import SignalQueue
    from trader.openclaw import receive_soulwinners_signal
    OPENCLAW_ENABLED = True
except ImportError:
    OPENCLAW_ENABLED = False

logger = logging.getLogger(__name__)

# Price APIs
SOL_MINT = "So11111111111111111111111111111111111111112"


class PriceService:
    """Get live SOL price from CoinGecko."""

    def __init__(self):
        self.sol_price_usd: float = 0
        self.last_update: datetime = None

    async def get_sol_price(self) -> float:
        """Fetch current SOL price from CoinGecko."""
        # Cache for 30 seconds
        if self.last_update and (datetime.now() - self.last_update).seconds < 30:
            return self.sol_price_usd

        # CoinGecko (most reliable, no API key needed)
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        price = data.get('solana', {}).get('usd', 0)
                        if price and price > 0:
                            self.sol_price_usd = float(price)
                            self.last_update = datetime.now()
                            logger.info(f"SOL price: ${self.sol_price_usd:.2f}")
                            return self.sol_price_usd
        except Exception as e:
            logger.error(f"CoinGecko price failed: {e}")

        # Return cached or reasonable fallback (~$78)
        return self.sol_price_usd if self.sol_price_usd > 0 else 78.0


class WalletDataService:
    """Fetch real wallet data from Helius."""

    def __init__(self):
        self.api_key = HELIUS_API_KEY
        self.base_url = f"https://api.helius.xyz/v0"

    async def get_wallet_balance(self, wallet: str) -> float:
        """Get actual SOL balance for a wallet."""
        url = f"{self.base_url}/addresses/{wallet}/balances?api-key={self.api_key}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as response:
                    if response.status == 200:
                        data = await response.json()
                        # Native balance is in lamports (1 SOL = 1e9 lamports)
                        native = data.get('nativeBalance', 0)
                        return native / 1e9
                    else:
                        logger.warning(f"Balance API returned {response.status}")
        except asyncio.TimeoutError:
            logger.warning(f"Balance request timed out for {wallet[:15]}...")
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")

        return 0

    async def get_recent_trades(self, wallet: str, limit: int = 5) -> List[Dict]:
        """Get actual last N trades for a wallet with token symbols."""
        url = f"{self.base_url}/addresses/{wallet}/transactions?api-key={self.api_key}&limit=50"

        trades = []
        token_cache = {}  # Cache token symbols

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=15) as response:
                    if response.status == 200:
                        txs = await response.json()

                        for tx in txs:
                            trade = self._parse_swap_transaction(tx, wallet)
                            if trade:
                                # Fetch token symbol if we only have address
                                token_addr = trade['token_address']
                                if trade['token_symbol'].endswith('...') or trade['token_symbol'] == '???':
                                    if token_addr not in token_cache:
                                        symbol = await self._get_token_symbol(session, token_addr)
                                        token_cache[token_addr] = symbol
                                    trade['token_symbol'] = token_cache[token_addr]

                                trades.append(trade)
                                if len(trades) >= limit:
                                    break

        except Exception as e:
            logger.error(f"Failed to get trades for {wallet[:20]}: {e}")

        return trades

    async def _get_token_symbol(self, session: aiohttp.ClientSession, token_address: str) -> str:
        """Get token symbol from DexScreener."""
        try:
            url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"
            async with session.get(url, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        return data[0].get('baseToken', {}).get('symbol', token_address[:6])
        except:
            pass
        return token_address[:6] + '...'

    def _parse_swap_transaction(self, tx: Dict, wallet: str) -> Optional[Dict]:
        """Parse a transaction to extract swap/trade info."""
        try:
            token_transfers = tx.get('tokenTransfers', [])
            if not token_transfers:
                return None

            # Skip stablecoins and wrapped SOL
            SKIP_MINTS = {
                SOL_MINT,
                'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
                'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
            }

            # Find the main token (not SOL/USDC/USDT)
            main_token = None
            for transfer in token_transfers:
                mint = transfer.get('mint', '')
                if mint and mint not in SKIP_MINTS:
                    main_token = transfer
                    break

            if not main_token:
                return None

            # Determine if buy or sell based on transfer direction
            to_user = main_token.get('toUserAccount', '')
            from_user = main_token.get('fromUserAccount', '')

            if to_user == wallet:
                tx_type = 'buy'
            elif from_user == wallet:
                tx_type = 'sell'
            else:
                return None  # Not relevant to this wallet

            # Get timestamp
            timestamp = tx.get('timestamp', 0)
            time_ago = self._format_time_ago(timestamp)

            # Calculate SOL amount from native transfers
            native_transfers = tx.get('nativeTransfers', [])
            sol_amount = 0
            for nt in native_transfers:
                amount = abs(nt.get('amount', 0)) / 1e9
                if amount > sol_amount:
                    sol_amount = amount

            # Get token symbol - try multiple fields
            token_symbol = (
                main_token.get('symbol') or
                main_token.get('tokenSymbol') or
                main_token.get('mint', '')[:6] + '...'
            )

            # Get token amount
            token_amount = main_token.get('tokenAmount', 0)

            return {
                'token_address': main_token.get('mint', ''),
                'token_symbol': token_symbol,
                'tx_type': tx_type,
                'sol_amount': sol_amount,
                'token_amount': token_amount,
                'timestamp': timestamp,
                'time_ago': time_ago,
                'signature': tx.get('signature', ''),
            }

        except Exception as e:
            logger.error(f"Error parsing transaction: {e}")
            return None

    def _format_time_ago(self, timestamp: int) -> str:
        """Format timestamp as 'Xh ago' or 'Xd ago'."""
        if not timestamp:
            return "unknown"

        now = datetime.now().timestamp()
        diff = now - timestamp

        if diff < 3600:
            return f"{int(diff / 60)}m ago"
        elif diff < 86400:
            return f"{int(diff / 3600)}h ago"
        else:
            return f"{int(diff / 86400)}d ago"


class AccumulationTracker:
    """Track multiple buys of same token by same wallet for accumulation alerts."""

    def __init__(self, window_minutes: int = 30, min_total_sol: float = 1.0):
        self.window_minutes = window_minutes
        self.min_total_sol = min_total_sol
        # Structure: {wallet_address: {token_address: [(sol_amount, timestamp), ...]}}
        self.buy_history: Dict[str, Dict[str, List[tuple]]] = {}

    def record_buy(self, wallet: str, token: str, sol_amount: float, timestamp: float) -> Optional[Dict]:
        """
        Record a buy and check if it triggers an accumulation alert.
        Returns accumulation data if threshold reached, None otherwise.
        """
        now = datetime.now().timestamp()
        window_start = now - (self.window_minutes * 60)

        # Initialize wallet and token tracking
        if wallet not in self.buy_history:
            self.buy_history[wallet] = {}
        if token not in self.buy_history[wallet]:
            self.buy_history[wallet][token] = []

        # Clean old entries outside window
        self.buy_history[wallet][token] = [
            (amt, ts) for amt, ts in self.buy_history[wallet][token]
            if ts > window_start
        ]

        # Add new buy
        self.buy_history[wallet][token].append((sol_amount, timestamp))

        # Calculate total
        buys = self.buy_history[wallet][token]
        total_sol = sum(amt for amt, _ in buys)
        buy_count = len(buys)

        # Check if accumulation threshold met
        if total_sol >= self.min_total_sol and buy_count >= 2:
            # Calculate time span of accumulation
            first_buy = min(ts for _, ts in buys)
            time_span_min = int((now - first_buy) / 60)

            # Format individual buys
            buy_amounts = [f"{amt:.1f}" for amt, _ in buys]

            return {
                'total_sol': total_sol,
                'buy_count': buy_count,
                'time_span_min': time_span_min,
                'buy_amounts': buy_amounts,
                'is_accumulation': True
            }

        return None

    def cleanup_old_entries(self):
        """Remove entries older than window to prevent memory bloat."""
        now = datetime.now().timestamp()
        window_start = now - (self.window_minutes * 60)

        for wallet in list(self.buy_history.keys()):
            for token in list(self.buy_history[wallet].keys()):
                self.buy_history[wallet][token] = [
                    (amt, ts) for amt, ts in self.buy_history[wallet][token]
                    if ts > window_start
                ]
                # Remove empty token entries
                if not self.buy_history[wallet][token]:
                    del self.buy_history[wallet][token]
            # Remove empty wallet entries
            if not self.buy_history[wallet]:
                del self.buy_history[wallet]


class SmartMoneyTracker:
    """Track how many smart money wallets are in a token."""

    def __init__(self):
        self.token_holdings: Dict[str, Set[str]] = {}  # token -> set of wallets

    def record_buy(self, token_address: str, wallet_address: str, tier: str):
        """Record a wallet buying a token."""
        if token_address not in self.token_holdings:
            self.token_holdings[token_address] = set()
        self.token_holdings[token_address].add(wallet_address)

    def get_smart_money_count(self, token_address: str) -> Dict:
        """Get count of smart money wallets in a token."""
        if token_address not in self.token_holdings:
            return {'elite': 0, 'high': 0, 'total': 0}

        wallets = self.token_holdings[token_address]

        # Query database for wallet tiers
        conn = get_connection()
        cursor = conn.cursor()

        elite = 0
        high = 0

        for wallet in wallets:
            cursor.execute(
                "SELECT tier FROM qualified_wallets WHERE wallet_address = ?",
                (wallet,)
            )
            row = cursor.fetchone()
            if row:
                if row[0] == 'Elite':
                    elite += 1
                elif row[0] == 'High-Quality':
                    high += 1

        conn.close()

        return {
            'elite': elite,
            'high': high,
            'total': len(wallets)
        }


class RealTimeMonitor:
    """
    Real-time transaction monitor using Helius websocket.
    Only monitors qualified wallets from database.
    """

    def __init__(self, alert_callback):
        self.api_key = HELIUS_API_KEY
        self.ws_url = f"wss://atlas-mainnet.helius-rpc.com/?api-key={self.api_key}"
        self.alert_callback = alert_callback
        self.running = False

        self.qualified_wallets: Dict[str, Dict] = {}  # address -> wallet data
        self.subscriptions: Dict[int, str] = {}  # subscription_id -> wallet_address

        self.price_service = PriceService()
        self.wallet_service = WalletDataService()
        self.smart_money = SmartMoneyTracker()
        self.accumulation_tracker = AccumulationTracker(window_minutes=30, min_total_sol=1.0)

    async def load_qualified_wallets(self):
        """Load qualified wallets from database."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM qualified_wallets")
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()

        self.qualified_wallets.clear()
        for row in rows:
            wallet_dict = dict(zip(columns, row))
            self.qualified_wallets[wallet_dict['wallet_address']] = wallet_dict

        logger.info(f"Loaded {len(self.qualified_wallets)} qualified wallets")
        return len(self.qualified_wallets)

    async def start(self):
        """Start real-time monitoring."""
        self.running = True

        # Load qualified wallets
        count = await self.load_qualified_wallets()
        if count == 0:
            logger.warning("No qualified wallets to monitor!")
            return

        logger.info(f"Starting real-time monitor for {count} qualified wallets")

        while self.running:
            try:
                await self._connect_and_monitor()
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket closed: {e}")
                if self.running:
                    await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                if self.running:
                    await asyncio.sleep(5)

    async def _connect_and_monitor(self):
        """Connect to Helius websocket and subscribe to wallets."""
        async with websockets.connect(self.ws_url) as ws:
            logger.info("WebSocket connected to Helius")

            # Subscribe to all qualified wallets
            await self._subscribe_all(ws)

            # Listen for transactions
            async for message in ws:
                if not self.running:
                    break

                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.error(f"Error handling message: {e}")

    async def _subscribe_all(self, ws):
        """Subscribe to account changes for all qualified wallets."""
        logger.info(f"Subscribing to {len(self.qualified_wallets)} wallets...")

        for i, wallet_addr in enumerate(self.qualified_wallets.keys()):
            msg = {
                "jsonrpc": "2.0",
                "id": i + 1,
                "method": "accountSubscribe",
                "params": [
                    wallet_addr,
                    {"encoding": "jsonParsed", "commitment": "confirmed"}
                ]
            }
            await ws.send(json.dumps(msg))

            # Rate limit
            if (i + 1) % 50 == 0:
                await asyncio.sleep(1)
                logger.info(f"Subscribed to {i + 1} wallets...")

        logger.info("All wallet subscriptions sent")

    async def _handle_message(self, data: Dict):
        """Handle incoming websocket message."""
        # Subscription confirmation
        if 'result' in data and isinstance(data['result'], int):
            sub_id = data['result']
            req_id = data.get('id', 0)
            # Map subscription to wallet
            wallets = list(self.qualified_wallets.keys())
            if 0 < req_id <= len(wallets):
                self.subscriptions[sub_id] = wallets[req_id - 1]
            return

        # Account notification
        if data.get('method') == 'accountNotification':
            params = data.get('params', {})
            sub_id = params.get('subscription')

            wallet_addr = self.subscriptions.get(sub_id)
            if wallet_addr:
                await self._check_for_new_transaction(wallet_addr)

    async def _check_for_new_transaction(self, wallet_addr: str):
        """Check if wallet has a new buy transaction."""
        # Get most recent transaction
        trades = await self.wallet_service.get_recent_trades(wallet_addr, limit=1)

        if not trades:
            return

        latest = trades[0]

        # Only alert on buys within last 60 seconds
        if latest['tx_type'] != 'buy':
            return

        tx_age = datetime.now().timestamp() - latest['timestamp']
        if tx_age > 60:  # Ignore transactions older than 60 seconds
            return

        sol_amount = latest.get('sol_amount', 0)
        token_address = latest['token_address']

        logger.info(f"📊 Buy detected: {wallet_addr[:15]}... bought {sol_amount:.2f} SOL of {token_address[:15]}...")

        # Track accumulation
        accumulation = self.accumulation_tracker.record_buy(
            wallet_addr,
            token_address,
            sol_amount,
            latest['timestamp']
        )

        # Alert if single buy >= 1 SOL OR accumulation detected
        if sol_amount >= 1.0:
            # Standard single buy alert
            logger.info(f"✅ Triggering alert: Single buy >= 1 SOL ({sol_amount:.2f} SOL)")
            await self._generate_alert(wallet_addr, latest, accumulation_data=None)
        elif accumulation:
            # Accumulation alert - multiple smaller buys totaling >= 1 SOL
            logger.info(f"✅ Triggering ACCUMULATION alert: {accumulation['buy_count']} buys, total {accumulation['total_sol']:.1f} SOL")
            await self._generate_alert(wallet_addr, latest, accumulation_data=accumulation)
        else:
            logger.debug(f"⏳ Buy tracked but below threshold: {sol_amount:.2f} SOL (waiting for accumulation)")

    async def _generate_alert(self, wallet_addr: str, trade: Dict, accumulation_data: Optional[Dict] = None):
        """Generate and send alert for a real transaction."""
        wallet_data = self.qualified_wallets.get(wallet_addr)
        if not wallet_data:
            return

        token_address = trade['token_address']

        # Get real data concurrently
        sol_price, token_info, recent_trades, actual_balance = await asyncio.gather(
            self.price_service.get_sol_price(),
            self._get_token_info(token_address),
            self.wallet_service.get_recent_trades(wallet_addr, limit=5),
            self.wallet_service.get_wallet_balance(wallet_addr),
        )

        # Record buy for smart money tracking
        self.smart_money.record_buy(token_address, wallet_addr, wallet_data.get('tier', ''))
        smart_money = self.smart_money.get_smart_money_count(token_address)

        # Build alert data
        alert_data = {
            'wallet': wallet_data,
            'token': token_info,
            'trade': trade,
            'sol_price': sol_price,
            'actual_balance': actual_balance,
            'recent_trades': recent_trades,
            'smart_money': smart_money,
            'accumulation': accumulation_data,  # Add accumulation data if present
        }

        # Send alert via callback
        await self.alert_callback(alert_data)

        # Send signal to OpenClaw auto-trader (if enabled)
        if OPENCLAW_ENABLED and wallet_data.get('tier') == 'Elite':
            try:
                signal_queue = SignalQueue()
                receive_soulwinners_signal(alert_data, signal_queue)
                logger.info(f"Signal sent to OpenClaw: {token_info.get('symbol', '???')}")
            except Exception as e:
                logger.debug(f"OpenClaw signal failed: {e}")

    async def _get_token_info(self, token_address: str) -> Dict:
        """Get token info from DexScreener."""
        url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            pair = data[0]
                            return {
                                'address': token_address,
                                'name': pair.get('baseToken', {}).get('name', 'Unknown'),
                                'symbol': pair.get('baseToken', {}).get('symbol', '???'),
                                'image_url': pair.get('info', {}).get('imageUrl', ''),
                                'price_usd': pair.get('priceUsd', '0'),
                                'liquidity': pair.get('liquidity', {}).get('usd', 0),
                                'market_cap': pair.get('marketCap', 0),
                            }
        except Exception as e:
            logger.error(f"Error fetching token info: {e}")

        return {
            'address': token_address,
            'name': 'Unknown',
            'symbol': '???',
            'image_url': '',
            'price_usd': '0',
            'liquidity': 0,
            'market_cap': 0,
        }

    def stop(self):
        """Stop monitoring."""
        self.running = False
        logger.info("Real-time monitor stopped")


async def main():
    """Test the real-time monitor."""
    async def test_callback(alert_data):
        print("\n" + "=" * 60)
        print("REAL ALERT RECEIVED!")
        print("=" * 60)
        print(f"Token: {alert_data['token']['symbol']}")
        print(f"Wallet Tier: {alert_data['wallet']['tier']}")
        print(f"SOL Price: ${alert_data['sol_price']:.2f}")
        print(f"Smart Money: {alert_data['smart_money']}")

    monitor = RealTimeMonitor(test_callback)

    # Check if we have qualified wallets
    count = await monitor.load_qualified_wallets()
    print(f"Found {count} qualified wallets to monitor")

    if count > 0:
        print("Starting monitor (Ctrl+C to stop)...")
        await monitor.start()
    else:
        print("No qualified wallets found. Run the pipeline first.")


if __name__ == "__main__":
    asyncio.run(main())
