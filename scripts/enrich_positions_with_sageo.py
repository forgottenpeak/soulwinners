#!/usr/bin/env python3
"""
Enrich position_lifecycle with SAGEO social intelligence data
Run as cron job every 6 hours
"""
import sys
sys.path.insert(0, '/root/Soulwinners')

from sageo.social_scanner import SocialScanner
from database import get_connection
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def enrich_positions():
    """Add SAGEO social data to positions missing it"""
    scanner = SocialScanner()
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get positions without social data (social_score IS NULL)
    cursor.execute("""
        SELECT id, token_address, token_symbol 
        FROM position_lifecycle 
        WHERE social_score IS NULL 
        AND wallet_type != 'backlog'
        LIMIT 100
    """)
    
    positions = cursor.fetchall()
    logger.info(f"Enriching {len(positions)} positions with SAGEO data...")
    
    for pos_id, token_address, token_symbol in positions:
        try:
            # Get SAGEO score
            result = scanner.calculate_social_score(token_address, token_symbol)
            
            # Update position
            cursor.execute("""
                UPDATE position_lifecycle SET
                    social_score = ?,
                    has_website = ?,
                    has_twitter = ?,
                    has_telegram = ?,
                    ai_rug_risk = ?
                WHERE id = ?
            """, (
                result['score'],
                result['metadata'].get('has_website', False),
                result['metadata'].get('has_twitter', False),
                result['metadata'].get('has_telegram', False),
                result["ai_rug_risk"],
                pos_id
            ))
            
            logger.info(f"✅ Position {pos_id} | ${token_symbol} | Score: {result['score']}")
            
        except Exception as e:
            logger.error(f"Error enriching position {pos_id}: {e}")
    
    conn.commit()
    conn.close()
    logger.info(f"✅ Enriched {len(positions)} positions")

if __name__ == "__main__":
    enrich_positions()
