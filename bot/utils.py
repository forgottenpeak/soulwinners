"""
Bot Utilities - Wallet extraction and helper functions
"""
import re
import logging
from typing import Optional, List, Dict
from datetime import datetime

logger = logging.getLogger(__name__)

# Solana wallet address pattern (base58, 32-44 chars)
SOLANA_WALLET_PATTERN = re.compile(r'[1-9A-HJ-NP-Za-km-z]{32,44}')

# Common wallet label patterns in alerts
WALLET_LABEL_PATTERNS = [
    r'Wallet[:\s]+`?([1-9A-HJ-NP-Za-km-z]{32,44})`?',
    r'Address[:\s]+`?([1-9A-HJ-NP-Za-km-z]{32,44})`?',
    r'Trader[:\s]+`?([1-9A-HJ-NP-Za-km-z]{32,44})`?',
    r'Buyer[:\s]+`?([1-9A-HJ-NP-Za-km-z]{32,44})`?',
    r'solscan\.io/account/([1-9A-HJ-NP-Za-km-z]{32,44})',
    r'birdeye\.so/profile/([1-9A-HJ-NP-Za-km-z]{32,44})',
    r'dexscreener\.com/solana/([1-9A-HJ-NP-Za-km-z]{32,44})',
]

# Known token/program addresses to exclude
EXCLUDED_ADDRESSES = {
    'So11111111111111111111111111111111111111112',   # WSOL
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
    '11111111111111111111111111111111',               # System Program
    'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA',   # Token Program
    'ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL',  # Associated Token
    '675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8',  # Raydium
}

# Token address suffixes to skip (pump.fun, etc.)
TOKEN_ADDRESS_SUFFIXES = ('pump', 'Pump', 'PUMP')


def is_likely_token_address(address: str) -> bool:
    """
    Check if address looks like a token mint rather than a wallet.

    Token addresses often:
    - End with 'pump' (pump.fun tokens)
    - Are in known program lists
    """
    if not address:
        return False

    # Check for pump.fun token suffix
    if address.endswith(TOKEN_ADDRESS_SUFFIXES):
        return True

    # Check excluded addresses
    if address in EXCLUDED_ADDRESSES:
        return True

    return False


def extract_wallet_from_text(text: str) -> Optional[str]:
    """
    Extract a Solana WALLET address from alert text.

    Tries multiple strategies:
    1. Look for labeled wallet patterns (Wallet:, Buyer:, Trader:, etc.)
    2. Look for profile URLs (solscan, birdeye)
    3. Find addresses that DON'T look like tokens

    Filters out:
    - Token addresses ending in 'pump'
    - Known program addresses
    - Stablecoin addresses

    Returns:
        Wallet address or None if not found
    """
    if not text:
        return None

    # Strategy 1: Try labeled patterns first (most reliable)
    # These explicitly label wallet addresses
    for pattern in WALLET_LABEL_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            wallet = match.group(1)
            # Validate it's a wallet, not a token
            if is_valid_solana_address(wallet) and not is_likely_token_address(wallet):
                logger.info(f"Found wallet via labeled pattern: {wallet[:12]}...")
                return wallet

    # Strategy 2: Find all potential addresses
    all_matches = SOLANA_WALLET_PATTERN.findall(text)

    # Filter out tokens and known programs
    valid_wallets = [
        addr for addr in all_matches
        if is_valid_solana_address(addr) and not is_likely_token_address(addr)
    ]

    if not valid_wallets:
        logger.warning(f"No valid wallet found in text (found {len(all_matches)} addresses, all filtered)")
        return None

    # Strategy 3: If we found labeled "Token:" or "CA:" skip those
    # Look for pattern that identifies token addresses to exclude
    token_patterns = [
        r'Token[:\s]+`?([1-9A-HJ-NP-Za-km-z]{32,44})`?',
        r'CA[:\s]+`?([1-9A-HJ-NP-Za-km-z]{32,44})`?',
        r'Contract[:\s]+`?([1-9A-HJ-NP-Za-km-z]{32,44})`?',
        r'Mint[:\s]+`?([1-9A-HJ-NP-Za-km-z]{32,44})`?',
    ]

    token_addresses = set()
    for pattern in token_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            token_addresses.add(match.group(1))

    # Remove identified token addresses
    valid_wallets = [addr for addr in valid_wallets if addr not in token_addresses]

    if valid_wallets:
        # Return the FIRST one found (usually the wallet mentioned first)
        # Not longest - token addresses are often longer
        wallet = valid_wallets[0]
        logger.info(f"Found wallet via pattern match: {wallet[:12]}...")
        return wallet

    logger.warning("No wallet found after filtering token addresses")
    return None


def is_valid_solana_address(address: str) -> bool:
    """
    Validate a Solana address format.

    Solana addresses are base58 encoded and 32-44 characters.
    This is a format check only, not on-chain validation.
    """
    if not address:
        return False

    # Length check (base58 encoded 32 bytes = 32-44 chars)
    if len(address) < 32 or len(address) > 44:
        return False

    # Base58 character set (no 0, O, I, l)
    base58_chars = set('123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz')
    if not all(c in base58_chars for c in address):
        return False

    return True


def truncate_wallet(address: str, show_chars: int = 4) -> str:
    """
    Truncate wallet address for display.

    Example: "AbC123...xyz9" format
    """
    if not address or len(address) < show_chars * 2 + 3:
        return address

    return f"{address[:show_chars]}...{address[-show_chars:]}"


def format_wallet_for_user(address: str, is_admin: bool = False) -> str:
    """
    Format wallet address based on user privilege level.

    Admin: Full address with code formatting
    Premium: Truncated address
    """
    if is_admin:
        return f"`{address}`"
    else:
        return truncate_wallet(address)


def format_stats(win_rate: float, roi: float, trades: int) -> str:
    """Format wallet stats for display."""
    wr_emoji = "🟢" if win_rate >= 0.6 else "🟡" if win_rate >= 0.4 else "🔴"
    roi_emoji = "📈" if roi >= 0 else "📉"

    return (
        f"{wr_emoji} Win Rate: {win_rate*100:.0f}%\n"
        f"{roi_emoji} ROI: {roi:+.0f}%\n"
        f"📊 Trades: {trades}"
    )


def parse_remove_index(text: str) -> Optional[int]:
    """
    Parse index number from /remove_wallet command.

    Examples:
        /remove_wallet 1 -> 1
        /remove_wallet 3 -> 3
    """
    parts = text.split()
    if len(parts) < 2:
        return None

    try:
        index = int(parts[1])
        if index > 0:
            return index
    except ValueError:
        pass

    return None


def format_time_ago(timestamp: datetime) -> str:
    """Format datetime as relative time string."""
    if not timestamp:
        return "Unknown"

    now = datetime.now()
    diff = (now - timestamp).total_seconds()

    if diff < 60:
        return "Just now"
    elif diff < 3600:
        return f"{int(diff/60)}m ago"
    elif diff < 86400:
        return f"{int(diff/3600)}h ago"
    elif diff < 604800:
        return f"{int(diff/86400)}d ago"
    else:
        return f"{int(diff/604800)}w ago"


# Test the extraction
if __name__ == "__main__":
    test_texts = [
        "🚀 BUY ALERT\nWallet: 5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
        "New buy from 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU on $TOKEN",
        "Check it out: https://solscan.io/account/DYw8jCTfwHNRJhhmFcbXvVDTqWMEVFBX6ZKUmG5CNSKK",
        "Buyer: `9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM` bought 5 SOL",
    ]

    for text in test_texts:
        wallet = extract_wallet_from_text(text)
        print(f"Found: {wallet[:20] if wallet else 'None'}...")
