"""
Smart Wallet Engine — wallet profiling, clustering, and rotation ratio.
"""

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from loguru import logger
from early_detector.config import SW_MIN_ROI, SW_MIN_TRADES, SW_MIN_WIN_RATE


def compute_wallet_stats(trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-wallet performance statistics from a trades DataFrame.

    Expected columns: wallet, entry_price, exit_price
    Returns DataFrame indexed by wallet with: avg_roi, total_trades, win_rate
    """
    if trades_df.empty:
        return pd.DataFrame(columns=["avg_roi", "total_trades", "win_rate"])

    grouped = trades_df.groupby("wallet")
    stats = grouped.apply(
        lambda x: pd.Series({
            "avg_roi": (x["exit_price"] / x["entry_price"]).mean(),
            "total_trades": len(x),
            "win_rate": (x["exit_price"] > x["entry_price"]).mean(),
        }),
        include_groups=False,
    )
    return stats


def detect_smart_wallets(stats_df: pd.DataFrame) -> list[str]:
    """
    Filter wallets that meet the 'smart' criteria:
    - avg_roi > SW_MIN_ROI (default 2.5)
    - total_trades >= SW_MIN_TRADES (default 15)
    - win_rate > SW_MIN_WIN_RATE (default 0.4)
    """
    if stats_df.empty:
        return []

    smart = stats_df[
        (stats_df["avg_roi"] > SW_MIN_ROI)
        & (stats_df["total_trades"] >= SW_MIN_TRADES)
        & (stats_df["win_rate"] > SW_MIN_WIN_RATE)
    ]
    logger.info(f"Detected {len(smart)} smart wallets out of {len(stats_df)} total")
    return smart.index.tolist()


def cluster_wallets(stats_df: pd.DataFrame, n_clusters: int = 3) -> pd.DataFrame:
    """
    Cluster wallets into behavioral groups using KMeans.

    Clusters:
    - Cluster 0 = retail (low ROI, high trades)
    - Cluster 1 = sniper bot (fast entry/exit, moderate ROI)
    - Cluster 2 = insider pattern (high ROI, early entry, selective)

    Labels are assigned post-hoc based on cluster centroids.
    """
    if stats_df.empty or len(stats_df) < n_clusters:
        stats_df["cluster_label"] = "unknown"
        return stats_df

    features = stats_df[["avg_roi", "total_trades", "win_rate"]].fillna(0).values

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(features)

    # Assign human-readable labels based on avg_roi centroid
    centroids = kmeans.cluster_centers_
    roi_order = np.argsort(centroids[:, 0])  # sort by avg_roi ascending

    label_map = {
        int(roi_order[0]): "retail",
        int(roi_order[1]): "sniper",
        int(roi_order[2]): "insider",
    }

    stats_df = stats_df.copy()
    stats_df["cluster_label"] = [label_map.get(l, "unknown") for l in labels]

    for label_name in ["retail", "sniper", "insider"]:
        count = (stats_df["cluster_label"] == label_name).sum()
        logger.debug(f"Cluster '{label_name}': {count} wallets")

    return stats_df


def compute_swr(active_wallets: list[str],
                smart_wallet_list: list[str],
                global_active_smart: int) -> float:
    """
    Smart Wallet Rotation Ratio (SWR).

    SWR = (smart wallets active in this token) / (global smart wallets active in 30m)
    """
    sw_active = len(set(active_wallets) & set(smart_wallet_list))
    return sw_active / (global_active_smart + 1e-9)
