"""
Auto-Trader Module for V3 Edge

Executes trades based on AI predictions with Telegram confirmation.

Features:
- Semi-autonomous mode: Telegram confirmation before execution
- Full-auto mode: Execute approved trades immediately
- Position sizing based on AI confidence
- Integration with Jupiter for swaps
"""
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, Tuple
from enum import Enum

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_USER_ID
from ml.predictor import LivePredictor, get_predictor

# AI Advisor for Claude supervision (optional)
try:
    from ml.ai_advisor import AIAdvisor, get_ai_advisor
    HAS_AI_ADVISOR = True
except ImportError:
    HAS_AI_ADVISOR = False
    AIAdvisor = None
    get_ai_advisor = None

logger = logging.getLogger(__name__)


class TradeMode(Enum):
    """Trading mode configuration."""
    DISABLED = "disabled"           # No auto-trading
    SEMI_AUTO = "semi_auto"         # Telegram confirmation required
    FULL_AUTO = "full_auto"         # Execute immediately (dangerous!)


class TradeStatus(Enum):
    """Trade execution status."""
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    EXECUTED = "executed"
    REJECTED = "rejected"
    FAILED = "failed"
    EXPIRED = "expired"


class AutoTrader:
    """
    Semi-autonomous trading bot.

    Flow:
    1. Receive signal from realtime_bot
    2. Run AI prediction
    3. If approved, send Telegram confirmation
    4. Wait for user confirmation (or auto-execute if full-auto)
    5. Execute trade via Jupiter
    6. Track position for exit
    """

    # Confirmation timeout (minutes)
    CONFIRMATION_TIMEOUT_MIN = 5

    def __init__(self, user_id: int = None):
        self.user_id = user_id or TELEGRAM_USER_ID
        self.bot = Bot(token=TELEGRAM_BOT_TOKEN)
        self.predictor = get_predictor()

        # Load settings
        self.mode = TradeMode.DISABLED
        self.max_position_sol = 0.5
        self.daily_trade_limit = 10
        self.require_confirmation = True

        self._load_settings()

    def _load_settings(self):
        """Load auto-trader settings from database."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT key, value FROM settings
                WHERE key LIKE 'autotrader_%'
            """)

            for key, value in cursor.fetchall():
                if key == "autotrader_enabled":
                    if value == "true":
                        self.mode = TradeMode.SEMI_AUTO
                    else:
                        self.mode = TradeMode.DISABLED
                elif key == "autotrader_max_position_sol":
                    self.max_position_sol = float(value)
                elif key == "autotrader_daily_trade_limit":
                    self.daily_trade_limit = int(value)
                elif key == "autotrader_require_confirmation":
                    self.require_confirmation = value == "true"

        except Exception as e:
            logger.warning(f"Could not load settings: {e}")
        finally:
            conn.close()

    def is_enabled(self) -> bool:
        """Check if auto-trading is enabled."""
        return self.mode != TradeMode.DISABLED

    def _is_ai_supervision_enabled(self) -> bool:
        """Check if Claude AI supervision is enabled."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'ai_advisor_enabled'")
            row = cursor.fetchone()
            conn.close()
            return row[0] == 'true' if row else False
        except:
            return False

    def _get_recent_model_performance(self) -> Dict:
        """Get recent model performance for AI supervision context."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Get last 10 AI decisions with outcomes
            cursor.execute("""
                SELECT d.decision, d.prob_runner, t.pnl_percent
                FROM ai_decisions d
                LEFT JOIN auto_trades t ON d.id = t.ai_decision_id
                WHERE d.decision = 'approve'
                AND t.pnl_percent IS NOT NULL
                ORDER BY d.created_at DESC
                LIMIT 10
            """)

            rows = cursor.fetchall()
            conn.close()

            if not rows:
                return {"accuracy_10": 0.5, "roi_10": 0}

            # Calculate accuracy (did runner prediction come true?)
            correct = sum(1 for _, prob, pnl in rows if (prob > 0.5 and pnl > 0) or (prob <= 0.5 and pnl <= 0))
            total_roi = sum(pnl or 0 for _, _, pnl in rows)

            return {
                "accuracy_10": correct / len(rows),
                "roi_10": total_roi,
                "trades_10": len(rows),
            }

        except Exception as e:
            logger.debug(f"Could not get model performance: {e}")
            return {"accuracy_10": 0.5, "roi_10": 0}

    def get_daily_trade_count(self) -> int:
        """Get number of trades executed today."""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM auto_trades
            WHERE user_id = ?
            AND DATE(created_at) = DATE('now')
            AND status IN ('executed', 'pending_confirmation', 'confirmed')
        """, (self.user_id,))

        count = cursor.fetchone()[0]
        conn.close()

        return count

    async def process_signal(
        self,
        wallet_data: Dict,
        token_data: Dict,
        parsed_tx: Dict,
    ) -> Optional[Dict]:
        """
        Process an incoming trade signal.

        Args:
            wallet_data: Qualified wallet info
            token_data: Token info from DexScreener
            parsed_tx: Parsed transaction data

        Returns:
            Trade record if approved, None otherwise
        """
        if not self.is_enabled():
            logger.debug("Auto-trader disabled, skipping signal")
            return None

        # Check daily limit
        daily_count = self.get_daily_trade_count()
        if daily_count >= self.daily_trade_limit:
            logger.info(f"Daily trade limit reached ({daily_count}/{self.daily_trade_limit})")
            return None

        # Get XGBoost prediction
        prediction = self.predictor.predict(wallet_data, token_data, parsed_tx)

        # Log decision
        self.predictor.log_decision(
            wallet_address=wallet_data.get("wallet_address", ""),
            token_address=parsed_tx.get("token_address", ""),
            prediction=prediction,
        )

        # Check if XGBoost approved
        if prediction["decision"] != "approve":
            logger.info(f"XGBoost rejected: {prediction['decision_reason']}")
            return None

        # =====================================================================
        # CLAUDE AI SUPERVISION (if enabled and available)
        # =====================================================================
        if HAS_AI_ADVISOR and self._is_ai_supervision_enabled():
            try:
                advisor = get_ai_advisor()
                if advisor.is_available():
                    # Get recent model performance for context
                    recent_performance = self._get_recent_model_performance()

                    # Have Claude supervise the XGBoost decision
                    approved, reason = await advisor.supervise_xgboost_decision(
                        user_id=self.user_id,
                        prediction=prediction,
                        token_data=token_data,
                        recent_performance=recent_performance,
                    )

                    if not approved:
                        logger.info(f"Claude overrode XGBoost: {reason}")
                        return None

                    logger.info(f"Claude approved: {reason}")

                    # Generate trade explanation for confirmation message
                    prediction["claude_explanation"] = await advisor.explain_trade_decision(
                        user_id=self.user_id,
                        token_data=token_data,
                        prediction=prediction,
                        wallet_data=wallet_data,
                    )

            except Exception as e:
                logger.warning(f"Claude supervision failed (continuing with XGBoost): {e}")

        # Calculate position size
        position_sol = self._calculate_position(prediction)

        # Create trade record
        trade = self._create_trade_record(
            wallet_data=wallet_data,
            token_data=token_data,
            parsed_tx=parsed_tx,
            prediction=prediction,
            position_sol=position_sol,
        )

        # Handle based on mode
        if self.require_confirmation:
            await self._send_confirmation_request(trade, prediction, token_data)
            trade["status"] = TradeStatus.PENDING_CONFIRMATION.value
        else:
            # Full auto mode - execute immediately
            trade = await self._execute_trade(trade)

        # Save trade record
        self._save_trade_record(trade)

        return trade

    def _calculate_position(self, prediction: Dict) -> float:
        """Calculate position size in SOL based on confidence."""
        position_pct = prediction["position_size_pct"]
        position_sol = self.max_position_sol * position_pct

        # Round to 2 decimal places
        return round(position_sol, 2)

    def _create_trade_record(
        self,
        wallet_data: Dict,
        token_data: Dict,
        parsed_tx: Dict,
        prediction: Dict,
        position_sol: float,
    ) -> Dict:
        """Create trade record dict."""
        return {
            "user_id": self.user_id,
            "wallet_address": wallet_data.get("wallet_address", ""),
            "token_address": parsed_tx.get("token_address", ""),
            "token_symbol": token_data.get("symbol", "???"),
            "trade_type": "buy",
            "sol_amount": position_sol,
            "prediction": prediction,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
        }

    async def _send_confirmation_request(
        self,
        trade: Dict,
        prediction: Dict,
        token_data: Dict,
    ):
        """Send Telegram confirmation request to user."""
        token_symbol = trade["token_symbol"]
        token_address = trade["token_address"]
        wallet_address = trade["wallet_address"]
        sol_amount = trade["sol_amount"]

        prob_runner = prediction["prob_runner"]
        prob_rug = prediction["prob_rug"]
        expected_roi = prediction["expected_roi"]
        confidence = prediction["confidence"]

        # Format message
        message = f"""🤖 **AUTO-TRADE REQUEST**

🪙 Token: **${token_symbol}**
📍 CA: `{token_address[:20]}...`

📊 **AI Analysis:**
├─ 🚀 Runner Prob: **{prob_runner:.0%}**
├─ ⚠️ Rug Prob: {prob_rug:.0%}
├─ 📈 Expected ROI: {expected_roi:+.0f}%
└─ 🎯 Confidence: {confidence:.0%}

💰 **Proposed Trade:**
├─ Amount: **{sol_amount} SOL**
└─ Wallet: `{wallet_address[:8]}...{wallet_address[-6:]}`

📊 **Token Stats:**
├─ MC: ${token_data.get('market_cap', 0)/1000:.0f}K
├─ Liq: ${token_data.get('liquidity', 0)/1000:.0f}K
└─ Age: {token_data.get('token_age_hours', 0):.1f}h

⏰ _Expires in {self.CONFIRMATION_TIMEOUT_MIN} minutes_"""

        # Add Claude's explanation if available
        claude_explanation = prediction.get("claude_explanation")
        if claude_explanation:
            message += f"\n\n🧠 **AI Reasoning:**\n_{claude_explanation}_"

        # Buttons
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Execute", callback_data=f"trade_confirm_{token_address}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"trade_reject_{token_address}"),
            ],
            [
                InlineKeyboardButton("🔄 Adjust Amount", callback_data=f"trade_adjust_{token_address}"),
            ]
        ])

        try:
            sent_msg = await self.bot.send_message(
                chat_id=self.user_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )

            # Store message ID for tracking
            trade["confirmation_msg_id"] = sent_msg.message_id

            logger.info(f"Sent confirmation request for ${token_symbol}")

        except Exception as e:
            logger.error(f"Failed to send confirmation: {e}")

    async def _execute_trade(self, trade: Dict) -> Dict:
        """
        Execute the trade via Jupiter.

        Returns updated trade record with execution details.
        """
        token_address = trade["token_address"]
        sol_amount = trade["sol_amount"]

        logger.info(f"Executing trade: {sol_amount} SOL -> {trade['token_symbol']}")

        try:
            # Import Jupiter integration
            from trader.solana_dex import JupiterSwap

            jupiter = JupiterSwap()

            # Execute swap
            result = await jupiter.swap_sol_to_token(
                token_address=token_address,
                sol_amount=sol_amount,
            )

            if result["success"]:
                trade["status"] = TradeStatus.EXECUTED.value
                trade["tx_signature"] = result["signature"]
                trade["execution_price"] = result.get("price", 0)
                trade["token_amount"] = result.get("token_amount", 0)
                trade["execution_time"] = datetime.now().isoformat()

                logger.info(f"Trade executed: {result['signature']}")
            else:
                trade["status"] = TradeStatus.FAILED.value
                trade["error"] = result.get("error", "Unknown error")

                logger.error(f"Trade failed: {trade['error']}")

        except ImportError:
            logger.warning("Jupiter integration not available")
            trade["status"] = TradeStatus.FAILED.value
            trade["error"] = "Jupiter integration not available"

        except Exception as e:
            trade["status"] = TradeStatus.FAILED.value
            trade["error"] = str(e)
            logger.error(f"Trade execution error: {e}")

        return trade

    def _save_trade_record(self, trade: Dict):
        """Save trade record to database."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO auto_trades
                (user_id, wallet_address, token_address, token_symbol,
                 trade_type, sol_amount, status, telegram_confirmation_msg_id,
                 tx_signature, execution_price, execution_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade["user_id"],
                trade["wallet_address"],
                trade["token_address"],
                trade["token_symbol"],
                trade["trade_type"],
                trade["sol_amount"],
                trade["status"],
                trade.get("confirmation_msg_id"),
                trade.get("tx_signature"),
                trade.get("execution_price"),
                trade.get("execution_time"),
                trade["created_at"],
            ))
            conn.commit()

            trade["id"] = cursor.lastrowid

        except Exception as e:
            logger.error(f"Failed to save trade: {e}")
        finally:
            conn.close()

    async def handle_confirmation(
        self,
        token_address: str,
        confirmed: bool,
        adjust_amount: float = None,
    ) -> Dict:
        """
        Handle user confirmation/rejection of trade.

        Called from Telegram callback handler.
        """
        conn = get_connection()
        cursor = conn.cursor()

        # Find pending trade
        cursor.execute("""
            SELECT id, user_id, wallet_address, token_address, token_symbol,
                   sol_amount, status
            FROM auto_trades
            WHERE token_address = ?
            AND status = 'pending_confirmation'
            ORDER BY created_at DESC
            LIMIT 1
        """, (token_address,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return {"error": "No pending trade found"}

        trade = {
            "id": row[0],
            "user_id": row[1],
            "wallet_address": row[2],
            "token_address": row[3],
            "token_symbol": row[4],
            "sol_amount": row[5],
            "status": row[6],
        }

        if adjust_amount:
            trade["sol_amount"] = adjust_amount

        if confirmed:
            # Execute the trade
            trade["status"] = TradeStatus.CONFIRMED.value
            trade["confirmed_at"] = datetime.now().isoformat()
            trade = await self._execute_trade(trade)
        else:
            trade["status"] = TradeStatus.REJECTED.value

        # Update database
        self._update_trade_status(trade)

        return trade

    def _update_trade_status(self, trade: Dict):
        """Update trade status in database."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE auto_trades
                SET status = ?,
                    confirmed_at = ?,
                    tx_signature = ?,
                    execution_price = ?,
                    execution_time = ?,
                    sol_amount = ?
                WHERE id = ?
            """, (
                trade["status"],
                trade.get("confirmed_at"),
                trade.get("tx_signature"),
                trade.get("execution_price"),
                trade.get("execution_time"),
                trade["sol_amount"],
                trade["id"],
            ))
            conn.commit()

        except Exception as e:
            logger.error(f"Failed to update trade: {e}")
        finally:
            conn.close()

    async def cleanup_expired_trades(self):
        """Mark expired confirmation requests."""
        conn = get_connection()
        cursor = conn.cursor()

        # Find trades pending confirmation for > timeout
        cursor.execute(f"""
            UPDATE auto_trades
            SET status = 'expired'
            WHERE status = 'pending_confirmation'
            AND datetime(created_at) < datetime('now', '-{self.CONFIRMATION_TIMEOUT_MIN} minutes')
        """)

        expired_count = cursor.rowcount
        conn.commit()
        conn.close()

        if expired_count > 0:
            logger.info(f"Marked {expired_count} trades as expired")

    def get_pending_trades(self) -> list:
        """Get all pending confirmation trades."""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, token_address, token_symbol, sol_amount, created_at
            FROM auto_trades
            WHERE user_id = ?
            AND status = 'pending_confirmation'
            ORDER BY created_at DESC
        """, (self.user_id,))

        trades = []
        for row in cursor.fetchall():
            trades.append({
                "id": row[0],
                "token_address": row[1],
                "token_symbol": row[2],
                "sol_amount": row[3],
                "created_at": row[4],
            })

        conn.close()
        return trades

    def get_today_stats(self) -> Dict:
        """Get today's trading statistics."""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'executed' THEN 1 ELSE 0 END) as executed,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'executed' THEN sol_amount ELSE 0 END) as total_sol,
                SUM(CASE WHEN status = 'executed' THEN pnl_sol ELSE 0 END) as total_pnl
            FROM auto_trades
            WHERE user_id = ?
            AND DATE(created_at) = DATE('now')
        """, (self.user_id,))

        row = cursor.fetchone()
        conn.close()

        return {
            "total_signals": row[0] or 0,
            "executed": row[1] or 0,
            "rejected": row[2] or 0,
            "failed": row[3] or 0,
            "total_sol_deployed": row[4] or 0,
            "total_pnl_sol": row[5] or 0,
            "remaining_limit": self.daily_trade_limit - (row[0] or 0),
        }


# Singleton instance
_auto_trader: Optional[AutoTrader] = None


def get_auto_trader(user_id: int = None) -> AutoTrader:
    """Get or create auto-trader instance."""
    global _auto_trader
    if _auto_trader is None or (user_id and _auto_trader.user_id != user_id):
        _auto_trader = AutoTrader(user_id)
    return _auto_trader


async def process_trade_signal(
    wallet_data: Dict,
    token_data: Dict,
    parsed_tx: Dict,
    user_id: int = None,
) -> Optional[Dict]:
    """
    Convenience function to process a trade signal.

    Called from realtime_bot.py when AI gate passes.
    """
    trader = get_auto_trader(user_id)
    return await trader.process_signal(wallet_data, token_data, parsed_tx)


if __name__ == "__main__":
    # Test auto-trader
    import logging
    logging.basicConfig(level=logging.INFO)

    trader = AutoTrader()

    print(f"Auto-trader mode: {trader.mode.value}")
    print(f"Max position: {trader.max_position_sol} SOL")
    print(f"Daily limit: {trader.daily_trade_limit}")
    print(f"Require confirmation: {trader.require_confirmation}")

    # Get today's stats
    stats = trader.get_today_stats()
    print(f"\nToday's stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
