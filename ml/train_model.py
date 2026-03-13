#!/usr/bin/env python3
"""
ML Model Training for V3 Edge Auto-Trader

Trains XGBoost/LightGBM models on historical trade data.

Objectives:
1. Multi-class classification: runner/sideways/rug
2. Probability estimates for each outcome
3. Expected ROI regression

Usage:
    python ml/train_model.py [--model xgboost|lightgbm] [--save] [--deploy]
"""
import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import numpy as np
import joblib

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from database import get_connection
from ml.feature_engineering import FeatureEngineer

# Optional imports - will use what's available
try:
    import xgboost as xgb
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False
    xgb = None

try:
    import lightgbm as lgb
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False
    lgb = None

try:
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score,
        classification_report, confusion_matrix, roc_auc_score
    )
    from sklearn.preprocessing import LabelEncoder
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Model save directory
MODEL_DIR = Path(__file__).parent.parent / "data" / "models"


class ModelTrainer:
    """
    Train and evaluate ML models for trade outcome prediction.

    Supports:
    - XGBoost (default)
    - LightGBM

    Output:
    - Multi-class classifier (runner/sideways/rug)
    - Probability estimates
    - Feature importance
    """

    OUTCOME_LABELS = {0: "rug", 1: "sideways", 2: "runner"}

    def __init__(self, model_type: str = "xgboost"):
        self.model_type = model_type
        self.model = None
        self.feature_names = None
        self.metrics = {}

        # Create model directory
        MODEL_DIR.mkdir(parents=True, exist_ok=True)

    def load_data(
        self,
        min_samples: int = 1000,
        only_labeled: bool = True,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Load training data from database.

        Args:
            min_samples: Minimum samples required to train
            only_labeled: Only use events with outcome labels

        Returns:
            (X, y) - features and labels
        """
        engineer = FeatureEngineer()
        self.feature_names = engineer.get_feature_names()

        X, y, event_ids = engineer.build_training_dataset(
            limit=None,
            only_with_outcomes=only_labeled,
        )

        if len(X) < min_samples:
            logger.warning(f"Only {len(X)} samples available (need {min_samples})")
            logger.info("You may need to run outcome labeling first")

        logger.info(f"Loaded {len(X)} samples with {len(self.feature_names)} features")

        return X, y

    def balance_classes(
        self,
        X: np.ndarray,
        y: np.ndarray,
        strategy: str = "oversample",
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Balance class distribution.

        Args:
            X: Feature matrix
            y: Labels
            strategy: 'oversample' or 'undersample'

        Returns:
            Balanced (X, y)
        """
        unique, counts = np.unique(y, return_counts=True)
        logger.info(f"Original distribution: {dict(zip(unique, counts))}")

        if strategy == "oversample":
            # Oversample minority classes to match majority
            max_count = counts.max()
            X_balanced = []
            y_balanced = []

            for label in unique:
                mask = y == label
                X_class = X[mask]
                count = len(X_class)

                if count < max_count:
                    # Oversample with replacement
                    indices = np.random.choice(count, max_count, replace=True)
                    X_balanced.append(X_class[indices])
                    y_balanced.append(np.full(max_count, label))
                else:
                    X_balanced.append(X_class)
                    y_balanced.append(np.full(count, label))

            X = np.vstack(X_balanced)
            y = np.concatenate(y_balanced)

        elif strategy == "undersample":
            # Undersample majority to match minority
            min_count = counts.min()
            X_balanced = []
            y_balanced = []

            for label in unique:
                mask = y == label
                X_class = X[mask]
                indices = np.random.choice(len(X_class), min_count, replace=False)
                X_balanced.append(X_class[indices])
                y_balanced.append(np.full(min_count, label))

            X = np.vstack(X_balanced)
            y = np.concatenate(y_balanced)

        # Shuffle
        perm = np.random.permutation(len(y))
        X = X[perm]
        y = y[perm]

        unique, counts = np.unique(y, return_counts=True)
        logger.info(f"Balanced distribution: {dict(zip(unique, counts))}")

        return X, y

    def train_xgboost(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ):
        """Train XGBoost classifier."""
        if not HAS_XGBOOST:
            raise ImportError("XGBoost not installed. Run: pip install xgboost")

        logger.info("Training XGBoost model...")

        # Parameters tuned for trading prediction
        params = {
            'objective': 'multi:softprob',
            'num_class': 3,
            'eval_metric': ['mlogloss', 'merror'],
            'max_depth': 6,
            'learning_rate': 0.1,
            'n_estimators': 200,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'min_child_weight': 3,
            'gamma': 0.1,
            'reg_alpha': 0.1,
            'reg_lambda': 1.0,
            'random_state': 42,
        }

        # Create DMatrix
        dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=self.feature_names)
        dval = xgb.DMatrix(X_val, label=y_val, feature_names=self.feature_names)

        # Train with early stopping
        evals = [(dtrain, 'train'), (dval, 'val')]
        self.model = xgb.train(
            params,
            dtrain,
            num_boost_round=500,
            evals=evals,
            early_stopping_rounds=30,
            verbose_eval=50,
        )

        logger.info(f"Best iteration: {self.model.best_iteration}")

    def train_lightgbm(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ):
        """Train LightGBM classifier."""
        if not HAS_LIGHTGBM:
            raise ImportError("LightGBM not installed. Run: pip install lightgbm")

        logger.info("Training LightGBM model...")

        params = {
            'objective': 'multiclass',
            'num_class': 3,
            'metric': ['multi_logloss', 'multi_error'],
            'boosting_type': 'gbdt',
            'num_leaves': 31,
            'learning_rate': 0.1,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'min_child_samples': 20,
            'lambda_l1': 0.1,
            'lambda_l2': 1.0,
            'verbose': -1,
            'random_state': 42,
        }

        # Create datasets
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

        # Train with callbacks
        callbacks = [
            lgb.early_stopping(30),
            lgb.log_evaluation(50),
        ]

        self.model = lgb.train(
            params,
            train_data,
            num_boost_round=500,
            valid_sets=[train_data, val_data],
            valid_names=['train', 'val'],
            callbacks=callbacks,
        )

        logger.info(f"Best iteration: {self.model.best_iteration}")

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        test_size: float = 0.2,
        balance: bool = True,
    ):
        """
        Full training pipeline.

        Args:
            X: Feature matrix
            y: Labels
            test_size: Validation split ratio
            balance: Whether to balance classes
        """
        if not HAS_SKLEARN:
            raise ImportError("scikit-learn not installed. Run: pip install scikit-learn")

        # Split data
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=test_size, stratify=y, random_state=42
        )

        logger.info(f"Train size: {len(X_train)}, Validation size: {len(X_val)}")

        # Balance training data
        if balance:
            X_train, y_train = self.balance_classes(X_train, y_train)

        # Train model
        if self.model_type == "xgboost":
            self.train_xgboost(X_train, y_train, X_val, y_val)
        elif self.model_type == "lightgbm":
            self.train_lightgbm(X_train, y_train, X_val, y_val)
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")

        # Evaluate
        self.evaluate(X_val, y_val)

    def predict(self, X: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Make predictions with probability estimates.

        Args:
            X: Feature matrix

        Returns:
            (predictions, probabilities) - class labels and prob matrix
        """
        if self.model is None:
            raise ValueError("Model not trained")

        if self.model_type == "xgboost":
            dmatrix = xgb.DMatrix(X, feature_names=self.feature_names)
            probs = self.model.predict(dmatrix)
        elif self.model_type == "lightgbm":
            probs = self.model.predict(X)
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")

        preds = np.argmax(probs, axis=1)

        return preds, probs

    def evaluate(self, X: np.ndarray, y: np.ndarray) -> Dict:
        """
        Evaluate model performance.

        Returns dict with all metrics.
        """
        preds, probs = self.predict(X)

        # Basic metrics
        self.metrics["accuracy"] = accuracy_score(y, preds)

        # Per-class metrics
        for label, name in self.OUTCOME_LABELS.items():
            y_binary = (y == label).astype(int)
            pred_binary = (preds == label).astype(int)

            self.metrics[f"precision_{name}"] = precision_score(y_binary, pred_binary, zero_division=0)
            self.metrics[f"recall_{name}"] = recall_score(y_binary, pred_binary, zero_division=0)
            self.metrics[f"f1_{name}"] = f1_score(y_binary, pred_binary, zero_division=0)

        # AUC-ROC (one vs rest)
        try:
            self.metrics["auc_roc"] = roc_auc_score(y, probs, multi_class='ovr')
        except Exception:
            self.metrics["auc_roc"] = 0

        # Print report
        logger.info("\n" + "=" * 60)
        logger.info("MODEL EVALUATION")
        logger.info("=" * 60)
        logger.info(f"Accuracy: {self.metrics['accuracy']:.4f}")
        logger.info(f"AUC-ROC: {self.metrics['auc_roc']:.4f}")

        logger.info("\nPer-class metrics:")
        for name in ["rug", "sideways", "runner"]:
            logger.info(f"  {name:10} | "
                       f"Precision: {self.metrics[f'precision_{name}']:.3f} | "
                       f"Recall: {self.metrics[f'recall_{name}']:.3f} | "
                       f"F1: {self.metrics[f'f1_{name}']:.3f}")

        # Confusion matrix
        logger.info(f"\nConfusion Matrix:")
        cm = confusion_matrix(y, preds)
        logger.info(f"            Pred Rug  Pred Side  Pred Run")
        logger.info(f"Actual Rug    {cm[0,0]:5}     {cm[0,1]:5}     {cm[0,2]:5}")
        logger.info(f"Actual Side   {cm[1,0]:5}     {cm[1,1]:5}     {cm[1,2]:5}")
        logger.info(f"Actual Run    {cm[2,0]:5}     {cm[2,1]:5}     {cm[2,2]:5}")

        return self.metrics

    def get_feature_importance(self) -> Dict[str, float]:
        """Get feature importance scores."""
        if self.model is None:
            return {}

        if self.model_type == "xgboost":
            importance = self.model.get_score(importance_type='gain')
            # Normalize
            total = sum(importance.values())
            importance = {k: v/total for k, v in importance.items()}
        elif self.model_type == "lightgbm":
            importance = dict(zip(
                self.feature_names,
                self.model.feature_importance(importance_type='gain')
            ))
            total = sum(importance.values())
            importance = {k: v/total for k, v in importance.items()}
        else:
            importance = {}

        # Sort by importance
        importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))

        logger.info("\nFeature Importance:")
        for name, score in list(importance.items())[:10]:
            bar = "█" * int(score * 50)
            logger.info(f"  {name:25} | {score:.4f} | {bar}")

        return importance

    def save_model(self, version: str = None) -> str:
        """
        Save model to disk and register in database.

        Returns:
            Model file path
        """
        if self.model is None:
            raise ValueError("No model to save")

        if version is None:
            version = datetime.now().strftime("v%Y%m%d_%H%M%S")

        # Save model file
        model_path = MODEL_DIR / f"model_{self.model_type}_{version}.joblib"
        joblib.dump({
            "model": self.model,
            "model_type": self.model_type,
            "feature_names": self.feature_names,
            "metrics": self.metrics,
            "version": version,
            "trained_at": datetime.now().isoformat(),
        }, model_path)

        logger.info(f"Model saved to: {model_path}")

        # Register in database
        self._register_model_in_db(version, str(model_path))

        return str(model_path)

    def _register_model_in_db(self, version: str, model_path: str):
        """Register model version in database."""
        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO ml_models
                (model_version, model_type, training_date, accuracy,
                 precision_runner, recall_runner, f1_runner,
                 precision_rug, recall_rug, f1_rug, auc_roc,
                 model_path, feature_importance_json, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, (
                version,
                self.model_type,
                datetime.now().isoformat(),
                self.metrics.get("accuracy", 0),
                self.metrics.get("precision_runner", 0),
                self.metrics.get("recall_runner", 0),
                self.metrics.get("f1_runner", 0),
                self.metrics.get("precision_rug", 0),
                self.metrics.get("recall_rug", 0),
                self.metrics.get("f1_rug", 0),
                self.metrics.get("auc_roc", 0),
                model_path,
                json.dumps(self.get_feature_importance()),
            ))
            conn.commit()
            logger.info(f"Model {version} registered in database")

        except Exception as e:
            logger.error(f"Failed to register model: {e}")
        finally:
            conn.close()

    def deploy_model(self, version: str = None):
        """
        Set a model version as the active model.

        Args:
            version: Model version to deploy (latest if None)
        """
        conn = get_connection()
        cursor = conn.cursor()

        try:
            # Deactivate all models
            cursor.execute("UPDATE ml_models SET is_active = 0")

            # Activate specified version
            if version:
                cursor.execute("""
                    UPDATE ml_models
                    SET is_active = 1
                    WHERE model_version = ?
                """, (version,))
            else:
                # Activate latest
                cursor.execute("""
                    UPDATE ml_models
                    SET is_active = 1
                    WHERE id = (SELECT MAX(id) FROM ml_models)
                """)

            # Update settings
            cursor.execute("""
                UPDATE settings
                SET value = ?
                WHERE key = 'ml_model_version'
            """, (version or "latest",))

            conn.commit()
            logger.info(f"Model {version or 'latest'} deployed as active")

        except Exception as e:
            logger.error(f"Failed to deploy model: {e}")
        finally:
            conn.close()

    @classmethod
    def load_model(cls, version: str = None) -> "ModelTrainer":
        """
        Load a trained model from disk.

        Args:
            version: Specific version or None for active model

        Returns:
            ModelTrainer instance with loaded model
        """
        conn = get_connection()
        cursor = conn.cursor()

        if version:
            cursor.execute("""
                SELECT model_path, model_type
                FROM ml_models
                WHERE model_version = ?
            """, (version,))
        else:
            cursor.execute("""
                SELECT model_path, model_type
                FROM ml_models
                WHERE is_active = 1
            """)

        row = cursor.fetchone()
        conn.close()

        if not row:
            raise ValueError(f"Model not found: {version or 'active'}")

        model_path, model_type = row

        # Load from disk
        data = joblib.load(model_path)

        trainer = cls(model_type=model_type)
        trainer.model = data["model"]
        trainer.feature_names = data["feature_names"]
        trainer.metrics = data.get("metrics", {})

        logger.info(f"Loaded model from {model_path}")

        return trainer


def main():
    parser = argparse.ArgumentParser(description="Train ML model for trade prediction")
    parser.add_argument(
        "--model",
        choices=["xgboost", "lightgbm"],
        default="xgboost",
        help="Model type to train"
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save trained model"
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy model as active"
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=1000,
        help="Minimum samples required"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("V3 Edge Auto-Trader: Model Training")
    logger.info(f"Model type: {args.model}")
    logger.info("=" * 60)

    # Check dependencies
    if args.model == "xgboost" and not HAS_XGBOOST:
        logger.error("XGBoost not installed. Run: pip install xgboost")
        sys.exit(1)
    if args.model == "lightgbm" and not HAS_LIGHTGBM:
        logger.error("LightGBM not installed. Run: pip install lightgbm")
        sys.exit(1)
    if not HAS_SKLEARN:
        logger.error("scikit-learn not installed. Run: pip install scikit-learn")
        sys.exit(1)

    # Initialize trainer
    trainer = ModelTrainer(model_type=args.model)

    # Load data
    X, y = trainer.load_data(min_samples=args.min_samples)

    if len(X) < args.min_samples:
        logger.error(f"Insufficient data: {len(X)} samples (need {args.min_samples})")
        logger.info("Run outcome labeling first: python ml/label_outcomes.py")
        sys.exit(1)

    # Train
    trainer.train(X, y)

    # Feature importance
    trainer.get_feature_importance()

    # Save if requested
    if args.save:
        model_path = trainer.save_model()
        logger.info(f"Model saved to: {model_path}")

        if args.deploy:
            trainer.deploy_model()

    logger.info("\nTraining complete!")


if __name__ == "__main__":
    main()
