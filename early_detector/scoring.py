"""
Scoring Engine — cross-sectional z-scores and Instability Index computation.
"""

import numpy as np
import pandas as pd
from loguru import logger
from early_detector.config import (
    WEIGHT_SA, WEIGHT_HOLDER, WEIGHT_VS, WEIGHT_SWR, WEIGHT_SELL,
    WEIGHT_VI,
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
    s = series.fillna(0.0)
    median = s.median()
    mad = (s - median).abs().median()
    
    if mad < 1e-7:
        # Fallback if MAD is 0 (all values identical or constant)
        std = s.std()
        if pd.isna(std) or std < 1e-9:
            # If all are identical, everything is 0.0 (neutral)
            return pd.Series(0.0, index=s.index)
        return (s - median) / (std + 1e-9)
    
    return (s - median) / (1.4826 * mad + 1e-9)


def detect_regime(df: pd.DataFrame, avg_vol_history: float = 0.0) -> str:
    """
    Detects market regime: 'DEGEN' (turbulent) or 'STABLE' (accumulation).
    Refined V4.0: Based on Z-score of Total Batch Volume vs History.
    """
    if df.empty or "volume_5m" not in df.columns:
        return "STABLE"
    
    # 1. Current Batch Stats
    total_vol = df["volume_5m"].sum()
    vol_z = zscore_robust(df["volume_5m"]).mean()
    
    # 2. Comparison vs History
    # If the total batch volume is 2x the historical average, it's DEGEN.
    if avg_vol_history > 0 and total_vol > (avg_vol_history * 2.0):
        return "DEGEN"
        
    # Fallback to local z-score if no history
    if vol_z > 1.5 or total_vol > 500000:
        return "DEGEN"
        
    return "STABLE"


def compute_instability(features_df: pd.DataFrame,
                        weights: dict | None = None,
                        avg_vol_history: float = 0.0) -> pd.DataFrame:
    """
    Compute the Instability Index for all tokens in the DataFrame.
    Adaptive weights shift based on detected market regime.
    """
    if features_df.empty:
        features_df["instability"] = pd.Series(dtype=float)
        return features_df

    regime = detect_regime(features_df, avg_vol_history)
    logger.info(f"Market Regime Detected: {regime}")

    # Baseline weights
    w_sa = weights["w_sa"] if weights else WEIGHT_SA
    w_holder = weights["w_holder"] if weights else WEIGHT_HOLDER
    w_vs = weights["w_vs"] if weights else WEIGHT_VS
    w_swr = weights["w_swr"] if weights else WEIGHT_SWR
    w_vi = weights["w_vi"] if weights else WEIGHT_VI
    w_sell = weights["w_sell"] if weights else WEIGHT_SELL

    # Regime adjustments
    if regime == "DEGEN":
        # In degen mode, prioritize SWR, VI and SA
        w_swr *= 1.5
        w_vi *= 1.8
        w_sa *= 1.2
        w_holder *= 0.8
    
    df = features_df.copy()

    # Robust Standardization
    df["z_sa"] = zscore_robust(df["sa"])
    df["z_holder"] = zscore_robust(df["holder_acc"])
    df["z_vs"] = zscore_robust(df["vol_shift"])
    df["z_swr"] = zscore_robust(df["swr"])
    df["z_vi"] = zscore_robust(df["vol_intensity"])
    df["z_sell"] = zscore_robust(df["sell_pressure"])

    # Instability Index
    df["instability"] = (
        w_sa * df["z_sa"]
        + w_holder * df["z_holder"]
        + w_vs * df["z_vs"]
        + w_swr * df["z_swr"]
        + w_vi * df["z_vi"]
        - w_sell * df["z_sell"]
    )

    # ── Velocity Baseline Boost V5.2 ──
    # If a token has massive velocity (turnover > 50% in 5 min), it receives an absolute boost.
    # This captures "p2p" type signals even in small batches where Z-score would be 0.
    if "vol_intensity" in df.columns:
        # Boost = log1p(velocity) * weight
        # Only applies if velocity > 0.5 (50% turnover)
        vi_boost_mask = df["vol_intensity"] > 0.5
        df.loc[vi_boost_mask, "instability"] += (np.log1p(df.loc[vi_boost_mask, "vol_intensity"]) * (w_vi * 1.5))

    # V4.2 Robustness: Add a tiny epsilon for tokens that at least have some real data
    # This prevents the "all zeros" trap when many RPC calls fail.
    epsilon = 0.0001
    has_data_mask = (df["sa"] > 0) | (df["holder_acc"] > 0) | (df["vol_intensity"] > 0)
    df.loc[has_data_mask, "instability"] += epsilon

    # Momentum dII/dt (Phase 4.0)
    if "last_instability" in df.columns:
        df["delta_instability"] = df["instability"] - df["last_instability"]
    else:
        df["delta_instability"] = 0.0

    logger.debug(
        f"Instability computed for {len(df)} tokens — "
        f"mean={df['instability'].mean():.3f}, delta_mean={df['delta_instability'].mean():.3f}"
    )
    return df


def get_signal_threshold(instability_series: pd.Series,
                         percentile: float | None = None) -> float:
    """
    Dynamic threshold = percentile of current instability distribution.
    Default is 60th percentile across all active tokens in the batch.
    
    Guards:
    - Minimum batch size of 3 required for a meaningful percentile.
      With 1-2 tokens the percentile is trivially the token's own value.
    - Absolute floor of 3.0: a token must have at least II=3.0 to qualify,
      regardless of batch composition. This prevents epsilon-level signals.
    """
    MIN_THRESHOLD = 4.0   # Lowered from 4.5 to capture p2p-type signals
    MIN_BATCH_SIZE = 3    # Below this, use MIN_THRESHOLD directly

    pct = percentile if percentile is not None else SIGNAL_PERCENTILE
    clean_series = instability_series.dropna()
    if clean_series.empty:
        return 99.0  # Fallback high threshold if no valid scores

    if len(clean_series) < MIN_BATCH_SIZE:
        # Batch too small for a meaningful percentile — use hard floor
        logger.info(f"Signal threshold (small batch={len(clean_series)}): {MIN_THRESHOLD:.3f} (floor)")
        return MIN_THRESHOLD

    threshold = float(np.percentile(clean_series, pct * 100))
    threshold = max(threshold, MIN_THRESHOLD)  # Never fall below the floor
    logger.info(f"Signal threshold (P{int(pct*100)}): {threshold:.3f}")
    return threshold
