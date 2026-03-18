import sys
sys.path.insert(0, '/root/Soulwinners')
from database import get_connection
import requests
import time

conn = get_connection()
cursor = conn.cursor()

cursor.execute("SELECT id, token_address FROM position_lifecycle WHERE token_symbol = 'UNKNOWN' LIMIT 500")
unknowns = cursor.fetchall()

print(f"Fixing {len(unknowns)} tokens...")
fixed = 0

for pos_id, token_addr in unknowns:
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_addr}"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        
        if data.get('pairs'):
            symbol = data['pairs'][0]['baseToken']['symbol']
            cursor.execute("UPDATE position_lifecycle SET token_symbol = ? WHERE id = ?", (symbol, pos_id))
            conn.commit()
            print(f"✅ {symbol}")
            fixed += 1
        
        time.sleep(0.2)
    except Exception as e:
        print(f"❌ {str(e)[:50]}")

conn.close()
print(f"\n✅ Fixed {fixed}/{len(unknowns)} ({fixed*100//len(unknowns)}%)")
