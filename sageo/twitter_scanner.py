"""Twitter sentiment via Kimi K2 AI"""
from ntscraper import Nitter
import requests
import logging

logger = logging.getLogger(__name__)

OPENROUTER_KEY = "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"

def analyze_with_kimi(token_symbol, tweets):
    """Use FREE Kimi K2 for sentiment analysis"""
    try:
        tweet_text = "\n".join([f"- {t}" for t in tweets[:5]])
        
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
                    "content": f"""Analyze these tweets about ${token_symbol}:
{tweet_text}

Reply ONLY with JSON:
{{"sentiment": "bullish/bearish/neutral", "rug_risk": "high/medium/low", "confidence": 0-100}}"""
                }]
            },
            timeout=15
        )
        
        result = response.json()['choices'][0]['message']['content']
        # Parse JSON from response
        import json
        return json.loads(result.strip())
    except Exception as e:
        logger.error(f"Kimi analysis error: {e}")
        return {"sentiment": "neutral", "rug_risk": "medium", "confidence": 0}

def scan_twitter(token_symbol):
    """Scan Twitter and analyze with AI"""
    try:
        scraper = Nitter()
        result = scraper.get_tweets(f"${token_symbol}", mode='term', number=20)
        
        if not result or 'tweets' not in result:
            return {'count': 0, 'ai_sentiment': 'neutral', 'rug_risk': 'medium'}
        
        tweets = [t.get('text', '') for t in result['tweets'][:10]]
        
        # Get AI analysis
        analysis = analyze_with_kimi(token_symbol, tweets)
        
        return {
            'count': len(tweets),
            'ai_sentiment': analysis.get('sentiment', 'neutral'),
            'rug_risk': analysis.get('rug_risk', 'medium'),
            'confidence': analysis.get('confidence', 0)
        }
    except Exception as e:
        logger.error(f"Twitter scan error: {e}")
        return {'count': 0, 'ai_sentiment': 'neutral', 'rug_risk': 'medium'}
