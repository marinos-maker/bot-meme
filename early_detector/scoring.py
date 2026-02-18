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
    """Cross-sectional z-score across all tokens in the current batch."""
    return (series - series.mean()) / (series.std() + 1e-9)


def compute_instability(features_df: pd.DataFrame,
                        weights: dict | None = None) -> pd.DataFrame:
    """
    Compute the Instability Index for all tokens in the DataFrame.

    Default formula:
        II = 2·Z(SA) + 1.5·Z(H) + 1.5·Z(VS) + 2·Z(SWR) − 2·Z(sell_pressure)

    Weights can be overridden by the ML optimizer.

    Args:
        features_df: DataFrame with columns [sa, holder_acc, vol_shift, swr, sell_pressure]
        weights: optional dict with keys w_sa, w_holder, w_vs, w_swr, w_sell

    Returns:
        Same DataFrame with added z-score columns and 'instability' column.
    """
    if features_df.empty:
        features_df["instability"] = pd.Series(dtype=float)
        return features_df

    w_sa = weights["w_sa"] if weights else WEIGHT_SA
    w_holder = weights["w_holder"] if weights else WEIGHT_HOLDER
    w_vs = weights["w_vs"] if weights else WEIGHT_VS
    w_swr = weights["w_swr"] if weights else WEIGHT_SWR
    w_sell = weights["w_sell"] if weights else WEIGHT_SELL

    df = features_df.copy()

    # Cross-sectional z-scores
    df["z_sa"] = zscore(df["sa"])
    df["z_holder"] = zscore(df["holder_acc"])
    df["z_vs"] = zscore(df["vol_shift"])
    df["z_swr"] = zscore(df["swr"])
    df["z_sell"] = zscore(df["sell_pressure"])

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
