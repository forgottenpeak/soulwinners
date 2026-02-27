"""
Pump.fun Wallet Collector
Collects profitable wallets trading pump.fun meme tokens
Uses DexScreener to find pump.fun tokens, then Helius for transaction data
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any
import logging

from .base import BaseCollector
from .helius import helius_rotator

logger = logging.getLogger(__name__)

# DexScreener API for finding pump.fun tokens
DEXSCREENER_API = "https://api.dexscreener.com"

# Headers to bypass Cloudflare protection
CLOUDFLARE_BYPASS_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Origin': 'https://dexscreener.com',
    'Referer': 'https://dexscreener.com/',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
}

# Skip these tokens (stablecoins, wrapped SOL)
SKIP_TOKENS = {
    'So11111111111111111111111111111111111111112',  # WSOL
    'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',  # USDC
    'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',  # USDT
}


class PumpFunCollector(BaseCollector):
    """Collector for Pump.fun trading wallets via DexScreener."""

    def __init__(self):
        super().__init__(rate_limit=10)
        self.rotator = helius_rotator  # Use API key rotation for 4x capacity

    def get_source_name(self) -> str:
        return "pumpfun"

    async def get_pumpfun_tokens_from_dexscreener(self) -> List[Dict]:
        """Get pump.fun tokens from DexScreener."""
        url = f"{DEXSCREENER_API}/token-profiles/latest/v1"
        result = await self.fetch_with_retry(url, headers=CLOUDFLARE_BYPASS_HEADERS)
        if not result:
            return []
        return [t for t in result if t.get('chainId') == 'solana'][:50]

    async def get_trending_solana_tokens(self) -> List[Dict]:
        """Get trending Solana tokens from DexScreener."""
        url = f"{DEXSCREENER_API}/token-boosts/top/v1"
        result = await self.fetch_with_retry(url, headers=CLOUDFLARE_BYPASS_HEADERS)
        if not result:
            return []
        return [t for t in result if t.get('chainId') == 'solana'][:30]

    async def get_fresh_pumpfun_launches(self, max_age_hours: int = 24) -> List[Dict]:
        """
        Get fresh Pump.fun launches from birth (0-24 hours old).

        Uses Helius blockchain queries to bypass Cloudflare blocking.

        Args:
            max_age_hours: Maximum age in hours (default 24)

        Returns:
            List of fresh token launches with metadata
        """
        fresh_tokens = []

        # Pump.fun program ID (bonding curve program)
        PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

        try:
            # Use Helius to get recent Pump.fun transactions
            api_key = await self.rotator.get_key()
            url = f"https://api.helius.xyz/v0/addresses/{PUMPFUN_PROGRAM}/transactions"
            params = {
                "api-key": api_key,
                "limit": 1000,
            }

            result = await self.fetch_with_retry(url, params=params)
            if not result:
                logger.warning("Helius returned no transactions for Pump.fun program")
                return []

            logger.info(f"Helius returned {len(result)} Pump.fun transactions")

            cutoff = datetime.now() - timedelta(hours=max_age_hours)
            seen_mints = set()

            for tx in result:
                try:
                    timestamp = tx.get('timestamp', 0)
                    if not timestamp:
                        continue

                    launch_time = datetime.fromtimestamp(timestamp)

                    # Filter by age (0-24 hours)
                    if launch_time <= cutoff:
                        continue

                    # Extract token mints from transaction
                    token_transfers = tx.get('tokenTransfers', [])
                    if not token_transfers:
                        continue

                    for transfer in token_transfers:
                        mint = transfer.get('mint', '')

                        if mint in seen_mints or not mint:
                            continue

                        # Skip stablecoins
                        if mint in SKIP_TOKENS:
                            continue

                        seen_mints.add(mint)

                        # Get token metadata
                        symbol = await self._get_token_metadata(mint, api_key)

                        # Check for Raydium migration
                        raydium_pool = await self._check_raydium_pool(mint, api_key)

                        now = datetime.now()
                        age_minutes = (now - launch_time).total_seconds() / 60

                        fresh_tokens.append({
                            'tokenAddress': mint,
                            'symbol': symbol or mint[:8],
                            'name': symbol or 'Unknown',
                            'launch_time': launch_time,
                            'age_minutes': age_minutes,
                            'complete': raydium_pool is not None,
                            'raydium_pool': raydium_pool,
                        })

                        logger.info(f"Found Pump.fun token: {symbol or mint[:8]} ({age_minutes:.1f} min old)")

                        if len(fresh_tokens) >= 100:
                            break

                except Exception as e:
                    logger.debug(f"Error parsing Pump.fun transaction: {e}")
                    continue

                if len(fresh_tokens) >= 100:
                    break

            logger.info(f"Found {len(fresh_tokens)} fresh Pump.fun launches (0-24h from birth) via Helius")

        except Exception as e:
            logger.error(f"Helius Pump.fun query failed: {e}")

        return fresh_tokens

    async def _get_token_metadata(self, mint: str, api_key: str) -> str:
        """Get token symbol/name via Helius."""
        try:
            url = f"https://api.helius.xyz/v0/token-metadata"
            params = {"api-key": api_key, "mint": mint}

            result = await self.fetch_with_retry(url, params=params)
            if result:
                return result.get('symbol', mint[:8])
        except:
            pass

        return mint[:8]

    async def _check_raydium_pool(self, mint: str, api_key: str) -> str:
        """Check if token has Raydium pool via blockchain query."""
        try:
            RAYDIUM_PROGRAM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"

            url = f"https://api.helius.xyz/v0/addresses/{mint}/transactions"
            params = {"api-key": api_key, "limit": 50}

            result = await self.fetch_with_retry(url, params=params)
            if not result:
                return None

            for tx in result:
                # Check for Raydium program in instructions
                instructions = tx.get('instructions', [])
                for instr in instructions:
                    if instr.get('programId') == RAYDIUM_PROGRAM:
                        # Found Raydium pool creation
                        return f"raydium_{mint[:8]}"

        except:
            pass

        return None

    async def get_token_traders(self, token_address: str) -> List[str]:
        """Get wallets that traded a token using Helius with key rotation and retry."""
        for attempt in range(3):
            api_key = await self.rotator.get_key()
            url = f"https://api.helius.xyz/v0/addresses/{token_address}/transactions?api-key={api_key}&limit=50"
            txs = await self.fetch_with_retry(url)
            if txs:
                wallets = set()
                for tx in txs:
                    fee_payer = tx.get('feePayer')
                    if fee_payer:
                        wallets.add(fee_payer)
                return list(wallets)
            await asyncio.sleep(1)
        return []

    async def get_wallet_transactions(self, wallet: str) -> List[Dict]:
        """Get transaction history for a wallet with key rotation and retry."""
        for attempt in range(3):
            api_key = await self.rotator.get_key()
            url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions?api-key={api_key}&limit=100"
            result = await self.fetch_with_retry(url)
            if result:
                return result
            await asyncio.sleep(1)
        return []

    async def get_wallet_balances(self, wallet: str) -> Dict:
        """Get current token balances for a wallet with key rotation and retry."""
        for attempt in range(3):
            api_key = await self.rotator.get_key()
            url = f"https://api.helius.xyz/v0/addresses/{wallet}/balances?api-key={api_key}"
            result = await self.fetch_with_retry(url)
            if result:
                return result
            await asyncio.sleep(1)
        return {}

    async def analyze_wallet_performance(self, wallet: str) -> Dict[str, Any]:
        """
        Analyze a wallet's trading performance.
        FIXED: Now tracks SOL value per token for accurate win rate.
        """
        transactions = await self.get_wallet_transactions(wallet)
        balances = await self.get_wallet_balances(wallet)

        if not transactions:
            return None

        # Initialize metrics
        metrics = {
            "wallet_address": wallet,
            "source": "pumpfun",
            "last_tx": None,
            "unique_tokens_traded": 0,
            "tokens_net_profit": 0,
            "buy_transactions": 0,
            "sell_transactions": 0,
            "current_balance_sol": 0,
            "total_sol_spent": 0,
            "total_sol_earned": 0,
            "win_rate": 0,
            "tokens_less_10x": 0,
            "tokens_10x_plus": 0,
            "tokens_20x_plus": 0,
            "tokens_50x_plus": 0,
            "tokens_100x_plus": 0,
            "days_since_first_trade": 30,
        }

        # Extract SOL balance
        if balances and 'nativeBalance' in balances:
            metrics['current_balance_sol'] = balances['nativeBalance'] / 1e9

        # Track SOL spent/earned PER TOKEN for accurate profit calculation
        token_positions = {}  # token -> {'sol_spent': x, 'sol_earned': y}

        first_timestamp = None
        last_timestamp = None

        for tx in transactions:
            timestamp = tx.get('timestamp', 0)
            if timestamp:
                if not last_timestamp:
                    last_timestamp = timestamp
                first_timestamp = timestamp

            token_transfers = tx.get('tokenTransfers', [])
            native_transfers = tx.get('nativeTransfers', [])

            # Build a map of SOL transfers in this tx
            sol_out = 0  # SOL leaving wallet
            sol_in = 0   # SOL coming to wallet

            for nt in native_transfers:
                amount = abs(nt.get('amount', 0)) / 1e9
                if nt.get('fromUserAccount') == wallet:
                    sol_out += amount
                elif nt.get('toUserAccount') == wallet:
                    sol_in += amount

            # Process token transfers
            for transfer in token_transfers:
                token_mint = transfer.get('mint', '')
                if not token_mint or token_mint in SKIP_TOKENS:
                    continue

                # Initialize token position
                if token_mint not in token_positions:
                    token_positions[token_mint] = {'sol_spent': 0, 'sol_earned': 0}

                # Determine if buy or sell
                to_user = transfer.get('toUserAccount', '')
                from_user = transfer.get('fromUserAccount', '')

                if to_user == wallet:
                    # BUY: Token coming IN, SOL going OUT
                    metrics['buy_transactions'] += 1
                    # Attribute SOL spent to this token
                    # (simplified: assume all SOL out in this tx is for this token)
                    token_positions[token_mint]['sol_spent'] += sol_out
                    metrics['total_sol_spent'] += sol_out
                    sol_out = 0  # Reset to avoid double counting

                elif from_user == wallet:
                    # SELL: Token going OUT, SOL coming IN
                    metrics['sell_transactions'] += 1
                    # Attribute SOL earned to this token
                    token_positions[token_mint]['sol_earned'] += sol_in
                    metrics['total_sol_earned'] += sol_in
                    sol_in = 0  # Reset to avoid double counting

        # Calculate metrics from token positions
        metrics['unique_tokens_traded'] = len(token_positions)
        profitable_tokens = 0
        total_closed_positions = 0

        for token, pos in token_positions.items():
            sol_spent = pos['sol_spent']
            sol_earned = pos['sol_earned']

            # Only count closed positions (both buy and sell)
            if sol_spent > 0 and sol_earned > 0:
                total_closed_positions += 1
                profit = sol_earned - sol_spent

                if profit > 0:
                    profitable_tokens += 1
                    metrics['tokens_net_profit'] += 1

                    # Calculate ROI multiple
                    roi_multiple = sol_earned / sol_spent
                    if roi_multiple >= 100:
                        metrics['tokens_100x_plus'] += 1
                    elif roi_multiple >= 50:
                        metrics['tokens_50x_plus'] += 1
                    elif roi_multiple >= 20:
                        metrics['tokens_20x_plus'] += 1
                    elif roi_multiple >= 10:
                        metrics['tokens_10x_plus'] += 1
                    else:
                        metrics['tokens_less_10x'] += 1

        # Calculate win rate from closed positions
        if total_closed_positions > 0:
            metrics['win_rate'] = profitable_tokens / total_closed_positions
        else:
            metrics['win_rate'] = 0

        # Calculate overall PnL
        metrics['realized_pnl'] = metrics['total_sol_earned'] - metrics['total_sol_spent']

        # Calculate days since first trade
        if first_timestamp and last_timestamp:
            metrics['last_tx'] = last_timestamp
            days = (datetime.now().timestamp() - first_timestamp) / 86400
            metrics['days_since_first_trade'] = max(1, int(days))

        return metrics

    async def collect_wallets(self, target_count: int = 500, use_fresh_launches: bool = True) -> List[Dict[str, Any]]:
        """
        Collect profitable pump.fun/meme wallets.

        Args:
            target_count: Number of wallets to collect
            use_fresh_launches: If True, scan ultra-fresh launches (10min-24h) instead of trending
        """
        logger.info(f"Starting Pump.fun wallet collection, target: {target_count}")

        token_addresses = set()

        if use_fresh_launches:
            # NEW: Get fresh launches from birth (0-24 hours old)
            fresh_tokens = await self.get_fresh_pumpfun_launches(
                max_age_hours=24
            )
            logger.info(f"Found {len(fresh_tokens)} fresh launches (0-24h from birth)")

            for t in fresh_tokens:
                addr = t.get('tokenAddress')
                if addr:
                    token_addresses.add(addr)
        else:
            # OLD: Get trending Solana tokens from DexScreener
            tokens = await self.get_trending_solana_tokens()
            logger.info(f"Found {len(tokens)} trending Solana tokens")

            # Also try to get latest token profiles
            profiles = await self.get_pumpfun_tokens_from_dexscreener()
            logger.info(f"Found {len(profiles)} token profiles")

            # Combine token addresses
            for t in tokens:
                addr = t.get('tokenAddress')
                if addr:
                    token_addresses.add(addr)
            for p in profiles:
                addr = p.get('tokenAddress')
                if addr:
                    token_addresses.add(addr)

        logger.info(f"Total unique tokens to scan: {len(token_addresses)}")

        # Collect wallets from token traders
        all_wallets = set()
        for token_addr in list(token_addresses)[:40]:
            traders = await self.get_token_traders(token_addr)
            all_wallets.update(traders)
            await asyncio.sleep(0.2)  # Rate limiting

            if len(all_wallets) >= target_count * 2:
                break

        logger.info(f"Found {len(all_wallets)} unique wallets")

        # Analyze each wallet
        results = []
        for wallet in list(all_wallets)[:target_count]:
            try:
                metrics = await self.analyze_wallet_performance(wallet)
                if metrics and metrics['buy_transactions'] > 0:
                    results.append(metrics)
                    if len(results) % 50 == 0:
                        logger.info(f"Analyzed {len(results)} wallets")
            except Exception as e:
                logger.error(f"Error analyzing wallet {wallet}: {e}")

            await asyncio.sleep(0.1)

        logger.info(f"Collected {len(results)} pump.fun wallets")
        return results


async def main():
    """Test the collector."""
    async with PumpFunCollector() as collector:
        wallets = await collector.collect_wallets(target_count=10)
        for w in wallets[:3]:
            print(f"\nWallet: {w['wallet_address'][:20]}...")
            print(f"  SOL Balance: {w['current_balance_sol']:.2f}")
            print(f"  Trades: {w['buy_transactions']} buys, {w['sell_transactions']} sells")
            print(f"  Win Rate: {w['win_rate']:.1%}")
            print(f"  PnL: {w['realized_pnl']:.2f} SOL")


if __name__ == "__main__":
    asyncio.run(main())
