#!/usr/bin/env python3
"""Fix UNKNOWN tokens with retry logic"""
import sys
sys.path.insert(0, '/root/Soulwinners')

from database import get_connection
import requests
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_token_symbol(token_address, retries=3):
    """Fetch symbol with retry on DNS/network errors"""
    for attempt in range(retries):
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
            response = requests.get(url, timeout=10)
            data = response.json()
            
            if data.get('pairs') and len(data['pairs']) > 0:
                return data['pairs'][0]['baseToken']['symbol']
            return None
            
        except requests.exceptions.RequestException as e:
            if attempt < retries - 1:
                logger.warning(f"Retry {attempt+1}/{retries} for {token_address[:8]}...")
                time.sleep(2)  # Wait before retry
            else:
                logger.error(f"Failed after {retries} attempts: {str(e)[:80]}")
                return None
    
    return None

def fix_unknowns():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get UNKNOWN positions
    cursor.execute("""
        SELECT id, token_address 
        FROM position_lifecycle 
        WHERE token_symbol = 'UNKNOWN' 
        LIMIT 200
    """)
    
    unknowns = cursor.fetchall()
    logger.info(f"Fixing {len(unknowns)} UNKNOWN tokens...")
    
    fixed = 0
    for pos_id, token_address in unknowns:
        symbol = get_token_symbol(token_address)
        
        if symbol:
            cursor.execute("""
                UPDATE position_lifecycle 
                SET token_symbol = ? 
                WHERE id = ?
            """, (symbol, pos_id))
            
            logger.info(f"✅ Fixed position {pos_id}: {symbol}")
            fixed += 1
            conn.commit()  # Commit after each success
        
        time.sleep(0.3)  # Rate limit
    
    conn.close()
    logger.info(f"✅ Fixed {fixed}/{len(unknowns)} tokens ({fixed*100//len(unknowns)}%)")

if __name__ == "__main__":
    fix_unknowns()
