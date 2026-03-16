"""
AI Assistant for SoulWinners Bot
Pattern-based responses (no external API needed)
"""
import logging
from database import get_connection
import re

logger = logging.getLogger(__name__)

def call_kimi_ai(user_message, conversation_history=[]):
    """Pattern-based AI responses"""
    msg = user_message.lower()
    
    # Pattern matching for commands
    if any(word in msg for word in ['top', 'wallet', 'leaderboard', 'best']):
        # Extract number
        match = re.search(r'\d+', msg)
        limit = int(match.group()) if match else 10
        return (
            f"Sure! Let me show you the top {limit} wallets by importance score.",
            ("get_top_wallets", limit)
        )
    
    elif any(word in msg for word in ['turn on', 'enable', 'start']) and 'alert' in msg:
        return (
            "Enabling buy alerts now!",
            ("toggle_alerts", "on")
        )
    
    elif any(word in msg for word in ['turn off', 'disable', 'stop']) and 'alert' in msg:
        return (
            "Disabling buy alerts.",
            ("toggle_alerts", "off")
        )
    
    elif 'limit' in msg or 'per hour' in msg:
        match = re.search(r'(\d+)', msg)
        limit = int(match.group()) if match else 2
        return (
            f"Setting alert limit to {limit} per hour.",
            ("set_alert_limit", limit)
        )
    
    elif any(word in msg for word in ['explain', 'what', 'how', 'feature']):
        return (
            "**Edge Bot Features:**\n\n"
            "🎯 **Wallet Tracking**: Monitor 641 elite Solana wallets\n"
            "📊 **Importance Scoring**: Wallets earn points for 2x, 3x, 5x, 10x trades\n"
            "🏆 **Tier System**: 7 tiers from Rookie to Whale Whisperer\n"
            "🚨 **Buy Alerts**: Real-time notifications when elites buy\n"
            "📈 **SAGEO**: Social intelligence scoring (website, Twitter, Telegram)\n\n"
            "Try: `/ai show top 10 wallets` or `/ai turn on alerts`",
            None
        )
    
    elif any(word in msg for word in ['hi', 'hello', 'hey']):
        return (
            "👋 Hey! I'm your Edge Bot assistant. I can show you top wallets, manage alerts, and explain features. What would you like to do?",
            None
        )
    
    else:
        return (
            "I can help with:\n"
            "• Show top wallets\n"
            "• Turn alerts on/off\n"
            "• Set alert limits\n"
            "• Explain features\n\n"
            "Try: `show me top 5 wallets`",
            None
        )

def execute_command(command):
    """Execute bot commands"""
    if not command:
        return None
    
    cmd_type, param = command
    
    if cmd_type == "get_top_wallets":
        from bot.wallet_tiers import get_wallet_tier, get_tier_color
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wallet_address, importance_score 
            FROM wallet_global_pool 
            ORDER BY importance_score DESC 
            LIMIT ?
        """, (param,))
        wallets = cursor.fetchall()
        conn.close()
        
        text = f"📊 *TOP {param} WALLETS*\n\n"
        for i, (wallet, score) in enumerate(wallets, 1):
            score_val = int(score) if score else 0
            tier = get_wallet_tier(score_val)
            color = get_tier_color(score_val)
            text += f"{i}. {color} `{wallet[:7]}...` | {tier} ({score_val})\n"
        
        return text
    
    elif cmd_type == "toggle_alerts":
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value) 
            VALUES ('buy_alerts', ?)
        """, (param,))
        conn.commit()
        conn.close()
        
        return f"✅ Buy alerts turned **{param.upper()}**"
    
    elif cmd_type == "set_alert_limit":
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value) 
            VALUES ('alert_limit_per_hour', ?)
        """, (str(param),))
        conn.commit()
        conn.close()
        
        return f"✅ Alert limit set to **{param} per hour**"
    
    return None
