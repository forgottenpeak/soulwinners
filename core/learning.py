"""
Hedgehog Learning System
Pattern recognition and performance optimization for trading
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from config import MEMORY_DIR


class PatternLearner:
    """
    Learning system that tracks trade outcomes and identifies patterns

    Responsibilities:
    - Track trade outcomes (entry, exit, ROI, ML confidence)
    - Analyze wallet performance and auto-tier wallets
    - Optimize ML thresholds for max profit
    - Identify winning patterns
    """

    def __init__(self):
        self.memory_dir = MEMORY_DIR
        self.memory_dir.mkdir(exist_ok=True)

        # Data files
        self.trade_history_path = self.memory_dir / "trade_history.json"
        self.wallet_rankings_path = self.memory_dir / "wallet_rankings.json"
        self.ml_performance_path = self.memory_dir / "ml_performance.json"
        self.learned_patterns_path = self.memory_dir / "learned_patterns.json"

        # Load data
        self.trade_history = self._load_json(self.trade_history_path, [])
        self.wallet_rankings = self._load_json(self.wallet_rankings_path, {})
        self.ml_performance = self._load_json(self.ml_performance_path, {"predictions": []})
        self.learned_patterns = self._load_json(self.learned_patterns_path, {"patterns": []})

    def _load_json(self, path: Path, default: Any) -> Any:
        """Load JSON file or return default"""
        if path.exists():
            try:
                return json.loads(path.read_text())
            except json.JSONDecodeError:
                return default
        return default

    def _save_json(self, path: Path, data: Any):
        """Save data to JSON file"""
        path.write_text(json.dumps(data, indent=2, default=str))

    # =========================================================================
    # TRADE OUTCOME TRACKING
    # =========================================================================

    def record_trade(
        self,
        token_address: str,
        entry_price: float,
        amount_sol: float,
        wallet_source: str = None,
        ml_confidence: float = None,
        trade_type: str = "buy",
    ) -> Dict:
        """
        Record a new trade entry

        Args:
            token_address: Token mint address
            entry_price: Entry price in USD
            amount_sol: SOL amount spent
            wallet_source: Insider wallet that triggered the trade
            ml_confidence: ML model confidence (0-1)
            trade_type: "buy" or "sell"

        Returns:
            Dict with trade ID
        """
        trade = {
            "id": len(self.trade_history) + 1,
            "token_address": token_address,
            "entry_price": entry_price,
            "amount_sol": amount_sol,
            "wallet_source": wallet_source,
            "ml_confidence": ml_confidence,
            "trade_type": trade_type,
            "entry_time": datetime.now().isoformat(),
            "exit_price": None,
            "exit_time": None,
            "roi_percent": None,
            "outcome": None,  # "runner", "sideways", "rug"
            "hold_time_minutes": None,
        }

        self.trade_history.append(trade)
        self._save_json(self.trade_history_path, self.trade_history)

        return {"trade_id": trade["id"], "status": "recorded"}

    def record_outcome(
        self,
        trade_id: int = None,
        token_address: str = None,
        exit_price: float = None,
        roi_percent: float = None,
        outcome: str = None,
    ) -> Dict:
        """
        Record trade outcome

        Args:
            trade_id: Trade ID (or use token_address to find latest)
            token_address: Token address to find trade
            exit_price: Exit price in USD
            roi_percent: Return on investment percentage
            outcome: "runner" (>100%), "sideways" (-20% to 100%), "rug" (<-50%)

        Returns:
            Dict with update status
        """
        # Find the trade
        trade = None
        if trade_id:
            for t in self.trade_history:
                if t["id"] == trade_id:
                    trade = t
                    break
        elif token_address:
            # Find most recent trade for this token without outcome
            for t in reversed(self.trade_history):
                if t["token_address"] == token_address and t["outcome"] is None:
                    trade = t
                    break

        if not trade:
            return {"error": "Trade not found"}

        # Update trade
        trade["exit_price"] = exit_price
        trade["exit_time"] = datetime.now().isoformat()
        trade["roi_percent"] = roi_percent

        # Calculate hold time
        if trade["entry_time"]:
            entry = datetime.fromisoformat(trade["entry_time"])
            trade["hold_time_minutes"] = (datetime.now() - entry).total_seconds() / 60

        # Determine outcome if not provided
        if outcome:
            trade["outcome"] = outcome
        elif roi_percent is not None:
            if roi_percent >= 100:
                trade["outcome"] = "runner"
            elif roi_percent <= -50:
                trade["outcome"] = "rug"
            else:
                trade["outcome"] = "sideways"

        self._save_json(self.trade_history_path, self.trade_history)

        # Update wallet ranking if we have a source
        if trade.get("wallet_source"):
            self._update_wallet_ranking(trade)

        # Record ML prediction outcome
        if trade.get("ml_confidence") is not None:
            self._record_ml_outcome(trade)

        # Check for new patterns
        self._analyze_patterns()

        return {"status": "updated", "trade_id": trade["id"], "outcome": trade["outcome"]}

    def get_trade_stats(self, hours: int = 24) -> Dict:
        """
        Get trading statistics for a time period

        Args:
            hours: Hours to look back

        Returns:
            Dict with win rate, avg ROI, etc.
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        recent_trades = [
            t for t in self.trade_history
            if t.get("exit_time") and datetime.fromisoformat(t["exit_time"]) >= cutoff
        ]

        if not recent_trades:
            return {"period_hours": hours, "total_trades": 0, "message": "No completed trades"}

        wins = [t for t in recent_trades if (t.get("roi_percent") or 0) > 0]
        runners = [t for t in recent_trades if t.get("outcome") == "runner"]
        rugs = [t for t in recent_trades if t.get("outcome") == "rug"]

        total_roi = sum(t.get("roi_percent", 0) for t in recent_trades)
        avg_roi = total_roi / len(recent_trades) if recent_trades else 0

        return {
            "period_hours": hours,
            "total_trades": len(recent_trades),
            "wins": len(wins),
            "losses": len(recent_trades) - len(wins),
            "win_rate": f"{len(wins)/len(recent_trades)*100:.1f}%",
            "runners": len(runners),
            "rugs": len(rugs),
            "avg_roi": f"{avg_roi:.1f}%",
            "total_roi": f"{total_roi:.1f}%",
            "best_trade": max(recent_trades, key=lambda t: t.get("roi_percent", 0)),
            "worst_trade": min(recent_trades, key=lambda t: t.get("roi_percent", 0)),
        }

    # =========================================================================
    # WALLET PERFORMANCE ANALYSIS
    # =========================================================================

    def _update_wallet_ranking(self, trade: Dict):
        """Update wallet ranking based on trade outcome"""
        wallet = trade.get("wallet_source")
        if not wallet:
            return

        if wallet not in self.wallet_rankings:
            self.wallet_rankings[wallet] = {
                "address": wallet,
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "runners": 0,
                "rugs": 0,
                "total_roi": 0,
                "trades": [],
                "tier": "unknown",
            }

        ranking = self.wallet_rankings[wallet]
        ranking["total_trades"] += 1

        roi = trade.get("roi_percent", 0)
        if roi > 0:
            ranking["wins"] += 1
        else:
            ranking["losses"] += 1

        if trade.get("outcome") == "runner":
            ranking["runners"] += 1
        elif trade.get("outcome") == "rug":
            ranking["rugs"] += 1

        ranking["total_roi"] += roi
        ranking["trades"].append({
            "token": trade["token_address"][:8],
            "roi": roi,
            "outcome": trade.get("outcome"),
            "time": trade.get("exit_time"),
        })

        # Keep last 50 trades
        ranking["trades"] = ranking["trades"][-50:]

        # Calculate metrics
        win_rate = ranking["wins"] / ranking["total_trades"] * 100 if ranking["total_trades"] > 0 else 0
        ranking["win_rate"] = win_rate
        ranking["avg_roi"] = ranking["total_roi"] / ranking["total_trades"] if ranking["total_trades"] > 0 else 0

        # Auto-tier: Elite (>80%), Good (>60%), Average (<60%)
        if win_rate >= 80:
            ranking["tier"] = "elite"
        elif win_rate >= 60:
            ranking["tier"] = "good"
        else:
            ranking["tier"] = "average"

        self._save_json(self.wallet_rankings_path, self.wallet_rankings)

    def get_wallet_rankings(self, min_trades: int = 5) -> Dict:
        """
        Get ranked list of wallets by performance

        Args:
            min_trades: Minimum trades required to be ranked

        Returns:
            Dict with wallet rankings by tier
        """
        qualified = {
            k: v for k, v in self.wallet_rankings.items()
            if v.get("total_trades", 0) >= min_trades
        }

        # Sort by win rate
        sorted_wallets = sorted(
            qualified.values(),
            key=lambda w: w.get("win_rate", 0),
            reverse=True
        )

        elite = [w for w in sorted_wallets if w.get("tier") == "elite"]
        good = [w for w in sorted_wallets if w.get("tier") == "good"]
        average = [w for w in sorted_wallets if w.get("tier") == "average"]

        return {
            "total_tracked": len(self.wallet_rankings),
            "qualified_wallets": len(qualified),
            "elite_count": len(elite),
            "good_count": len(good),
            "average_count": len(average),
            "elite_wallets": elite[:10],
            "good_wallets": good[:10],
            "best_performer": sorted_wallets[0] if sorted_wallets else None,
        }

    def get_wallet_performance(self, wallet_address: str) -> Dict:
        """Get detailed performance for a specific wallet"""
        if wallet_address not in self.wallet_rankings:
            return {"error": "Wallet not tracked", "address": wallet_address}

        return self.wallet_rankings[wallet_address]

    # =========================================================================
    # ML THRESHOLD OPTIMIZATION
    # =========================================================================

    def _record_ml_outcome(self, trade: Dict):
        """Record ML prediction outcome for analysis"""
        prediction = {
            "confidence": trade.get("ml_confidence"),
            "predicted_runner": trade.get("ml_confidence", 0) >= 0.7,  # Assuming 0.7 threshold
            "actual_outcome": trade.get("outcome"),
            "actual_runner": trade.get("outcome") == "runner",
            "roi_percent": trade.get("roi_percent"),
            "timestamp": trade.get("exit_time"),
        }

        self.ml_performance["predictions"].append(prediction)

        # Keep last 1000 predictions
        self.ml_performance["predictions"] = self.ml_performance["predictions"][-1000:]

        self._save_json(self.ml_performance_path, self.ml_performance)

    def analyze_ml_performance(self) -> Dict:
        """
        Analyze ML predictions and recommend threshold adjustments

        Returns:
            Dict with current performance and recommendations
        """
        predictions = self.ml_performance.get("predictions", [])

        if len(predictions) < 20:
            return {"error": "Not enough data", "predictions_count": len(predictions)}

        # Analyze at different thresholds
        thresholds = [0.5, 0.6, 0.7, 0.8, 0.9]
        threshold_analysis = []

        for threshold in thresholds:
            # Calculate metrics at this threshold
            trades_taken = [p for p in predictions if p.get("confidence", 0) >= threshold]
            if not trades_taken:
                continue

            runners_caught = sum(1 for p in trades_taken if p.get("actual_runner"))
            total_roi = sum(p.get("roi_percent", 0) for p in trades_taken)
            win_rate = sum(1 for p in trades_taken if (p.get("roi_percent") or 0) > 0) / len(trades_taken) * 100

            # Count runners missed (above threshold but we filtered out)
            runners_missed = sum(
                1 for p in predictions
                if p.get("confidence", 0) < threshold and p.get("actual_runner")
            )

            threshold_analysis.append({
                "threshold": threshold,
                "trades_taken": len(trades_taken),
                "runners_caught": runners_caught,
                "runners_missed": runners_missed,
                "total_roi": round(total_roi, 1),
                "avg_roi": round(total_roi / len(trades_taken), 1) if trades_taken else 0,
                "win_rate": round(win_rate, 1),
            })

        # Find optimal threshold (maximize ROI, not accuracy)
        optimal = max(threshold_analysis, key=lambda t: t["total_roi"]) if threshold_analysis else None

        # Current threshold (assuming 0.7)
        current_threshold = 0.7
        current = next((t for t in threshold_analysis if t["threshold"] == current_threshold), None)

        recommendation = None
        if optimal and current and optimal["threshold"] != current_threshold:
            diff_roi = optimal["total_roi"] - current["total_roi"]
            diff_runners = optimal["runners_caught"] - current["runners_caught"]

            if diff_roi > 0:
                recommendation = {
                    "action": "adjust_threshold",
                    "from": current_threshold,
                    "to": optimal["threshold"],
                    "roi_improvement": f"+{diff_roi:.1f}%",
                    "runner_change": f"{'+' if diff_runners > 0 else ''}{diff_runners}",
                    "reason": f"Would capture {diff_runners} more runners with {diff_roi:.1f}% higher ROI",
                }

        return {
            "total_predictions": len(predictions),
            "current_threshold": current_threshold,
            "current_performance": current,
            "optimal_threshold": optimal["threshold"] if optimal else None,
            "optimal_performance": optimal,
            "threshold_analysis": threshold_analysis,
            "recommendation": recommendation,
        }

    def get_optimal_threshold(self) -> float:
        """Get the current optimal ML threshold"""
        analysis = self.analyze_ml_performance()
        return analysis.get("optimal_threshold", 0.7)

    # =========================================================================
    # PATTERN RECOGNITION
    # =========================================================================

    def _analyze_patterns(self):
        """Analyze trades to identify winning patterns"""
        if len(self.trade_history) < 20:
            return

        completed_trades = [t for t in self.trade_history if t.get("outcome")]
        patterns = []

        # Pattern 1: Token age analysis
        # (Would need token creation time data)

        # Pattern 2: Entry time analysis
        hour_stats = defaultdict(lambda: {"total": 0, "wins": 0})
        for trade in completed_trades:
            if trade.get("entry_time"):
                hour = datetime.fromisoformat(trade["entry_time"]).hour
                hour_stats[hour]["total"] += 1
                if (trade.get("roi_percent") or 0) > 0:
                    hour_stats[hour]["wins"] += 1

        best_hours = []
        for hour, stats in hour_stats.items():
            if stats["total"] >= 3:
                win_rate = stats["wins"] / stats["total"] * 100
                if win_rate >= 60:
                    best_hours.append({
                        "hour": hour,
                        "win_rate": round(win_rate, 1),
                        "trades": stats["total"],
                    })

        if best_hours:
            patterns.append({
                "type": "best_entry_times",
                "description": f"Best trading hours with >60% win rate",
                "data": sorted(best_hours, key=lambda x: x["win_rate"], reverse=True),
            })

        # Pattern 3: ML confidence correlation
        confidence_ranges = [
            (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)
        ]
        confidence_stats = []
        for low, high in confidence_ranges:
            trades_in_range = [
                t for t in completed_trades
                if t.get("ml_confidence") is not None and low <= t["ml_confidence"] < high
            ]
            if trades_in_range:
                avg_roi = sum(t.get("roi_percent", 0) for t in trades_in_range) / len(trades_in_range)
                runners = sum(1 for t in trades_in_range if t.get("outcome") == "runner")
                confidence_stats.append({
                    "range": f"{int(low*100)}-{int(high*100)}%",
                    "trades": len(trades_in_range),
                    "avg_roi": round(avg_roi, 1),
                    "runners": runners,
                })

        if confidence_stats:
            patterns.append({
                "type": "ml_confidence_correlation",
                "description": "Performance by ML confidence range",
                "data": confidence_stats,
            })

        # Pattern 4: Wallet tier performance
        tier_stats = defaultdict(lambda: {"total": 0, "wins": 0, "total_roi": 0})
        for trade in completed_trades:
            wallet = trade.get("wallet_source")
            if wallet and wallet in self.wallet_rankings:
                tier = self.wallet_rankings[wallet].get("tier", "unknown")
                tier_stats[tier]["total"] += 1
                tier_stats[tier]["total_roi"] += trade.get("roi_percent", 0)
                if (trade.get("roi_percent") or 0) > 0:
                    tier_stats[tier]["wins"] += 1

        tier_data = []
        for tier, stats in tier_stats.items():
            if stats["total"] >= 3:
                tier_data.append({
                    "tier": tier,
                    "trades": stats["total"],
                    "win_rate": round(stats["wins"] / stats["total"] * 100, 1),
                    "avg_roi": round(stats["total_roi"] / stats["total"], 1),
                })

        if tier_data:
            patterns.append({
                "type": "wallet_tier_performance",
                "description": "Performance by wallet tier",
                "data": sorted(tier_data, key=lambda x: x["avg_roi"], reverse=True),
            })

        # Save patterns
        self.learned_patterns = {
            "last_updated": datetime.now().isoformat(),
            "total_trades_analyzed": len(completed_trades),
            "patterns": patterns,
        }
        self._save_json(self.learned_patterns_path, self.learned_patterns)

    def get_patterns(self) -> Dict:
        """Get all learned patterns"""
        return self.learned_patterns

    def get_insights(self) -> Dict:
        """Get key trading insights based on learned patterns"""
        patterns = self.learned_patterns.get("patterns", [])

        insights = []

        for pattern in patterns:
            if pattern["type"] == "best_entry_times" and pattern.get("data"):
                best = pattern["data"][0]
                insights.append(f"Best entry hour: {best['hour']}:00 UTC ({best['win_rate']}% win rate)")

            if pattern["type"] == "wallet_tier_performance" and pattern.get("data"):
                elite = next((t for t in pattern["data"] if t["tier"] == "elite"), None)
                if elite:
                    insights.append(f"Elite wallets: {elite['win_rate']}% win rate, {elite['avg_roi']}% avg ROI")

            if pattern["type"] == "ml_confidence_correlation" and pattern.get("data"):
                best_conf = max(pattern["data"], key=lambda x: x["avg_roi"])
                insights.append(f"Best ML confidence range: {best_conf['range']} ({best_conf['avg_roi']}% avg ROI)")

        return {
            "insights": insights,
            "patterns_count": len(patterns),
            "last_updated": self.learned_patterns.get("last_updated"),
        }

    # =========================================================================
    # TRADING RECOMMENDATIONS
    # =========================================================================

    def should_trade(
        self,
        wallet_source: str = None,
        ml_confidence: float = None,
        token_age_minutes: int = None,
    ) -> Dict:
        """
        Get trading recommendation based on learned patterns

        Args:
            wallet_source: Insider wallet address
            ml_confidence: ML model confidence
            token_age_minutes: Token age in minutes

        Returns:
            Dict with recommendation and reasoning
        """
        score = 50  # Base score
        reasons = []

        # Check wallet tier
        if wallet_source and wallet_source in self.wallet_rankings:
            wallet_data = self.wallet_rankings[wallet_source]
            tier = wallet_data.get("tier", "unknown")

            if tier == "elite":
                score += 30
                reasons.append(f"Elite wallet ({wallet_data.get('win_rate', 0):.1f}% win rate)")
            elif tier == "good":
                score += 15
                reasons.append(f"Good wallet ({wallet_data.get('win_rate', 0):.1f}% win rate)")
            elif tier == "average":
                score -= 10
                reasons.append(f"Average wallet ({wallet_data.get('win_rate', 0):.1f}% win rate)")
        elif wallet_source:
            reasons.append("Unknown wallet (no history)")

        # Check ML confidence
        optimal_threshold = self.get_optimal_threshold()
        if ml_confidence is not None:
            if ml_confidence >= optimal_threshold:
                bonus = int((ml_confidence - optimal_threshold) * 100)
                score += bonus
                reasons.append(f"Above optimal threshold ({ml_confidence:.2f} >= {optimal_threshold})")
            else:
                penalty = int((optimal_threshold - ml_confidence) * 50)
                score -= penalty
                reasons.append(f"Below optimal threshold ({ml_confidence:.2f} < {optimal_threshold})")

        # Determine recommendation
        if score >= 70:
            recommendation = "STRONG_BUY"
        elif score >= 55:
            recommendation = "BUY"
        elif score >= 40:
            recommendation = "HOLD"
        else:
            recommendation = "SKIP"

        return {
            "recommendation": recommendation,
            "score": score,
            "reasons": reasons,
            "wallet_source": wallet_source,
            "ml_confidence": ml_confidence,
        }


# Singleton
_learner = None

def get_learner() -> PatternLearner:
    """Get or create learner instance"""
    global _learner
    if _learner is None:
        _learner = PatternLearner()
    return _learner
