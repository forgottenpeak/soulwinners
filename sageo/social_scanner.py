"""
SAGEO Social Intelligence Layer
Token legitimacy + AI name analysis
"""
import requests
import logging
from typing import Dict

logger = logging.getLogger(__name__)

OPENROUTER_KEY = "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"

class SocialScanner:
    
    def get_token_metadata(self, token_address: str) -> Dict:
        """Get token info from DexScreener (free API)"""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            response = requests.get(url, timeout=5)
            data = response.json()
            
            if not data.get('pairs'):
                return {}
            
            pair = data['pairs'][0]
            info = pair.get('info', {})
            
            return {
                'has_website': bool(info.get('websites')),
                'has_twitter': bool(any(s.get('type') == 'twitter' for s in info.get('socials', []))),
                'has_telegram': bool(any(s.get('type') == 'telegram' for s in info.get('socials', []))),
                'website_url': info.get('websites', [{}])[0].get('url') if info.get('websites') else None,
            }
        except Exception as e:
            logger.error(f"Error fetching metadata: {e}")
            return {}
    
    def analyze_token_name_with_ai(self, token_symbol: str) -> Dict:
        """Use Kimi K2 to analyze token name for rug signals"""
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "HTTP-Referer": "https://soulwinners.ai",
                },
                json={
                    "model": "moonshot/moonshot-v1-8k",
                    "messages": [{
                        "role": "user",
                        "content": f"""Analyze this crypto token name: ${token_symbol}

Rate rug risk (0-100) based on:
- Scam keywords (moon, pump, elon, inu)
- Profanity/offensive terms
- Copy of major brands

Reply ONLY with number 0-100."""
                    }]
                },
                timeout=10
            )
            
            rug_score = int(response.json()['choices'][0]['message']['content'].strip())
            return {'ai_rug_risk': rug_score}
        except:
            return {'ai_rug_risk': 50}  # Neutral if AI fails
    
    def calculate_social_score(self, token_address: str, token_symbol: str) -> Dict:
        """Calculate SAGEO score (0-100)"""
        score = 0
        signals = []
        
        # 1. Legitimacy (70 points)
        metadata = self.get_token_metadata(token_address)
        
        if metadata.get('has_website'):
            score += 30
            signals.append("✅ Has website")
        
        if metadata.get('has_twitter'):
            score += 20
            signals.append("✅ Has Twitter")
        
        if metadata.get('has_telegram'):
            score += 20
            signals.append("✅ Has Telegram")
        
        # 2. AI Name Analysis (30 points)
        ai_analysis = self.analyze_token_name_with_ai(token_symbol)
        rug_risk = ai_analysis['ai_rug_risk']
        
        # Convert rug risk to score (0 risk = +30, 100 risk = -30)
        name_score = 30 - (rug_risk * 0.6)
        score += name_score
        
        if rug_risk > 70:
            signals.append("⚠️ High rug risk name")
        elif rug_risk < 30:
            signals.append("✅ Legitimate name")
        
        return {
            'score': max(0, min(100, int(score))),
            'signals': signals,
            'metadata': metadata,
            'ai_rug_risk': rug_risk
        }

if __name__ == "__main__":
    scanner = SocialScanner()
    result = scanner.calculate_social_score(
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "USDC"
    )
    print(f"Score: {result['score']}")
    print(f"Signals: {result['signals']}")
    print(f"AI Rug Risk: {result['ai_rug_risk']}")
