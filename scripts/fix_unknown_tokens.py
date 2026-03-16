#!/usr/bin/env python3
"""Re-fetch token symbols for UNKNOWN tokens"""
import sys
sys.path.insert(0, '/root/Soulwinners')

from database import get_connection
import requests
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def fix_unknowns():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get UNKNOWN positions
    cursor.execute("""
        SELECT id, token_address 
        FROM position_lifecycle 
        WHERE token_symbol = 'UNKNOWN' 
        LIMIT 100
    """)
    
    unknowns = cursor.fetchall()
    logger.info(f"Fixing {len(unknowns)} UNKNOWN tokens...")
    
    fixed = 0
    for pos_id, token_address in unknowns:
        try:
            # Try DexScreener
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            response = requests.get(url, timeout=5)
            data = response.json()
            
            if data.get('pairs'):
                symbol = data['pairs'][0]['baseToken']['symbol']
                
                cursor.execute("""
                    UPDATE position_lifecycle 
                    SET token_symbol = ? 
                    WHERE id = ?
                """, (symbol, pos_id))
                
                logger.info(f"✅ Fixed position {pos_id}: {symbol}")
                fixed += 1
            
            time.sleep(0.5)  # Rate limit
            
        except Exception as e:
            logger.error(f"Error fixing {pos_id}: {e}")
    
    conn.commit()
    conn.close()
    logger.info(f"✅ Fixed {fixed} tokens")

if __name__ == "__main__":
    fix_unknowns()
