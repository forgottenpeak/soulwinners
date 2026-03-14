#!/usr/bin/env python3
"""
Continuous Learning Pipeline for V3 Edge Auto-Trader

Weekly retraining with new trade outcomes.
Appends closed trades to training set and deploys new model version.

Usage:
    python ml/continuous_learning.py [--retrain] [--label-outcomes] [--deploy]

Cron schedule (every Saturday at 3 AM UTC):
    0 3 * * 6 cd /root/Soulwinners && python ml/continuous_learning.py --retrain --deploy >> logs/ml_training.log 2>&1
"""
import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import aiohttp
import asyncio

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection
from ml.train_model import ModelTrainer
from ml.feature_engineering import FeatureEngineer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OutcomeLabeler:
    """
    Label trade outcomes based on subsequent price action.

    Outcome definitions:
    - RUNNER: Token achieved 2x+ from entry price
    - RUG: Token dropped 80%+ from entry price
    - SIDEWAYS: Neither runner nor rug
    """

    # Outcome thresholds
    RUNNER_THRESHOLD = 2.0      # 2x from entry = runner
    RUG_THRESHOLD = -0.80       # -80% from entry = rug
    MIN_HOLDING_HOURS = 24      # Minimum time to wait before labeling

    def __init__(self):
        self.labeled_count = 0
        self.runner_count = 0
        self.rug_count = 0
        self.sideways_count = 0

    async def get_token_peak_and_current(
        self,
        token_address: str,
        entry_mcap: float,
        session: aiohttp.ClientSession,
    ) -> Dict:
        """
        Get token's peak and current market cap.

        Returns:
            Dict with peak_mcap, current_mcap, and roi calculations
        """
        try:
            url = f"https://api.dexscreener.com/tokens/v1/solana/{token_address}"
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if data and len(data) > 0:
                        pair = data[0]
                        current_mcap = float(pair.get('marketCap', 0) or 0)

                        # We don't have historical peak from API
                        # Use current as approximation (will improve with historical data)
                        return {
                            "current_mcap": current_mcap,
                            "peak_mcap": current_mcap,  # Would need historical tracking
                            "current_roi": ((current_mcap - entry_mcap) / entry_mcap * 100)
                                           if entry_mcap > 0 else 0,
                        }

        except Exception as e:
            logger.debug(f"Could not fetch token data: {e}")

        return {
            "current_mcap": 0,
            "peak_mcap": 0,
            "current_roi": 0,
        }

    def determine_outcome(
        self,
        entry_mcap: float,
        peak_mcap: float,
        current_mcap: float,
    ) -> tuple:
        """
        Determine trade outcome based on price action.

        Returns:
            (outcome, roi_percent, max_drawdown)
        """
        if entry_mcap <= 0:
            return "sideways", 0, 0

        # Calculate peak ROI
        peak_roi = (peak_mcap - entry_mcap) / entry_mcap

        # Calculate current ROI
        current_roi = (current_mcap - entry_mcap) / entry_mcap

        # Calculate max drawdown from peak
        if peak_mcap > 0:
            max_drawdown = (current_mcap - peak_mcap) / peak_mcap
        else:
            max_drawdown = 0

        # Determine outcome
        if peak_roi >= self.RUNNER_THRESHOLD - 1:  # 2x = 100% gain
            outcome = "runner"
        elif current_roi <= self.RUG_THRESHOLD:
            outcome = "rug"
        else:
            outcome = "sideways"

        return outcome, current_roi * 100, max_drawdown * 100

    async def label_unlabeled_events(self, batch_size: int = 100) -> Dict:
        """
        Label trade events that don't have outcomes yet.

        Only labels events that are old enough (> MIN_HOLDING_HOURS).
        """
        conn = get_connection()
        cursor = conn.cursor()

        # Get unlabeled buy events that are old enough
        cutoff_ts = int((datetime.now() - timedelta(hours=self.MIN_HOLDING_HOURS)).timestamp())

        cursor.execute(f"""
            SELECT id, token_address, marketcap_at_trade, timestamp
            FROM trade_events
            WHERE outcome IS NULL
            AND trade_type = 'buy'
            AND timestamp < ?
            ORDER BY timestamp ASC
            LIMIT ?
        """, (cutoff_ts, batch_size))

        events = cursor.fetchall()
        conn.close()

        if not events:
            logger.info("No unlabeled events to process")
            return {"labeled": 0}

        logger.info(f"Labeling {len(events)} trade events...")

        connector = aiohttp.TCPConnector(limit=10)
        async with aiohttp.ClientSession(connector=connector) as session:
            for event_id, token_address, entry_mcap, timestamp in events:
                try:
                    # Get current token data
                    token_data = await self.get_token_peak_and_current(
                        token_address, entry_mcap or 0, session
                    )

                    # Determine outcome
                    outcome, roi, drawdown = self.determine_outcome(
                        entry_mcap=entry_mcap or 0,
                        peak_mcap=token_data["peak_mcap"],
                        current_mcap=token_data["current_mcap"],
                    )

                    # Update database
                    self._save_outcome(
                        event_id=event_id,
                        outcome=outcome,
                        final_roi=roi,
                        max_drawdown=drawdown,
                        peak_mcap=token_data["peak_mcap"],
                    )

                    self.labeled_count += 1
                    if outcome == "runner":
                        self.runner_count += 1
                    elif outcome == "rug":
                        self.rug_count += 1
                    else:
                        self.sideways_count += 1

                    # Rate limit
                    await asyncio.sleep(0.5)

                except Exception as e:
                    logger.warning(f"Error labeling event {event_id}: {e}")

        return {
            "labeled": self.labeled_count,
            "runners": self.runner_count,
            "rugs": self.rug_count,
            "sideways": self.sideways_count,
        }

    def _save_outcome(
        self,
        event_id: int,
        outcome: str,
        final_roi: float,
        max_drawdown: float,
        peak_mcap: float,
    ):
        """Save outcome to database."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE trade_events
                SET outcome = ?,
                    final_roi_percent = ?,
                    max_drawdown_percent = ?,
                    max_mc_after_entry = ?,
                    outcome_filled_at = ?
                WHERE id = ?
            """, (
                outcome,
                final_roi,
                max_drawdown,
                peak_mcap,
                datetime.now().isoformat(),
                event_id,
            ))
            conn.commit()

        except Exception as e:
            logger.error(f"Error saving outcome: {e}")
        finally:
            conn.close()


class ContinuousLearner:
    """
    Manages the continuous learning pipeline.

    Workflow:
    1. Label new trade outcomes
    2. Build updated training dataset
    3. Train new model version
    4. Evaluate against previous version
    5. Deploy if improved
    """

    def __init__(self):
        self.labeler = OutcomeLabeler()
        self.trainer = None

    async def run_labeling(self, batch_size: int = 500) -> Dict:
        """Run outcome labeling on recent trades."""
        logger.info("=" * 60)
        logger.info("STEP 1: Labeling Trade Outcomes")
        logger.info("=" * 60)

        total_labeled = 0
        total_runners = 0
        total_rugs = 0
        total_sideways = 0

        # Process in batches
        while True:
            result = await self.labeler.label_unlabeled_events(batch_size)

            if result["labeled"] == 0:
                break

            total_labeled += result["labeled"]
            total_runners += result["runners"]
            total_rugs += result["rugs"]
            total_sideways += result["sideways"]

            logger.info(f"Batch complete: {result['labeled']} labeled "
                       f"({result['runners']} runners, {result['rugs']} rugs, "
                       f"{result['sideways']} sideways)")

        logger.info(f"\nTotal labeled: {total_labeled}")
        logger.info(f"  Runners: {total_runners} ({total_runners/max(total_labeled, 1)*100:.1f}%)")
        logger.info(f"  Rugs: {total_rugs} ({total_rugs/max(total_labeled, 1)*100:.1f}%)")
        logger.info(f"  Sideways: {total_sideways} ({total_sideways/max(total_labeled, 1)*100:.1f}%)")

        return {
            "total_labeled": total_labeled,
            "runners": total_runners,
            "rugs": total_rugs,
            "sideways": total_sideways,
        }

    def run_training(
        self,
        model_type: str = "xgboost",
        min_samples: int = 1000,
    ) -> Optional[str]:
        """
        Train a new model on updated dataset.

        Returns:
            Model version string if successful, None otherwise
        """
        logger.info("=" * 60)
        logger.info("STEP 2: Training New Model")
        logger.info("=" * 60)

        try:
            self.trainer = ModelTrainer(model_type=model_type)

            # Load data
            X, y = self.trainer.load_data(
                min_samples=min_samples,
                only_labeled=True,
            )

            if len(X) < min_samples:
                logger.warning(f"Insufficient data: {len(X)} samples")
                return None

            # Train
            self.trainer.train(X, y)

            # Get feature importance
            self.trainer.get_feature_importance()

            # Save model
            version = datetime.now().strftime("v%Y%m%d_%H%M%S")
            model_path = self.trainer.save_model(version)

            logger.info(f"Model saved: {version}")

            return version

        except Exception as e:
            logger.error(f"Training failed: {e}")
            return None

    def compare_models(
        self,
        new_version: str,
        metric: str = "f1_runner",
    ) -> Dict:
        """
        Compare new model against currently active model.

        Returns:
            Comparison results
        """
        logger.info("=" * 60)
        logger.info("STEP 3: Model Comparison")
        logger.info("=" * 60)

        conn = get_connection()
        cursor = conn.cursor()

        # Get active model metrics
        cursor.execute("""
            SELECT model_version, accuracy, precision_runner, recall_runner, f1_runner
            FROM ml_models
            WHERE is_active = 1
        """)
        active = cursor.fetchone()

        # Get new model metrics
        cursor.execute("""
            SELECT model_version, accuracy, precision_runner, recall_runner, f1_runner
            FROM ml_models
            WHERE model_version = ?
        """, (new_version,))
        new = cursor.fetchone()

        conn.close()

        if not active:
            logger.info("No active model - new model will be deployed")
            return {"should_deploy": True, "reason": "No active model"}

        if not new:
            logger.warning("Could not find new model metrics")
            return {"should_deploy": False, "reason": "New model not found"}

        # Compare metrics
        metric_idx = {"accuracy": 1, "precision_runner": 2, "recall_runner": 3, "f1_runner": 4}[metric]

        active_score = active[metric_idx] or 0
        new_score = new[metric_idx] or 0
        improvement = new_score - active_score

        logger.info(f"Active model ({active[0]}): {metric} = {active_score:.4f}")
        logger.info(f"New model ({new[0]}): {metric} = {new_score:.4f}")
        logger.info(f"Improvement: {improvement:+.4f}")

        # Deploy if improved
        should_deploy = improvement > 0

        return {
            "should_deploy": should_deploy,
            "active_version": active[0],
            "new_version": new[0],
            "active_score": active_score,
            "new_score": new_score,
            "improvement": improvement,
            "metric": metric,
            "reason": f"New model {'improved' if should_deploy else 'did not improve'} {metric}",
        }

    def deploy_model(self, version: str):
        """Deploy a specific model version."""
        logger.info("=" * 60)
        logger.info("STEP 4: Model Deployment")
        logger.info("=" * 60)

        if self.trainer is None:
            self.trainer = ModelTrainer()

        self.trainer.deploy_model(version)
        logger.info(f"Model {version} is now active")

    async def run_full_pipeline(
        self,
        model_type: str = "xgboost",
        min_samples: int = 1000,
        auto_deploy: bool = True,
    ) -> Dict:
        """
        Run the complete continuous learning pipeline.

        Args:
            model_type: Type of model to train
            min_samples: Minimum samples required
            auto_deploy: Automatically deploy if improved

        Returns:
            Pipeline results
        """
        start_time = datetime.now()

        logger.info("=" * 60)
        logger.info("V3 EDGE: CONTINUOUS LEARNING PIPELINE")
        logger.info(f"Started at: {start_time.isoformat()}")
        logger.info("=" * 60)

        results = {
            "started_at": start_time.isoformat(),
            "labeling": None,
            "training": None,
            "comparison": None,
            "deployed": False,
        }

        # Step 1: Label outcomes
        labeling_result = await self.run_labeling()
        results["labeling"] = labeling_result

        # Step 2: Train new model
        new_version = self.run_training(model_type, min_samples)
        results["training"] = {"version": new_version}

        if not new_version:
            logger.warning("Training failed or insufficient data")
            return results

        # Step 3: Compare models
        comparison = self.compare_models(new_version)
        results["comparison"] = comparison

        # Step 4: Deploy if improved (or no active model)
        if auto_deploy and comparison["should_deploy"]:
            self.deploy_model(new_version)
            results["deployed"] = True

        # Summary
        elapsed = (datetime.now() - start_time).total_seconds() / 60

        logger.info("\n" + "=" * 60)
        logger.info("PIPELINE COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Duration: {elapsed:.1f} minutes")
        logger.info(f"Events labeled: {labeling_result['total_labeled']}")
        logger.info(f"Model trained: {new_version}")
        logger.info(f"Deployed: {results['deployed']}")

        results["elapsed_minutes"] = elapsed

        return results


def get_dataset_stats() -> Dict:
    """Get current dataset statistics."""
    conn = get_connection()
    cursor = conn.cursor()

    stats = {}

    # Total events
    cursor.execute("SELECT COUNT(*) FROM trade_events WHERE trade_type = 'buy'")
    stats["total_buy_events"] = cursor.fetchone()[0]

    # Labeled events
    cursor.execute("SELECT COUNT(*) FROM trade_events WHERE outcome IS NOT NULL")
    stats["labeled_events"] = cursor.fetchone()[0]

    # By outcome
    cursor.execute("""
        SELECT outcome, COUNT(*)
        FROM trade_events
        WHERE outcome IS NOT NULL
        GROUP BY outcome
    """)
    stats["by_outcome"] = dict(cursor.fetchall())

    # Pending labeling
    stats["pending_labeling"] = stats["total_buy_events"] - stats["labeled_events"]

    # Position lifecycle stats (V3)
    try:
        cursor.execute("SELECT COUNT(*) FROM position_lifecycle")
        stats["lifecycle_total"] = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM position_lifecycle
            WHERE outcome IS NOT NULL AND outcome != 'open'
        """)
        stats["lifecycle_labeled"] = cursor.fetchone()[0]

        cursor.execute("""
            SELECT outcome, COUNT(*)
            FROM position_lifecycle
            WHERE outcome IS NOT NULL AND outcome != 'open'
            GROUP BY outcome
        """)
        stats["lifecycle_by_outcome"] = dict(cursor.fetchall())
    except:
        stats["lifecycle_total"] = 0
        stats["lifecycle_labeled"] = 0
        stats["lifecycle_by_outcome"] = {}

    conn.close()

    return stats


def get_lifecycle_training_data() -> list:
    """
    Get training data from position_lifecycle table.

    This provides higher quality labeled data with:
    - Accurate entry/exit timestamps
    - Peak MC tracked hourly
    - Proper sell matching (FIFO)

    Returns:
        List of dicts with training features and labels
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Join with trade_events to get full feature set
        cursor.execute("""
            SELECT
                pl.id,
                pl.wallet_address,
                pl.wallet_type,
                pl.wallet_tier,
                pl.token_address,
                pl.token_symbol,
                pl.entry_timestamp,
                pl.entry_mc,
                pl.entry_liquidity,
                pl.buy_sol_amount,
                pl.peak_mc,
                pl.time_to_peak_hours,
                pl.exit_mc,
                pl.sell_sol_received,
                pl.final_roi_percent,
                pl.hold_duration_hours,
                pl.outcome,
                -- Trade event features if available
                te.token_age_hours,
                te.volume_24h_at_trade,
                te.holder_count_at_trade,
                te.buy_sell_ratio_at_trade
            FROM position_lifecycle pl
            LEFT JOIN trade_events te ON pl.buy_event_id = te.id
            WHERE pl.outcome IS NOT NULL
            AND pl.outcome != 'open'
            AND pl.final_roi_percent IS NOT NULL
            ORDER BY pl.entry_timestamp DESC
        """)

        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

        return [dict(zip(columns, row)) for row in rows]

    except Exception as e:
        logger.warning(f"Error getting lifecycle training data: {e}")
        return []

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Continuous learning pipeline for V3 Edge Auto-Trader"
    )
    parser.add_argument(
        "--label-outcomes",
        action="store_true",
        help="Label trade outcomes only"
    )
    parser.add_argument(
        "--retrain",
        action="store_true",
        help="Run full retraining pipeline"
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Auto-deploy if model improves"
    )
    parser.add_argument(
        "--model",
        choices=["xgboost", "lightgbm"],
        default="xgboost",
        help="Model type"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show dataset statistics"
    )

    args = parser.parse_args()

    if args.stats:
        stats = get_dataset_stats()
        print("\n" + "=" * 60)
        print("DATASET STATISTICS")
        print("=" * 60)
        print(f"Total buy events: {stats['total_buy_events']:,}")
        print(f"Labeled events: {stats['labeled_events']:,}")
        print(f"Pending labeling: {stats['pending_labeling']:,}")
        print(f"\nBy outcome:")
        for outcome, count in stats.get('by_outcome', {}).items():
            pct = count / max(stats['labeled_events'], 1) * 100
            print(f"  {outcome}: {count:,} ({pct:.1f}%)")
        return

    learner = ContinuousLearner()

    if args.label_outcomes:
        # Just run labeling
        asyncio.run(learner.run_labeling())

    elif args.retrain:
        # Full pipeline
        result = asyncio.run(learner.run_full_pipeline(
            model_type=args.model,
            auto_deploy=args.deploy,
        ))
        print(f"\nPipeline result: {result}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
