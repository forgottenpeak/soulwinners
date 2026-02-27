"""
SoulWinners Trading API Bridge
REST API server for remote trade execution from OpenClaw

Endpoints:
- POST /api/execute_buy     - Execute buy order
- POST /api/execute_sell    - Execute sell order
- GET  /api/status          - Get trader status
- POST /api/update_strategy - Update strategy settings
- GET  /api/health          - Health check

Authentication: Bearer token in Authorization header
"""
import os
import logging
import secrets
import asyncio
from datetime import datetime
from typing import Optional, Dict
from functools import wraps

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Import trader components
from trader.solana_dex import JupiterDEX
from trader.position_manager import PositionManager
from trader.strategy import TradingStrategy, StrategyConfig

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/trading_api.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for remote access

# Configuration
API_TOKEN = os.getenv('TRADING_API_TOKEN') or secrets.token_urlsafe(32)
OPENCLAW_PRIVATE_KEY = os.getenv('OPENCLAW_PRIVATE_KEY')
RPC_URL = os.getenv('SOLANA_RPC_URL', 'https://api.mainnet-beta.solana.com')

# Global instances
position_manager = PositionManager()
strategy = TradingStrategy()
dex: Optional[JupiterDEX] = None

# Rate limiting (simple in-memory)
request_count: Dict[str, list] = {}


def require_auth(f):
    """Decorator to require Bearer token authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')

        if not auth_header:
            logger.warning(f"Missing auth header from {request.remote_addr}")
            return jsonify({'error': 'Missing Authorization header'}), 401

        if not auth_header.startswith('Bearer '):
            logger.warning(f"Invalid auth format from {request.remote_addr}")
            return jsonify({'error': 'Invalid Authorization format'}), 401

        token = auth_header.split('Bearer ')[1]

        if token != API_TOKEN:
            logger.warning(f"Invalid token from {request.remote_addr}")
            return jsonify({'error': 'Invalid token'}), 403

        return f(*args, **kwargs)

    return decorated_function


def rate_limit(max_requests: int = 60, window_seconds: int = 60):
    """Simple rate limiting decorator."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            client_ip = request.remote_addr
            now = datetime.now().timestamp()

            # Clean old requests
            if client_ip in request_count:
                request_count[client_ip] = [
                    ts for ts in request_count[client_ip]
                    if now - ts < window_seconds
                ]
            else:
                request_count[client_ip] = []

            # Check rate limit
            if len(request_count[client_ip]) >= max_requests:
                logger.warning(f"Rate limit exceeded for {client_ip}")
                return jsonify({'error': 'Rate limit exceeded'}), 429

            # Add current request
            request_count[client_ip].append(now)

            return f(*args, **kwargs)

        return decorated_function
    return decorator


async def init_dex():
    """Initialize DEX connection."""
    global dex

    if not OPENCLAW_PRIVATE_KEY:
        logger.error("OPENCLAW_PRIVATE_KEY not set")
        return False

    try:
        dex = JupiterDEX(OPENCLAW_PRIVATE_KEY, RPC_URL)
        await dex.__aenter__()
        logger.info("DEX connection initialized")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize DEX: {e}")
        return False


def run_async(coro):
    """Run async coroutine in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint (no auth required)."""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'dex_connected': dex is not None,
    })


@app.route('/api/status', methods=['GET'])
@require_auth
@rate_limit(max_requests=120, window_seconds=60)
def get_status():
    """Get current trading status."""
    try:
        stats = position_manager.get_stats()
        positions = position_manager.get_open_positions()

        # Get balance if DEX connected
        balance = None
        if dex:
            try:
                balance = run_async(dex.get_sol_balance())
            except Exception as e:
                logger.error(f"Failed to get balance: {e}")

        return jsonify({
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'balance_sol': balance,
            'stats': stats,
            'open_positions': len(positions),
            'positions': [p.to_dict() for p in positions],
        })

    except Exception as e:
        logger.error(f"Status error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/execute_buy', methods=['POST'])
@require_auth
@rate_limit(max_requests=20, window_seconds=60)
def execute_buy():
    """
    Execute a buy order.

    Request body:
    {
        "token_mint": "...",
        "token_symbol": "...",
        "sol_amount": 0.1,
        "source_wallet": "...",
        "signal_metadata": {...}
    }
    """
    try:
        data = request.json

        # Validate request
        required_fields = ['token_mint', 'token_symbol', 'sol_amount']
        missing = [f for f in required_fields if f not in data]
        if missing:
            return jsonify({
                'success': False,
                'error': f'Missing required fields: {missing}'
            }), 400

        token_mint = data['token_mint']
        token_symbol = data['token_symbol']
        sol_amount = float(data['sol_amount'])
        source_wallet = data.get('source_wallet', 'unknown')

        # Validate inputs
        if sol_amount <= 0:
            return jsonify({
                'success': False,
                'error': 'sol_amount must be positive'
            }), 400

        # Check if DEX is connected
        if not dex:
            return jsonify({
                'success': False,
                'error': 'DEX not initialized'
            }), 503

        # Check if we can open position
        if not position_manager.can_open_position():
            return jsonify({
                'success': False,
                'error': 'Max positions reached (3/3)'
            }), 400

        # Check if already holding
        if position_manager.has_position(token_mint):
            return jsonify({
                'success': False,
                'error': f'Already holding position in {token_symbol}'
            }), 400

        logger.info(f"Executing buy: {sol_amount} SOL of {token_symbol}")

        # Execute buy
        result = run_async(dex.buy_token(token_mint, sol_amount))

        if not result or not result.get('success'):
            error_msg = result.get('error', 'Unknown error') if result else 'No result'
            logger.error(f"Buy failed: {error_msg}")
            return jsonify({
                'success': False,
                'error': error_msg
            }), 500

        # Get token balance and price
        token_balance = run_async(dex.get_token_balance(token_mint))
        token_price = run_async(dex.get_token_price(token_mint)) or 0
        sol_price = run_async(dex.get_sol_price()) or 78.0

        entry_price = (sol_amount * sol_price) / token_balance if token_balance > 0 else 0

        # Open position
        position = position_manager.open_position(
            token_mint=token_mint,
            token_symbol=token_symbol,
            entry_price=entry_price,
            entry_sol=sol_amount,
            token_amount=token_balance,
            source_wallet=source_wallet,
            entry_signature=result['signature']
        )

        logger.info(f"Position opened: {token_symbol} | {sol_amount} SOL | Sig: {result['signature'][:16]}...")

        return jsonify({
            'success': True,
            'signature': result['signature'],
            'token_amount': token_balance,
            'entry_price': entry_price,
            'position': position.to_dict() if position else None,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Buy execution error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/execute_sell', methods=['POST'])
@require_auth
@rate_limit(max_requests=20, window_seconds=60)
def execute_sell():
    """
    Execute a sell order.

    Request body:
    {
        "token_mint": "...",
        "sell_percent": 50.0,  # or 100 for full exit
        "reason": "tp1" | "tp2" | "stop" | "manual"
    }
    """
    try:
        data = request.json

        # Validate request
        required_fields = ['token_mint', 'sell_percent']
        missing = [f for f in required_fields if f not in data]
        if missing:
            return jsonify({
                'success': False,
                'error': f'Missing required fields: {missing}'
            }), 400

        token_mint = data['token_mint']
        sell_percent = float(data['sell_percent'])
        reason = data.get('reason', 'manual')

        # Validate inputs
        if sell_percent <= 0 or sell_percent > 100:
            return jsonify({
                'success': False,
                'error': 'sell_percent must be between 0 and 100'
            }), 400

        # Check if DEX is connected
        if not dex:
            return jsonify({
                'success': False,
                'error': 'DEX not initialized'
            }), 503

        # Find position
        positions = position_manager.get_open_positions()
        position = None
        for pos in positions:
            if pos.token_mint == token_mint:
                position = pos
                break

        if not position:
            return jsonify({
                'success': False,
                'error': 'Position not found or already closed'
            }), 404

        logger.info(f"Executing sell: {sell_percent}% of {position.token_symbol} ({reason})")

        # Execute sell
        token_decimals = 6  # Most SPL tokens use 6 decimals
        result = run_async(dex.sell_token_percentage(
            token_mint,
            sell_percent,
            token_decimals
        ))

        if not result or not result.get('success'):
            error_msg = result.get('error', 'Unknown error') if result else 'No result'
            logger.error(f"Sell failed: {error_msg}")
            return jsonify({
                'success': False,
                'error': error_msg
            }), 500

        exit_sol = result['output_amount']

        # Update position
        if sell_percent >= 100:
            updated_position = position_manager.close_position(
                token_mint,
                exit_sol,
                result['signature'],
                reason
            )
        else:
            updated_position = position_manager.partial_close(
                token_mint,
                sell_percent,
                exit_sol,
                result['signature'],
                reason
            )

        logger.info(f"Position updated: {position.token_symbol} | {exit_sol} SOL | Sig: {result['signature'][:16]}...")

        return jsonify({
            'success': True,
            'signature': result['signature'],
            'sol_received': exit_sol,
            'sell_percent': sell_percent,
            'position': updated_position.to_dict() if updated_position else None,
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Sell execution error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/update_strategy', methods=['POST'])
@require_auth
@rate_limit(max_requests=30, window_seconds=60)
def update_strategy():
    """
    Update strategy settings.

    Request body:
    {
        "stop_loss_percent": -20.0,
        "tp1_percent": 50.0,
        "tp2_percent": 100.0,
        "position_size_percent": 70.0
    }
    """
    try:
        data = request.json

        # Update strategy config
        config = strategy.config
        updated_fields = []

        if 'stop_loss_percent' in data:
            config.stop_loss_percent = float(data['stop_loss_percent'])
            updated_fields.append('stop_loss_percent')

        if 'tp1_percent' in data:
            config.tp1_percent = float(data['tp1_percent'])
            updated_fields.append('tp1_percent')

        if 'tp2_percent' in data:
            config.tp2_percent = float(data['tp2_percent'])
            updated_fields.append('tp2_percent')

        if 'position_size_percent' in data:
            config.position_size_percent = float(data['position_size_percent'])
            updated_fields.append('position_size_percent')

        if 'tp1_sell_percent' in data:
            config.tp1_sell_percent = float(data['tp1_sell_percent'])
            updated_fields.append('tp1_sell_percent')

        if 'tp2_sell_percent' in data:
            config.tp2_sell_percent = float(data['tp2_sell_percent'])
            updated_fields.append('tp2_sell_percent')

        logger.info(f"Strategy updated: {updated_fields}")

        return jsonify({
            'success': True,
            'updated_fields': updated_fields,
            'current_config': {
                'stop_loss_percent': config.stop_loss_percent,
                'tp1_percent': config.tp1_percent,
                'tp2_percent': config.tp2_percent,
                'position_size_percent': config.position_size_percent,
                'tp1_sell_percent': config.tp1_sell_percent,
                'tp2_sell_percent': config.tp2_sell_percent,
            },
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Strategy update error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/positions', methods=['GET'])
@require_auth
@rate_limit(max_requests=120, window_seconds=60)
def get_positions():
    """Get all open positions."""
    try:
        positions = position_manager.get_open_positions()

        return jsonify({
            'success': True,
            'count': len(positions),
            'positions': [p.to_dict() for p in positions],
            'timestamp': datetime.now().isoformat()
        })

    except Exception as e:
        logger.error(f"Get positions error: {e}", exc_info=True)
        return jsonify({'success': False, 'error': str(e)}), 500


# Error handlers
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    logger.error(f"Internal error: {error}")
    return jsonify({'error': 'Internal server error'}), 500


def main():
    """Start the API server."""
    import sys
    from pathlib import Path

    # Ensure logs directory exists
    Path('logs').mkdir(exist_ok=True)

    logger.info("=" * 60)
    logger.info("SOULWINNERS TRADING API STARTING")
    logger.info("=" * 60)

    # Check for private key
    if not OPENCLAW_PRIVATE_KEY:
        logger.error("OPENCLAW_PRIVATE_KEY not set in .env")
        logger.error("Trading API cannot function without wallet key")
        sys.exit(1)

    # Generate token if needed
    if not os.getenv('TRADING_API_TOKEN'):
        logger.warning("TRADING_API_TOKEN not set, using generated token")
        logger.warning(f"Generated token: {API_TOKEN}")
        logger.warning("Add this to your .env file:")
        logger.warning(f"TRADING_API_TOKEN={API_TOKEN}")

    logger.info(f"API Token: {API_TOKEN[:16]}...{API_TOKEN[-8:]}")
    logger.info(f"DEX RPC: {RPC_URL}")

    # Initialize DEX
    logger.info("Initializing DEX connection...")
    if not run_async(init_dex()):
        logger.error("Failed to initialize DEX")
        sys.exit(1)

    logger.info("DEX connection successful")

    # Start server
    port = int(os.getenv('API_PORT', 5000))
    logger.info(f"Starting API server on port {port}")
    logger.info("API Endpoints:")
    logger.info("  GET  /api/health")
    logger.info("  GET  /api/status")
    logger.info("  GET  /api/positions")
    logger.info("  POST /api/execute_buy")
    logger.info("  POST /api/execute_sell")
    logger.info("  POST /api/update_strategy")
    logger.info("")
    logger.info("API server ready for connections")
    logger.info("=" * 60)

    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True
    )


if __name__ == '__main__':
    main()
