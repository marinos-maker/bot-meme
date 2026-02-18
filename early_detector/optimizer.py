"""
ML Weight Optimizer — Logistic Regression on historical data to calibrate
the Instability Index weights.
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import classification_report
from loguru import logger


FEATURE_COLS = ["sa", "holder_acc", "vol_shift", "swr", "sell_pressure"]


def prepare_training_data(signals_df: pd.DataFrame,
                          price_outcomes_df: pd.DataFrame,
                          target_multiple: float = 2.0,
                          target_window_min: int = 120) -> tuple[np.ndarray, np.ndarray]:
    """
    Build training dataset from historical signals and price outcomes.

    Args:
        signals_df: DataFrame with feature columns for each historical token snapshot
        price_outcomes_df: DataFrame with columns [token_id, timestamp, max_price_120m]
        target_multiple: price multiple to define success (default 2x)
        target_window_min: time window in minutes (default 120)

    Returns:
        X: feature matrix (n_samples, 5)
        y: binary target (1 = token achieved target_multiple within window)
    """
    merged = signals_df.merge(price_outcomes_df, on=["token_id", "timestamp"],
                              how="inner")

    if merged.empty:
        logger.warning("No training data available after merge")
        return np.array([]), np.array([])

    X = merged[FEATURE_COLS].fillna(0).values
    y = (merged["max_price_120m"] / merged["price"] >= target_multiple).astype(int).values

    logger.info(
        f"Training data: {len(y)} samples, "
        f"{y.sum()} positive ({y.mean()*100:.1f}%)"
    )
    return X, y


def optimize_weights(X: np.ndarray, y: np.ndarray,
                     n_splits: int = 3) -> dict:
    """
    Train Logistic Regression with walk-forward validation.

    Returns optimized weights as a dict matching the scoring engine format.
    """
    if len(X) == 0 or len(y) == 0:
        logger.warning("Empty data — returning default weights")
        return _default_weights()

    if len(X) < 50:
        logger.warning(f"Only {len(X)} samples — using defaults, need at least 50")
        return _default_weights()

    # Walk-forward time series split
    tscv = TimeSeriesSplit(n_splits=n_splits)

    best_model = None
    best_score = -1.0

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X)):
        X_train, X_test = X[train_idx], X[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]

        model = LogisticRegression(
            class_weight="balanced",  # handle imbalanced data
            max_iter=1000,
            random_state=42,
        )
        model.fit(X_train, y_train)

        score = model.score(X_test, y_test)
        logger.info(f"Fold {fold+1}/{n_splits}: accuracy={score:.3f}")

        if score > best_score:
            best_score = score
            best_model = model

    if best_model is None:
        return _default_weights()

    coefs = best_model.coef_[0]
    logger.info(f"Optimized coefficients: {dict(zip(FEATURE_COLS, coefs))}")

    # Report
    y_pred = best_model.predict(X)
    logger.info(f"\n{classification_report(y, y_pred, target_names=['no_pump', 'pump'])}")

    return {
        "w_sa": float(coefs[0]),
        "w_holder": float(coefs[1]),
        "w_vs": float(coefs[2]),
        "w_swr": float(coefs[3]),
        "w_sell": float(-abs(coefs[4])),  # ensure sell pressure is subtracted
    }


def _default_weights() -> dict:
    """Return the manually tuned default weights."""
    return {
        "w_sa": 2.0,
        "w_holder": 1.5,
        "w_vs": 1.5,
        "w_swr": 2.0,
        "w_sell": -2.0,
    }
