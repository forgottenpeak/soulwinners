"""
ML-Gated Alert System for Small Buys (0.8-1.5 SOL)

Only alerts if ML predicts 'runner' with high confidence.
"""
import joblib
import numpy as np
from typing import Dict

class MLGatedAlerts:
    def __init__(self):
        self.model = None
        self.scaler = None
        self.min_confidence = 0.10  # 10% threshold (realistic for rare runners)
        
    def load_model(self):
        """Load the trained ML model."""
        try:
            self.model = joblib.load('data/models/best_predictor.pkl')
            self.scaler = joblib.load('data/models/feature_scaler.pkl')
            return True
        except Exception as e:
            print(f"Error loading model: {e}")
            return False
    
    def should_alert_small_buy(
        self,
        buy_sol_amount: float,
        entry_mc: float,
        entry_liquidity: float,
        holder_count: int = 0,
        top10_concentration: float = 0,
        insider_wallet_count: int = 0,
        elite_wallet_count: int = 0,
        volume_24h: float = 0,
        social_score: int = 0,
        has_website: bool = False,
        has_twitter: bool = False,
        has_telegram: bool = False
    ) -> Dict:
        """
        Determine if a small buy (0.8-1.5 SOL) should trigger an alert.
        
        Returns:
            dict with 'should_alert', 'confidence', 'predicted_outcome'
        """
        # Only evaluate small buys
        if buy_sol_amount < 0.8 or buy_sol_amount >= 1.5:
            return {
                'should_alert': False,
                'reason': 'Not in small buy range (0.8-1.5 SOL)',
                'confidence': 0.0
            }
        
        if not self.model:
            if not self.load_model():
                return {
                    'should_alert': False,
                    'reason': 'ML model not loaded',
                    'confidence': 0.0
                }
        
        # Build feature vector
        features = np.array([[
            entry_mc,
            entry_liquidity,
            buy_sol_amount,
            holder_count,
            top10_concentration,
            insider_wallet_count,
            elite_wallet_count,
            volume_24h,
            social_score,
            int(has_website),
            int(has_twitter),
            int(has_telegram),
            entry_liquidity / max(entry_mc, 1),
            buy_sol_amount / max(entry_mc, 1),
            insider_wallet_count + elite_wallet_count,
        ]])
        
        # Get prediction
        probabilities = self.model.predict_proba(features)[0]
        predicted_class = self.model.predict(features)[0]
        
        outcomes = ['rug', 'sideways', 'runner']
        predicted_outcome = outcomes[predicted_class]
        runner_confidence = probabilities[2]
        
        # Alert if runner prediction meets threshold
        should_alert = (
            predicted_outcome == 'runner' and 
            runner_confidence >= self.min_confidence
        )
        
        return {
            'should_alert': should_alert,
            'predicted_outcome': predicted_outcome,
            'confidence': runner_confidence,
            'probabilities': {
                'rug': probabilities[0],
                'sideways': probabilities[1],
                'runner': probabilities[2]
            },
            'alert_type': 'ML_GATED_SMALL_BUY' if should_alert else None,
            'threshold': self.min_confidence
        }
