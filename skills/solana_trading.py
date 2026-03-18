"""
Hedgehog Solana Trading Skills
Complete trading capabilities for Solana tokens
"""
import json
import os
import time
import base64
import struct
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from skills.base import get_registry

# Configuration
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY", "")
SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}")
JUPITER_API_URL = os.getenv("JUPITER_API_URL", "https://quote-api.jup.ag/v6")
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY", "")

# Constants
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
LAMPORTS_PER_SOL = 1_000_000_000

# Trading safety limits (configurable via env)
MAX_POSITION_PERCENT = float(os.getenv("MAX_POSITION_PERCENT", "10"))  # Max 10% per trade
SLIPPAGE_BPS = int(os.getenv("SLIPPAGE_BPS", "100"))  # 1% default slippage
STOP_LOSS_PERCENT = float(os.getenv("STOP_LOSS_PERCENT", "50"))  # -50% stop loss

# Action log for tracking all operations
ACTION_LOG_PATH = Path(__file__).parent.parent / "memory" / "action_log.json"


def _log_action(action: str, params: Dict, result: Dict):
    """Log all trading actions for audit trail"""
    try:
        ACTION_LOG_PATH.parent.mkdir(exist_ok=True)

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "params": params,
            "result": result,
        }

        # Load existing log
        if ACTION_LOG_PATH.exists():
            logs = json.loads(ACTION_LOG_PATH.read_text())
        else:
            logs = []

        logs.append(log_entry)

        # Keep last 1000 entries
        logs = logs[-1000:]
        ACTION_LOG_PATH.write_text(json.dumps(logs, indent=2, default=str))
    except Exception as e:
        print(f"Warning: Failed to log action: {e}")


def _rpc_request(method: str, params: List = None, retries: int = 3) -> Dict:
    """Make RPC request with retry logic"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or [],
    }

    for attempt in range(retries):
        try:
            req = Request(
                SOLANA_RPC_URL,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())

                if "error" in result:
                    raise Exception(result["error"].get("message", "RPC Error"))

                return result.get("result", {})

        except (HTTPError, URLError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
                continue
            raise Exception(f"RPC request failed after {retries} attempts: {e}")

    return {}


def _jupiter_request(endpoint: str, method: str = "GET", data: Dict = None) -> Dict:
    """Make Jupiter API request"""
    url = f"{JUPITER_API_URL}/{endpoint}"

    try:
        if method == "GET" and data:
            params = "&".join(f"{k}={v}" for k, v in data.items())
            url = f"{url}?{params}"
            req = Request(url, method="GET")
        else:
            req = Request(
                url,
                data=json.dumps(data).encode() if data else None,
                headers={"Content-Type": "application/json"},
                method=method,
            )

        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())

    except Exception as e:
        raise Exception(f"Jupiter API error: {e}")


def _get_wallet_pubkey() -> str:
    """Get wallet public key from private key"""
    if not WALLET_PRIVATE_KEY:
        raise ValueError("WALLET_PRIVATE_KEY not set")

    # For now, assume pubkey is stored separately or derive it
    pubkey = os.getenv("WALLET_PUBLIC_KEY", "")
    if pubkey:
        return pubkey

    # If using base58 encoded private key, we'd need solders to derive
    raise ValueError("WALLET_PUBLIC_KEY not set. Set it or install solders for derivation.")


# =============================================================================
# WALLET MANAGEMENT
# =============================================================================

def get_wallet_balance() -> Dict:
    """
    Get wallet SOL balance and all token holdings

    Returns:
        Dict with SOL balance, token balances, and total USD value
    """
    try:
        pubkey = _get_wallet_pubkey()

        # Get SOL balance
        sol_result = _rpc_request("getBalance", [pubkey])
        sol_balance = sol_result.get("value", 0) / LAMPORTS_PER_SOL

        # Get token accounts
        token_result = _rpc_request("getTokenAccountsByOwner", [
            pubkey,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"}
        ])

        tokens = []
        total_token_value_usd = 0

        for account in token_result.get("value", []):
            parsed = account.get("account", {}).get("data", {}).get("parsed", {})
            info = parsed.get("info", {})
            token_amount = info.get("tokenAmount", {})

            if float(token_amount.get("uiAmount", 0)) > 0:
                tokens.append({
                    "mint": info.get("mint"),
                    "balance": token_amount.get("uiAmount"),
                    "decimals": token_amount.get("decimals"),
                })

        # Get SOL price for USD value
        sol_price = _get_token_price(SOL_MINT)
        sol_value_usd = sol_balance * sol_price if sol_price else 0

        result = {
            "wallet": pubkey,
            "sol_balance": sol_balance,
            "sol_value_usd": round(sol_value_usd, 2),
            "sol_price": sol_price,
            "token_count": len(tokens),
            "tokens": tokens[:20],  # First 20 tokens
        }

        _log_action("get_wallet_balance", {}, result)
        return result

    except Exception as e:
        return {"error": str(e)}


def get_wallet_address() -> Dict:
    """
    Get the wallet public key/address

    Returns:
        Dict with wallet address
    """
    try:
        pubkey = _get_wallet_pubkey()
        return {
            "address": pubkey,
            "explorer_url": f"https://solscan.io/account/{pubkey}",
        }
    except Exception as e:
        return {"error": str(e)}


def get_recent_transactions(limit: int = 20) -> Dict:
    """
    Get recent wallet transactions

    Args:
        limit: Number of transactions to fetch (max 50)

    Returns:
        Dict with recent transactions
    """
    try:
        pubkey = _get_wallet_pubkey()
        limit = min(limit, 50)

        result = _rpc_request("getSignaturesForAddress", [
            pubkey,
            {"limit": limit}
        ])

        transactions = []
        for sig in result:
            transactions.append({
                "signature": sig.get("signature"),
                "slot": sig.get("slot"),
                "block_time": sig.get("blockTime"),
                "status": "success" if sig.get("err") is None else "failed",
                "memo": sig.get("memo"),
            })

        return {
            "wallet": pubkey,
            "transaction_count": len(transactions),
            "transactions": transactions,
        }

    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# TOKEN OPERATIONS
# =============================================================================

def _get_token_price(mint: str) -> Optional[float]:
    """Get token price from Jupiter"""
    try:
        result = _jupiter_request("price", "GET", {"ids": mint})
        data = result.get("data", {}).get(mint, {})
        return float(data.get("price", 0))
    except:
        return None


def get_token_info(address: str) -> Dict:
    """
    Get comprehensive token information

    Args:
        address: Token mint address

    Returns:
        Dict with price, holders, liquidity, age, etc.
    """
    try:
        # Get token account info
        account_info = _rpc_request("getAccountInfo", [
            address,
            {"encoding": "jsonParsed"}
        ])

        # Get price from Jupiter
        price = _get_token_price(address)

        # Get token supply
        supply_result = _rpc_request("getTokenSupply", [address])
        supply = supply_result.get("value", {})

        # Try to get metadata (simplified)
        result = {
            "mint": address,
            "price_usd": price,
            "total_supply": supply.get("uiAmount"),
            "decimals": supply.get("decimals"),
            "explorer_url": f"https://solscan.io/token/{address}",
        }

        # Try Helius DAS API for more metadata
        try:
            das_result = _helius_get_asset(address)
            if das_result:
                result["name"] = das_result.get("content", {}).get("metadata", {}).get("name")
                result["symbol"] = das_result.get("content", {}).get("metadata", {}).get("symbol")
        except:
            pass

        _log_action("get_token_info", {"address": address}, result)
        return result

    except Exception as e:
        return {"error": str(e), "address": address}


def _helius_get_asset(mint: str) -> Optional[Dict]:
    """Get asset info from Helius DAS API"""
    if not HELIUS_API_KEY:
        return None

    try:
        url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAsset",
            "params": {"id": mint}
        }

        req = Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode())
            return result.get("result")
    except:
        return None


def check_token_safety(address: str) -> Dict:
    """
    Check token safety (rug pull indicators)

    Args:
        address: Token mint address

    Returns:
        Dict with safety checks (honeypot, freeze authority, etc.)
    """
    try:
        # Get mint account info
        account_info = _rpc_request("getAccountInfo", [
            address,
            {"encoding": "jsonParsed"}
        ])

        parsed_data = account_info.get("value", {}).get("data", {}).get("parsed", {})
        info = parsed_data.get("info", {})

        # Safety checks
        checks = {
            "mint": address,
            "freeze_authority": info.get("freezeAuthority"),
            "mint_authority": info.get("mintAuthority"),
            "has_freeze_authority": info.get("freezeAuthority") is not None,
            "has_mint_authority": info.get("mintAuthority") is not None,
        }

        # Risk assessment
        risk_score = 0
        risk_factors = []

        if checks["has_freeze_authority"]:
            risk_score += 30
            risk_factors.append("Has freeze authority - tokens can be frozen")

        if checks["has_mint_authority"]:
            risk_score += 20
            risk_factors.append("Has mint authority - more tokens can be minted")

        checks["risk_score"] = risk_score
        checks["risk_factors"] = risk_factors
        checks["risk_level"] = "HIGH" if risk_score >= 40 else "MEDIUM" if risk_score >= 20 else "LOW"

        _log_action("check_token_safety", {"address": address}, checks)
        return checks

    except Exception as e:
        return {"error": str(e), "address": address}


def get_token_holders(address: str, limit: int = 10) -> Dict:
    """
    Get top token holders and distribution

    Args:
        address: Token mint address
        limit: Number of top holders to return

    Returns:
        Dict with holder distribution
    """
    try:
        # Get largest token accounts
        result = _rpc_request("getTokenLargestAccounts", [address])

        accounts = result.get("value", [])

        # Get total supply for percentage calculation
        supply_result = _rpc_request("getTokenSupply", [address])
        total_supply = float(supply_result.get("value", {}).get("uiAmount", 1))

        holders = []
        top_10_percent = 0

        for i, account in enumerate(accounts[:limit]):
            amount = float(account.get("uiAmount", 0))
            percent = (amount / total_supply * 100) if total_supply > 0 else 0

            if i < 10:
                top_10_percent += percent

            holders.append({
                "address": account.get("address"),
                "amount": amount,
                "percent": round(percent, 2),
            })

        result = {
            "mint": address,
            "total_supply": total_supply,
            "holder_count": len(accounts),
            "top_10_concentration": round(top_10_percent, 2),
            "holders": holders,
            "concentration_risk": "HIGH" if top_10_percent > 80 else "MEDIUM" if top_10_percent > 50 else "LOW",
        }

        _log_action("get_token_holders", {"address": address}, result)
        return result

    except Exception as e:
        return {"error": str(e), "address": address}


# =============================================================================
# TRADING EXECUTION
# =============================================================================

def execute_swap(
    token_in: str,
    token_out: str,
    amount_in: float,
    slippage: float = 0.01
) -> Dict:
    """
    Execute token swap via Jupiter aggregator

    REQUIRES APPROVAL - Executes a real trade

    Args:
        token_in: Input token mint address (or "SOL")
        token_out: Output token mint address (or "SOL")
        amount_in: Amount of input token
        slippage: Slippage tolerance (0.01 = 1%)

    Returns:
        Dict with tx_hash, amount_out, price_impact
    """
    try:
        # Normalize token addresses
        input_mint = SOL_MINT if token_in.upper() == "SOL" else token_in
        output_mint = SOL_MINT if token_out.upper() == "SOL" else token_out

        # Get decimals for amount conversion
        if input_mint == SOL_MINT:
            decimals = 9
        else:
            supply = _rpc_request("getTokenSupply", [input_mint])
            decimals = supply.get("value", {}).get("decimals", 9)

        amount_lamports = int(amount_in * (10 ** decimals))
        slippage_bps = int(slippage * 10000)

        # Safety check: ensure we're not trading too much
        wallet_balance = get_wallet_balance()
        if "error" not in wallet_balance:
            if input_mint == SOL_MINT:
                max_trade = wallet_balance["sol_balance"] * (MAX_POSITION_PERCENT / 100)
                if amount_in > max_trade:
                    return {
                        "error": f"Trade exceeds {MAX_POSITION_PERCENT}% limit",
                        "max_allowed": max_trade,
                        "requested": amount_in,
                    }

        # Get quote from Jupiter
        quote = _jupiter_request("quote", "GET", {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": amount_lamports,
            "slippageBps": slippage_bps,
        })

        if "error" in quote:
            return {"error": f"Failed to get quote: {quote.get('error')}"}

        # Get swap transaction
        pubkey = _get_wallet_pubkey()
        swap_response = _jupiter_request("swap", "POST", {
            "quoteResponse": quote,
            "userPublicKey": pubkey,
            "wrapAndUnwrapSol": True,
        })

        if "error" in swap_response:
            return {"error": f"Failed to get swap tx: {swap_response.get('error')}"}

        # At this point, we have the unsigned transaction
        # In production, this would be signed and sent
        result = {
            "status": "prepared",
            "input_token": token_in,
            "output_token": token_out,
            "input_amount": amount_in,
            "output_amount": int(quote.get("outAmount", 0)) / (10 ** 9),  # Assuming 9 decimals
            "price_impact": quote.get("priceImpactPct"),
            "route": f"{len(quote.get('routePlan', []))} hop(s)",
            "note": "Transaction prepared. Sign and send to execute.",
            "swap_transaction": swap_response.get("swapTransaction")[:100] + "..." if swap_response.get("swapTransaction") else None,
        }

        _log_action("execute_swap", {
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": amount_in,
        }, result)

        return result

    except Exception as e:
        return {"error": str(e)}


def copy_insider_trade(
    wallet_address: str,
    token_address: str,
    percentage: int = 100
) -> Dict:
    """
    Mirror an insider wallet's position

    REQUIRES APPROVAL - Executes a real trade

    Args:
        wallet_address: Insider wallet to copy
        token_address: Token they bought
        percentage: What percentage of their trade size to copy (scaled to our wallet)

    Returns:
        Dict with trade details
    """
    try:
        # Get insider's position size
        insider_accounts = _rpc_request("getTokenAccountsByOwner", [
            wallet_address,
            {"mint": token_address},
            {"encoding": "jsonParsed"}
        ])

        insider_balance = 0
        for account in insider_accounts.get("value", []):
            amount = account.get("account", {}).get("data", {}).get("parsed", {}).get("info", {}).get("tokenAmount", {})
            insider_balance += float(amount.get("uiAmount", 0))

        if insider_balance == 0:
            return {"error": "Insider has no position in this token"}

        # Get our wallet balance
        our_balance = get_wallet_balance()
        if "error" in our_balance:
            return our_balance

        our_sol = our_balance["sol_balance"]

        # Calculate trade size (scaled)
        # Use percentage of what insider has, but cap at our limit
        max_trade_sol = our_sol * (MAX_POSITION_PERCENT / 100)
        trade_sol = min(max_trade_sol, our_sol * (percentage / 100))

        # Execute the swap
        return execute_swap(
            token_in="SOL",
            token_out=token_address,
            amount_in=trade_sol,
        )

    except Exception as e:
        return {"error": str(e)}


def take_profit(token_address: str, percentage: int = 50) -> Dict:
    """
    Take profit on a position by selling a percentage

    REQUIRES APPROVAL - Executes a real trade

    Args:
        token_address: Token to sell
        percentage: Percentage of holding to sell (1-100)

    Returns:
        Dict with trade details
    """
    try:
        if not 1 <= percentage <= 100:
            return {"error": "Percentage must be between 1 and 100"}

        # Get our token balance
        pubkey = _get_wallet_pubkey()
        accounts = _rpc_request("getTokenAccountsByOwner", [
            pubkey,
            {"mint": token_address},
            {"encoding": "jsonParsed"}
        ])

        token_balance = 0
        for account in accounts.get("value", []):
            amount = account.get("account", {}).get("data", {}).get("parsed", {}).get("info", {}).get("tokenAmount", {})
            token_balance += float(amount.get("uiAmount", 0))

        if token_balance == 0:
            return {"error": "No position in this token"}

        sell_amount = token_balance * (percentage / 100)

        return execute_swap(
            token_in=token_address,
            token_out="SOL",
            amount_in=sell_amount,
        )

    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# POSITION TRACKING
# =============================================================================

def get_open_positions() -> Dict:
    """
    Get all current token holdings with values

    Returns:
        Dict with all positions and PnL where available
    """
    try:
        balance = get_wallet_balance()
        if "error" in balance:
            return balance

        positions = []
        total_value_usd = balance.get("sol_value_usd", 0)

        for token in balance.get("tokens", []):
            mint = token.get("mint")
            amount = token.get("balance", 0)

            if amount > 0:
                price = _get_token_price(mint)
                value_usd = amount * price if price else 0
                total_value_usd += value_usd

                positions.append({
                    "token": mint[:8] + "...",
                    "mint": mint,
                    "balance": amount,
                    "price_usd": price,
                    "value_usd": round(value_usd, 2),
                })

        # Sort by value
        positions.sort(key=lambda x: x.get("value_usd", 0), reverse=True)

        return {
            "sol_balance": balance.get("sol_balance"),
            "sol_value_usd": balance.get("sol_value_usd"),
            "position_count": len(positions),
            "positions": positions[:20],
            "total_portfolio_usd": round(total_value_usd, 2),
        }

    except Exception as e:
        return {"error": str(e)}


def get_position_pnl(token_address: str) -> Dict:
    """
    Get profit/loss for a specific position

    Args:
        token_address: Token mint address

    Returns:
        Dict with entry price, current price, PnL
    """
    try:
        # Get current holding
        pubkey = _get_wallet_pubkey()
        accounts = _rpc_request("getTokenAccountsByOwner", [
            pubkey,
            {"mint": token_address},
            {"encoding": "jsonParsed"}
        ])

        token_balance = 0
        for account in accounts.get("value", []):
            amount = account.get("account", {}).get("data", {}).get("parsed", {}).get("info", {}).get("tokenAmount", {})
            token_balance += float(amount.get("uiAmount", 0))

        if token_balance == 0:
            return {"error": "No position in this token", "token": token_address}

        # Get current price
        current_price = _get_token_price(token_address)
        current_value = token_balance * current_price if current_price else 0

        # Try to get entry price from action log
        entry_price = None
        entry_value = None

        if ACTION_LOG_PATH.exists():
            logs = json.loads(ACTION_LOG_PATH.read_text())
            for log in reversed(logs):
                if (log.get("action") == "execute_swap" and
                    log.get("params", {}).get("token_out") == token_address):
                    # Found our entry
                    result = log.get("result", {})
                    entry_value = result.get("input_amount", 0)  # SOL spent
                    break

        pnl_usd = None
        pnl_percent = None

        if entry_value and current_value:
            pnl_usd = current_value - entry_value
            pnl_percent = ((current_value / entry_value) - 1) * 100 if entry_value > 0 else 0

        return {
            "token": token_address,
            "balance": token_balance,
            "current_price": current_price,
            "current_value_usd": round(current_value, 2) if current_value else None,
            "entry_value_sol": entry_value,
            "pnl_usd": round(pnl_usd, 2) if pnl_usd else None,
            "pnl_percent": round(pnl_percent, 2) if pnl_percent else None,
            "status": "PROFIT" if pnl_percent and pnl_percent > 0 else "LOSS" if pnl_percent else "UNKNOWN",
        }

    except Exception as e:
        return {"error": str(e)}


def get_portfolio_value() -> Dict:
    """
    Get total portfolio value in USD

    Returns:
        Dict with total value and breakdown
    """
    positions = get_open_positions()
    if "error" in positions:
        return positions

    return {
        "total_usd": positions.get("total_portfolio_usd"),
        "sol_balance": positions.get("sol_balance"),
        "sol_value_usd": positions.get("sol_value_usd"),
        "token_positions": positions.get("position_count"),
        "top_holdings": positions.get("positions", [])[:5],
    }


# =============================================================================
# REGISTER ALL SKILLS
# =============================================================================

registry = get_registry()

# Wallet Management
@registry.register(
    name="get_wallet_balance",
    description="Get wallet SOL balance and all token holdings",
    parameters=[]
)
def _get_wallet_balance() -> Dict:
    return get_wallet_balance()


@registry.register(
    name="get_wallet_address",
    description="Get the trading wallet public key/address",
    parameters=[]
)
def _get_wallet_address() -> Dict:
    return get_wallet_address()


@registry.register(
    name="get_recent_transactions",
    description="Get recent wallet transactions",
    parameters=[
        {"name": "limit", "type": "int", "description": "Number of transactions (max 50)", "optional": True}
    ]
)
def _get_recent_transactions(limit: int = 20) -> Dict:
    return get_recent_transactions(limit)


# Token Operations
@registry.register(
    name="get_token_info",
    description="Get token price, supply, and metadata",
    parameters=[
        {"name": "address", "type": "str", "description": "Token mint address"}
    ]
)
def _get_token_info(address: str) -> Dict:
    return get_token_info(address)


@registry.register(
    name="check_token_safety",
    description="Check token for rug pull indicators (freeze auth, mint auth)",
    parameters=[
        {"name": "address", "type": "str", "description": "Token mint address"}
    ]
)
def _check_token_safety(address: str) -> Dict:
    return check_token_safety(address)


@registry.register(
    name="get_token_holders",
    description="Get top token holders and concentration risk",
    parameters=[
        {"name": "address", "type": "str", "description": "Token mint address"},
        {"name": "limit", "type": "int", "description": "Number of holders to return", "optional": True}
    ]
)
def _get_token_holders(address: str, limit: int = 10) -> Dict:
    return get_token_holders(address, limit)


# Trading Execution
@registry.register(
    name="execute_swap",
    description="Execute token swap via Jupiter (REQUIRES APPROVAL - real trade)",
    parameters=[
        {"name": "token_in", "type": "str", "description": "Input token (address or 'SOL')"},
        {"name": "token_out", "type": "str", "description": "Output token (address or 'SOL')"},
        {"name": "amount_in", "type": "float", "description": "Amount of input token"},
        {"name": "slippage", "type": "float", "description": "Slippage tolerance (0.01 = 1%)", "optional": True}
    ]
)
def _execute_swap(token_in: str, token_out: str, amount_in: float, slippage: float = 0.01) -> Dict:
    return execute_swap(token_in, token_out, amount_in, slippage)


@registry.register(
    name="copy_insider_trade",
    description="Mirror an insider wallet's position (REQUIRES APPROVAL - real trade)",
    parameters=[
        {"name": "wallet_address", "type": "str", "description": "Insider wallet to copy"},
        {"name": "token_address", "type": "str", "description": "Token they bought"},
        {"name": "percentage", "type": "int", "description": "Percentage of trade size to copy", "optional": True}
    ]
)
def _copy_insider_trade(wallet_address: str, token_address: str, percentage: int = 100) -> Dict:
    return copy_insider_trade(wallet_address, token_address, percentage)


@registry.register(
    name="take_profit",
    description="Sell percentage of a position (REQUIRES APPROVAL - real trade)",
    parameters=[
        {"name": "token_address", "type": "str", "description": "Token to sell"},
        {"name": "percentage", "type": "int", "description": "Percentage to sell (1-100)", "optional": True}
    ]
)
def _take_profit(token_address: str, percentage: int = 50) -> Dict:
    return take_profit(token_address, percentage)


# Position Tracking
@registry.register(
    name="get_open_positions",
    description="Get all current token holdings with USD values",
    parameters=[]
)
def _get_open_positions() -> Dict:
    return get_open_positions()


@registry.register(
    name="get_position_pnl",
    description="Get profit/loss for a specific token position",
    parameters=[
        {"name": "token_address", "type": "str", "description": "Token mint address"}
    ]
)
def _get_position_pnl(token_address: str) -> Dict:
    return get_position_pnl(token_address)


@registry.register(
    name="get_portfolio_value",
    description="Get total portfolio value in USD",
    parameters=[]
)
def _get_portfolio_value() -> Dict:
    return get_portfolio_value()
