"""
SoulWinners - Solana Smart Money Discovery System
Main entry point
"""
import asyncio
import logging
import signal
import sys
from datetime import datetime, time as dt_time
from typing import Dict, List

from config.settings import REFRESH_HOUR_UTC, DATA_DIR, LOGS_DIR
from database import init_database, get_connection
from pipeline.orchestrator import PipelineOrchestrator
from bot.telegram_bot import SoulWinnersBot
from bot.monitor import EnhancedMonitor

# Configure logging
LOGS_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOGS_DIR / 'soulwinners.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class SoulWinnersSystem:
    """
    Main system coordinator.
    Manages:
    - Daily pipeline execution
    - Real-time transaction monitoring
    - Telegram bot
    """

    def __init__(self):
        self.pipeline = PipelineOrchestrator()
        self.bot = SoulWinnersBot()
        self.monitor = None
        self.running = False
        self.qualified_wallets: Dict[str, Dict] = {}

    async def start(self):
        """Start the complete system."""
        self.running = True
        logger.info("=" * 60)
        logger.info("SOULWINNERS SYSTEM STARTING")
        logger.info("=" * 60)

        # Initialize database
        init_database()

        # Load existing qualified wallets
        await self._load_qualified_wallets()

        # Run initial pipeline if needed
        if not self.qualified_wallets:
            logger.info("No qualified wallets found, running initial pipeline...")
            await self._run_pipeline()
        else:
            logger.info(f"Loaded {len(self.qualified_wallets)} qualified wallets")

        # Start components concurrently
        await asyncio.gather(
            self._run_telegram_bot(),
            self._run_transaction_monitor(),
            self._run_daily_scheduler(),
        )

    async def stop(self):
        """Stop the system gracefully."""
        logger.info("Stopping SoulWinners system...")
        self.running = False

        if self.monitor:
            self.monitor.stop()

        await self.bot.stop()
        logger.info("System stopped")

    async def _load_qualified_wallets(self):
        """Load qualified wallets from database."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM qualified_wallets")
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            wallet_dict = dict(zip(columns, row))
            self.qualified_wallets[wallet_dict['wallet_address']] = wallet_dict

    async def _run_pipeline(self):
        """Run the data pipeline."""
        try:
            df_qualified = await self.pipeline.run_full_pipeline()

            # Update wallet cache
            self.qualified_wallets.clear()
            for _, row in df_qualified.iterrows():
                self.qualified_wallets[row['wallet_address']] = row.to_dict()

            # Update monitor if running
            if self.monitor:
                self.monitor.update_wallets(list(self.qualified_wallets.keys()))

            logger.info(f"Pipeline complete, {len(self.qualified_wallets)} wallets loaded")

        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)

    async def _run_telegram_bot(self):
        """Run the Telegram bot."""
        try:
            await self.bot.start()
            # Keep running
            while self.running:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Telegram bot error: {e}", exc_info=True)

    async def _run_transaction_monitor(self):
        """Run the real-time transaction monitor."""
        while self.running:
            if not self.qualified_wallets:
                logger.info("Waiting for qualified wallets before starting monitor...")
                await asyncio.sleep(60)
                continue

            try:
                self.monitor = EnhancedMonitor(
                    wallets=list(self.qualified_wallets.keys()),
                    on_transaction=self._handle_transaction,
                    poll_interval=30.0  # 30 second cycles to stay within rate limits
                )
                await self.monitor.start()
            except Exception as e:
                logger.error(f"Monitor error: {e}")
                await asyncio.sleep(30)

    async def _handle_transaction(self, wallet: str, parsed_tx: Dict):
        """Handle a detected transaction from a qualified wallet."""
        if wallet not in self.qualified_wallets:
            return

        wallet_data = self.qualified_wallets[wallet]
        trade_type = parsed_tx.get('trade_type')

        logger.info(f"Transaction detected: {wallet[:20]}... {trade_type}")

        token_info = {
            'address': parsed_tx.get('token_address', ''),
            'symbol': parsed_tx.get('token_symbol', '???'),
            'name': '',
        }

        trade_info = {
            'signature': parsed_tx.get('signature'),
            'sol_amount': parsed_tx.get('sol_amount', 0),
            'token_amount': parsed_tx.get('token_amount', 0),
            'timestamp': parsed_tx.get('timestamp'),
        }

        # Get recent trades for context
        recent_trades = await self._get_recent_trades(wallet)

        if trade_type == 'buy':
            await self.bot.send_buy_alert(
                wallet=wallet_data,
                token=token_info,
                trade=trade_info,
                recent_trades=recent_trades
            )
        elif trade_type == 'sell':
            # Calculate PnL (simplified)
            pnl = self._calculate_trade_pnl(wallet, parsed_tx)
            await self.bot.send_sell_alert(
                wallet=wallet_data,
                token=token_info,
                trade=trade_info,
                pnl_percent=pnl
            )

        # Record alert in database
        self._record_alert(wallet, token_info, trade_type)

    async def _get_recent_trades(self, wallet: str) -> List[Dict]:
        """Get recent trades for a wallet."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT token_symbol, pnl_percent, tx_type
            FROM transactions
            WHERE wallet_address = ?
            ORDER BY timestamp DESC
            LIMIT 5
        """, (wallet,))
        rows = cursor.fetchall()
        conn.close()

        return [
            {'token_symbol': r[0], 'pnl_percent': r[1], 'tx_type': r[2]}
            for r in rows
        ]

    def _calculate_trade_pnl(self, wallet: str, trade: Dict) -> float:
        """Calculate PnL for a sell trade (simplified)."""
        # In production, track buy/sell prices properly
        return 0.0

    def _record_alert(self, wallet: str, token: Dict, alert_type: str):
        """Record an alert in the database."""
        conn = get_connection()
        conn.execute("""
            INSERT INTO alerts (
                wallet_address, token_address, token_symbol, alert_type, sent_at
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            wallet,
            token.get('address'),
            token.get('symbol'),
            alert_type,
            datetime.now().isoformat()
        ))
        conn.commit()
        conn.close()

    async def _run_daily_scheduler(self):
        """Run the daily pipeline scheduler."""
        while self.running:
            now = datetime.utcnow()

            # Calculate time until next midnight UTC
            tomorrow = now.replace(
                hour=REFRESH_HOUR_UTC,
                minute=0,
                second=0,
                microsecond=0
            )
            if now.hour >= REFRESH_HOUR_UTC:
                tomorrow = tomorrow.replace(day=now.day + 1)

            wait_seconds = (tomorrow - now).total_seconds()
            logger.info(f"Next pipeline run in {wait_seconds / 3600:.1f} hours")

            # Wait until midnight (check every hour to handle drift)
            while wait_seconds > 0 and self.running:
                sleep_time = min(3600, wait_seconds)
                await asyncio.sleep(sleep_time)
                wait_seconds -= sleep_time

            if self.running:
                logger.info("Starting scheduled pipeline run...")
                await self._run_pipeline()


def main():
    """Main entry point."""
    system = SoulWinnersSystem()

    # Handle graceful shutdown
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(system.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Run the system
    try:
        asyncio.run(system.start())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"System error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
