"""
Lifecycle Stage Detector

Recognizes token behavior patterns over time:
- LAUNCH (0-2h): Initial pump, early volatility
- CONSOLIDATION (2-12h): Range-bound, accumulation phase
- DELAYED_PUMP (12-48h): Stagnant then sudden spike
- SLOW_RUG (12-48h): Gradual decline before dump
- INSTANT_RUG (any time): Dev sells, LP removed
- STAGNANT (6h+): No movement, volume dying

AI learns stage transition sequences to predict outcomes.
"""
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from database import get_connection

logger = logging.getLogger(__name__)


# Stage definitions
STAGES = {
    'launch_volatile': 'LAUNCH (volatile)',
    'launch_stable': 'LAUNCH (stable)',
    'consolidation': 'CONSOLIDATION',
    'delayed_pump': 'DELAYED PUMP',
    'slow_rug': 'SLOW RUG',
    'instant_rug': 'INSTANT RUG',
    'stagnant': 'STAGNANT',
    'active': 'ACTIVE',
    'breakout_up': 'BREAKOUT UP',
    'breakdown': 'BREAKDOWN',
}


class LifecycleStageDetector:
    """
    Detect which lifecycle stage a token is in based on price action.
    """

    # Thresholds
    LAUNCH_HOURS = 2
    CONSOLIDATION_RANGE_PCT = 20  # Within 20% range = consolidating
    MIN_CONSOLIDATION_CHECKS = 4  # Need 4+ hourly checks to confirm
    STAGNANT_HOURS = 6
    STAGNANT_CHANGE_PCT = 10  # <10% change = stagnant

    def __init__(self):
        pass

    def detect_stage(self, position: Dict) -> str:
        """
        Classify current lifecycle stage based on price action.

        Args:
            position: Position data with MC history

        Returns:
            Stage string identifier
        """
        entry_ts = position.get('entry_timestamp', 0)
        age_hours = (time.time() - entry_ts) / 3600 if entry_ts else 0

        current_mc = position.get('current_mc', 0) or 0
        entry_mc = position.get('entry_mc', 0) or 1
        peak_mc = position.get('peak_mc', 0) or current_mc

        # Price movement from entry
        price_change = ((current_mc - entry_mc) / entry_mc * 100) if entry_mc > 0 else 0

        # Drawdown from peak
        drawdown = ((current_mc - peak_mc) / peak_mc * 100) if peak_mc > 0 else 0

        # Volume trend
        volume_trend = self._get_volume_trend(position)

        # Dev activity (CRITICAL for rug detection)
        dev_sold = position.get('dev_sold', False)
        lp_removed = position.get('liquidity_removed', False)

        # ============================================================
        # STAGE DETECTION (order matters - check critical cases first)
        # ============================================================

        # INSTANT RUG - Dev sold or LP removed
        if dev_sold or lp_removed:
            return 'instant_rug'

        # LAUNCH PHASE (0-2 hours)
        if age_hours < self.LAUNCH_HOURS:
            if abs(price_change) > 50:  # +/-50% movement
                return 'launch_volatile'
            else:
                return 'launch_stable'

        # SLOW RUG - Gradual decline with dying volume
        if drawdown < -30 and volume_trend == 'decreasing':
            return 'slow_rug'

        # DELAYED PUMP - Was flat/down, now pumping with volume
        if age_hours > 6 and price_change > 100 and volume_trend == 'increasing':
            return 'delayed_pump'

        # CONSOLIDATION - Price range-bound
        if self._is_consolidating(position):
            return 'consolidation'

        # STAGNANT - No movement for 6+ hours
        if age_hours > self.STAGNANT_HOURS:
            if abs(price_change) < self.STAGNANT_CHANGE_PCT and volume_trend in ('flat', 'decreasing'):
                return 'stagnant'

        # ACTIVE - Default state (moving but not in defined pattern)
        return 'active'

    def _get_volume_trend(self, position: Dict) -> str:
        """
        Determine volume trend from metrics.

        Returns: 'increasing', 'decreasing', or 'flat'
        """
        vol_5m = position.get('volume_5m', 0) or 0
        vol_1h = position.get('volume_1h', 0) or 0
        vol_24h = position.get('volume_24h', 0) or 0

        if vol_1h == 0:
            return 'flat'

        # Compare 5m annualized to 1h
        vol_5m_annualized = vol_5m * 12
        change_pct = ((vol_5m_annualized - vol_1h) / vol_1h * 100) if vol_1h > 0 else 0

        if change_pct > 50:
            return 'increasing'
        elif change_pct < -30:
            return 'decreasing'
        else:
            return 'flat'

    def _is_consolidating(self, position: Dict) -> bool:
        """
        Check if price is range-bound for extended period.

        Updates consolidation metrics if true.
        """
        mc_history = self._get_mc_history(position)

        if len(mc_history) < self.MIN_CONSOLIDATION_CHECKS:
            return False

        # Use last 6 readings for consolidation check
        recent_history = mc_history[-6:]
        valid_mcs = [mc for mc in recent_history if mc and mc > 0]

        if len(valid_mcs) < 4:
            return False

        high = max(valid_mcs)
        low = min(valid_mcs)

        if low <= 0:
            return False

        # Range-bound if within threshold
        range_pct = ((high - low) / low * 100)

        if range_pct < self.CONSOLIDATION_RANGE_PCT:
            # Update consolidation tracking
            self._update_consolidation_metrics(
                position['id'],
                range_low=low,
                range_high=high,
                duration_hours=len(recent_history),
            )
            return True

        return False

    def _get_mc_history(self, position: Dict) -> List[float]:
        """
        Get MC history from stored JSON or build from current data.
        """
        try:
            history_json = position.get('mc_history')
            if history_json:
                return json.loads(history_json)
        except:
            pass

        # If no history, return current MC
        return [position.get('current_mc', 0)]

    def _update_consolidation_metrics(
        self,
        position_id: int,
        range_low: float,
        range_high: float,
        duration_hours: float,
    ):
        """Update consolidation tracking in database."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE position_lifecycle SET
                    consolidation_range_low = ?,
                    consolidation_range_high = ?,
                    consolidation_duration_hours = ?,
                    updated_at = ?
                WHERE id = ?
            """, (range_low, range_high, duration_hours,
                  datetime.now().isoformat(), position_id))
            conn.commit()
        except Exception as e:
            logger.debug(f"Error updating consolidation metrics: {e}")
        finally:
            conn.close()

    def detect_breakout(self, position: Dict, new_mc: float) -> Optional[str]:
        """
        Detect if token broke out of consolidation range.

        Args:
            position: Position with consolidation range data
            new_mc: Current market cap

        Returns:
            'breakout_up', 'breakdown', 'in_range', or None
        """
        range_high = position.get('consolidation_range_high')
        range_low = position.get('consolidation_range_low')

        if not range_high or not range_low:
            return None

        # Upward breakout (>10% above range)
        if new_mc > range_high * 1.1:
            return 'breakout_up'

        # Downward breakdown (>10% below range)
        if new_mc < range_low * 0.9:
            return 'breakdown'

        return 'in_range'

    def track_stage_transitions(
        self,
        position: Dict,
        new_stage: str,
    ) -> List[Dict]:
        """
        Track how token moves through stages.

        Records transitions with timestamps for pattern learning.

        Returns:
            Updated transitions list
        """
        # Load transition history
        try:
            transitions = json.loads(position.get('stage_transitions') or '[]')
        except:
            transitions = []

        entry_ts = position.get('entry_timestamp', 0)
        age_hours = (time.time() - entry_ts) / 3600 if entry_ts else 0

        # Add new transition if stage changed
        if not transitions or transitions[-1].get('stage') != new_stage:
            transitions.append({
                'stage': new_stage,
                'timestamp': int(time.time()),
                'mc': position.get('current_mc', 0),
                'age_hours': round(age_hours, 2),
            })

            # Save to database
            self._save_transitions(position['id'], transitions)

            logger.info(
                f"📊 Stage transition: Position {position['id']} -> {STAGES.get(new_stage, new_stage)} "
                f"at {age_hours:.1f}h"
            )

        return transitions

    def _save_transitions(self, position_id: int, transitions: List[Dict]):
        """Save transitions to database."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE position_lifecycle SET
                    stage_transitions = ?,
                    updated_at = ?
                WHERE id = ?
            """, (json.dumps(transitions), datetime.now().isoformat(), position_id))
            conn.commit()
        except Exception as e:
            logger.debug(f"Error saving transitions: {e}")
        finally:
            conn.close()

    def update_mc_history(self, position_id: int, current_mc: float, max_history: int = 48):
        """
        Append current MC to history (for consolidation detection).

        Keeps last 48 hourly readings.
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Get existing history
            cursor.execute("SELECT mc_history FROM position_lifecycle WHERE id = ?", (position_id,))
            row = cursor.fetchone()

            try:
                history = json.loads(row[0]) if row and row[0] else []
            except:
                history = []

            # Append new MC
            history.append(current_mc)

            # Trim to max size
            if len(history) > max_history:
                history = history[-max_history:]

            # Save
            cursor.execute("""
                UPDATE position_lifecycle SET
                    mc_history = ?,
                    updated_at = ?
                WHERE id = ?
            """, (json.dumps(history), datetime.now().isoformat(), position_id))
            conn.commit()

        except Exception as e:
            logger.debug(f"Error updating MC history: {e}")
        finally:
            conn.close()

    def update_position_stage(
        self,
        position_id: int,
        stage: str,
        breakout: Optional[str] = None,
    ):
        """Update position stage in database."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE position_lifecycle SET
                    lifecycle_stage = ?,
                    breakout_direction = ?,
                    updated_at = ?
                WHERE id = ?
            """, (stage, breakout, datetime.now().isoformat(), position_id))
            conn.commit()
        except Exception as e:
            logger.debug(f"Error updating stage: {e}")
        finally:
            conn.close()


def get_stage_detector() -> LifecycleStageDetector:
    """Get stage detector instance."""
    return LifecycleStageDetector()


# ============================================================
# STAGE SEQUENCE ANALYSIS (for Pattern Memory)
# ============================================================

def analyze_stage_sequence(transitions: List[Dict]) -> Dict:
    """
    Analyze a sequence of stage transitions.

    Used for pattern matching and outcome prediction.
    """
    if not transitions:
        return {'sequence': '', 'duration_hours': 0}

    # Extract stage sequence
    stages = [t['stage'] for t in transitions]
    sequence = ' → '.join(stages)

    # Calculate durations
    total_duration = 0
    stage_durations = {}

    for i, t in enumerate(transitions):
        if i + 1 < len(transitions):
            duration = (transitions[i + 1]['timestamp'] - t['timestamp']) / 3600
        else:
            duration = 0

        stage = t['stage']
        stage_durations[stage] = stage_durations.get(stage, 0) + duration
        total_duration += duration

    return {
        'sequence': sequence,
        'stages': stages,
        'stage_count': len(stages),
        'total_duration_hours': round(total_duration, 2),
        'stage_durations': stage_durations,
        'had_consolidation': 'consolidation' in stages,
        'had_breakout': 'breakout_up' in stages or 'breakdown' in stages,
    }


def get_common_sequences(min_occurrences: int = 5) -> List[Dict]:
    """
    Find common stage sequences and their outcomes.

    Returns patterns like:
    "launch_stable → consolidation → breakout_up" → 70% runner
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT stage_transitions, outcome, final_roi_percent
            FROM position_lifecycle
            WHERE outcome IS NOT NULL
            AND outcome != 'open'
            AND stage_transitions IS NOT NULL
        """)

        rows = cursor.fetchall()

        # Group by sequence
        sequences = {}
        for transitions_json, outcome, roi in rows:
            try:
                transitions = json.loads(transitions_json)
                analysis = analyze_stage_sequence(transitions)
                seq = analysis['sequence']

                if seq not in sequences:
                    sequences[seq] = {
                        'sequence': seq,
                        'outcomes': {'runner': 0, 'rug': 0, 'sideways': 0},
                        'total': 0,
                        'rois': [],
                    }

                sequences[seq]['outcomes'][outcome] += 1
                sequences[seq]['total'] += 1
                if roi is not None:
                    sequences[seq]['rois'].append(roi)

            except:
                continue

        # Filter to common sequences
        common = []
        for seq, data in sequences.items():
            if data['total'] >= min_occurrences:
                total = data['total']
                data['runner_pct'] = data['outcomes']['runner'] / total * 100
                data['rug_pct'] = data['outcomes']['rug'] / total * 100
                data['sideways_pct'] = data['outcomes']['sideways'] / total * 100
                data['avg_roi'] = sum(data['rois']) / len(data['rois']) if data['rois'] else 0
                common.append(data)

        # Sort by occurrence count
        common.sort(key=lambda x: x['total'], reverse=True)

        return common

    except Exception as e:
        logger.warning(f"Error getting common sequences: {e}")
        return []

    finally:
        conn.close()


def format_stage_for_ai(position: Dict, transitions: List[Dict]) -> str:
    """
    Format stage info for Claude AI context.
    """
    stage = position.get('lifecycle_stage', 'unknown')
    stage_name = STAGES.get(stage, stage)

    analysis = analyze_stage_sequence(transitions)

    entry_ts = position.get('entry_timestamp', 0)
    age_hours = (time.time() - entry_ts) / 3600 if entry_ts else 0

    context = f"""
TOKEN LIFECYCLE STAGE:

Current: {stage_name}
Token age: {age_hours:.1f} hours

Transition history:
{analysis['sequence']}

Stage durations:
"""
    for stage, duration in analysis.get('stage_durations', {}).items():
        context += f"  - {STAGES.get(stage, stage)}: {duration:.1f}h\n"

    # Add consolidation info if applicable
    if position.get('consolidation_range_high'):
        range_low = position.get('consolidation_range_low', 0)
        range_high = position.get('consolidation_range_high', 0)
        duration = position.get('consolidation_duration_hours', 0)
        context += f"""
CONSOLIDATION DETECTED:
  Range: ${range_low:,.0f} - ${range_high:,.0f}
  Duration: {duration:.1f} hours
  Breakout: {position.get('breakout_direction', 'none')}
"""

    return context
