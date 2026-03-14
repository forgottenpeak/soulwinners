"""
Comprehensive Position Lifecycle Tracker

Tracks ALL metrics for ML training:
- Market structure (MC, liquidity, age)
- Momentum (volume, price velocity)
- Wallet confluence (insiders, elites, repeated buyers)
- Holder dynamics (growth, concentration, new wallets)
- Dev activity (sells, LP removal) - RUG DETECTION
- Volume patterns (acceleration, trends)

AI learns: "When insiders + elites buy early + holders growing +
           dev NOT selling + volume accelerating = RUNNER"
"""
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
import aiohttp
import asyncio

from database import get_connection

logger = logging.getLogger(__name__)


class ComprehensiveTracker:
    """
    Full lifecycle tracker with all ML features.
    """

    def __init__(self):
        self.dex_base_url = "https://api.dexscreener.com"

    async def fetch_comprehensive_metrics(
        self,
        token_address: str,
        session: aiohttp.ClientSession,
    ) -> Dict:
        """
        Fetch ALL metrics for a token in one call.

        Returns:
            Dict with mc, volume, holder data, etc.
        """
        try:
            url = f"{self.dex_base_url}/tokens/v1/solana/{token_address}"
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        pair = data[0]

                        # Extract all available metrics
                        volume = pair.get('volume', {})
                        txns = pair.get('txns', {})
                        price_change = pair.get('priceChange', {})
                        info = pair.get('info', {})

                        # Calculate buy/sell ratio from 1h txns
                        txns_h1 = txns.get('h1', {})
                        buys_h1 = int(txns_h1.get('buys', 0) or 0)
                        sells_h1 = int(txns_h1.get('sells', 0) or 0)
                        total_h1 = buys_h1 + sells_h1
                        buy_sell_ratio = buys_h1 / total_h1 if total_h1 > 0 else 0.5

                        # Volume acceleration
                        vol_5m = float(volume.get('m5', 0) or 0)
                        vol_1h = float(volume.get('h1', 0) or 0)
                        vol_24h = float(volume.get('h24', 0) or 0)
                        volume_acceleration = 0
                        if vol_1h > 0:
                            # Annualize 5m to compare to 1h
                            volume_acceleration = ((vol_5m * 12) - vol_1h) / vol_1h * 100

                        # Price velocity (1h change)
                        price_velocity = float(price_change.get('h1', 0) or 0)

                        return {
                            'current_mc': float(pair.get('marketCap', 0) or 0),
                            'liquidity': float(pair.get('liquidity', {}).get('usd', 0) or 0),
                            'volume_5m': vol_5m,
                            'volume_1h': vol_1h,
                            'volume_24h': vol_24h,
                            'volume_acceleration': volume_acceleration,
                            'price_velocity': price_velocity,
                            'buy_sell_ratio': buy_sell_ratio,
                            'holders': int(info.get('holders', 0) or 0),
                            'buys_1h': buys_h1,
                            'sells_1h': sells_h1,
                        }

        except Exception as e:
            logger.debug(f"Error fetching metrics for {token_address[:12]}...: {e}")

        return {
            'current_mc': 0,
            'liquidity': 0,
            'volume_5m': 0,
            'volume_1h': 0,
            'volume_24h': 0,
            'volume_acceleration': 0,
            'price_velocity': 0,
            'buy_sell_ratio': 0.5,
            'holders': 0,
            'buys_1h': 0,
            'sells_1h': 0,
        }

    def check_wallet_confluence(self, token_address: str) -> Dict:
        """
        Count how many elite/insider wallets are in this token.

        This is a CRITICAL signal - multiple smart wallets = high conviction.
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Get all tracked positions for this token
            cursor.execute("""
                SELECT wallet_address, wallet_type, wallet_tier
                FROM position_lifecycle
                WHERE token_address = ?
                AND created_at > datetime('now', '-24 hours')
            """, (token_address,))

            positions = cursor.fetchall()

            insider_count = 0
            elite_count = 0
            wallet_set = set()

            for wallet, w_type, w_tier in positions:
                wallet_set.add(wallet)
                if w_type == 'insider':
                    insider_count += 1
                if w_tier == 'Elite':
                    elite_count += 1

            # Check for repeated buyers (same wallet buying multiple times)
            cursor.execute("""
                SELECT wallet_address, COUNT(*) as buy_count
                FROM position_lifecycle
                WHERE token_address = ?
                GROUP BY wallet_address
                HAVING buy_count > 1
            """, (token_address,))

            repeated_buyers = len(cursor.fetchall())

            return {
                'insider_count': insider_count,
                'elite_count': elite_count,
                'unique_wallets': len(wallet_set),
                'repeated_buyers': repeated_buyers,
            }

        except Exception as e:
            logger.debug(f"Error checking confluence: {e}")
            return {
                'insider_count': 0,
                'elite_count': 0,
                'unique_wallets': 0,
                'repeated_buyers': 0,
            }

        finally:
            conn.close()

    def update_position_comprehensive(
        self,
        position_id: int,
        metrics: Dict,
        confluence: Dict,
        prev_holder_count: Optional[int] = None,
    ):
        """
        Update position with all comprehensive metrics.
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Calculate holder growth rate
            holder_growth = 0
            if prev_holder_count and prev_holder_count > 0:
                holder_growth = ((metrics['holders'] - prev_holder_count)
                                / prev_holder_count * 100)

            cursor.execute("""
                UPDATE position_lifecycle SET
                    current_mc = ?,
                    volume_5m = ?,
                    volume_1h = ?,
                    volume_24h = ?,
                    volume_acceleration = ?,
                    price_velocity = ?,
                    buy_sell_ratio = ?,
                    insider_wallet_count = ?,
                    elite_wallet_count = ?,
                    repeated_buyer_count = ?,
                    holder_count = ?,
                    holder_growth_rate = ?,
                    last_checked_timestamp = ?,
                    check_count = check_count + 1,
                    updated_at = ?
                WHERE id = ?
            """, (
                metrics['current_mc'],
                metrics['volume_5m'],
                metrics['volume_1h'],
                metrics['volume_24h'],
                metrics['volume_acceleration'],
                metrics['price_velocity'],
                metrics['buy_sell_ratio'],
                confluence['insider_count'],
                confluence['elite_count'],
                confluence['repeated_buyers'],
                metrics['holders'],
                holder_growth,
                int(time.time()),
                datetime.now().isoformat(),
                position_id,
            ))

            # Update peak MC if higher
            cursor.execute("""
                SELECT peak_mc, entry_timestamp FROM position_lifecycle WHERE id = ?
            """, (position_id,))
            row = cursor.fetchone()

            if row:
                peak_mc, entry_ts = row
                if metrics['current_mc'] > (peak_mc or 0):
                    now = int(time.time())
                    time_to_peak = (now - entry_ts) / 3600.0
                    cursor.execute("""
                        UPDATE position_lifecycle SET
                            peak_mc = ?,
                            peak_timestamp = ?,
                            time_to_peak_hours = ?
                        WHERE id = ?
                    """, (metrics['current_mc'], now, time_to_peak, position_id))

            conn.commit()

        except Exception as e:
            logger.warning(f"Error updating comprehensive metrics: {e}")

        finally:
            conn.close()

    def update_dev_tracking(
        self,
        position_id: int,
        dev_sold: bool,
        liquidity_removed: bool,
        dev_address: str = None,
    ):
        """
        Update dev wallet tracking - CRITICAL for rug detection!
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            now = int(time.time())

            updates = ["updated_at = ?"]
            params = [datetime.now().isoformat()]

            if dev_sold:
                updates.append("dev_sold = 1")
                updates.append("dev_sell_timestamp = ?")
                params.append(now)

            if liquidity_removed:
                updates.append("liquidity_removed = 1")
                updates.append("liquidity_removal_timestamp = ?")
                params.append(now)

            if dev_address:
                updates.append("dev_wallet_address = ?")
                params.append(dev_address)

            params.append(position_id)

            cursor.execute(f"""
                UPDATE position_lifecycle SET
                    {', '.join(updates)}
                WHERE id = ?
            """, params)

            conn.commit()

            if dev_sold or liquidity_removed:
                logger.warning(
                    f"🚨 RUG SIGNAL position {position_id}: "
                    f"dev_sold={dev_sold}, lp_removed={liquidity_removed}"
                )

        except Exception as e:
            logger.warning(f"Error updating dev tracking: {e}")

        finally:
            conn.close()


def get_comprehensive_tracker():
    """Get or create comprehensive tracker instance."""
    return ComprehensiveTracker()


# Stage to integer mapping for ML
STAGE_TO_INT = {
    'launch_volatile': 1,
    'launch_stable': 2,
    'consolidation': 3,
    'delayed_pump': 4,
    'slow_rug': 5,
    'instant_rug': 6,
    'stagnant': 7,
    'active': 8,
    'breakout_up': 9,
    'breakdown': 10,
}


# ML Feature extraction for training
def extract_ml_features(position_data: Dict) -> Dict:
    """
    Extract all features for ML training.

    Features are normalized and ready for XGBoost/LightGBM.
    Includes lifecycle stage features for pattern-aware predictions.
    """
    entry_mc = position_data.get('entry_mc', 0) or 1
    entry_liq = position_data.get('entry_liquidity', 0) or 1

    # Parse stage transitions for sequence features
    try:
        transitions = json.loads(position_data.get('stage_transitions') or '[]')
    except:
        transitions = []

    features = {
        # MARKET STRUCTURE
        'mc_to_liquidity_ratio': entry_mc / entry_liq,
        'token_age_normalized': (position_data.get('token_age_at_entry', 0) or 0) / 24,
        'liquidity_at_entry': position_data.get('entry_liquidity', 0),
        'entry_mc': entry_mc,

        # MOMENTUM
        'price_velocity': position_data.get('price_velocity', 0),
        'volume_acceleration': position_data.get('volume_acceleration', 0),
        'buy_sell_ratio': position_data.get('buy_sell_ratio', 0.5),

        # WALLET SIGNALS (CRITICAL!)
        'insider_wallet_count': position_data.get('insider_wallet_count', 0),
        'elite_wallet_count': position_data.get('elite_wallet_count', 0),
        'repeated_buyer_count': position_data.get('repeated_buyer_count', 0),
        'new_wallet_influx': position_data.get('new_wallet_influx', 0),

        # HOLDER DYNAMICS
        'holder_count': position_data.get('holder_count', 0),
        'holder_growth_rate': position_data.get('holder_growth_rate', 0),
        'top10_concentration': position_data.get('top10_concentration', 0),

        # DEV SIGNALS (RUG DETECTION!)
        'dev_sold': 1 if position_data.get('dev_sold') else 0,
        'liquidity_removed': 1 if position_data.get('liquidity_removed') else 0,

        # VOLUME
        'volume_24h': position_data.get('volume_24h', 0),
        'volume_trend': (
            position_data.get('volume_5m', 0) / position_data.get('volume_1h', 1)
            if position_data.get('volume_1h', 0) > 0 else 0
        ),

        # POSITION SIZE
        'buy_sol_amount': position_data.get('buy_sol_amount', 0),

        # WALLET TYPE (one-hot encoded)
        'is_insider': 1 if position_data.get('wallet_type') == 'insider' else 0,
        'is_elite': 1 if position_data.get('wallet_tier') == 'Elite' else 0,

        # LIFECYCLE STAGE FEATURES (CRITICAL for pattern recognition!)
        'current_stage': STAGE_TO_INT.get(position_data.get('lifecycle_stage', ''), 0),
        'stage_count': len(transitions),
        'had_consolidation': 1 if any(t.get('stage') == 'consolidation' for t in transitions) else 0,
        'consolidation_duration': position_data.get('consolidation_duration_hours', 0) or 0,
        'had_breakout': 1 if position_data.get('breakout_direction') in ('breakout_up', 'breakdown') else 0,
        'breakout_up': 1 if position_data.get('breakout_direction') == 'breakout_up' else 0,
        'breakdown': 1 if position_data.get('breakout_direction') == 'breakdown' else 0,

        # Time in current stage
        'time_since_last_transition': _calc_time_since_transition(transitions),
    }

    return features


def _calc_time_since_transition(transitions: list) -> float:
    """Calculate hours since last stage transition."""
    if not transitions:
        return 0
    last = transitions[-1]
    last_ts = last.get('timestamp', 0)
    if not last_ts:
        return 0
    return (time.time() - last_ts) / 3600


import json
import time
