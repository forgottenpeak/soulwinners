"""
OpenClaw Auto-Trader
Copy-trading bot that follows SoulWinners elite wallet signals

Goal: Turn $15 → $10k by copy-trading elite wallet buys
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Optional
from dotenv import load_dotenv

from telegram import Bot
from telegram.constants import ParseMode

from .solana_dex import JupiterDEX
from .position_manager import PositionManager, Position, PositionStatus
from .strategy import TradingStrategy, StrategyConfig, ExitAction, SignalQueue

load_dotenv()
logger = logging.getLogger(__name__)


class OpenClawTrader:
    """
    Main OpenClaw trading bot.

    Workflow:
    1. Receive signal from SoulWinners (via queue)
    2. Validate signal (BES, win rate, liquidity)
    3. Calculate position size (70% of balance)
    4. Execute buy on Jupiter
    5. Monitor position for exits
    6. Execute exits (stop loss, take profits)
    7. Send Telegram notifications
    """

    def __init__(
        self,
        private_key: Optional[str] = None,
        telegram_token: Optional[str] = None,
        telegram_chat_id: Optional[str] = None,
        rpc_url: str = "https://api.mainnet-beta.solana.com",
        starting_balance: float = 0.2  # ~$15 in SOL
    ):
        # Load from env if not provided
        self.private_key = private_key or os.getenv('OPENCLAW_PRIVATE_KEY')
        self.telegram_token = telegram_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = telegram_chat_id or os.getenv('OPENCLAW_CHAT_ID')
        self.rpc_url = rpc_url

        if not self.private_key:
            raise ValueError("OPENCLAW_PRIVATE_KEY required")

        # Initialize components
        self.dex: Optional[JupiterDEX] = None
        self.position_manager = PositionManager()
        self.strategy = TradingStrategy()
        self.signal_queue = SignalQueue()

        # Telegram bot for notifications
        self.bot = Bot(token=self.telegram_token) if self.telegram_token else None

        # State
        self.running = False
        self.starting_balance = starting_balance
        self.current_balance = starting_balance
        self.sol_price = 78.0  # Updated periodically

        # Initialize starting balance
        self.position_manager.set_starting_balance(starting_balance)

    async def start(self):
        """Start the trading bot."""
        logger.info("=" * 60)
        logger.info("OPENCLAW AUTO-TRADER STARTING")
        logger.info("=" * 60)

        self.running = True

        # Initialize DEX connection
        self.dex = JupiterDEX(self.private_key, self.rpc_url)
        self.dex.session = await self.dex.__aenter__()

        # Update balance
        await self._update_balance()

        # Send startup notification
        await self._notify(
            f"🤖 **OPENCLAW STARTED**\n\n"
            f"💰 Balance: {self.current_balance:.4f} SOL (~${self.current_balance * self.sol_price:.2f})\n"
            f"🎯 Goal: $10,000\n"
            f"📊 Strategy: Copy Elite Wallets\n\n"
            f"Waiting for signals..."
        )

        # Start main loops
        await asyncio.gather(
            self._signal_processor(),
            self._position_monitor(),
            self._balance_updater(),
        )

    async def stop(self):
        """Stop the trading bot."""
        self.running = False
        if self.dex:
            await self.dex.__aexit__(None, None, None)

        stats = self.position_manager.get_stats()
        await self._notify(
            f"🛑 **OPENCLAW STOPPED**\n\n"
            f"📊 **Final Stats:**\n"
            f"├ Balance: {stats['current_balance']:.4f} SOL\n"
            f"├ Total P&L: {stats['total_pnl_sol']:+.4f} SOL ({stats['total_pnl_percent']:+.1f}%)\n"
            f"├ Trades: {stats['total_trades']}\n"
            f"└ Win Rate: {stats['win_rate']:.1f}%"
        )

    async def _signal_processor(self):
        """Process incoming signals from queue."""
        logger.info("Signal processor started")

        while self.running:
            try:
                # Get next signal
                signal = self.signal_queue.pop_signal()

                if signal:
                    await self._process_signal(signal)
                else:
                    await asyncio.sleep(1)  # No signal, wait

            except Exception as e:
                logger.error(f"Signal processor error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _process_signal(self, signal: Dict):
        """Process a trading signal."""
        token_mint = signal['token_mint']
        token_symbol = signal['token_symbol']
        wallet_bes = signal['wallet_bes']
        wallet_win_rate = signal['wallet_win_rate']
        token_liquidity = signal['token_liquidity']

        logger.info(f"Processing signal: {token_symbol} from wallet with BES {wallet_bes:.0f}")

        # Check entry criteria
        should_enter, reason = self.strategy.should_enter(
            wallet_bes=wallet_bes,
            wallet_win_rate=wallet_win_rate,
            token_liquidity=token_liquidity,
            current_positions=len(self.position_manager.get_open_positions()),
            already_holding_token=self.position_manager.has_position(token_mint)
        )

        if not should_enter:
            logger.info(f"Skipping signal: {reason}")
            self.signal_queue.complete_signal(signal['id'], 'skipped')
            return

        # Calculate position size
        position_size = self.strategy.calculate_position_size(self.current_balance)

        # Ensure we have enough balance
        actual_balance = await self.dex.get_sol_balance()
        if actual_balance < position_size + 0.01:  # Keep 0.01 SOL for fees
            logger.warning(f"Insufficient balance: {actual_balance:.4f} SOL")
            self.signal_queue.complete_signal(signal['id'], 'skipped')
            return

        # Execute buy
        logger.info(f"Executing buy: {position_size:.4f} SOL of {token_symbol}")

        try:
            result = await self.dex.buy_token(token_mint, position_size)

            if result and result.get('success'):
                # Get entry price
                token_balance = await self.dex.get_token_balance(token_mint)
                token_price = await self.dex.get_token_price(token_mint) or 0
                entry_price = (position_size * self.sol_price) / token_balance if token_balance > 0 else 0

                # Open position
                position = self.position_manager.open_position(
                    token_mint=token_mint,
                    token_symbol=token_symbol,
                    entry_price=entry_price,
                    entry_sol=position_size,
                    token_amount=token_balance,
                    source_wallet=signal['wallet_address'],
                    entry_signature=result['signature']
                )

                # Notify
                await self._notify_trade_entry(position, signal)

                self.signal_queue.complete_signal(signal['id'], 'executed')
                logger.info(f"Position opened: {token_symbol} | {position_size:.4f} SOL")

            else:
                logger.error(f"Buy failed for {token_symbol}")
                self.signal_queue.complete_signal(signal['id'], 'failed')

        except Exception as e:
            logger.error(f"Trade execution error: {e}", exc_info=True)
            self.signal_queue.complete_signal(signal['id'], 'failed')

    async def _position_monitor(self):
        """Monitor open positions for exit conditions."""
        logger.info("Position monitor started")

        while self.running:
            try:
                positions = self.position_manager.get_open_positions()

                for position in positions:
                    await self._check_position(position)

                await asyncio.sleep(5)  # Check every 5 seconds

            except Exception as e:
                logger.error(f"Position monitor error: {e}", exc_info=True)
                await asyncio.sleep(10)

    async def _check_position(self, position: Position):
        """Check a single position for exit conditions."""
        # Get current price
        current_price = await self.dex.get_token_price(position.token_mint)
        if not current_price:
            return

        # Update price and P&L
        self.strategy.record_price(position.token_mint, current_price)
        self.position_manager.update_position_price(
            position.token_mint,
            current_price,
            self.sol_price
        )

        # Check exit conditions
        action, sell_percent = self.strategy.check_exit(position)

        if action == ExitAction.HOLD or action == ExitAction.MOMENTUM_HOLD:
            return  # No action needed

        # Execute exit
        logger.info(f"Exit triggered: {action.value} for {position.token_symbol}")

        try:
            # Get token decimals (assume 6 for most SPL tokens)
            token_decimals = 6

            result = await self.dex.sell_token_percentage(
                position.token_mint,
                sell_percent,
                token_decimals
            )

            if result and result.get('success'):
                exit_sol = result['output_amount']

                # Update position
                if sell_percent >= 100:
                    reason = 'stop' if action == ExitAction.STOP_LOSS else 'manual'
                    self.position_manager.close_position(
                        position.token_mint,
                        exit_sol,
                        result['signature'],
                        reason
                    )
                else:
                    reason = 'tp1' if action == ExitAction.TAKE_PROFIT_1 else 'tp2'
                    self.position_manager.partial_close(
                        position.token_mint,
                        sell_percent,
                        exit_sol,
                        result['signature'],
                        reason
                    )

                # Notify
                await self._notify_trade_exit(position, action, exit_sol, sell_percent)

            else:
                logger.error(f"Exit failed for {position.token_symbol}")

        except Exception as e:
            logger.error(f"Exit execution error: {e}", exc_info=True)

    async def _balance_updater(self):
        """Periodically update balance and SOL price."""
        while self.running:
            try:
                await self._update_balance()
                await asyncio.sleep(60)  # Update every minute

            except Exception as e:
                logger.error(f"Balance updater error: {e}")
                await asyncio.sleep(30)

    async def _update_balance(self):
        """Update current balance and SOL price."""
        if self.dex:
            self.current_balance = await self.dex.get_sol_balance()
            self.sol_price = await self.dex.get_sol_price() or 78.0
            self.position_manager.update_current_balance(self.current_balance)

            logger.debug(f"Balance: {self.current_balance:.4f} SOL | SOL: ${self.sol_price:.2f}")

    async def _notify(self, message: str):
        """Send Telegram notification."""
        if self.bot and self.telegram_chat_id:
            try:
                await self.bot.send_message(
                    chat_id=self.telegram_chat_id,
                    text=message,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
            except Exception as e:
                logger.error(f"Notification failed: {e}")

    async def _notify_trade_entry(self, position: Position, signal: Dict):
        """Send trade entry notification."""
        usd_value = position.entry_sol * self.sol_price

        message = f"""
🟢 **TRADE OPENED**

🪙 **Token:** {position.token_symbol}
💰 **Entry:** {position.entry_sol:.4f} SOL (~${usd_value:.2f})
📊 **Position:** #{len(self.position_manager.get_open_positions())}/3

📈 **Source Wallet:**
├ BES: {signal['wallet_bes']:.0f}
├ Win Rate: {signal['wallet_win_rate']:.0%}
└ Tier: {signal['wallet_tier']}

⚙️ **Exit Strategy:**
├ Stop Loss: -20%
├ TP1: +50% (sell 50%)
└ TP2: +100% (sell 50%)

🔗 [DexScreener](https://dexscreener.com/solana/{position.token_mint})
"""
        await self._notify(message)

    async def _notify_trade_exit(self, position: Position, action: ExitAction, exit_sol: float, sell_percent: float):
        """Send trade exit notification."""
        pnl_sol = exit_sol - (position.entry_sol * sell_percent / 100)
        pnl_pct = position.pnl_percent
        emoji = "🟢" if pnl_sol >= 0 else "🔴"

        reason_text = self.strategy.format_exit_reason(action, position)

        message = f"""
{emoji} **TRADE EXIT**

🪙 **Token:** {position.token_symbol}
📊 **Action:** {reason_text}
💰 **Sold:** {sell_percent:.0f}% → {exit_sol:.4f} SOL

📈 **Result:**
├ P&L: {pnl_sol:+.4f} SOL ({pnl_pct:+.1f}%)
└ Remaining: {position.remaining_percent:.0f}%

💼 **Portfolio:**
├ Balance: {self.current_balance:.4f} SOL
└ Open Positions: {len(self.position_manager.get_open_positions())}
"""
        await self._notify(message)

    def get_status(self) -> Dict:
        """Get current bot status."""
        stats = self.position_manager.get_stats()
        positions = self.position_manager.get_open_positions()

        return {
            'running': self.running,
            'balance_sol': self.current_balance,
            'balance_usd': self.current_balance * self.sol_price,
            'sol_price': self.sol_price,
            'total_pnl_sol': stats['total_pnl_sol'],
            'total_pnl_percent': stats['total_pnl_percent'],
            'goal_progress': stats['progress_percent'],
            'total_trades': stats['total_trades'],
            'win_rate': stats['win_rate'],
            'open_positions': len(positions),
            'positions': [p.to_dict() for p in positions],
            'pending_signals': self.signal_queue.get_pending_count(),
        }


def receive_soulwinners_signal(alert_data: Dict, signal_queue: SignalQueue):
    """
    Integration point: Called by SoulWinners when elite wallet buys.
    This function is called from realtime_monitor.py after an alert.
    """
    wallet = alert_data.get('wallet', {})
    token = alert_data.get('token', {})
    trade = alert_data.get('trade', {})

    # Only process elite wallet buys
    if wallet.get('tier') != 'Elite':
        return

    # Calculate BES
    roi_per_trade = wallet.get('roi_per_trade', 0) or 0
    win_rate = wallet.get('profit_token_ratio', 0) or wallet.get('win_rate', 0) or 0
    trade_freq = wallet.get('trade_frequency', 0) or 0
    total_trades = wallet.get('total_trades', 1) or 1
    balance = wallet.get('current_balance_sol', 1) or 1
    avg_buy = balance / total_trades

    bes = (abs(roi_per_trade) * win_rate * trade_freq) / avg_buy if avg_buy > 0 else 0

    signal_queue.push_signal(
        token_mint=token.get('address', ''),
        token_symbol=token.get('symbol', '???'),
        wallet_address=wallet.get('wallet_address', ''),
        wallet_bes=bes,
        wallet_win_rate=win_rate,
        wallet_tier=wallet.get('tier', ''),
        buy_sol=trade.get('sol_amount', 0),
        token_liquidity=token.get('liquidity', 0),
        token_market_cap=token.get('market_cap', 0)
    )


async def main():
    """Run OpenClaw standalone."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    trader = OpenClawTrader()

    try:
        await trader.start()
    except KeyboardInterrupt:
        await trader.stop()


if __name__ == "__main__":
    asyncio.run(main())
