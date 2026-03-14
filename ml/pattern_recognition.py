"""
Pattern Memory & Recognition for AI Trading

Clusters similar token setups and tracks their historical outcomes.
Enables AI to say: "I've seen 73 tokens like this - 68% rugged, 18% ran"

After 30+ days of tracking, this provides CRITICAL context for AI decisions.
"""
import logging
from typing import Dict, List, Optional
from database import get_connection

logger = logging.getLogger(__name__)


class PatternMemory:
    """
    Clusters similar token setups and tracks their outcomes.

    Provides historical context for AI decision making.
    """

    # Bucket thresholds for pattern fingerprinting
    TOKEN_AGE_BUCKETS = [0, 2, 6, 24, 168]  # hours: ultra-early, early, day, week+
    MC_BUCKETS = [0, 10000, 50000, 200000, 1000000]  # MC at entry
    LIQUIDITY_BUCKETS = [0, 5000, 20000, 100000, 500000]
    INSIDER_BUCKETS = [0, 2, 5, 10, 20]
    ELITE_BUCKETS = [0, 1, 3, 5, 10]
    HOLDER_BUCKETS = [0, 50, 200, 500, 1000]

    def __init__(self):
        pass

    def _bucket(self, value: float, thresholds: List[float]) -> int:
        """Put value into bucket for pattern matching."""
        if value is None:
            return 0
        for i, threshold in enumerate(thresholds):
            if value < threshold:
                return i
        return len(thresholds)

    def create_pattern_signature(self, position_data: Dict) -> Dict:
        """
        Generate fingerprint of token setup.

        Two positions with the same signature are "similar patterns".
        """
        return {
            'token_age_bucket': self._bucket(
                position_data.get('token_age_at_entry', 0),
                self.TOKEN_AGE_BUCKETS
            ),
            'mc_bucket': self._bucket(
                position_data.get('entry_mc', 0),
                self.MC_BUCKETS
            ),
            'liquidity_bucket': self._bucket(
                position_data.get('entry_liquidity', 0),
                self.LIQUIDITY_BUCKETS
            ),
            'insider_count_bucket': self._bucket(
                position_data.get('insider_wallet_count', 0),
                self.INSIDER_BUCKETS
            ),
            'elite_count_bucket': self._bucket(
                position_data.get('elite_wallet_count', 0),
                self.ELITE_BUCKETS
            ),
            'holder_bucket': self._bucket(
                position_data.get('holder_count', 0),
                self.HOLDER_BUCKETS
            ),
            'dev_sold': 1 if position_data.get('dev_sold') else 0,
            'lp_removed': 1 if position_data.get('liquidity_removed') else 0,
        }

    def signature_to_string(self, sig: Dict) -> str:
        """Convert signature to string for SQL matching."""
        return f"{sig['token_age_bucket']}_{sig['mc_bucket']}_{sig['liquidity_bucket']}_{sig['insider_count_bucket']}_{sig['elite_count_bucket']}_{sig['holder_bucket']}_{sig['dev_sold']}_{sig['lp_removed']}"

    def find_similar_patterns(
        self,
        new_position: Dict,
        min_matches: int = 5,
    ) -> Optional[Dict]:
        """
        Find all historical positions matching this pattern.

        Args:
            new_position: Position data to match
            min_matches: Minimum similar patterns required

        Returns:
            Dict with outcome distribution and confidence
        """
        new_sig = self.create_pattern_signature(new_position)

        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Build query to find similar patterns
            # Match on key buckets (relaxed matching for more results)
            cursor.execute("""
                SELECT
                    id, outcome, final_roi_percent,
                    token_age_at_entry, entry_mc, entry_liquidity,
                    insider_wallet_count, elite_wallet_count,
                    dev_sold, liquidity_removed
                FROM position_lifecycle
                WHERE outcome IS NOT NULL
                AND outcome != 'open'
            """)

            all_positions = cursor.fetchall()

            # Filter to similar patterns
            matches = []
            for row in all_positions:
                pos_data = {
                    'id': row[0],
                    'outcome': row[1],
                    'final_roi_percent': row[2],
                    'token_age_at_entry': row[3],
                    'entry_mc': row[4],
                    'entry_liquidity': row[5],
                    'insider_wallet_count': row[6],
                    'elite_wallet_count': row[7],
                    'dev_sold': row[8],
                    'liquidity_removed': row[9],
                }

                pos_sig = self.create_pattern_signature(pos_data)

                # Count matching buckets (out of 8)
                match_score = 0
                if pos_sig['token_age_bucket'] == new_sig['token_age_bucket']:
                    match_score += 2  # Weight age heavily
                if pos_sig['mc_bucket'] == new_sig['mc_bucket']:
                    match_score += 1
                if pos_sig['insider_count_bucket'] == new_sig['insider_count_bucket']:
                    match_score += 2  # Weight confluence heavily
                if pos_sig['elite_count_bucket'] == new_sig['elite_count_bucket']:
                    match_score += 1
                if pos_sig['dev_sold'] == new_sig['dev_sold']:
                    match_score += 2  # Weight dev behavior heavily
                if pos_sig['lp_removed'] == new_sig['lp_removed']:
                    match_score += 2

                # Require at least 6/10 matching (60% similarity)
                if match_score >= 6:
                    matches.append({
                        'outcome': pos_data['outcome'],
                        'roi': pos_data['final_roi_percent'],
                        'match_score': match_score,
                    })

            if len(matches) < min_matches:
                return None

            # Calculate outcome distribution
            outcomes = {'runner': 0, 'rug': 0, 'sideways': 0}
            rois = {'runner': [], 'rug': [], 'sideways': []}

            for m in matches:
                outcome = m['outcome']
                outcomes[outcome] += 1
                if m['roi'] is not None:
                    rois[outcome].append(m['roi'])

            total = sum(outcomes.values())

            # Calculate average ROI per outcome
            avg_rois = {}
            for outcome in rois:
                if rois[outcome]:
                    avg_rois[outcome] = sum(rois[outcome]) / len(rois[outcome])
                else:
                    avg_rois[outcome] = 0

            return {
                'total_matches': total,
                'runner_prob': outcomes['runner'] / total * 100,
                'rug_prob': outcomes['rug'] / total * 100,
                'sideways_prob': outcomes['sideways'] / total * 100,
                'runner_count': outcomes['runner'],
                'rug_count': outcomes['rug'],
                'sideways_count': outcomes['sideways'],
                'avg_runner_roi': avg_rois['runner'],
                'avg_rug_roi': avg_rois['rug'],
                'confidence': min(total / 20, 1.0),  # Max confidence at 20+ matches
                'pattern_signature': self.signature_to_string(new_sig),
            }

        except Exception as e:
            logger.warning(f"Error finding similar patterns: {e}")
            return None

        finally:
            conn.close()

    def get_pattern_description(self, position_data: Dict) -> str:
        """
        Generate human-readable pattern description.
        """
        age = position_data.get('token_age_at_entry', 0)
        mc = position_data.get('entry_mc', 0)
        insiders = position_data.get('insider_wallet_count', 0)
        elites = position_data.get('elite_wallet_count', 0)
        dev_sold = position_data.get('dev_sold', False)

        # Age description
        if age < 2:
            age_desc = "ultra-early (<2h)"
        elif age < 6:
            age_desc = "early (2-6h)"
        elif age < 24:
            age_desc = "day-old"
        else:
            age_desc = "established (>24h)"

        # MC description
        if mc < 10000:
            mc_desc = "micro-cap (<$10K)"
        elif mc < 50000:
            mc_desc = "small-cap ($10-50K)"
        elif mc < 200000:
            mc_desc = "mid-cap ($50-200K)"
        else:
            mc_desc = "large-cap (>$200K)"

        # Confluence description
        if insiders >= 5 and elites >= 3:
            confluence = "🔥 HIGH confluence"
        elif insiders >= 3 or elites >= 2:
            confluence = "👥 Moderate confluence"
        else:
            confluence = "👤 Low confluence"

        # Dev behavior
        dev_desc = "🚩 DEV SOLD" if dev_sold else "✅ Dev holding"

        return f"""
Pattern: {age_desc} | {mc_desc}
{confluence}: {insiders} insiders + {elites} elites
{dev_desc}
"""

    def format_ai_context(
        self,
        position_data: Dict,
        similar: Optional[Dict],
    ) -> str:
        """
        Format pattern analysis for Claude AI context injection.
        """
        pattern_desc = self.get_pattern_description(position_data)

        if similar and similar['total_matches'] >= 5:
            context = f"""
HISTORICAL PATTERN ANALYSIS:
{pattern_desc}
I've seen {similar['total_matches']} tokens with this exact pattern before:

Outcome distribution:
- 🚀 {similar['runner_prob']:.1f}% became runners ({similar['runner_count']} tokens)
- 💀 {similar['rug_prob']:.1f}% rugged ({similar['rug_count']} tokens)
- 📊 {similar['sideways_prob']:.1f}% went sideways ({similar['sideways_count']} tokens)

Average ROI by outcome:
- Runners averaged: {similar['avg_runner_roi']:+.0f}%
- Rugs averaged: {similar['avg_rug_roi']:+.0f}%

Pattern confidence: {similar['confidence']*100:.0f}%
"""
        else:
            context = f"""
HISTORICAL PATTERN ANALYSIS:
{pattern_desc}
⚠️ This is a NEW pattern - insufficient historical data.
(Less than 5 similar setups in database)

Recommendation: Exercise caution - no pattern precedent.
"""

        return context


def get_pattern_memory() -> PatternMemory:
    """Get pattern memory instance."""
    return PatternMemory()
