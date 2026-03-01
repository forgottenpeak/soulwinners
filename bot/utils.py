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


def extract_wallet_from_text(text: str) -> Optional[str]:
    """
    Extract a Solana wallet address from alert text.

    Tries multiple strategies:
    1. Look for labeled wallet patterns (Wallet:, Address:, etc.)
    2. Look for URLs containing wallet addresses
    3. Find any valid Solana address (longest match wins)

    Returns:
        Wallet address or None if not found
    """
    if not text:
        return None

    # Strategy 1: Try labeled patterns first (most reliable)
    for pattern in WALLET_LABEL_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            wallet = match.group(1)
            if is_valid_solana_address(wallet):
                logger.debug(f"Found wallet via labeled pattern: {wallet[:12]}...")
                return wallet

    # Strategy 2: Find all potential addresses
    all_matches = SOLANA_WALLET_PATTERN.findall(text)

    # Filter out known tokens/programs
    valid_wallets = [
        addr for addr in all_matches
        if addr not in EXCLUDED_ADDRESSES and is_valid_solana_address(addr)
    ]

    if valid_wallets:
        # Return the longest one (usually the wallet, not token mint)
        # Or the first one found
        wallet = max(valid_wallets, key=len)
        logger.debug(f"Found wallet via pattern match: {wallet[:12]}...")
        return wallet

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
