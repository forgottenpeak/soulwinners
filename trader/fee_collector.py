"""
Fee Collection System
Collects trading fees from users and sends to owner wallet
"""

import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction
from solders.message import Message
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed

from .wallet_manager import decrypt_private_key, update_balance, get_user_wallet

logger = logging.getLogger(__name__)

# Configuration
FEE_PER_TRADE_SOL = 0.01
OWNER_WALLET = "2oytCBZDcS1nT2siFZGbABRifq9gud71GhoemasotvsW"
LAMPORTS_PER_SOL = 1_000_000_000

DB_PATH = Path(__file__).parent.parent / "data" / "soulwinners.db"


def init_fee_tables():
    """Create fee_history table if not exists."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fee_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            trade_id INTEGER,
            fee_amount_sol REAL NOT NULL,
            collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            tx_signature TEXT,
            status TEXT DEFAULT 'collected'
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fee_transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total_amount_sol REAL NOT NULL,
            tx_signature TEXT,
            transferred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'pending'
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fee_history_user ON fee_history(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fee_history_status ON fee_history(status)")

    conn.commit()
    conn.close()
    logger.info("Fee tables initialized")


def collect_fee(user_id: int, trade_id: int = None, fee_amount_sol: float = FEE_PER_TRADE_SOL) -> Dict:
    """
    Collect fee from user's balance after a trade.

    Args:
        user_id: Telegram user ID
        trade_id: Optional trade reference ID
        fee_amount_sol: Fee amount (default 0.01 SOL)

    Returns:
        Dict with success status and details
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Get current user balance
        cursor.execute("""
            SELECT balance_sol FROM user_wallets WHERE user_id = ?
        """, (user_id,))

        row = cursor.fetchone()
        if not row:
            return {"success": False, "error": "User wallet not found"}

        current_balance = row[0]

        # Check if user has enough balance for fee
        if current_balance < fee_amount_sol:
            return {
                "success": False,
                "error": f"Insufficient balance for fee. Has: {current_balance:.4f}, Need: {fee_amount_sol:.4f}"
            }

        # Deduct fee from user balance
        new_balance = current_balance - fee_amount_sol
        cursor.execute("""
            UPDATE user_wallets
            SET balance_sol = ?, last_updated = CURRENT_TIMESTAMP
            WHERE user_id = ?
        """, (new_balance, user_id))

        # Record fee in history
        cursor.execute("""
            INSERT INTO fee_history (user_id, trade_id, fee_amount_sol, status)
            VALUES (?, ?, ?, 'collected')
        """, (user_id, trade_id, fee_amount_sol))

        fee_id = cursor.lastrowid

        conn.commit()

        logger.info(f"Fee collected: {fee_amount_sol} SOL from user {user_id} (trade {trade_id})")

        return {
            "success": True,
            "fee_id": fee_id,
            "fee_amount": fee_amount_sol,
            "old_balance": current_balance,
            "new_balance": new_balance
        }

    except Exception as e:
        conn.rollback()
        logger.error(f"Fee collection failed: {e}")
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def get_user_fees(user_id: int) -> Dict:
    """
    Get total fees paid by a user.

    Args:
        user_id: Telegram user ID

    Returns:
        Dict with fee statistics
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*) as total_trades,
            COALESCE(SUM(fee_amount_sol), 0) as total_fees,
            MIN(collected_at) as first_fee,
            MAX(collected_at) as last_fee
        FROM fee_history
        WHERE user_id = ?
    """, (user_id,))

    row = cursor.fetchone()
    conn.close()

    return {
        "user_id": user_id,
        "total_trades": row[0],
        "total_fees_sol": row[1],
        "first_fee_at": row[2],
        "last_fee_at": row[3]
    }


def get_total_fees() -> Dict:
    """
    Get all fees collected across all users.

    Returns:
        Dict with total fee statistics
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Total collected
    cursor.execute("""
        SELECT
            COUNT(*) as total_trades,
            COALESCE(SUM(fee_amount_sol), 0) as total_collected,
            COUNT(DISTINCT user_id) as unique_users
        FROM fee_history
    """)
    collected = cursor.fetchone()

    # Total transferred to owner
    cursor.execute("""
        SELECT COALESCE(SUM(total_amount_sol), 0)
        FROM fee_transfers
        WHERE status = 'completed'
    """)
    transferred = cursor.fetchone()[0]

    # Pending (collected but not transferred)
    pending = collected[1] - transferred

    conn.close()

    return {
        "total_trades": collected[0],
        "total_collected_sol": collected[1],
        "total_transferred_sol": transferred,
        "pending_transfer_sol": pending,
        "unique_users": collected[2]
    }


def get_pending_fees() -> float:
    """Get total fees collected but not yet transferred to owner."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Sum of collected fees
    cursor.execute("""
        SELECT COALESCE(SUM(fee_amount_sol), 0) FROM fee_history
    """)
    total_collected = cursor.fetchone()[0]

    # Sum of transferred fees
    cursor.execute("""
        SELECT COALESCE(SUM(total_amount_sol), 0)
        FROM fee_transfers
        WHERE status = 'completed'
    """)
    total_transferred = cursor.fetchone()[0]

    conn.close()

    return total_collected - total_transferred


async def send_to_owner(rpc_url: str = "https://api.mainnet-beta.solana.com") -> Dict:
    """
    Transfer accumulated fees to owner wallet.
    Uses the bot's treasury wallet to send fees.

    Args:
        rpc_url: Solana RPC endpoint

    Returns:
        Dict with transfer status
    """
    import os
    from dotenv import load_dotenv
    load_dotenv()

    treasury_key = os.getenv('TREASURY_PRIVATE_KEY') or os.getenv('OPENCLAW_PRIVATE_KEY')
    if not treasury_key:
        return {"success": False, "error": "Treasury private key not configured"}

    pending_amount = get_pending_fees()

    if pending_amount < 0.01:
        return {"success": False, "error": f"Pending amount too small: {pending_amount:.4f} SOL"}

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Record pending transfer
        cursor.execute("""
            INSERT INTO fee_transfers (total_amount_sol, status)
            VALUES (?, 'pending')
        """, (pending_amount,))
        transfer_id = cursor.lastrowid
        conn.commit()

        # Execute Solana transfer
        client = Client(rpc_url, commitment=Confirmed)

        try:
            keypair = Keypair.from_base58_string(treasury_key)
        except:
            # Try hex format
            keypair = Keypair.from_bytes(bytes.fromhex(treasury_key))

        owner_pubkey = Pubkey.from_string(OWNER_WALLET)

        # Create transfer instruction
        lamports = int(pending_amount * LAMPORTS_PER_SOL)

        transfer_ix = transfer(
            TransferParams(
                from_pubkey=keypair.pubkey(),
                to_pubkey=owner_pubkey,
                lamports=lamports
            )
        )

        # Get recent blockhash
        recent_blockhash = client.get_latest_blockhash().value.blockhash

        # Create and sign transaction
        msg = Message.new_with_blockhash(
            [transfer_ix],
            keypair.pubkey(),
            recent_blockhash
        )
        tx = Transaction([keypair], msg, recent_blockhash)

        # Send transaction
        result = client.send_transaction(tx)

        if result.value:
            signature = str(result.value)

            # Update transfer record
            cursor.execute("""
                UPDATE fee_transfers
                SET tx_signature = ?, status = 'completed', transferred_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (signature, transfer_id))
            conn.commit()

            logger.info(f"Fee transfer successful: {pending_amount:.4f} SOL to {OWNER_WALLET[:20]}... | TX: {signature}")

            return {
                "success": True,
                "amount_sol": pending_amount,
                "signature": signature,
                "owner_wallet": OWNER_WALLET
            }
        else:
            cursor.execute("""
                UPDATE fee_transfers SET status = 'failed' WHERE id = ?
            """, (transfer_id,))
            conn.commit()
            return {"success": False, "error": "Transaction failed"}

    except Exception as e:
        cursor.execute("""
            UPDATE fee_transfers SET status = 'failed' WHERE id = ?
        """, (transfer_id,))
        conn.commit()
        logger.error(f"Fee transfer failed: {e}")
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def get_fee_history(user_id: int = None, limit: int = 50) -> List[Dict]:
    """
    Get fee collection history.

    Args:
        user_id: Filter by user (optional)
        limit: Max records to return

    Returns:
        List of fee records
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if user_id:
        cursor.execute("""
            SELECT id, user_id, trade_id, fee_amount_sol, collected_at, tx_signature, status
            FROM fee_history
            WHERE user_id = ?
            ORDER BY collected_at DESC
            LIMIT ?
        """, (user_id, limit))
    else:
        cursor.execute("""
            SELECT id, user_id, trade_id, fee_amount_sol, collected_at, tx_signature, status
            FROM fee_history
            ORDER BY collected_at DESC
            LIMIT ?
        """, (limit,))

    rows = cursor.fetchall()
    conn.close()

    return [
        {
            "id": row[0],
            "user_id": row[1],
            "trade_id": row[2],
            "fee_amount_sol": row[3],
            "collected_at": row[4],
            "tx_signature": row[5],
            "status": row[6]
        }
        for row in rows
    ]


# Initialize tables on import
init_fee_tables()
