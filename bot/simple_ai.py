"""Simple AI chat handler - clean and working"""
import requests
from database import get_connection

import os
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "")

async def handle_ai_message(message_text):
    """Send message to GPT-4o-mini with system context"""
    
    # Get live system data
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM position_lifecycle WHERE wallet_type != 'backlog'")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM insider_pool")
    insiders = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM qualified_wallets")
    qualified = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM wallet_global_pool WHERE importance_score > 5")
    performing = cursor.fetchone()[0]
    
    conn.close()
    
    # System context for AI
    context = f"""You are Edge Bot AI for SoulWinners.

LIVE DATA:
- Positions tracked: {total}
- Insider wallets: {insiders}
- Qualified wallets: {qualified}
- Performing wallets: {performing}

DATABASE TABLES:
- insider_pool: detected insider wallets
- qualified_wallets: elite wallets monitored
- wallet_global_pool: all wallets with scores
- position_lifecycle: buy positions

Respond naturally and helpfully."""

    # Call OpenAI
    try:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": context},
                    {"role": "user", "content": message_text}
                ],
                "temperature": 0.7,
                "max_tokens": 300,
            },
            timeout=15
        )
        
        result = response.json()
        return result['choices'][0]['message']['content']
    
    except Exception as e:
        return f"AI error: {str(e)}"
