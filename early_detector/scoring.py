"""
Scoring Engine — cross-sectional z-scores and Instability Index computation.
"""

import numpy as np
import pandas as pd
from loguru import logger
from early_detector.config import (
    WEIGHT_SA, WEIGHT_HOLDER, WEIGHT_VS, WEIGHT_SWR, WEIGHT_SELL,
    SIGNAL_PERCENTILE,
)


def zscore(series: pd.Series) -> pd.Series:
    """Standard z-score."""
    return (series - series.mean()) / (series.std() + 1e-9)


def zscore_robust(series: pd.Series) -> pd.Series:
    """
    Robust Z-Score using Median and Median Absolute Deviation (MAD).
    Neutralizes the impact of outliers in high-volatility environments.
    """
    median = series.median()
    mad = (series - median).abs().median()
    if mad < 1e-7:
        # Fallback if MAD is 0
        std = series.std()
        if std < 1e-9:
            return pd.Series(0, index=series.index)
        return (series - median) / (std + 1e-9)
    
    return (series - median) / (1.4826 * mad + 1e-9)


def detect_regime(df: pd.DataFrame) -> str:
    """
    Detects market regime: 'DEGEN' (turbulent) or 'STABLE' (accumulation).
    Based on average volatility shift and volume concentration.
    """
    if df.empty or "vol_shift" not in df.columns:
        return "STABLE"
    
    avg_vol_shift = df["vol_shift"].mean()
    if avg_vol_shift > 1.5:
        return "DEGEN"
    return "STABLE"


def compute_instability(features_df: pd.DataFrame,
                        weights: dict | None = None) -> pd.DataFrame:
    """
    Compute the Instability Index for all tokens in the DataFrame.
    Adaptive weights shift based on detected market regime.
    """
    if features_df.empty:
        features_df["instability"] = pd.Series(dtype=float)
        return features_df

    regime = detect_regime(features_df)
    logger.info(f"Market Regime Detected: {regime}")

    # Baseline weights
    w_sa = weights["w_sa"] if weights else WEIGHT_SA
    w_holder = weights["w_holder"] if weights else WEIGHT_HOLDER
    w_vs = weights["w_vs"] if weights else WEIGHT_VS
    w_swr = weights["w_swr"] if weights else WEIGHT_SWR
    w_sell = weights["w_sell"] if weights else WEIGHT_SELL

    # Regime adjustments
    if regime == "DEGEN":
        # In degen mode, prioritize SWR and SA over Holder growth (which might be bots)
        w_swr *= 1.5
        w_sa *= 1.2
        w_holder *= 0.8
    
    df = features_df.copy()

    # Robust Standardization
    df["z_sa"] = zscore_robust(df["sa"])
    df["z_holder"] = zscore_robust(df["holder_acc"])
    df["z_vs"] = zscore_robust(df["vol_shift"])
    df["z_swr"] = zscore_robust(df["swr"])
    df["z_sell"] = zscore_robust(df["sell_pressure"])

    # Instability Index
    df["instability"] = (
        w_sa * df["z_sa"]
        + w_holder * df["z_holder"]
        + w_vs * df["z_vs"]
        + w_swr * df["z_swr"]
        - w_sell * df["z_sell"]
    )

    logger.debug(
        f"Instability computed for {len(df)} tokens — "
        f"mean={df['instability'].mean():.3f}, "
        f"max={df['instability'].max():.3f}"
    )
    return df


def get_signal_threshold(instability_series: pd.Series,
                         percentile: float | None = None) -> float:
    """
    Dynamic threshold = percentile of current instability distribution.
    Default is 95th percentile across all active tokens.
    """
    pct = percentile if percentile is not None else SIGNAL_PERCENTILE
    if instability_series.empty:
        return float("inf")
    threshold = float(np.percentile(instability_series.dropna(), pct * 100))
    logger.debug(f"Signal threshold (P{int(pct*100)}): {threshold:.3f}")
    return threshold
