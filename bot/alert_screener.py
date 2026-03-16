"""
Buy Alert Screening System
Two-layer filter: ML (fast) → AI (smart)

Flow:
100 elite buys/day → ML filters to 60 → AI screens to top 15
"""
import logging
from database import get_connection
import requests
import os
from datetime import datetime

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

class AlertScreener:
    """Dual-layer alert filtering"""
    
    def __init__(self):
        self.daily_limit = 15  # Max alerts per day
        self.min_probability = 70  # Minimum runner probability
        self.alerts_sent_today = 0
        self.last_reset = datetime.now().date()
    
    def ml_filter(self, position_data):
        """Fast ML-based filter (free, instant)"""
        
        wallet_score = position_data.get('wallet_importance_score', 0)
        social_score = position_data.get('social_score', 0)
        momentum_score = position_data.get('momentum_score', 0)
        has_socials = position_data.get('has_website') or position_data.get('has_twitter')
        
        # ML filtering rules
        if wallet_score < 3:
            return False, "Wallet score too low"
        
        if social_score < 20 and not has_socials:
            return False, "No social presence"
        
        if momentum_score < 0.3:
            return False, "Weak momentum"
        
        # Passed ML filter
        return True, "ML approved"
    
    async def ai_screen(self, position_data):
        """AI screening for runner probability"""
        
        # Build context for AI
        prompt = f"""Analyze this Solana memecoin buy for runner probability.

WALLET INFO:
• Importance score: {position_data.get('wallet_importance_score', 0)}
• Recent trades: {position_data.get('recent_trades', 'Unknown')}
• Tier: {position_data.get('wallet_tier', 'Unknown')}

TOKEN INFO:
• Symbol: ${position_data.get('token_symbol', 'UNKNOWN')}
• Entry MC: ${position_data.get('entry_mc', 0):,}
• SAGEO score: {position_data.get('social_score', 0)}/100
• Has website: {position_data.get('has_website', False)}
• Has Twitter: {position_data.get('has_twitter', False)}
• Momentum: {position_data.get('momentum_score', 0):.2f}

BUY SIZE: {position_data.get('buy_sol_amount', 0)} SOL

Estimate runner probability (0-100%) based on:
1. Wallet performance history
2. Token legitimacy signals
3. Entry timing and momentum
4. Social presence quality

Respond with ONLY a number 0-100, nothing else."""

        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You are a crypto trading analyst. Respond with only a probability number."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 10,
                },
                timeout=10
            )
            
            result = response.json()
            probability_text = result['choices'][0]['message']['content'].strip()
            
            # Extract number
            probability = int(''.join(filter(str.isdigit, probability_text)))
            
            logger.info(f"AI screening: {position_data.get('token_symbol')} = {probability}% probability")
            
            return probability
            
        except Exception as e:
            logger.error(f"AI screening error: {e}")
            # Fallback to simple scoring
            return self.fallback_probability(position_data)
    
    def fallback_probability(self, data):
        """Simple probability without AI"""
        score = 50  # Base
        
        # Wallet performance
        if data.get('wallet_importance_score', 0) > 10:
            score += 20
        elif data.get('wallet_importance_score', 0) > 5:
            score += 10
        
        # Social signals
        if data.get('social_score', 0) > 60:
            score += 15
        
        # Momentum
        if data.get('momentum_score', 0) > 0.7:
            score += 10
        
        return min(100, score)
    
    async def should_send_alert(self, position_data):
        """Complete screening pipeline"""
        
        # Reset daily counter
        today = datetime.now().date()
        if today != self.last_reset:
            self.alerts_sent_today = 0
            self.last_reset = today
        
        # Check daily limit
        if self.alerts_sent_today >= self.daily_limit:
            return False, 0, "Daily limit reached"
        
        # Step 1: ML filter (fast, free)
        ml_pass, ml_reason = self.ml_filter(position_data)
        
        if not ml_pass:
            return False, 0, f"ML filtered: {ml_reason}"
        
        # Step 2: AI screening (costs $)
        probability = await self.ai_screen(position_data)
        
        # Check probability threshold
        if probability < self.min_probability:
            return False, probability, f"Low probability: {probability}%"
        
        # Approved!
        self.alerts_sent_today += 1
        return True, probability, "Approved"
    
    def update_settings(self, daily_limit=None, min_probability=None):
        """Update screening settings"""
        if daily_limit is not None:
            self.daily_limit = daily_limit
            logger.info(f"Daily limit updated to {daily_limit}")
        
        if min_probability is not None:
            self.min_probability = min_probability
            logger.info(f"Min probability updated to {min_probability}%")
    
    def get_stats(self):
        """Get screening statistics"""
        return {
            'daily_limit': self.daily_limit,
            'min_probability': self.min_probability,
            'alerts_sent_today': self.alerts_sent_today,
            'remaining_today': self.daily_limit - self.alerts_sent_today,
        }

# Global screener instance
alert_screener = AlertScreener()

async def screen_buy_alert(position_data):
    """Screen a buy alert through ML + AI"""
    return await alert_screener.should_send_alert(position_data)

def update_alert_settings(daily_limit=None, min_probability=None):
    """Update alert screening settings"""
    alert_screener.update_settings(daily_limit, min_probability)

def get_screening_stats():
    """Get current screening stats"""
    return alert_screener.get_stats()
