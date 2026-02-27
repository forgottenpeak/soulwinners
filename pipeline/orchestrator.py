"""
Pipeline Orchestrator
Runs the complete data pipeline: Collect → Calculate → Cluster → Rank → Filter
Designed to run daily at midnight UTC
"""
import asyncio
import logging
import pandas as pd
from datetime import datetime
from typing import Optional
import sqlite3

from config.settings import DATABASE_PATH, DATA_DIR, TARGET_WALLETS_DAILY
from database import init_database, get_connection
from collectors.pumpfun import PumpFunCollector
from collectors.dexscreener import DexScreenerCollector
from pipeline.metrics import MetricsCalculator
from pipeline.clustering import ClusteringPipeline
from pipeline.ranking import RankingSystem, QualityFilter

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """
    Orchestrates the full wallet analysis pipeline.

    Steps:
    1. Collect wallets from Pump.fun and DexScreener
    2. Merge and deduplicate, tag source
    3. Calculate all performance metrics
    4. Run K-Means clustering
    5. Calculate priority scores and assign tiers
    6. Apply quality filters
    7. Save qualified wallets to database
    """

    def __init__(self):
        self.metrics_calculator = MetricsCalculator()
        self.clustering = ClusteringPipeline()
        self.ranking = RankingSystem()
        self.quality_filter = QualityFilter()

    async def run_full_pipeline(self) -> pd.DataFrame:
        """Execute the complete pipeline."""
        run_id = self._start_pipeline_run()

        try:
            logger.info("=" * 60)
            logger.info("STARTING SOULWINNERS PIPELINE")
            logger.info("=" * 60)

            # STEP 1: Data Collection
            logger.info("\n[STEP 1/6] Collecting wallets...")
            pumpfun_wallets, dex_wallets = await self._collect_wallets()

            # STEP 2: Merge and Calculate Metrics
            logger.info("\n[STEP 2/6] Merging wallets and calculating metrics...")
            df_metrics = self.metrics_calculator.merge_wallet_sources(
                pumpfun_wallets,
                dex_wallets
            )

            if df_metrics.empty:
                logger.error("No wallets collected! Keeping existing pool intact.")
                self._complete_pipeline_run(run_id, 'failed', error="No wallets collected - pool unchanged")
                # Return empty df but DON'T touch the database
                return pd.DataFrame()

            logger.info(f"Merged wallets: {len(df_metrics)}")

            # STEP 3: K-Means Clustering
            logger.info("\n[STEP 3/6] Running K-Means clustering...")
            df_clustered = self.clustering.fit_transform(df_metrics)
            self.clustering.save_model()

            # STEP 4: Priority Scoring & Tier Assignment
            logger.info("\n[STEP 4/6] Calculating priority scores and assigning tiers...")
            df_ranked = self.ranking.rank_and_tier(df_clustered)

            # STEP 5: Quality Filtering
            logger.info("\n[STEP 5/6] Applying quality filters...")
            df_qualified = self.quality_filter.apply_filters(df_ranked)

            # STEP 6: Save to Database (ONLY ADD, NEVER REMOVE)
            logger.info("\n[STEP 6/6] Saving to database...")

            # Safety check: If qualified wallets are very few, log warning
            if len(df_qualified) < 5:
                logger.warning(f"Only {len(df_qualified)} wallets qualified - adding to pool without removing any")

            added, removed = self._save_qualified_wallets(df_qualified)

            # Save full ranked data for analysis
            self._save_all_metrics(df_ranked)

            # Export to CSV (your df_ranked.csv format)
            self._export_csv(df_qualified)

            # Complete pipeline run
            self._complete_pipeline_run(
                run_id,
                'completed',
                wallets_collected=len(df_metrics),
                wallets_qualified=len(df_qualified),
                wallets_added=added,
                wallets_removed=removed
            )

            logger.info("\n" + "=" * 60)
            logger.info("PIPELINE COMPLETED SUCCESSFULLY")
            logger.info(f"Qualified wallets: {len(df_qualified)}")
            logger.info(f"Added: {added}, Removed: {removed}")
            logger.info("=" * 60)

            return df_qualified

        except Exception as e:
            logger.error(f"Pipeline failed: {e}", exc_info=True)
            self._complete_pipeline_run(run_id, 'failed', error=str(e))
            raise

    async def _collect_wallets(self) -> tuple:
        """Collect wallets from both sources."""
        target_per_source = TARGET_WALLETS_DAILY // 2

        pumpfun_wallets = []
        dex_wallets = []

        # Collect from Pump.fun
        try:
            async with PumpFunCollector() as collector:
                # Use fresh launches from birth (0-24 hours old)
                # Get insiders, dev team, fastest snipers!
                pumpfun_wallets = await collector.collect_wallets(
                    target_count=target_per_source,
                    use_fresh_launches=True  # Scan 0-24h launches from birth, not trending
                )
                logger.info(f"Collected {len(pumpfun_wallets)} pump.fun wallets from fresh launches")
        except Exception as e:
            logger.error(f"Pump.fun collection failed: {e}")

        # Collect from DexScreener
        try:
            async with DexScreenerCollector() as collector:
                dex_wallets = await collector.collect_wallets(target_count=target_per_source)
                logger.info(f"Collected {len(dex_wallets)} DEX wallets")
        except Exception as e:
            logger.error(f"DexScreener collection failed: {e}")

        return pumpfun_wallets, dex_wallets

    def _save_qualified_wallets(self, df: pd.DataFrame) -> tuple:
        """Save qualified wallets to database. NEVER removes wallets - only adds/updates."""
        conn = get_connection()
        cursor = conn.cursor()

        # Get current qualified wallets
        cursor.execute("SELECT wallet_address FROM qualified_wallets")
        current_wallets = set(row[0] for row in cursor.fetchall())

        logger.info(f"Current pool size: {len(current_wallets)} wallets")

        # If no new wallets in df, just keep existing pool unchanged
        if df.empty:
            logger.warning("No new qualified wallets in this run - keeping existing pool intact")
            conn.close()
            return 0, 0

        new_wallets = set(df['wallet_address'].tolist())
        logger.info(f"New qualified wallets in this run: {len(new_wallets)}")

        # Calculate new additions only (NEVER remove wallets)
        added = new_wallets - current_wallets
        logger.info(f"New wallets to add: {len(added)}")
        # removed = 0 - we keep ALL wallets forever, they just drop in leaderboard

        # Insert/update qualified wallets (existing wallets get updated metrics)
        # This ONLY updates wallets in df, leaving others untouched
        for _, row in df.iterrows():
            cursor.execute("""
                INSERT OR REPLACE INTO qualified_wallets (
                    wallet_address, source, roi_pct, median_roi_pct,
                    profit_token_ratio, trade_frequency, roi_per_trade,
                    x10_ratio, x20_ratio, x50_ratio, x100_ratio,
                    median_hold_time, profit_per_hold_second,
                    cluster, cluster_label, cluster_name,
                    roi_final, priority_score, tier, strategy_bucket,
                    current_balance_sol, total_trades, win_rate,
                    qualified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row.get('wallet_address'),
                row.get('source'),
                row.get('roi_pct'),
                row.get('median_roi_pct'),
                row.get('profit_token_ratio'),
                row.get('trade_frequency'),
                row.get('roi_per_trade'),
                row.get('x10_ratio'),
                row.get('x20_ratio'),
                row.get('x50_ratio'),
                row.get('x100_ratio'),
                row.get('median_hold_time'),
                row.get('profit_per_hold_second'),
                row.get('cluster'),
                row.get('cluster_label'),
                row.get('cluster_name'),
                row.get('roi_final'),
                row.get('priority_score'),
                row.get('tier'),
                row.get('strategy_bucket'),
                row.get('current_balance_sol'),
                row.get('total_trades'),
                row.get('profit_token_ratio'),  # win_rate
                datetime.now().isoformat()
            ))

        conn.commit()
        conn.close()

        return len(added), 0  # Never remove wallets

    def _save_all_metrics(self, df: pd.DataFrame):
        """Save all wallet metrics (not just qualified) for analysis."""
        conn = get_connection()

        # Save to wallet_metrics table
        for _, row in df.iterrows():
            conn.execute("""
                INSERT OR REPLACE INTO wallet_metrics (
                    wallet_address, source, current_balance_sol, total_trades,
                    buy_transactions, sell_transactions, unique_tokens_traded,
                    roi_pct, median_roi_pct, profit_token_ratio, trade_frequency,
                    roi_per_trade, x10_ratio, x20_ratio, x50_ratio, x100_ratio,
                    median_hold_time, profit_per_hold_second,
                    cluster, cluster_label, cluster_name,
                    roi_final, priority_score, tier, strategy_bucket,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row.get('wallet_address'),
                row.get('source'),
                row.get('current_balance_sol'),
                row.get('total_trades'),
                row.get('buy_transactions'),
                row.get('sell_transactions'),
                row.get('unique_tokens_traded'),
                row.get('roi_pct'),
                row.get('median_roi_pct'),
                row.get('profit_token_ratio'),
                row.get('trade_frequency'),
                row.get('roi_per_trade'),
                row.get('x10_ratio'),
                row.get('x20_ratio'),
                row.get('x50_ratio'),
                row.get('x100_ratio'),
                row.get('median_hold_time'),
                row.get('profit_per_hold_second'),
                row.get('cluster'),
                row.get('cluster_label'),
                row.get('cluster_name'),
                row.get('roi_final'),
                row.get('priority_score'),
                row.get('tier'),
                row.get('strategy_bucket'),
                datetime.now().isoformat()
            ))

        conn.commit()
        conn.close()

    def _export_csv(self, df: pd.DataFrame):
        """Export qualified wallets to CSV in your df_ranked format."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Define columns in your exact order
        columns = [
            'wallet_address', 'source', 'roi_pct', 'median_roi_pct',
            'profit_token_ratio', 'trade_frequency', 'roi_per_trade',
            'x10_ratio', 'x20_ratio', 'x50_ratio', 'x100_ratio',
            'median_hold_time', 'profit_per_hold_second',
            'cluster', 'cluster_label', 'cluster_name',
            'roi_final', 'priority_score', 'tier', 'strategy_bucket'
        ]

        # Select and reorder columns
        df_export = df[[c for c in columns if c in df.columns]].copy()

        # Save with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = DATA_DIR / f"df_ranked_{timestamp}.csv"
        df_export.to_csv(filepath, index=False)
        logger.info(f"Exported to {filepath}")

        # Also save as latest
        latest_path = DATA_DIR / "df_ranked.csv"
        df_export.to_csv(latest_path, index=False)
        logger.info(f"Exported to {latest_path}")

    def _start_pipeline_run(self) -> int:
        """Record start of pipeline run."""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO pipeline_runs (started_at, status)
            VALUES (?, 'running')
        """, (datetime.now().isoformat(),))
        run_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return run_id

    def _complete_pipeline_run(
        self,
        run_id: int,
        status: str,
        wallets_collected: int = 0,
        wallets_qualified: int = 0,
        wallets_added: int = 0,
        wallets_removed: int = 0,
        error: str = None
    ):
        """Record completion of pipeline run."""
        conn = get_connection()
        conn.execute("""
            UPDATE pipeline_runs SET
                completed_at = ?,
                status = ?,
                wallets_collected = ?,
                wallets_qualified = ?,
                wallets_added = ?,
                wallets_removed = ?,
                error_message = ?
            WHERE id = ?
        """, (
            datetime.now().isoformat(),
            status,
            wallets_collected,
            wallets_qualified,
            wallets_added,
            wallets_removed,
            error,
            run_id
        ))
        conn.commit()
        conn.close()


async def main():
    """Run the pipeline."""
    # Initialize database
    init_database()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run pipeline
    orchestrator = PipelineOrchestrator()
    df_qualified = await orchestrator.run_full_pipeline()

    if not df_qualified.empty:
        print(f"\n✅ Pipeline completed! {len(df_qualified)} qualified wallets")
        print("\nTop 5 wallets:")
        print(df_qualified[['wallet_address', 'tier', 'priority_score']].head())


if __name__ == "__main__":
    asyncio.run(main())
