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


def compute_all_features(h_t: int, h_t10: int, h_t20: int,
                         unique_buyers: int, sells_20m: int, buys_20m: int,
                         price_series_20m: np.ndarray, price_series_5m: np.ndarray,
                         sells_5m: int, buys_5m: int,
                         swr: float) -> dict:
    """Compute all features for a single token at the current timestamp."""
    return {
        "holder_acc": holder_acceleration(h_t, h_t10, h_t20),
        "sa": stealth_accumulation(unique_buyers, sells_20m, buys_20m,
                                   price_series_20m),
        "vol_shift": volatility_shift(price_series_20m, price_series_5m),
        "sell_pressure": sell_pressure(sells_5m, buys_5m),
        "swr": swr,
    }
