"""Register webhook with Helius"""
import requests
import sqlite3
from config.settings import WEBHOOK_HELIUS_KEYS

HELIUS_KEY = WEBHOOK_HELIUS_KEYS[0]

# Read all wallet addresses from database
conn = sqlite3.connect('data/soulwinners.db')
cursor = conn.cursor()

# Correct table names
qualified = cursor.execute("SELECT wallet_address FROM wallet_global_pool").fetchall()
insiders = cursor.execute("SELECT wallet_address FROM insider_pool").fetchall() 
watchlist = cursor.execute("SELECT wallet_address FROM user_watchlists").fetchall()

all_wallets = list(set([w[0] for w in qualified + insiders + watchlist]))
print(f"📋 Registering {len(all_wallets)} wallets")

# Create webhook
webhook_url = "http://80.240.22.200:5000/webhook/helius"

response = requests.post(
    f"https://api.helius.xyz/v0/webhooks?api-key={HELIUS_KEY}",
    json={
        "webhookURL": webhook_url,
        "transactionTypes": ["SWAP"],
        "accountAddresses": all_wallets,
        "webhookType": "enhanced"
    }
)

if response.status_code == 200:
    webhook_id = response.json()['webhookID']
    print(f"✅ Webhook registered! ID: {webhook_id}")
    print(f"📍 URL: {webhook_url}")
    print(f"👀 Watching {len(all_wallets)} wallets")
    
    with open('.webhook_id', 'w') as f:
        f.write(webhook_id)
else:
    print(f"❌ Failed: {response.status_code}")
    print(response.text)
