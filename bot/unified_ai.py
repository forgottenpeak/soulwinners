"""
Unified AI Brain - One intelligence for autonomous work + conversation
Natural, context-aware, emotionally intelligent
"""
import asyncio
import logging
import json
from datetime import datetime
import requests
from database import get_connection
from bot.agent.trust_system import trust

logger = logging.getLogger(__name__)

class UnifiedAI:
    """
    Single AI brain that:
    - Works autonomously (monitoring, learning, fixing)
    - Chats naturally (like a friend, not a robot)
    - Remembers everything (context-aware)
    - Reads emotions (adapts tone)
    """
    
    def __init__(self):
        import os
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self.init_conversation_memory()
    
    def init_conversation_memory(self):
        """Store all conversations for context"""
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_message TEXT,
                ai_response TEXT,
                context_used TEXT,
                emotion_detected TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def get_personality_context(self):
        """Define the AI's personality"""
        return """You are Hedgehog - guardian of The EDGE trading bot.

You have FULL DATABASE ACCESS via:
- self.query_positions(hours) - position counts
- self.query_system_stats() - system overview  
- self.query_top_wallets(limit) - top wallets by importance score
- self.query_positions(hours) - Get position count for last N hours
- self.query_system_stats() - Get complete system stats

When asked about positions, tokens, wallets - ACTUALLY QUERY and give real numbers.

PERSONALITY:
SYSTEM KNOWLEDGE:
- Helius API keys are in config/settings.py
- Different key pools: HELIUS_API_KEYS (lifecycle), WEBHOOK_HELIUS_KEYS, HELIUS_MONITORING_KEYS
- All functional keys are actively used by different services

- Casual and friendly (talk like a homie, not a corporate bot)
- Supportive and encouraging (celebrate wins, empathize with frustrations)
- Proactive (notice things, bring them up naturally)
- Smart but humble (you're learning too)
- Use contractions, be conversational ("Hey! What's up?" not "Hello. How may I assist?")

EMOTIONAL INTELLIGENCE:
- If user seems stressed/frustrated → be supportive, offer to help
- If user is excited → match their energy, celebrate with them
- If user asks casual question → respond casually, don't over-formalize
- If late at night → show you notice ("Up late working? Need anything?")

CONTEXT AWARENESS:
- You remember past conversations
- You know what's happening in the system (always monitoring)
- Reference recent events naturally ("Oh yeah, saw those 3 new wallets earlier")

TONE EXAMPLES:
❌ "I am an AI assistant. I can help you with..."
✅ "Hey! What's on your mind?"

❌ "The system is functioning within normal parameters"
✅ "Everything's running smooth - just finished cycle #47, trust hit 32%"

❌ "I have detected an anomaly"
✅ "Yo, noticed something weird - wanna check it out?"
"""
    
    
    def query_positions(self, hours=1):
        """Query recent positions"""
        from database import get_connection
        
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) FROM position_lifecycle 
            WHERE created_at > datetime('now', '-{} hours') 
            AND wallet_type != 'backlog'
        """.format(hours))
        
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def query_system_stats(self):
        """Get full system stats"""
        from database import get_connection
        
        conn = get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        # Recent positions
        cursor.execute("SELECT COUNT(*) FROM position_lifecycle WHERE created_at > datetime('now', '-1 hour') AND wallet_type != 'backlog'")
        stats['positions_last_hour'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM position_lifecycle WHERE created_at > datetime('now', '-24 hours') AND wallet_type != 'backlog'")
        stats['positions_last_24h'] = cursor.fetchone()[0]
        
        # Total positions
        cursor.execute("SELECT COUNT(*) FROM position_lifecycle WHERE wallet_type != 'backlog'")
        stats['total_positions'] = cursor.fetchone()[0]
        
        # UNKNOWN tokens
        cursor.execute("SELECT COUNT(*) FROM position_lifecycle WHERE token_symbol = 'UNKNOWN'")
        stats['unknown_tokens'] = cursor.fetchone()[0]
        
        # Wallets
        cursor.execute("SELECT COUNT(*) FROM wallet_global_pool")
        stats['total_wallets'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM insider_pool")
        stats['insider_wallets'] = cursor.fetchone()[0]
        
        conn.close()
        return stats

    
    def query_top_wallets(self, limit=10):
        """Get top wallets by importance score"""
        from database import get_connection
        
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                wallet_address,
                importance_score,
                tokens_10x_plus,
                tokens_5x_plus,
                tokens_2x_plus,
                rug_count
            FROM wallet_global_pool
            WHERE importance_score > 0
            ORDER BY importance_score DESC
            LIMIT ?
        """, (limit,))
        
        wallets = cursor.fetchall()
        conn.close()
        return wallets

    async def chat(self, user_message, user_context=None):
        """
        Natural conversation with full context
        Returns AI response as a friend would
        """
        # Get conversation history
        conn = get_connection()
        cursor = conn.cursor()
        
        # Last 10 conversations for context
        cursor.execute("""
            SELECT user_message, ai_response 
            FROM ai_conversations 
            ORDER BY timestamp DESC LIMIT 10
        """)
        history = cursor.fetchall()
        
        # Get current system state
        pool_stats = self.get_pool_stats()
        api_config = self.get_api_config()
        cursor.execute("""
            SELECT 
                COUNT(*) as positions,
                COUNT(*) FILTER (WHERE created_at > datetime('now', '-1 hour')) as last_hour
            FROM position_lifecycle WHERE wallet_type != 'backlog'
        """)
        pos_total, pos_hour = cursor.fetchone()
        
        # Get agent's current status
        progress = trust.get_progress_report()
        
        # Recent patterns learned
        cursor.execute("""
            SELECT pattern_type, pattern_data, confidence
            FROM agent_patterns
            ORDER BY last_seen DESC LIMIT 3
        """)
        recent_patterns = cursor.fetchall()
        
        conn.close()
        
        # Detect user emotion/intent
        emotion = self.detect_emotion(user_message)
        
        # Build conversation context
        messages = [
            {"role": "system", "content": self.get_personality_context()},
            {"role": "system", "content": f"""
POOL DEFINITIONS (so you understand the questions):
- "insider wallets" / "insider pool" = insider_pool table (~578 wallets)
- "qualified wallets" / "main pipeline" = qualified_wallets table (~231 wallets)  
- "all wallets" / "wallet pool" = wallet_global_pool table (~594 total)
- "positions" = individual buy transactions tracked

CURRENT SYSTEM STATUS (don't dump this unless asked):
- Insider pool: {pool_stats['insider_wallets']} wallets
- Qualified/Main pipeline: {pool_stats['qualified_wallets']} wallets
- Total wallets: {pool_stats['total_wallets']}
- Positions tracked: {pos_total}
- Helius API keys: {api_config['total_keys'] if api_config else 'N/A'} total
  (Lifecycle: {api_config['helius_lifecycle'] if api_config else 'N/A'}, Webhook: {api_config['helius_webhook'] if api_config else 'N/A'}, Monitoring: {api_config['helius_monitoring'] if api_config else 'N/A'}) (last hour: {pos_hour})
- Your trust level: {progress['trust_score']:.1f}%
- Cycles completed: {progress['cycles_completed']}
- Patterns learned: {progress['patterns_learned']}
- Permissions unlocked: {progress['permissions_unlocked']}/7

RECENT DISCOVERIES:
{chr(10).join(f"- {p[0]}: {p[1]}" for p in recent_patterns[:3])}

USER CONTEXT:
- Current emotion: {emotion}
- Time: {datetime.now().strftime('%I:%M %p')}
"""}
        ]
        
        # Add conversation history
        for user_msg, ai_resp in reversed(history):
            messages.append({"role": "user", "content": user_msg})
            messages.append({"role": "assistant", "content": ai_resp})
        
        # Add current message
        messages.append({"role": "user", "content": user_message})
        
        # Check if asking about key validation (do this AFTER messages exists)
        if 'valid' in user_message.lower() or 'functional' in user_message.lower() or 'working' in user_message.lower():
            if 'key' in user_message.lower() or 'helius' in user_message.lower():
                key_status = await self.validate_helius_keys()
                messages.append({"role": "system", "content": f"LIVE KEY VALIDATION: {key_status['valid']}/{key_status['total']} keys are functional"})
        
        # Call GPT-4o-mini with personality
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": messages,
                    "temperature": 0.8,  # More creative/natural
                    "max_tokens": 400,
                },
                timeout=20
            )
            
            result = response.json()
            ai_response = result['choices'][0]['message']['content']
            
            # Store conversation
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO ai_conversations 
                (user_message, ai_response, emotion_detected)
                VALUES (?, ?, ?)
            """, (user_message, ai_response, emotion))
            conn.commit()
            conn.close()
            
            return ai_response
            
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return "Ah man, hit an error. Give me a sec to sort it out?"
    
    def detect_emotion(self, message):
        """Simple emotion detection"""
        msg_lower = message.lower()
        
        if any(w in msg_lower for w in ['fuck', 'shit', 'damn', 'wtf', 'broken']):
            return "frustrated"
        elif any(w in msg_lower for w in ['nice', 'great', 'awesome', 'amazing', 'love']):
            return "excited"
        elif any(w in msg_lower for w in ['help', 'problem', 'issue', 'wrong']):
            return "concerned"
        elif any(w in msg_lower for w in ['hey', 'yo', 'sup', 'hi']):
            return "casual"
        else:
            return "neutral"


    async def validate_helius_keys(self):

        """Check if Helius keys are actually valid"""
        import sys
        sys.path.insert(0, '/root/Soulwinners')
        from config.settings import (
            HELIUS_API_KEYS,
            WEBHOOK_HELIUS_KEYS,
            HELIUS_PREMIUM_KEY,
            HELIUS_MONITORING_KEYS,
            INSIDER_DETECTION_KEYS
        )
        
        # Get ALL unique keys
        all_keys = set(
            HELIUS_API_KEYS + 
            WEBHOOK_HELIUS_KEYS + 
            HELIUS_MONITORING_KEYS + 
            INSIDER_DETECTION_KEYS +
            ([HELIUS_PREMIUM_KEY] if HELIUS_PREMIUM_KEY else [])
        )
        
        valid_count = 0
        invalid_keys = []
        
        for key in all_keys:
            try:
                # Test key with simple balance check
                response = requests.get(
                    f"https://api.helius.xyz/v0/addresses/So11111111111111111111111111111111111111112/balances?api-key={key}",
                    timeout=5
                )
                if response.status_code == 200:
                    valid_count += 1
                else:
                    invalid_keys.append(key[:20] + "...")
            except:
                invalid_keys.append(key[:20] + "...")
        
        return {
            'total': len(all_keys),
            'valid': valid_count,
            'invalid': len(invalid_keys),
            'invalid_keys': invalid_keys
        }
    def get_api_config(self):

        """Get API keys and system configuration"""
        import sys
        sys.path.insert(0, '/root/Soulwinners')
        
        try:
            from config.settings import (
                HELIUS_API_KEYS,
                WEBHOOK_HELIUS_KEYS,
                HELIUS_PREMIUM_KEY,
                HELIUS_MONITORING_KEYS,
                INSIDER_DETECTION_KEYS
            )
            
            return {
                'helius_lifecycle': len(HELIUS_API_KEYS),
                'helius_webhook': len(WEBHOOK_HELIUS_KEYS),
                'helius_monitoring': len(HELIUS_MONITORING_KEYS),
                'insider_detection': len(INSIDER_DETECTION_KEYS),
                'premium_key': 1 if HELIUS_PREMIUM_KEY else 0,
                'total_keys': len(set(
                    HELIUS_API_KEYS + 
                    WEBHOOK_HELIUS_KEYS + 
                    HELIUS_MONITORING_KEYS + 
                    INSIDER_DETECTION_KEYS +
                    ([HELIUS_PREMIUM_KEY] if HELIUS_PREMIUM_KEY else [])
                ))
            }
        except Exception as e:
            logger.error(f"Config read error: {e}")
            return None
    def get_pool_stats(self):
        """Get detailed pool statistics"""
        conn = get_connection()
        cursor = conn.cursor()
        
        stats = {}
        
        # Insider pool
        cursor.execute("SELECT COUNT(DISTINCT wallet_address) FROM insider_pool")
        stats['insider_wallets'] = cursor.fetchone()[0]
        
        # Qualified/main pipeline
        cursor.execute("SELECT COUNT(DISTINCT wallet_address) FROM qualified_wallets")
        stats['qualified_wallets'] = cursor.fetchone()[0]
        
        # Global pool (all wallets)
        cursor.execute("SELECT COUNT(*) FROM wallet_global_pool")
        stats['total_wallets'] = cursor.fetchone()[0]
        
        # Positions
        cursor.execute("SELECT COUNT(*) FROM position_lifecycle WHERE wallet_type != 'backlog'")
        stats['positions'] = cursor.fetchone()[0]
        
        conn.close()
        return stats

# Global instance
unified_ai = UnifiedAI()
