"""
Live Predictor for V3 Edge Auto-Trader

Provides real-time predictions for incoming trades.
Called from realtime_bot.py for AI decision gate.
"""
import logging
from typing import Dict, Optional, Tuple
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection
from ml.feature_engineering import FeatureEngineer, build_live_features
from ml.train_model import ModelTrainer

logger = logging.getLogger(__name__)


class LivePredictor:
    """
    Real-time prediction service for trade signals.

    Provides:
    - Probability estimates (runner/sideways/rug)
    - Trade decision recommendations
    - Position sizing suggestions
    """

    # Decision thresholds (can be configured via settings)
    DEFAULT_THRESHOLDS = {
        "min_prob_runner": 0.60,   # Minimum probability of being a runner
        "max_prob_rug": 0.30,      # Maximum acceptable rug probability
        "flag_threshold": 0.50,    # Below this, flag for manual review
    }

    # Position sizing based on confidence
    POSITION_SIZING = {
        "high_confidence": 1.00,   # prob_runner > 0.80
        "medium_confidence": 0.75, # prob_runner > 0.70
        "low_confidence": 0.50,    # prob_runner > 0.60
    }

    def __init__(self):
        self.model: Optional[ModelTrainer] = None
        self.engineer = FeatureEngineer()
        self.thresholds = self.DEFAULT_THRESHOLDS.copy()
        self._load_thresholds()

    def _load_thresholds(self):
        """Load thresholds from database settings."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT key, value FROM settings
                WHERE key LIKE 'autotrader_%'
            """)

            for key, value in cursor.fetchall():
                if key == "autotrader_min_prob_runner":
                    self.thresholds["min_prob_runner"] = float(value)
                elif key == "autotrader_max_prob_rug":
                    self.thresholds["max_prob_rug"] = float(value)

        except Exception as e:
            logger.debug(f"Could not load thresholds: {e}")
        finally:
            conn.close()

    def load_model(self, version: str = None) -> bool:
        """
        Load the ML model for predictions.

        Args:
            version: Specific version or None for active model

        Returns:
            True if loaded successfully
        """
        try:
            self.model = ModelTrainer.load_model(version)
            logger.info(f"Predictor loaded model: {self.model.model_type}")
            return True
        except Exception as e:
            logger.warning(f"Could not load ML model: {e}")
            self.model = None
            return False

    def is_ready(self) -> bool:
        """Check if predictor is ready for predictions."""
        return self.model is not None

    def predict(
        self,
        wallet_data: Dict,
        token_data: Dict,
        parsed_tx: Dict,
    ) -> Dict:
        """
        Make prediction for a live trade signal.

        Args:
            wallet_data: Wallet info from qualified_wallets
            token_data: Token info from DexScreener
            parsed_tx: Parsed transaction data

        Returns:
            Prediction dict with probabilities and decision
        """
        if not self.is_ready():
            logger.warning("Predictor not ready - no model loaded")
            return self._default_prediction()

        try:
            # Build feature vector
            features = build_live_features(wallet_data, token_data, parsed_tx)

            # Make prediction
            preds, probs = self.model.predict(features.reshape(1, -1))

            prob_rug = probs[0][0]
            prob_sideways = probs[0][1]
            prob_runner = probs[0][2]

            # Make decision
            decision, reason = self._make_decision(prob_runner, prob_rug)

            # Calculate position size
            position_size = self._calculate_position_size(prob_runner, prob_rug)

            # Calculate expected ROI (weighted by probabilities)
            # Rough estimates: rug = -80%, sideways = -10%, runner = +100%
            expected_roi = (
                prob_rug * -80 +
                prob_sideways * -10 +
                prob_runner * 100
            )

            # Confidence score (entropy-based)
            probs_array = np.array([prob_rug, prob_sideways, prob_runner])
            entropy = -np.sum(probs_array * np.log(probs_array + 1e-10))
            max_entropy = np.log(3)  # Maximum possible entropy for 3 classes
            confidence = 1.0 - (entropy / max_entropy)

            result = {
                "prob_runner": float(prob_runner),
                "prob_sideways": float(prob_sideways),
                "prob_rug": float(prob_rug),
                "expected_roi": float(expected_roi),
                "confidence": float(confidence),
                "decision": decision,
                "decision_reason": reason,
                "position_size_pct": float(position_size),
                "predicted_class": int(preds[0]),
                "predicted_label": ["rug", "sideways", "runner"][int(preds[0])],
            }

            logger.info(f"Prediction: {result['predicted_label']} "
                       f"(runner: {prob_runner:.1%}, rug: {prob_rug:.1%}) "
                       f"-> {decision}")

            return result

        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return self._default_prediction()

    def _make_decision(
        self,
        prob_runner: float,
        prob_rug: float,
    ) -> Tuple[str, str]:
        """
        Make trade decision based on probabilities.

        Returns:
            (decision, reason) tuple
        """
        min_runner = self.thresholds["min_prob_runner"]
        max_rug = self.thresholds["max_prob_rug"]
        flag_threshold = self.thresholds["flag_threshold"]

        # Reject if rug probability too high
        if prob_rug > max_rug:
            return "reject", f"High rug risk ({prob_rug:.0%} > {max_rug:.0%})"

        # Approve if runner probability high enough
        if prob_runner >= min_runner:
            return "approve", f"Strong runner signal ({prob_runner:.0%})"

        # Flag for review if borderline
        if prob_runner >= flag_threshold:
            return "flag", f"Borderline ({prob_runner:.0%}), needs review"

        # Reject otherwise
        return "reject", f"Weak signal ({prob_runner:.0%} < {min_runner:.0%})"

    def _calculate_position_size(
        self,
        prob_runner: float,
        prob_rug: float,
    ) -> float:
        """
        Calculate recommended position size as percentage.

        Higher confidence = larger position.
        """
        if prob_runner >= 0.80 and prob_rug < 0.15:
            return self.POSITION_SIZING["high_confidence"]
        elif prob_runner >= 0.70 and prob_rug < 0.25:
            return self.POSITION_SIZING["medium_confidence"]
        else:
            return self.POSITION_SIZING["low_confidence"]

    def _default_prediction(self) -> Dict:
        """Return default prediction when model unavailable."""
        return {
            "prob_runner": 0.33,
            "prob_sideways": 0.34,
            "prob_rug": 0.33,
            "expected_roi": 0.0,
            "confidence": 0.0,
            "decision": "flag",
            "decision_reason": "Model unavailable - manual review required",
            "position_size_pct": 0.50,
            "predicted_class": 1,
            "predicted_label": "sideways",
        }

    def log_decision(
        self,
        wallet_address: str,
        token_address: str,
        prediction: Dict,
        trade_event_id: int = None,
    ):
        """Log AI decision to database for tracking."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO ai_decisions
                (trade_event_id, wallet_address, token_address,
                 prob_runner, prob_sideways, prob_rug, expected_roi,
                 confidence_score, decision, decision_reason,
                 position_size_pct, model_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade_event_id,
                wallet_address,
                token_address,
                prediction["prob_runner"],
                prediction["prob_sideways"],
                prediction["prob_rug"],
                prediction["expected_roi"],
                prediction["confidence"],
                prediction["decision"],
                prediction["decision_reason"],
                prediction["position_size_pct"],
                self.model.metrics.get("version") if self.model else None,
            ))
            conn.commit()

        except Exception as e:
            logger.error(f"Failed to log decision: {e}")
        finally:
            conn.close()


# Singleton predictor instance
_predictor: Optional[LivePredictor] = None


def get_predictor() -> LivePredictor:
    """Get or create the singleton predictor instance."""
    global _predictor
    if _predictor is None:
        _predictor = LivePredictor()
        _predictor.load_model()
    return _predictor


def predict_trade(
    wallet_data: Dict,
    token_data: Dict,
    parsed_tx: Dict,
) -> Dict:
    """
    Convenience function for making predictions.

    Called from realtime_bot.py.
    """
    predictor = get_predictor()
    return predictor.predict(wallet_data, token_data, parsed_tx)


def should_approve_trade(
    wallet_data: Dict,
    token_data: Dict,
    parsed_tx: Dict,
) -> Tuple[bool, str, Dict]:
    """
    Quick check if a trade should be approved.

    Returns:
        (approved, reason, full_prediction)
    """
    prediction = predict_trade(wallet_data, token_data, parsed_tx)

    approved = prediction["decision"] == "approve"
    reason = prediction["decision_reason"]

    return approved, reason, prediction


if __name__ == "__main__":
    # Test predictor
    import logging
    logging.basicConfig(level=logging.INFO)

    predictor = LivePredictor()

    # Try to load model
    if predictor.load_model():
        print("Model loaded successfully!")

        # Test prediction with dummy data
        wallet = {"wallet_address": "test123", "tier": "Elite"}
        token = {
            "market_cap": 500000,
            "liquidity": 50000,
            "token_age_hours": 2,
            "holders": 100,
            "volume_24h": 100000,
        }
        tx = {
            "token_address": "token123",
            "timestamp": 1700000000,
            "sol_amount": 2.0,
        }

        result = predictor.predict(wallet, token, tx)
        print(f"\nPrediction result:")
        for k, v in result.items():
            print(f"  {k}: {v}")
    else:
        print("No model available - train one first!")
        print("Run: python ml/train_model.py --save --deploy")
