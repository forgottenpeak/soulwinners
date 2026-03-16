"""
Sync webhook wallets with database
Runs after main pipeline to update Helius webhook
"""
import requests
import sqlite3
from config.settings import WEBHOOK_HELIUS_KEYS

def get_all_wallets():
    """Get all wallets from database"""
    conn = sqlite3.connect('data/soulwinners.db')
    cursor = conn.cursor()
    
    qualified = cursor.execute("SELECT wallet_address FROM wallet_global_pool").fetchall()
    insiders = cursor.execute("SELECT wallet_address FROM insider_pool").fetchall()
    user_watchlists = cursor.execute("SELECT wallet_address FROM user_watchlists").fetchall()
    
    return list(set([w[0] for w in qualified + insiders + user_watchlists]))

def update_webhook():
    """Update Helius webhook with current wallet list"""
    # Read webhook ID
    with open('.webhook_id', 'r') as f:
        webhook_id = f.read().strip()
    
    wallets = get_all_wallets()
    
    response = requests.put(
        f"https://api.helius.xyz/v0/webhooks/{webhook_id}?api-key={WEBHOOK_HELIUS_KEYS[0]}",
        json={
            "accountAddresses": wallets
        }
    )
    
    if response.status_code == 200:
        print(f"✅ Webhook updated: {len(wallets)} wallets")
    else:
        print(f"❌ Update failed: {response.text}")

if __name__ == '__main__':
    update_webhook()
