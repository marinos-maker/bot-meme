"""
Feature Engineering — mathematical features for the Instability Index.
V6.0 OPTIMIZED: Enhanced momentum features, volume analysis, and trend detection.
"""

import numpy as np


def holder_acceleration(h_t: int, h_t10: int, h_t20: int) -> float:
    """
    Normalised second derivative of holder growth.

    velocity_1 = H_t - H_{t-10}
    velocity_2 = H_{t-10} - H_{t-20}
    acceleration = (v1 - v2) / (H_t + 1)

    Positive values = accelerating holder growth (bullish signal).
    V6.0: Added clipping to prevent extreme values.
    """
    v1 = h_t - h_t10
    v2 = h_t10 - h_t20
    raw_acc = (v1 - v2) / (h_t + 1)
    # Clip to reasonable range to prevent outliers
    return float(np.clip(raw_acc, -10.0, 10.0))


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


def volume_intensity(vol_5m: float, liquidity: float) -> float:
    """
    Volume Intensity (Turnover Velocity).
    VI = Volume_5m / (Liquidity + 1)
    
    High VI = High capital rotation relative to liquidity -> Explosive potential.
    """
    return vol_5m / (liquidity + 1.0)


def compute_all_features(h_t: int, h_t10: int, h_t20: int,
                         unique_buyers: int, sells_20m: int, buys_20m: int,
                         price_series_20m: np.ndarray, price_series_5m: np.ndarray,
                         sells_5m: int, buys_5m: int,
                         vol_5m: float, liquidity: float,
                         liquidity_series: np.ndarray,
                         buyers_volumes: list[float],
                         swr: float) -> dict:
    """Compute all features for a single token at the current timestamp.
    V6.0: Enhanced with momentum and trend features."""
    
    # helper for HHI input
    buyers_dicts = [{"volume": v} for v in buyers_volumes]
    
    # V6.0: Compute advanced features
    momentum_score = compute_momentum_score(price_series_5m, vol_5m, liquidity)
    trend_quality = compute_trend_quality(price_series_20m)
    volume_quality = compute_volume_quality(vol_5m, liquidity, buys_5m, sells_5m)
    
    return {
        "holder_acc": holder_acceleration(h_t, h_t10, h_t20),
        "sa": stealth_accumulation(unique_buyers, sells_20m, buys_20m,
                                   price_series_20m),
        "vol_shift": volatility_shift(price_series_20m, price_series_5m),
        "sell_pressure": sell_pressure(sells_5m, buys_5m),
        "accel_liq": compute_liquidity_acceleration(liquidity_series),
        "vol_hhi": compute_volume_hhi(buyers_dicts),
        "dip_recovery": compute_dip_recovery(price_series_5m),
        "vol_intensity": volume_intensity(vol_5m, liquidity),
        "swr": swr,
        # V6.0: New enhanced features
        "momentum_score": momentum_score,
        "trend_quality": trend_quality,
        "volume_quality": volume_quality,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# V6.0 ENHANCED FEATURES - Nuove funzioni per analisi avanzata
# ═══════════════════════════════════════════════════════════════════════════════

def compute_momentum_score(price_series: np.ndarray, volume_5m: float, 
                           liquidity: float) -> float:
    """
    V6.0: Calcola un punteggio di momentum combinato.
    
    Combina:
    - Price momentum (trend direzionale)
    - Volume momentum (turnover rate)
    - Acceleration (second derivative)
    
    Ritorna un valore normalizzato 0.0-1.0.
    """
    if len(price_series) < 3:
        return 0.5
    
    # 1. Price Momentum - slope of recent prices
    recent_prices = price_series[-5:] if len(price_series) >= 5 else price_series
    if len(recent_prices) >= 2:
        price_start = np.mean(recent_prices[:2])
        price_end = np.mean(recent_prices[-2:])
        if price_start > 0:
            price_momentum = (price_end - price_start) / price_start
            price_momentum = float(np.clip(price_momentum, -0.5, 0.5)) + 0.5  # Normalize to 0-1
        else:
            price_momentum = 0.5
    else:
        price_momentum = 0.5
    
    # 2. Volume Momentum - turnover rate
    if liquidity > 0:
        turnover = volume_5m / liquidity
        volume_momentum = float(np.clip(turnover / 2.0, 0.0, 1.0))  # 200% turnover = max
    else:
        volume_momentum = 0.5
    
    # 3. Acceleration - second derivative of price
    if len(price_series) >= 3:
        first_deriv = np.diff(price_series[-3:])
        if len(first_deriv) >= 2:
            acceleration = first_deriv[-1] - first_deriv[0]
            # Normalize acceleration
            price_range = np.max(price_series[-3:]) - np.min(price_series[-3:])
            if price_range > 0:
                acceleration = float(np.clip((acceleration / price_range + 1) / 2, 0.0, 1.0))
            else:
                acceleration = 0.5
        else:
            acceleration = 0.5
    else:
        acceleration = 0.5
    
    # Weighted combination
    momentum_score = (
        price_momentum * 0.4 +
        volume_momentum * 0.35 +
        acceleration * 0.25
    )
    
    return float(np.clip(momentum_score, 0.0, 1.0))


def compute_trend_quality(price_series: np.ndarray) -> float:
    """
    V6.0: Valuta la qualità del trend prezzo.
    
    Analizza:
    - Consistenza del trend (higher highs, higher lows)
    - Forza del trend (percentuale di movimenti nella direzione del trend)
    - Pulizia del trend (volatilità relativa)
    
    Ritorna un valore 0.0-1.0.
    """
    if len(price_series) < 5:
        return 0.5
    
    # 1. Count higher highs and higher lows
    highs = []
    lows = []
    
    for i in range(1, len(price_series) - 1):
        if price_series[i] > price_series[i-1] and price_series[i] > price_series[i+1]:
            highs.append(price_series[i])
        elif price_series[i] < price_series[i-1] and price_series[i] < price_series[i+1]:
            lows.append(price_series[i])
    
    # Trend consistency score
    hh_count = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i-1]) if len(highs) > 1 else 0
    hl_count = sum(1 for i in range(1, len(lows)) if lows[i] > lows[i-1]) if len(lows) > 1 else 0
    
    total_swings = len(highs) + len(lows)
    if total_swings > 0:
        consistency = (hh_count + hl_count) / max(total_swings, 1)
    else:
        consistency = 0.5
    
    # 2. Trend strength - direction consistency
    up_moves = sum(1 for i in range(1, len(price_series)) if price_series[i] > price_series[i-1])
    trend_strength = up_moves / (len(price_series) - 1)
    
    # 3. Clean trend - low volatility relative to move
    total_move = abs(price_series[-1] - price_series[0])
    volatility = np.std(price_series)
    
    if total_move > 0 and volatility > 0:
        efficiency = float(np.clip(total_move / (volatility * len(price_series) + 1e-9), 0.0, 1.0))
    else:
        efficiency = 0.5
    
    # Combine scores
    trend_quality = (
        consistency * 0.4 +
        trend_strength * 0.35 +
        efficiency * 0.25
    )
    
    return float(np.clip(trend_quality, 0.0, 1.0))


def compute_volume_quality(volume_5m: float, liquidity: float, 
                           buys_5m: int, sells_5m: int) -> float:
    """
    V6.0: Valuta la qualità del volume.
    
    Analizza:
    - Volume intensity (turnover rate)
    - Buy/sell balance
    - Volume sustainability (non-spike volume)
    
    Ritorna un valore 0.0-1.0.
    """
    # 1. Volume Intensity Score
    if liquidity > 0:
        turnover = volume_5m / liquidity
        # Optimal turnover range: 20-100%
        if turnover < 0.1:
            intensity_score = turnover * 5  # Low but building up
        elif turnover < 1.0:
            intensity_score = 0.5 + (turnover - 0.1) * 0.5  # Good range
        elif turnover < 3.0:
            intensity_score = 0.9  # High but acceptable
        else:
            intensity_score = max(0.5, 1.0 - (turnover - 3.0) * 0.1)  # Too high, might be pump
    else:
        intensity_score = 0.3
    
    # 2. Buy/Sell Balance Score
    total_trades = buys_5m + sells_5m
    if total_trades > 0:
        buy_ratio = buys_5m / total_trades
        # Optimal buy ratio: 55-75%
        if 0.55 <= buy_ratio <= 0.75:
            balance_score = 0.9
        elif 0.45 <= buy_ratio <= 0.85:
            balance_score = 0.7
        elif buy_ratio > 0.85:
            balance_score = 0.5  # Too one-sided, might be pump
        else:
            balance_score = 0.4  # Selling pressure
    else:
        balance_score = 0.5
    
    # 3. Participation Score
    if total_trades > 0:
        # More trades = more participation = better
        participation_score = float(np.clip(total_trades / 50, 0.3, 1.0))
    else:
        participation_score = 0.3
    
    # Combine scores
    volume_quality = (
        intensity_score * 0.35 +
        balance_score * 0.40 +
        participation_score * 0.25
    )
    
    return float(np.clip(volume_quality, 0.0, 1.0))


def compute_relative_strength(price_series: np.ndarray, 
                               market_prices: np.ndarray | None = None) -> float:
    """
    V6.0: Calcola la forza relativa del token rispetto al mercato.
    
    Se market_prices non è fornito, usa un benchmark interno.
    Ritorna un valore 0.0-1.0 dove > 0.5 indica outperformance.
    """
    if len(price_series) < 5:
        return 0.5
    
    # Token performance
    token_start = price_series[0]
    token_end = price_series[-1]
    
    if token_start <= 0:
        return 0.5
    
    token_return = (token_end - token_start) / token_start
    
    if market_prices is not None and len(market_prices) >= 5:
        # Compare to market
        market_start = market_prices[0]
        market_end = market_prices[-1]
        
        if market_start > 0:
            market_return = (market_end - market_start) / market_start
            relative_return = token_return - market_return
            
            # Normalize to 0-1
            rs = float(np.clip((relative_return + 0.2) / 0.4, 0.0, 1.0))
        else:
            rs = 0.5
    else:
        # No market data, use absolute performance
        # Normalize token return to 0-1
        rs = float(np.clip((token_return + 0.2) / 0.4, 0.0, 1.0))
    
    return rs
