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


def detect_coordinated_entry(trades: list[dict], window_sec: int = 15) -> list[str]:
    """
    Detects coordinated entries (Louvain-lite).
    Identifies groups of wallets that buy within the same narrow time window.
    returns list of 'coordinated' wallet addresses.
    """
    if len(trades) < 2:
        return []

    # Sort by timestamp (or first_trade_time if passing a buyer list)
    key_fn = lambda x: x.get("timestamp") or x.get("first_trade_time") or 0
    sorted_trades = sorted([t for t in trades if t.get("type", "buy") == "buy"], 
                           key=key_fn)
    
    coordinated = set()
    for i in range(len(sorted_trades)):
        for j in range(i + 1, len(sorted_trades)):
            t_i = sorted_trades[i].get("timestamp") or sorted_trades[i].get("first_trade_time") or 0
            t_j = sorted_trades[j].get("timestamp") or sorted_trades[j].get("first_trade_time") or 0
            if abs(t_i - t_j) <= window_sec:
                coordinated.add(sorted_trades[i]["wallet"])
                coordinated.add(sorted_trades[j]["wallet"])
            else:
                break # sorted
    
    return list(coordinated)


def compute_p_insider(early_score: float, funding_overlap: float, 
                      buy_ratio_120s: float, holder_delta: float) -> float:
    """
    Sigmoid-based Insider Probability (V4.0 Game Changer).
    
    P_insider = 1 / (1 + exp(-z))
    z = w1*early + w2*funding + w3*buy_ratio + w4*holder_delta - bias
    """
    # Weights for the sigmoid model
    w_early = 3.0
    w_funding = 4.0
    w_buy_ratio = 2.5
    w_holder_delta = 2.0
    bias = 3.5 # Threshold bias
    
    z = (w_early * early_score + 
         w_funding * funding_overlap + 
         w_buy_ratio * buy_ratio_120s + 
         w_holder_delta * holder_delta) - bias
         
    probability = 1 / (1 + np.exp(-z))
    return float(probability)


def compute_insider_score(wallet_stats: dict,
                          first_trade_timestamp: int,
                          pair_created_at: int | None,
                          is_coordinated: bool = False,
                          buy_ratio_120s: float = 0.0,
                          holder_delta: float = 0.0) -> float:
    """
    Calculate probability (0.0 - 1.0) that a wallet/token has insider activity.
    Refined V4.0: Uses Sigmoid-based P_insider.
    """
    # 1. Base Early Score (0-1)
    early_score = 0.0
    if pair_created_at:
        created_sec = pair_created_at / 1000 if pair_created_at > 1e11 else pair_created_at
        trade_sec = first_trade_timestamp
        seconds_since_launch = trade_sec - created_sec
        
        if 0 <= seconds_since_launch <= 60:
            early_score = 1.0
        elif 60 < seconds_since_launch <= 300:
            early_score = 0.6
        elif seconds_since_launch <= 600:
            early_score = 0.3

    # 2. Funding Overlap (Placeholder: 0.0 for now, requires deep on-chain trace)
    funding_overlap = 0.0
    if is_coordinated:
        funding_overlap = 0.5 # Coordination is a strong proxy for shared funding

    # 3. Compute P_insider
    p_insider = compute_p_insider(
        early_score=early_score,
        funding_overlap=funding_overlap,
        buy_ratio_120s=buy_ratio_120s,
        holder_delta=holder_delta
    )

    return p_insider
