"""
Feature Engineering — mathematical features for the Instability Index.
"""

import numpy as np


def holder_acceleration(h_t: int, h_t10: int, h_t20: int) -> float:
    """
    Normalised second derivative of holder growth.

    velocity_1 = H_t - H_{t-10}
    velocity_2 = H_{t-10} - H_{t-20}
    acceleration = (v1 - v2) / (H_t + 1)

    Positive values = accelerating holder growth (bullish signal).
    """
    v1 = h_t - h_t10
    v2 = h_t10 - h_t20
    return (v1 - v2) / (h_t + 1)


def stealth_accumulation(unique_buyers: int, sells_20m: int,
                         buys_20m: int, price_series: np.ndarray) -> float:
    """
    Stealth Accumulation Score.

    SA = unique_buyers × (1 - sell_ratio) × price_stability

    High SA = many unique buyers, few sells, stable price → silent accumulation.
    """
    sell_ratio = sells_20m / (buys_20m + 1e-9)
    mean_price = np.mean(price_series)
    price_stability = 1.0 - (np.std(price_series) / (mean_price + 1e-9))
    # Clamp stability to [0, 1]
    price_stability = max(0.0, min(1.0, price_stability))
    return unique_buyers * (1.0 - sell_ratio) * price_stability


def volatility_shift(price_20m: np.ndarray, price_5m: np.ndarray) -> float:
    """
    Volatility Shift — detects compression → breakout.

    VS = std(P_5m) / std(P_20m)

    High VS = recent volatility expanding relative to longer window → potential breakout.
    """
    vol_20 = np.std(price_20m)
    vol_5 = np.std(price_5m)
    return vol_5 / (vol_20 + 1e-9)


def sell_pressure(sells_5m: int, buys_5m: int) -> float:
    """
    Sell Pressure ratio.

    SP = sells_5m / (buys_5m + sells_5m + 1)

    Low SP = buying dominance (bullish).
    """
    return sells_5m / (buys_5m + sells_5m + 1)


def compute_liquidity_acceleration(liq_series: np.ndarray) -> float:
    """
    Second derivative of liquidity.
    accel = (L_t - 2*L_{t-1} + L_{t-2})
    Normalized by current liquidity.
    """
    if len(liq_series) < 3:
        return 0.0
    
    l_t = liq_series[-1]
    l_t1 = liq_series[-2]
    l_t2 = liq_series[-3]
    
    accel = (l_t - 2*l_t1 + l_t2)
    return accel / (l_t + 1e-9)


def compute_volume_hhi(buyers_data: list[dict]) -> float:
    """
    Herfindahl-Hirschman Index (HHI) for volume concentration.
    HHI = sum(s^2) where s is market share of each buyer.
    
    buyers_data: list of dicts with 'amount' or similar. 
    Note: 'buyers_data' from Helius only has valid wallet addresses currently, 
    we need volume per wallet. If we don't have volume, we use simple count 
    concentration or assume equal volume (which makes HHI = 1/N).
    
    CRITICAL: 'get_buyers_stats' currently returns unique wallets and first trade time, 
    BUT NOT volume per wallet. We need to upgrade 'get_buyers_stats' to return volume 
    or use a proxy. 
    
    Proxy for now: If we can't get volume, we return 0.0 (neutral).
    Actually, let's allow passing a list of volumes.
    """
    if not buyers_data:
        return 0.0
        
    # extract volumes if available, else assume uniform (useless for HHI)
    # If the input list is just volumes, use that.
    # We will assume buyers_data contains {"volume": float} for this feature.
    cols = [b.get("volume", 0) for b in buyers_data]
    total_vol = sum(cols)
    if total_vol == 0:
        return 0.0
        
    shares = [v / total_vol for v in cols]
    hhi = sum(s**2 for s in shares)
    return hhi


def compute_dip_recovery(price_series: np.ndarray) -> float:
    """
    Measures how quickly price recovers from the lowest point in the series.
    Recovery = (Current - Low) / (High - Low)
    
    1.0 = Fully recovered to High (or at High)
    0.0 = At the Low (no recovery)
    """
    if len(price_series) < 2:
        return 0.5
        
    high = np.max(price_series)
    low = np.min(price_series)
    current = price_series[-1]
    
    range_ = high - low
    if range_ == 0:
        return 0.5 # Flat
        
    return (current - low) / range_


def compute_all_features(h_t: int, h_t10: int, h_t20: int,
                         unique_buyers: int, sells_20m: int, buys_20m: int,
                         price_series_20m: np.ndarray, price_series_5m: np.ndarray,
                         sells_5m: int, buys_5m: int,
                         liquidity_series: np.ndarray,
                         buyers_volumes: list[float],
                         swr: float) -> dict:
    """Compute all features for a single token at the current timestamp."""
    
    # helper for HHI input
    buyers_dicts = [{"volume": v} for v in buyers_volumes]
    
    return {
        "holder_acc": holder_acceleration(h_t, h_t10, h_t20),
        "sa": stealth_accumulation(unique_buyers, sells_20m, buys_20m,
                                   price_series_20m),
        "vol_shift": volatility_shift(price_series_20m, price_series_5m),
        "sell_pressure": sell_pressure(sells_5m, buys_5m),
        "accel_liq": compute_liquidity_acceleration(liquidity_series),
        "vol_hhi": compute_volume_hhi(buyers_dicts),
        "dip_recovery": compute_dip_recovery(price_series_5m),
        "swr": swr,
    }
