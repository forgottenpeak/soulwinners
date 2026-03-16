#!/usr/bin/env python3
"""
Real-time wallet scoring with 24h confirmation + 1.5 SOL minimum
"""
import sys
sys.path.insert(0, '/root/Soulwinners')

from database import get_connection
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def calculate_realtime_scores():
    """Score wallets based on positions >24h old AND >1.5 SOL buys"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Only score positions that are:
    # 1. 24h+ old
    # 2. Buy amount >= 1.5 SOL
    cursor.execute("""
        SELECT 
            wallet_address,
            COUNT(*) as total_positions,
            SUM(CASE WHEN peak_mc >= entry_mc * 10 THEN 1 ELSE 0 END) as tokens_10x,
            SUM(CASE WHEN peak_mc >= entry_mc * 5 THEN 1 ELSE 0 END) as tokens_5x,
            SUM(CASE WHEN peak_mc >= entry_mc * 3 THEN 1 ELSE 0 END) as tokens_3x,
            SUM(CASE WHEN peak_mc >= entry_mc * 2 THEN 1 ELSE 0 END) as tokens_2x,
            SUM(CASE WHEN current_mc < entry_mc * 0.5 THEN 1 ELSE 0 END) as rugged,
            AVG(CASE WHEN peak_mc > 0 AND entry_mc > 0 
                THEN peak_mc / entry_mc ELSE 0 END) as avg_peak_multiple
        FROM position_lifecycle
        WHERE wallet_type != 'backlog' 
        AND entry_mc > 0
        AND buy_sol_amount >= 1.5
        AND entry_timestamp < strftime('%s', 'now', '-24 hours')
        GROUP BY wallet_address
    """)
    
    wallets = cursor.fetchall()
    logger.info(f"Scoring {len(wallets)} wallets (24h+ positions, 1.5+ SOL buys only)...")
    
    scored = 0
    for wallet_data in wallets:
        wallet, total, t10x, t5x, t3x, t2x, rugged, avg_mult = wallet_data
        
        # Score formula
        score = (t10x * 5) + (t5x * 3) + (t3x * 2) + (t2x * 1) - (rugged * 1)
        
        # Update wallet_global_pool
        cursor.execute("""
            INSERT OR REPLACE INTO wallet_global_pool 
            (wallet_address, importance_score, tokens_10x_plus, tokens_5x_plus, 
             tokens_3x_plus, tokens_2x_plus, rug_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (wallet, score, t10x, t5x, t3x, t2x, rugged))
        
        scored += 1
        if score > 3:
            logger.info(f"🔥 {wallet[:12]}... | Score: {score} | 2x+: {t2x} | Rugs: {rugged}")
    
    conn.commit()
    
    # Show top performers
    cursor.execute("""
        SELECT wallet_address, importance_score, tokens_10x_plus, tokens_2x_plus, rug_count
        FROM wallet_global_pool
        WHERE importance_score > 0
        ORDER BY importance_score DESC
        LIMIT 10
    """)
    
    top_wallets = cursor.fetchall()
    
    logger.info("\n" + "="*60)
    logger.info(f"TOP WALLETS (scored {scored} wallets, 1.5+ SOL buys only)")
    logger.info("="*60)
    
    if top_wallets:
        for i, (wallet, score, t10x, t2x, rugs) in enumerate(top_wallets, 1):
            logger.info(f"#{i}: {wallet[:12]}... | Score: {score:.0f} | 10x: {t10x} | 2x+: {t2x} | Rugs: {rugs}")
    else:
        logger.info("No wallets scored yet (need 24h+ positions with 1.5+ SOL)")
    
    conn.close()

if __name__ == "__main__":
    calculate_realtime_scores()
