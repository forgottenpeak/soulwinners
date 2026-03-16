"""
Simplified Telegram buy alerts with wallet scores
"""
import sys
sys.path.insert(0, '/root/Soulwinners')

from database import get_connection
import requests

TELEGRAM_BOT_TOKEN = "8483614914:AAFjwtH2pct_OdZgi4zrcPNKq6zWdb62ypQ"
TELEGRAM_CHANNEL_ID = "-1003534177506"

def get_wallet_recent_trades(wallet_address, limit=5):
    """Get last N trades for a wallet"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            token_symbol,
            CASE 
                WHEN peak_mc > entry_mc THEN ROUND((peak_mc / entry_mc), 1)
                ELSE ROUND((current_mc / entry_mc), 1)
            END as multiple
        FROM position_lifecycle
        WHERE wallet_address = ?
        AND entry_timestamp < strftime('%s', 'now', '-24 hours')
        ORDER BY entry_timestamp DESC
        LIMIT ?
    """, (wallet_address, limit))
    
    trades = []
    for symbol, mult in cursor.fetchall():
        if mult >= 1.0:
            trades.append(f"• {mult}x ✅")
        else:
            trades.append(f"• {int((mult - 1) * 100)}% ❌")
    
    conn.close()
    return trades

def send_buy_alert(wallet_address, token_symbol, token_address, entry_mc, buy_sol_amount):
    """Send simplified buy alert"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get wallet score
    cursor.execute("""
        SELECT importance_score 
        FROM wallet_global_pool 
        WHERE wallet_address = ?
    """, (wallet_address,))
    
    result = cursor.fetchone()
    score = int(result[0]) if result else 0
    
    # Get recent trades
    recent = get_wallet_recent_trades(wallet_address)
    recent_str = "\n".join(recent) if recent else "No 24h+ trades yet"
    
    # Format message
    message = f"""💰 BUY ALERT

${token_symbol} | Entry: ${int(entry_mc):,} MC
🔸 Wallet: {wallet_address[:7]}... | Score: {score}

📊 Recent trades:
{recent_str}

🔗 [DexScreener](https://dexscreener.com/solana/{token_address})
"""
    
    # Send to Telegram
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
    )
    
    conn.close()

if __name__ == "__main__":
    # Test
    send_buy_alert(
        "2DjfP3UCLyKm...",
        "TEST",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        45000,
        2.5
    )
