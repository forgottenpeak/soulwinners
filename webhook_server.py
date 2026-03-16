#!/usr/bin/env python3
"""
Helius Webhook Server for Elite Wallet Tracking

Receives SWAP transactions from Helius webhooks for 641 elite wallets.
- Creates lifecycle positions when wallets BUY >= 0.8 SOL
- Tracks SELL events in wallet_exits table (position stays open for 48h)
- Deduplicates: same wallet+token within 24h, >10% SOL difference

Run:
    python webhook_server.py --port 8080

Production (with gunicorn):
    gunicorn webhook_server:app -b 0.0.0.0:8080 -w 4

Helius Webhook Setup:
    - URL: https://your-server.com/webhook/helius
    - Transaction Types: SWAP
    - Account Addresses: Your 641 elite wallets
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path
import sys

# Flask for webhook server
from flask import Flask, request, jsonify

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from database import get_connection
from bot.lifecycle_tracker import get_lifecycle_tracker, should_track_position

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
MIN_BUY_SOL = 0.8           # Minimum SOL for tracking buys
MIN_SELL_SOL = 0.1          # Minimum SOL for tracking sells
DUP_WINDOW_HOURS = 24       # Dedup window for same wallet+token
DUP_SOL_THRESHOLD = 0.10    # 10% difference to consider new position

# Skip tokens (stablecoins, wrapped SOL)
SKIP_TOKENS = {
    'So11111111111111111111111111111111111111112',   # WSOL
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v', # USDC
    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB', # USDT
}

# Cache for elite wallets
_qualified_wallets: Dict[str, Dict] = {}
_wallets_loaded_at: float = 0
WALLET_CACHE_TTL = 300  # Reload every 5 minutes


def load_qualified_wallets() -> Dict[str, Dict]:
    """Load elite wallets from database with caching."""
    global _qualified_wallets, _wallets_loaded_at

    now = time.time()
    if _qualified_wallets and (now - _wallets_loaded_at) < WALLET_CACHE_TTL:
        return _qualified_wallets

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Load qualified wallets (main elite pool)
        cursor.execute("""
            SELECT wallet_address, tier, win_rate, roi_final, total_trades
            FROM qualified_wallets
        """)
        qualified = cursor.fetchall()

        # Load insider wallets
        cursor.execute("""
            SELECT wallet_address, pattern, confidence, win_rate, roi_final
            FROM insider_pool
        """)
        insiders = cursor.fetchall()

        conn.close()

        _qualified_wallets = {}

        for row in qualified:
            wallet, tier, wr, roi, trades = row
            _qualified_wallets[wallet] = {
                'type': 'qualified',
                'tier': tier,
                'win_rate': wr or 0,
                'roi_final': roi or 0,
                'total_trades': trades or 0,
            }

        for row in insiders:
            wallet, pattern, conf, wr, roi = row
            if wallet not in _qualified_wallets:  # Don't override qualified
                _qualified_wallets[wallet] = {
                    'type': 'insider',
                    'tier': pattern,
                    'confidence': conf or 0,
                    'win_rate': wr or 0,
                    'roi_final': roi or 0,
                }

        _wallets_loaded_at = now
        logger.info(f"Loaded {len(_qualified_wallets)} elite wallets")

        return _qualified_wallets

    except Exception as e:
        logger.error(f"Error loading elite wallets: {e}")
        return _qualified_wallets  # Return cached if available


def is_elite_wallet(wallet_address: str) -> Optional[Dict]:
    """Check if wallet is in elite pool."""
    wallets = load_qualified_wallets()
    return wallets.get(wallet_address)


def check_duplicate_position(wallet_address: str, token_address: str, sol_amount: float) -> bool:
    """
    Check if this buy is a duplicate (same wallet+token within 24h).

    Returns True if duplicate (should skip), False if new position.

    Dedup logic:
    - Same wallet + same token within 24h
    - SOL amount within 10% of existing position
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cutoff = int(time.time()) - (DUP_WINDOW_HOURS * 3600)

        cursor.execute("""
            SELECT buy_sol_amount
            FROM position_lifecycle
            WHERE wallet_address = ?
            AND token_address = ?
            AND entry_timestamp > ?
            ORDER BY entry_timestamp DESC
            LIMIT 1
        """, (wallet_address, token_address, cutoff))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return False  # No recent position, not a duplicate

        existing_amount = row[0]

        # Check if amounts are within threshold
        if existing_amount > 0:
            diff_pct = abs(sol_amount - existing_amount) / existing_amount
            if diff_pct < DUP_SOL_THRESHOLD:
                logger.debug(
                    f"Duplicate detected: {wallet_address[:8]}... {token_address[:8]}... "
                    f"({sol_amount:.2f} vs {existing_amount:.2f} SOL)"
                )
                return True

        return False

    except Exception as e:
        logger.error(f"Error checking duplicate: {e}")
        return False  # Allow on error


def parse_helius_swap(tx: Dict) -> Optional[Dict]:
    """
    Parse Helius enhanced transaction for SWAP data.

    Returns dict with:
    - signature: tx signature
    - wallet_address: the elite wallet
    - type: 'buy' or 'sell'
    - token_address: token contract
    - sol_amount: SOL spent (buy) or received (sell)
    - timestamp: unix timestamp
    """
    try:
        signature = tx.get('signature', '')
        timestamp = tx.get('timestamp', int(time.time()))

        # Get accounts involved
        account_data = tx.get('accountData', [])
        token_transfers = tx.get('tokenTransfers', [])
        native_transfers = tx.get('nativeTransfers', [])

        if not token_transfers:
            return None

        # Find the main token (not SOL/stables)
        main_transfer = None
        for transfer in token_transfers:
            mint = transfer.get('mint', '')
            if mint and mint not in SKIP_TOKENS:
                main_transfer = transfer
                break

        if not main_transfer:
            return None

        token_address = main_transfer.get('mint', '')
        from_account = main_transfer.get('fromUserAccount', '')
        to_account = main_transfer.get('toUserAccount', '')

        # Determine wallet and direction
        wallets = load_qualified_wallets()
        wallet_address = None
        tx_type = None

        # Check if sender or receiver is elite wallet
        if to_account in wallets:
            # Elite wallet received tokens = BUY
            wallet_address = to_account
            tx_type = 'buy'
        elif from_account in wallets:
            # Elite wallet sent tokens = SELL
            wallet_address = from_account
            tx_type = 'sell'
        else:
            return None  # Not an elite wallet trade

        # Calculate SOL amount from native transfers
        sol_amount = 0.0
        for nt in native_transfers:
            amount = abs(nt.get('amount', 0)) / 1e9
            if tx_type == 'buy' and nt.get('fromUserAccount') == wallet_address:
                sol_amount += amount  # SOL out = buying
            elif tx_type == 'sell' and nt.get('toUserAccount') == wallet_address:
                sol_amount += amount  # SOL in = selling

        if sol_amount == 0:
            # Try to calculate from token transfer amount and price (fallback)
            token_amount = float(main_transfer.get('tokenAmount', 0) or 0)
            # Without price data, we can't accurately determine SOL value
            # Skip if no native transfer detected
            return None

        return {
            'signature': signature,
            'wallet_address': wallet_address,
            'type': tx_type,
            'token_address': token_address,
            'sol_amount': abs(sol_amount),
            'timestamp': timestamp,
        }

    except Exception as e:
        logger.error(f"Error parsing swap: {e}")
        return None


async def fetch_token_info(token_address: str) -> Dict:
    """Fetch token info from DexScreener."""
    import aiohttp

    try:
        url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        pair = data[0]
                        return {
                            'symbol': pair.get('baseToken', {}).get('symbol', '???'),
                            'name': pair.get('baseToken', {}).get('name', 'Unknown'),
                            'market_cap': float(pair.get('marketCap', 0) or 0),
                            'liquidity': float(pair.get('liquidity', {}).get('usd', 0) or 0),
                            'volume_5m': float(pair.get('volume', {}).get('m5', 0) or 0),
                            'volume_1h': float(pair.get('volume', {}).get('h1', 0) or 0),
                            'volume_24h': float(pair.get('volume', {}).get('h24', 0) or 0),
                        }
    except Exception as e:
        logger.debug(f"Token info error: {e}")

    return {
        'symbol': '???',
        'name': 'Unknown',
        'market_cap': 0,
        'liquidity': 0,
        'volume_5m': 0,
        'volume_1h': 0,
        'volume_24h': 0,
    }


def fetch_token_info_sync(token_address: str) -> Dict:
    """Synchronous wrapper for token info fetch."""
    import requests

    try:
        url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                pair = data[0]
                return {
                    'symbol': pair.get('baseToken', {}).get('symbol', '???'),
                    'name': pair.get('baseToken', {}).get('name', 'Unknown'),
                    'market_cap': float(pair.get('marketCap', 0) or 0),
                    'liquidity': float(pair.get('liquidity', {}).get('usd', 0) or 0),
                    'volume_5m': float(pair.get('volume', {}).get('m5', 0) or 0),
                    'volume_1h': float(pair.get('volume', {}).get('h1', 0) or 0),
                    'volume_24h': float(pair.get('volume', {}).get('h24', 0) or 0),
                }
    except Exception as e:
        logger.debug(f"Token info error: {e}")

    return {
        'symbol': '???',
        'name': 'Unknown',
        'market_cap': 0,
        'liquidity': 0,
        'volume_5m': 0,
        'volume_1h': 0,
        'volume_24h': 0,
    }


def process_buy(parsed: Dict, wallet_info: Dict) -> Dict:
    """
    Process a BUY transaction and create lifecycle position.

    Returns status dict.
    """
    wallet_address = parsed['wallet_address']
    token_address = parsed['token_address']
    sol_amount = parsed['sol_amount']
    timestamp = parsed['timestamp']
    signature = parsed['signature']

    # Check minimum SOL threshold
    if sol_amount < MIN_BUY_SOL:
        return {
            'action': 'skip',
            'reason': f'Below threshold ({sol_amount:.2f} < {MIN_BUY_SOL} SOL)'
        }

    # Check duplicate
    if check_duplicate_position(wallet_address, token_address, sol_amount):
        return {
            'action': 'skip',
            'reason': 'Duplicate position (same wallet+token within 24h)'
        }

    # Get token info
    token_info = fetch_token_info_sync(token_address)

    # Check if we should track this position
    wallet_type = wallet_info.get('type', 'qualified')
    wallet_tier = wallet_info.get('tier')

    if not should_track_position(sol_amount, wallet_tier, wallet_type):
        return {
            'action': 'skip',
            'reason': f'Does not meet tracking criteria ({wallet_type}/{wallet_tier})'
        }

    # Create lifecycle position
    tracker = get_lifecycle_tracker()

    try:
        position_id = tracker.create_position(
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol=token_info['symbol'],
            entry_timestamp=timestamp,
            entry_mc=token_info['market_cap'],
            entry_liquidity=token_info['liquidity'],
            buy_sol_amount=sol_amount,
            buy_event_id=None,
            wallet_type=wallet_type,
            wallet_tier=wallet_tier,
            alert_message_id=None,
        )

        if position_id:
            logger.info(
                f"📊 BUY TRACKED: {wallet_address[:8]}... | "
                f"${token_info['symbol']} | {sol_amount:.2f} SOL | "
                f"MC: ${token_info['market_cap']:,.0f}"
            )
            return {
                'action': 'created',
                'position_id': position_id,
                'token': token_info['symbol'],
                'sol': sol_amount,
                'mc': token_info['market_cap'],
            }
        else:
            return {
                'action': 'skip',
                'reason': 'Position already exists'
            }

    except Exception as e:
        logger.error(f"Error creating position: {e}")
        return {
            'action': 'error',
            'reason': str(e)
        }


def process_sell(parsed: Dict, wallet_info: Dict) -> Dict:
    """
    Process a SELL transaction.

    Records exit in wallet_exits table but KEEPS position open for 48h tracking.

    Returns status dict.
    """
    wallet_address = parsed['wallet_address']
    token_address = parsed['token_address']
    sol_amount = parsed['sol_amount']
    timestamp = parsed['timestamp']
    signature = parsed['signature']

    # Check minimum SOL threshold for tracking
    if sol_amount < MIN_SELL_SOL:
        return {
            'action': 'skip',
            'reason': f'Below threshold ({sol_amount:.2f} < {MIN_SELL_SOL} SOL)'
        }

    # Get token info
    token_info = fetch_token_info_sync(token_address)

    # Find matching open position(s) for this wallet+token
    tracker = get_lifecycle_tracker()

    position = tracker.get_oldest_open_position(wallet_address, token_address)

    if not position:
        # No tracked position for this sell - might have bought before tracking started
        logger.debug(
            f"SELL without position: {wallet_address[:8]}... | "
            f"{token_address[:8]}... | {sol_amount:.2f} SOL"
        )
        return {
            'action': 'skip',
            'reason': 'No matching open position'
        }

    position_id = position['id']
    entry_timestamp = position['entry_timestamp']
    buy_sol = position['buy_sol_amount']

    # Calculate ROI at exit
    roi_at_exit = 0
    if buy_sol > 0:
        roi_at_exit = ((sol_amount - buy_sol) / buy_sol) * 100

    # Calculate hold duration
    hold_duration_hours = (timestamp - entry_timestamp) / 3600.0

    # Record exit in wallet_exits table
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Check for duplicate signature
        cursor.execute(
            "SELECT id FROM wallet_exits WHERE signature = ?",
            (signature,)
        )
        if cursor.fetchone():
            conn.close()
            return {
                'action': 'skip',
                'reason': 'Duplicate transaction signature'
            }

        # Insert exit record
        cursor.execute("""
            INSERT INTO wallet_exits (
                position_id, wallet_address, token_address,
                exit_timestamp, sell_sol_received, exit_mc,
                hold_duration_hours, roi_at_exit, signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position_id,
            wallet_address,
            token_address,
            timestamp,
            sol_amount,
            token_info['market_cap'],
            hold_duration_hours,
            roi_at_exit,
            signature,
        ))

        # Update elite exit counts on position_lifecycle
        cursor.execute("""
            UPDATE position_lifecycle
            SET elite_exit_count = elite_exit_count + 1,
                first_elite_exit_timestamp = COALESCE(first_elite_exit_timestamp, ?),
                updated_at = ?
            WHERE id = ?
        """, (timestamp, datetime.now().isoformat(), position_id))

        # Also update via lifecycle tracker to record sell
        tracker.record_sell_event(
            position_id=position_id,
            exit_timestamp=timestamp,
            sell_sol_received=sol_amount,
            sell_event_id=None,
        )

        conn.commit()
        conn.close()

        logger.info(
            f"💰 SELL TRACKED: {wallet_address[:8]}... | "
            f"${token_info['symbol']} | {sol_amount:.2f} SOL | "
            f"ROI: {roi_at_exit:+.1f}% | Hold: {hold_duration_hours:.1f}h | "
            f"Position stays OPEN for lifecycle tracking"
        )

        return {
            'action': 'recorded',
            'position_id': position_id,
            'token': token_info['symbol'],
            'sol': sol_amount,
            'roi': roi_at_exit,
            'hold_hours': hold_duration_hours,
        }

    except Exception as e:
        logger.error(f"Error recording sell: {e}")
        return {
            'action': 'error',
            'reason': str(e)
        }


def update_elite_holding_counts(token_address: str):
    """
    Update elite_still_holding count for all positions of this token.

    Called after recording a sell to update the count of wallets still holding.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Get all open positions for this token
        cursor.execute("""
            SELECT id, wallet_address
            FROM position_lifecycle
            WHERE token_address = ?
            AND (outcome IS NULL OR outcome = 'open')
        """, (token_address,))

        positions = cursor.fetchall()
        total_positions = len(positions)

        # Count how many have exited
        cursor.execute("""
            SELECT COUNT(DISTINCT wallet_address)
            FROM wallet_exits
            WHERE token_address = ?
        """, (token_address,))

        exited_count = cursor.fetchone()[0] or 0
        still_holding = total_positions - exited_count

        # Update all positions for this token
        cursor.execute("""
            UPDATE position_lifecycle
            SET elite_still_holding = ?,
                updated_at = ?
            WHERE token_address = ?
            AND (outcome IS NULL OR outcome = 'open')
        """, (still_holding, datetime.now().isoformat(), token_address))

        conn.commit()
        conn.close()

        logger.debug(
            f"Updated holding counts for {token_address[:8]}...: "
            f"{still_holding} holding, {exited_count} exited"
        )

    except Exception as e:
        logger.error(f"Error updating holding counts: {e}")


@app.route('/webhook/helius', methods=['POST'])
def helius_webhook():
    """
    Receive Helius webhook for SWAP transactions.

    Expected payload:
    [
        {
            "signature": "...",
            "timestamp": 1234567890,
            "tokenTransfers": [...],
            "nativeTransfers": [...],
            ...
        }
    ]
    """
    try:
        # Parse incoming data
        data = request.get_json()

        if not data:
            return jsonify({'error': 'No data received'}), 400

        # Handle both single tx and array of txs
        transactions = data if isinstance(data, list) else [data]

        results = []
        buys_processed = 0
        sells_processed = 0

        for tx in transactions:
            # Parse the swap
            parsed = parse_helius_swap(tx)

            if not parsed:
                results.append({'action': 'skip', 'reason': 'Not a valid swap'})
                continue

            # Get wallet info
            wallet_info = is_elite_wallet(parsed['wallet_address'])

            if not wallet_info:
                results.append({'action': 'skip', 'reason': 'Not an elite wallet'})
                continue

            # Process based on type
            if parsed['type'] == 'buy':
                result = process_buy(parsed, wallet_info)
                if result.get('action') == 'created':
                    buys_processed += 1
            elif parsed['type'] == 'sell':
                result = process_sell(parsed, wallet_info)
                if result.get('action') == 'recorded':
                    sells_processed += 1
                    # Update holding counts
                    update_elite_holding_counts(parsed['token_address'])
            else:
                result = {'action': 'skip', 'reason': 'Unknown type'}

            results.append(result)

        return jsonify({
            'status': 'ok',
            'processed': len(transactions),
            'buys': buys_processed,
            'sells': sells_processed,
            'results': results,
        })

    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    wallets = load_qualified_wallets()
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'qualified_wallets': len(wallets),
    })


@app.route('/stats', methods=['GET'])
def get_stats():
    """Get webhook processing statistics."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Open positions
        cursor.execute("""
            SELECT COUNT(*) FROM position_lifecycle
            WHERE outcome IS NULL OR outcome = 'open'
        """)
        open_positions = cursor.fetchone()[0]

        # Positions today
        today_start = int(time.time()) - (int(time.time()) % 86400)
        cursor.execute("""
            SELECT COUNT(*) FROM position_lifecycle
            WHERE entry_timestamp > ?
        """, (today_start,))
        positions_today = cursor.fetchone()[0]

        # Exits today
        cursor.execute("""
            SELECT COUNT(*) FROM wallet_exits
            WHERE exit_timestamp > ?
        """, (today_start,))
        exits_today = cursor.fetchone()[0]

        # Labeled outcomes
        cursor.execute("""
            SELECT outcome, COUNT(*) FROM position_lifecycle
            WHERE outcome IS NOT NULL AND outcome != 'open'
            GROUP BY outcome
        """)
        outcomes = dict(cursor.fetchall())

        conn.close()

        return jsonify({
            'open_positions': open_positions,
            'positions_today': positions_today,
            'exits_today': exits_today,
            'outcomes': outcomes,
            'qualified_wallets': len(load_qualified_wallets()),
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Helius Webhook Server')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    args = parser.parse_args()

    # Load wallets on startup
    wallets = load_qualified_wallets()
    logger.info(f"Starting webhook server with {len(wallets)} elite wallets")

    app.run(host=args.host, port=args.port, debug=args.debug)
