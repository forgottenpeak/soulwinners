"""
Multi-User Wallet Management
Generates and manages Solana wallets for each user
"""

import sqlite3
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from cryptography.fernet import Fernet
import base64
import os
from pathlib import Path

# Encryption key (store securely - DO NOT commit to git!)
ENCRYPTION_KEY = os.getenv('WALLET_ENCRYPTION_KEY', Fernet.generate_key())
cipher = Fernet(ENCRYPTION_KEY)

DB_PATH = Path(__file__).parent.parent / "data" / "soulwinners.db"

def create_user_wallet(user_id: int) -> dict:
    """Generate new Solana wallet for user"""
    # Generate keypair
    keypair = Keypair()
    public_key = str(keypair.pubkey())
    private_key = bytes(keypair).hex()
    
    # Encrypt private key
    encrypted_key = cipher.encrypt(private_key.encode()).decode()
    
    # Save to database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO user_wallets 
        (user_id, deposit_address, encrypted_private_key, balance_sol)
        VALUES (?, ?, ?, 0.0)
    """, (user_id, public_key, encrypted_key))
    
    conn.commit()
    conn.close()
    
    return {
        "user_id": user_id,
        "deposit_address": public_key,
        "balance": 0.0
    }

def get_user_wallet(user_id: int) -> dict:
    """Retrieve user wallet info"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT deposit_address, balance_sol, created_at
        FROM user_wallets WHERE user_id = ?
    """, (user_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    return {
        "user_id": user_id,
        "deposit_address": row[0],
        "balance": row[1],
        "created_at": row[2]
    }

def decrypt_private_key(user_id: int) -> str:
    """Get decrypted private key for trading (ADMIN ONLY!)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT encrypted_private_key FROM user_wallets WHERE user_id = ?
    """, (user_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    encrypted_key = row[0]
    private_key = cipher.decrypt(encrypted_key.encode()).decode()
    
    return private_key

def update_balance(user_id: int, new_balance: float):
    """Update user SOL balance"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE user_wallets 
        SET balance_sol = ?, last_updated = CURRENT_TIMESTAMP
        WHERE user_id = ?
    """, (new_balance, user_id))
    
    conn.commit()
    conn.close()
