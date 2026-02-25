"""
Base collector class with common functionality
"""
import asyncio
import aiohttp
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """Base class for all wallet collectors."""

    def __init__(self, rate_limit: int = 3):
        # Low concurrency to avoid rate limits with 4-key rotation
        self.rate_limit = rate_limit
        self.semaphore = asyncio.Semaphore(rate_limit)
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def fetch_with_retry(
        self,
        url: str,
        method: str = "GET",
        headers: Dict = None,
        json_data: Dict = None,
        max_retries: int = 3,
    ) -> Optional[Dict]:
        """Fetch URL with rate limiting and retry logic."""
        async with self.semaphore:
            for attempt in range(max_retries):
                try:
                    # Increased delay to avoid rate limiting
                    await asyncio.sleep(0.5)

                    async with self.session.request(
                        method, url, headers=headers, json=json_data, timeout=30
                    ) as response:
                        if response.status == 200:
                            return await response.json()
                        elif response.status == 429:  # Rate limited
                            wait_time = 2 ** (attempt + 1)
                            logger.warning(f"Rate limited, waiting {wait_time}s")
                            await asyncio.sleep(wait_time)
                            # Return None to trigger retry with fresh key at caller level
                            return None
                        elif response.status in [500, 502, 503, 504]:
                            # Server error, retry
                            await asyncio.sleep(2)
                        else:
                            logger.debug(f"HTTP {response.status}: {url[:50]}...")
                            return None
                except asyncio.TimeoutError:
                    logger.warning(f"Request timeout, attempt {attempt + 1}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"Request error: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
            return None

    @abstractmethod
    async def collect_wallets(self) -> List[Dict[str, Any]]:
        """Collect wallets from the data source."""
        pass

    @abstractmethod
    def get_source_name(self) -> str:
        """Return the source identifier."""
        pass
