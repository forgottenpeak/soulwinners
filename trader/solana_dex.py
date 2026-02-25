"""
Solana DEX Integration - Jupiter Aggregator
Executes swaps on Solana using Jupiter's API for best routes
"""
import asyncio
import base64
import json
import logging
from typing import Dict, Optional, Tuple
from decimal import Decimal
import aiohttp
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from solders.commitment_config import CommitmentLevel
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed

logger = logging.getLogger(__name__)

# Constants
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
LAMPORTS_PER_SOL = 1_000_000_000

# Jupiter API endpoints
JUPITER_QUOTE_API = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_API = "https://quote-api.jup.ag/v6/swap"
JUPITER_PRICE_API = "https://price.jup.ag/v6/price"


class JupiterDEX:
    """
    Jupiter DEX integration for Solana swaps.

    Features:
    - Get quotes for token swaps
    - Execute buy/sell transactions
    - Track transaction status
    - Get real-time token prices
    """

    def __init__(self, private_key: str, rpc_url: str = "https://api.mainnet-beta.solana.com"):
        """
        Initialize Jupiter DEX client.

        Args:
            private_key: Base58 encoded Solana private key
            rpc_url: Solana RPC endpoint
        """
        self.rpc_url = rpc_url
        self.client = AsyncClient(rpc_url, commitment=Confirmed)

        # Load keypair from private key
        try:
            self.keypair = Keypair.from_base58_string(private_key)
            self.wallet_address = str(self.keypair.pubkey())
            logger.info(f"Wallet initialized: {self.wallet_address[:20]}...")
        except Exception as e:
            logger.error(f"Failed to load keypair: {e}")
            raise ValueError("Invalid private key")

        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
        await self.client.close()

    async def get_sol_balance(self) -> float:
        """Get SOL balance of wallet in SOL units."""
        try:
            response = await self.client.get_balance(self.keypair.pubkey())
            if response.value is not None:
                return response.value / LAMPORTS_PER_SOL
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
        return 0.0

    async def get_token_balance(self, token_mint: str) -> float:
        """Get SPL token balance."""
        try:
            response = await self.client.get_token_accounts_by_owner_json_parsed(
                self.keypair.pubkey(),
                {"mint": token_mint}
            )
            if response.value:
                for account in response.value:
                    info = account.account.data.parsed.get('info', {})
                    token_amount = info.get('tokenAmount', {})
                    return float(token_amount.get('uiAmount', 0))
        except Exception as e:
            logger.error(f"Failed to get token balance: {e}")
        return 0.0

    async def get_token_price(self, token_mint: str) -> Optional[float]:
        """Get token price in USD from Jupiter."""
        try:
            url = f"{JUPITER_PRICE_API}?ids={token_mint}"
            async with self.session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    price_data = data.get('data', {}).get(token_mint, {})
                    return float(price_data.get('price', 0))
        except Exception as e:
            logger.error(f"Failed to get price: {e}")
        return None

    async def get_sol_price(self) -> float:
        """Get current SOL price in USD."""
        price = await self.get_token_price(SOL_MINT)
        return price or 0.0

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,  # In smallest units (lamports for SOL)
        slippage_bps: int = 100  # 1% default slippage
    ) -> Optional[Dict]:
        """
        Get swap quote from Jupiter.

        Args:
            input_mint: Token to sell
            output_mint: Token to buy
            amount: Amount in smallest units
            slippage_bps: Slippage tolerance in basis points (100 = 1%)

        Returns:
            Quote data dict or None if failed
        """
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": slippage_bps,
            "onlyDirectRoutes": "false",
            "asLegacyTransaction": "false",
        }

        try:
            async with self.session.get(JUPITER_QUOTE_API, params=params, timeout=15) as response:
                if response.status == 200:
                    quote = await response.json()
                    logger.debug(f"Quote received: {quote.get('outAmount')} output for {amount} input")
                    return quote
                else:
                    error = await response.text()
                    logger.error(f"Quote API error {response.status}: {error}")
        except Exception as e:
            logger.error(f"Failed to get quote: {e}")

        return None

    async def execute_swap(
        self,
        quote: Dict,
        priority_fee_lamports: int = 100000  # 0.0001 SOL priority fee
    ) -> Optional[str]:
        """
        Execute a swap using Jupiter.

        Args:
            quote: Quote data from get_quote()
            priority_fee_lamports: Priority fee for faster confirmation

        Returns:
            Transaction signature or None if failed
        """
        swap_data = {
            "quoteResponse": quote,
            "userPublicKey": self.wallet_address,
            "wrapAndUnwrapSol": True,
            "computeUnitPriceMicroLamports": priority_fee_lamports,
            "dynamicComputeUnitLimit": True,
        }

        try:
            # Get swap transaction
            async with self.session.post(
                JUPITER_SWAP_API,
                json=swap_data,
                headers={"Content-Type": "application/json"},
                timeout=30
            ) as response:
                if response.status != 200:
                    error = await response.text()
                    logger.error(f"Swap API error {response.status}: {error}")
                    return None

                swap_response = await response.json()

            # Decode and sign transaction
            swap_tx_base64 = swap_response.get('swapTransaction')
            if not swap_tx_base64:
                logger.error("No swap transaction in response")
                return None

            tx_bytes = base64.b64decode(swap_tx_base64)
            tx = VersionedTransaction.from_bytes(tx_bytes)

            # Sign transaction
            signed_tx = VersionedTransaction(tx.message, [self.keypair])

            # Send transaction
            tx_sig = await self.client.send_transaction(
                signed_tx,
                opts={"skip_preflight": True, "max_retries": 3}
            )

            if tx_sig.value:
                signature = str(tx_sig.value)
                logger.info(f"Transaction sent: {signature}")

                # Wait for confirmation
                confirmed = await self._wait_for_confirmation(signature)
                if confirmed:
                    logger.info(f"Transaction confirmed: {signature}")
                    return signature
                else:
                    logger.warning(f"Transaction may have failed: {signature}")
                    return signature  # Return anyway, let caller verify

        except Exception as e:
            logger.error(f"Swap execution failed: {e}", exc_info=True)

        return None

    async def _wait_for_confirmation(self, signature: str, timeout: int = 60) -> bool:
        """Wait for transaction confirmation."""
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                response = await self.client.get_signature_statuses([signature])
                if response.value and response.value[0]:
                    status = response.value[0]
                    if status.confirmation_status:
                        # Confirmed or Finalized
                        if status.err is None:
                            return True
                        else:
                            logger.error(f"Transaction failed: {status.err}")
                            return False
            except Exception as e:
                logger.debug(f"Status check error: {e}")

            await asyncio.sleep(2)

        return False

    async def buy_token(
        self,
        token_mint: str,
        sol_amount: float,
        slippage_bps: int = 150  # 1.5% for volatile tokens
    ) -> Optional[Dict]:
        """
        Buy a token with SOL.

        Args:
            token_mint: Token to buy
            sol_amount: Amount of SOL to spend
            slippage_bps: Slippage tolerance

        Returns:
            Trade result dict with signature and amounts
        """
        amount_lamports = int(sol_amount * LAMPORTS_PER_SOL)

        logger.info(f"Buying token {token_mint[:20]}... with {sol_amount:.4f} SOL")

        # Get quote
        quote = await self.get_quote(
            input_mint=SOL_MINT,
            output_mint=token_mint,
            amount=amount_lamports,
            slippage_bps=slippage_bps
        )

        if not quote:
            logger.error("Failed to get buy quote")
            return None

        # Execute swap
        signature = await self.execute_swap(quote)

        if signature:
            out_amount = int(quote.get('outAmount', 0))
            price_impact = float(quote.get('priceImpactPct', 0))

            return {
                'success': True,
                'signature': signature,
                'input_amount': sol_amount,
                'output_amount': out_amount,
                'price_impact': price_impact,
                'token_mint': token_mint,
                'type': 'buy'
            }

        return None

    async def sell_token(
        self,
        token_mint: str,
        token_amount: float,
        token_decimals: int = 6,
        slippage_bps: int = 200  # 2% for sells
    ) -> Optional[Dict]:
        """
        Sell a token for SOL.

        Args:
            token_mint: Token to sell
            token_amount: Amount of tokens to sell
            token_decimals: Token decimal places
            slippage_bps: Slippage tolerance

        Returns:
            Trade result dict with signature and amounts
        """
        amount_raw = int(token_amount * (10 ** token_decimals))

        logger.info(f"Selling {token_amount} of {token_mint[:20]}...")

        # Get quote
        quote = await self.get_quote(
            input_mint=token_mint,
            output_mint=SOL_MINT,
            amount=amount_raw,
            slippage_bps=slippage_bps
        )

        if not quote:
            logger.error("Failed to get sell quote")
            return None

        # Execute swap
        signature = await self.execute_swap(quote)

        if signature:
            out_amount = int(quote.get('outAmount', 0)) / LAMPORTS_PER_SOL
            price_impact = float(quote.get('priceImpactPct', 0))

            return {
                'success': True,
                'signature': signature,
                'input_amount': token_amount,
                'output_amount': out_amount,
                'price_impact': price_impact,
                'token_mint': token_mint,
                'type': 'sell'
            }

        return None

    async def sell_token_percentage(
        self,
        token_mint: str,
        percentage: float,
        token_decimals: int = 6,
        slippage_bps: int = 200
    ) -> Optional[Dict]:
        """
        Sell a percentage of token holdings.

        Args:
            token_mint: Token to sell
            percentage: Percentage to sell (0-100)
            token_decimals: Token decimal places
            slippage_bps: Slippage tolerance

        Returns:
            Trade result dict
        """
        balance = await self.get_token_balance(token_mint)
        if balance <= 0:
            logger.warning(f"No balance to sell for {token_mint}")
            return None

        sell_amount = balance * (percentage / 100)
        return await self.sell_token(token_mint, sell_amount, token_decimals, slippage_bps)


async def test_jupiter():
    """Test Jupiter integration (requires funded wallet)."""
    import os
    from dotenv import load_dotenv
    load_dotenv()

    private_key = os.getenv('OPENCLAW_PRIVATE_KEY')
    if not private_key:
        print("Set OPENCLAW_PRIVATE_KEY in .env to test")
        return

    async with JupiterDEX(private_key) as dex:
        # Check balance
        balance = await dex.get_sol_balance()
        print(f"SOL Balance: {balance:.4f}")

        # Get SOL price
        sol_price = await dex.get_sol_price()
        print(f"SOL Price: ${sol_price:.2f}")

        # Test quote (don't execute)
        quote = await dex.get_quote(
            SOL_MINT,
            "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",  # BONK
            int(0.01 * LAMPORTS_PER_SOL),  # 0.01 SOL
            100
        )
        if quote:
            print(f"Quote: {quote.get('outAmount')} BONK for 0.01 SOL")


if __name__ == "__main__":
    asyncio.run(test_jupiter())
