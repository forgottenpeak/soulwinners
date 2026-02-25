"""
Cluster Detector - Bubble Map / Wallet Clustering Analysis
Finds connected wallets (insiders, dev groups, coordinated buying)
"""
import asyncio
import aiohttp
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import json

from config.settings import HELIUS_API_KEY
from database import get_connection

logger = logging.getLogger(__name__)


@dataclass
class WalletCluster:
    """A group of connected wallets."""
    cluster_id: str
    wallets: Set[str] = field(default_factory=set)
    connection_type: str = ""  # "funding", "trading", "dev_group", "coordinated"
    total_volume_sol: float = 0
    shared_tokens: Set[str] = field(default_factory=set)
    first_seen: datetime = None
    risk_score: float = 0  # Higher = more suspicious
    label: str = ""  # "Dev Cluster", "Whale Pod", "Bot Network", etc.


@dataclass
class WalletConnection:
    """A connection between two wallets."""
    wallet_a: str
    wallet_b: str
    connection_type: str  # "direct_transfer", "same_funder", "shared_tokens", "timing"
    strength: float  # 0-1, how strong the connection is
    evidence: List[str] = field(default_factory=list)


class ClusterDetector:
    """
    Detects connected wallets using multiple signals:

    1. Direct SOL/Token Transfers - Wallets sending to each other
    2. Same Funder - Multiple wallets funded by same source
    3. Shared Token Trading - Wallets buying same tokens within minutes
    4. Timing Correlation - Wallets always active at same times
    5. DEX Pattern Matching - Similar trade sizes, timing, tokens
    """

    def __init__(self):
        self.api_key = HELIUS_API_KEY
        self.connections: Dict[Tuple[str, str], WalletConnection] = {}
        self.clusters: Dict[str, WalletCluster] = {}
        self.wallet_to_cluster: Dict[str, str] = {}

    async def analyze_wallet_connections(self, wallet: str) -> List[WalletConnection]:
        """Find all wallets connected to a given wallet."""
        connections = []

        # Get funding history
        funders = await self._get_funding_sources(wallet)
        for funder in funders:
            conn = WalletConnection(
                wallet_a=wallet,
                wallet_b=funder,
                connection_type="funded_by",
                strength=0.8,
                evidence=[f"Funded by {funder[:15]}..."],
            )
            connections.append(conn)

            # Check if funder funded other wallets
            siblings = await self._get_funded_wallets(funder)
            for sibling in siblings:
                if sibling != wallet:
                    conn = WalletConnection(
                        wallet_a=wallet,
                        wallet_b=sibling,
                        connection_type="same_funder",
                        strength=0.9,
                        evidence=[f"Both funded by {funder[:15]}..."],
                    )
                    connections.append(conn)

        # Get direct transfer partners
        transfer_partners = await self._get_transfer_partners(wallet)
        for partner, count in transfer_partners.items():
            conn = WalletConnection(
                wallet_a=wallet,
                wallet_b=partner,
                connection_type="direct_transfer",
                strength=min(0.5 + (count * 0.1), 1.0),
                evidence=[f"{count} direct transfers"],
            )
            connections.append(conn)

        # Get shared token buyers
        shared_buyers = await self._get_shared_token_buyers(wallet)
        for buyer, tokens in shared_buyers.items():
            if len(tokens) >= 3:  # At least 3 shared tokens
                conn = WalletConnection(
                    wallet_a=wallet,
                    wallet_b=buyer,
                    connection_type="shared_tokens",
                    strength=min(0.3 + (len(tokens) * 0.1), 0.9),
                    evidence=[f"{len(tokens)} shared tokens: {', '.join(list(tokens)[:3])}"],
                )
                connections.append(conn)

        return connections

    async def _get_funding_sources(self, wallet: str) -> List[str]:
        """Get wallets that funded this wallet with SOL."""
        funders = []
        url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
        params = {"api-key": self.api_key, "limit": 100}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        txs = await response.json()

                        for tx in txs:
                            native_transfers = tx.get('nativeTransfers', [])
                            for transfer in native_transfers:
                                # SOL sent TO this wallet
                                if transfer.get('toUserAccount') == wallet:
                                    from_wallet = transfer.get('fromUserAccount')
                                    amount = transfer.get('amount', 0) / 1e9

                                    # Significant funding (> 0.5 SOL)
                                    if from_wallet and amount > 0.5:
                                        if from_wallet not in funders:
                                            funders.append(from_wallet)

        except Exception as e:
            logger.error(f"Failed to get funding sources: {e}")

        return funders[:10]  # Limit to top 10

    async def _get_funded_wallets(self, funder: str) -> List[str]:
        """Get wallets that this funder sent SOL to."""
        funded = []
        url = f"https://api.helius.xyz/v0/addresses/{funder}/transactions"
        params = {"api-key": self.api_key, "limit": 100}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        txs = await response.json()

                        for tx in txs:
                            native_transfers = tx.get('nativeTransfers', [])
                            for transfer in native_transfers:
                                # SOL sent FROM this funder
                                if transfer.get('fromUserAccount') == funder:
                                    to_wallet = transfer.get('toUserAccount')
                                    amount = transfer.get('amount', 0) / 1e9

                                    # Significant funding (> 0.5 SOL)
                                    if to_wallet and amount > 0.5:
                                        if to_wallet not in funded:
                                            funded.append(to_wallet)

        except Exception as e:
            logger.error(f"Failed to get funded wallets: {e}")

        return funded[:20]  # Limit to 20

    async def _get_transfer_partners(self, wallet: str) -> Dict[str, int]:
        """Get wallets that have transferred tokens directly with this wallet."""
        partners = defaultdict(int)
        url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
        params = {"api-key": self.api_key, "limit": 100}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        txs = await response.json()

                        for tx in txs:
                            # Check token transfers
                            token_transfers = tx.get('tokenTransfers', [])
                            for transfer in token_transfers:
                                to_wallet = transfer.get('toUserAccount')
                                from_wallet = transfer.get('fromUserAccount')

                                if to_wallet == wallet and from_wallet:
                                    partners[from_wallet] += 1
                                elif from_wallet == wallet and to_wallet:
                                    partners[to_wallet] += 1

                            # Check native SOL transfers
                            native_transfers = tx.get('nativeTransfers', [])
                            for transfer in native_transfers:
                                to_wallet = transfer.get('toUserAccount')
                                from_wallet = transfer.get('fromUserAccount')

                                if to_wallet == wallet and from_wallet:
                                    partners[from_wallet] += 1
                                elif from_wallet == wallet and to_wallet:
                                    partners[to_wallet] += 1

        except Exception as e:
            logger.error(f"Failed to get transfer partners: {e}")

        return dict(partners)

    async def _get_shared_token_buyers(self, wallet: str) -> Dict[str, Set[str]]:
        """Find wallets that bought the same tokens within a time window."""
        shared_buyers = defaultdict(set)

        # Get this wallet's recent token buys
        token_buys = await self._get_wallet_token_buys(wallet)

        # For each token, check other recent buyers
        for token_address, buy_time in list(token_buys.items())[:10]:  # Limit to 10 tokens
            other_buyers = await self._get_token_buyers_around_time(
                token_address, buy_time, window_minutes=10
            )

            for other_wallet in other_buyers:
                if other_wallet != wallet:
                    # Get token symbol from DexScreener
                    symbol = await self._get_token_symbol(token_address)
                    shared_buyers[other_wallet].add(symbol)

            await asyncio.sleep(0.2)  # Rate limiting

        return dict(shared_buyers)

    async def _get_wallet_token_buys(self, wallet: str) -> Dict[str, float]:
        """Get recent token buys for a wallet. Returns {token_address: timestamp}"""
        buys = {}
        url = f"https://api.helius.xyz/v0/addresses/{wallet}/transactions"
        params = {"api-key": self.api_key, "limit": 50}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=15) as response:
                    if response.status == 200:
                        txs = await response.json()

                        for tx in txs:
                            token_transfers = tx.get('tokenTransfers', [])
                            timestamp = tx.get('timestamp', 0)

                            for transfer in token_transfers:
                                # Token received = buy
                                if transfer.get('toUserAccount') == wallet:
                                    mint = transfer.get('mint', '')
                                    if mint and mint not in buys:
                                        buys[mint] = timestamp

        except Exception as e:
            logger.error(f"Failed to get token buys: {e}")

        return buys

    async def _get_token_buyers_around_time(
        self,
        token_address: str,
        target_time: float,
        window_minutes: int = 10
    ) -> List[str]:
        """Get wallets that bought a token around a specific time."""
        # This would require querying token transaction history
        # For now, return empty - would need indexer/API for this
        return []

    async def _get_token_symbol(self, token_address: str) -> str:
        """Get token symbol from DexScreener."""
        try:
            url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data and len(data) > 0:
                            return data[0].get('baseToken', {}).get('symbol', token_address[:8])
        except:
            pass
        return token_address[:8]

    def build_clusters(self) -> List[WalletCluster]:
        """Build clusters from detected connections using Union-Find."""
        parent = {}

        def find(x):
            if x not in parent:
                parent[x] = x
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Union connected wallets
        for (wallet_a, wallet_b), conn in self.connections.items():
            if conn.strength >= 0.5:  # Only strong connections
                union(wallet_a, wallet_b)

        # Group by root
        clusters_raw = defaultdict(set)
        for wallet in parent:
            root = find(wallet)
            clusters_raw[root].add(wallet)

        # Create cluster objects
        clusters = []
        for cluster_id, wallets in clusters_raw.items():
            if len(wallets) >= 2:  # Only clusters with 2+ wallets
                cluster = WalletCluster(
                    cluster_id=cluster_id[:15],
                    wallets=wallets,
                    first_seen=datetime.now(),
                )

                # Determine cluster type
                cluster.label = self._classify_cluster(wallets)
                cluster.risk_score = self._calculate_risk_score(wallets)

                clusters.append(cluster)

        return clusters

    def _classify_cluster(self, wallets: Set[str]) -> str:
        """Classify what type of cluster this is."""
        # Count connection types
        connection_types = defaultdict(int)

        for (a, b), conn in self.connections.items():
            if a in wallets or b in wallets:
                connection_types[conn.connection_type] += 1

        # Classify based on dominant connection type
        if connection_types['same_funder'] > len(wallets) * 0.5:
            return "Dev Cluster"
        elif connection_types['direct_transfer'] > len(wallets):
            return "Trading Network"
        elif connection_types['shared_tokens'] > len(wallets) * 2:
            return "Whale Pod"
        else:
            return "Connected Group"

    def _calculate_risk_score(self, wallets: Set[str]) -> float:
        """Calculate risk score for cluster (0-1, higher = more suspicious)."""
        score = 0.0

        # More wallets = higher risk
        if len(wallets) > 5:
            score += 0.3
        elif len(wallets) > 10:
            score += 0.5

        # Same funder connections are suspicious
        for (a, b), conn in self.connections.items():
            if (a in wallets or b in wallets) and conn.connection_type == 'same_funder':
                score += 0.1

        return min(score, 1.0)

    async def save_cluster_to_db(self, cluster: WalletCluster):
        """Save cluster to database."""
        conn = get_connection()
        cursor = conn.cursor()

        # Create tables if not exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet_clusters (
                cluster_id TEXT PRIMARY KEY,
                label TEXT,
                wallet_count INTEGER,
                risk_score REAL,
                connection_types TEXT,
                first_seen TIMESTAMP,
                last_updated TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cluster_members (
                cluster_id TEXT,
                wallet_address TEXT,
                role TEXT,
                added_at TIMESTAMP,
                PRIMARY KEY (cluster_id, wallet_address)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet_connections (
                wallet_a TEXT,
                wallet_b TEXT,
                connection_type TEXT,
                strength REAL,
                evidence TEXT,
                detected_at TIMESTAMP,
                PRIMARY KEY (wallet_a, wallet_b)
            )
        """)

        # Save cluster
        cursor.execute("""
            INSERT OR REPLACE INTO wallet_clusters (
                cluster_id, label, wallet_count, risk_score, first_seen, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            cluster.cluster_id,
            cluster.label,
            len(cluster.wallets),
            cluster.risk_score,
            cluster.first_seen.isoformat() if cluster.first_seen else datetime.now().isoformat(),
            datetime.now().isoformat(),
        ))

        # Save members
        for wallet in cluster.wallets:
            cursor.execute("""
                INSERT OR IGNORE INTO cluster_members (
                    cluster_id, wallet_address, role, added_at
                ) VALUES (?, ?, ?, ?)
            """, (
                cluster.cluster_id,
                wallet,
                "member",
                datetime.now().isoformat(),
            ))

        conn.commit()
        conn.close()

    async def save_connection_to_db(self, connection: WalletConnection):
        """Save connection to database."""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wallet_connections (
                wallet_a TEXT,
                wallet_b TEXT,
                connection_type TEXT,
                strength REAL,
                evidence TEXT,
                detected_at TIMESTAMP,
                PRIMARY KEY (wallet_a, wallet_b)
            )
        """)

        cursor.execute("""
            INSERT OR REPLACE INTO wallet_connections (
                wallet_a, wallet_b, connection_type, strength, evidence, detected_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            connection.wallet_a,
            connection.wallet_b,
            connection.connection_type,
            connection.strength,
            json.dumps(connection.evidence),
            datetime.now().isoformat(),
        ))

        conn.commit()
        conn.close()

    async def get_wallet_cluster_info(self, wallet: str) -> Optional[Dict]:
        """Get cluster info for a wallet if it belongs to one."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT c.cluster_id, c.label, c.wallet_count, c.risk_score
                FROM cluster_members m
                JOIN wallet_clusters c ON m.cluster_id = c.cluster_id
                WHERE m.wallet_address = ?
            """, (wallet,))

            row = cursor.fetchone()
            if row:
                return {
                    'cluster_id': row[0],
                    'label': row[1],
                    'wallet_count': row[2],
                    'risk_score': row[3],
                }
        except:
            pass
        finally:
            conn.close()

        return None


class ClusterScanner:
    """Background scanner for building cluster map."""

    def __init__(self):
        self.detector = ClusterDetector()
        self.running = False
        self.scan_interval = 600  # 10 minutes

    async def start(self):
        """Start the cluster scanner."""
        self.running = True
        logger.info("Cluster Scanner started")

        while self.running:
            try:
                await self._scan_cycle()
            except Exception as e:
                logger.error(f"Cluster scan failed: {e}")

            await asyncio.sleep(self.scan_interval)

    async def _scan_cycle(self):
        """Run one scan cycle on qualified wallets."""
        conn = get_connection()
        cursor = conn.cursor()

        # Get qualified wallets to analyze
        cursor.execute("""
            SELECT wallet_address FROM qualified_wallets
            ORDER BY priority_score DESC
            LIMIT 50
        """)

        wallets = [row[0] for row in cursor.fetchall()]
        conn.close()

        logger.info(f"Scanning {len(wallets)} wallets for connections")

        for wallet in wallets:
            try:
                connections = await self.detector.analyze_wallet_connections(wallet)

                for conn in connections:
                    # Store connection
                    key = (min(conn.wallet_a, conn.wallet_b), max(conn.wallet_a, conn.wallet_b))
                    self.detector.connections[key] = conn
                    await self.detector.save_connection_to_db(conn)

                await asyncio.sleep(0.5)  # Rate limiting

            except Exception as e:
                logger.error(f"Failed to analyze {wallet[:15]}...: {e}")

        # Build clusters from connections
        clusters = self.detector.build_clusters()
        logger.info(f"Found {len(clusters)} clusters")

        for cluster in clusters:
            await self.detector.save_cluster_to_db(cluster)

    def stop(self):
        """Stop the scanner."""
        self.running = False


async def main():
    """Test the cluster detector."""
    detector = ClusterDetector()

    # Test with a wallet
    test_wallet = "DYw8jCTfwHNRJhhmFcbXvVDTqWMEVFBX6ZKUmG5CNSKK"

    print(f"Analyzing connections for {test_wallet[:20]}...")
    connections = await detector.analyze_wallet_connections(test_wallet)

    print(f"\nFound {len(connections)} connections:")
    for conn in connections[:5]:
        print(f"  {conn.connection_type}: {conn.wallet_b[:20]}...")
        print(f"    Strength: {conn.strength:.2f}")
        print(f"    Evidence: {conn.evidence}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
