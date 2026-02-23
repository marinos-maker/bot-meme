"""
Candle Analysis Module — Analyze the first 5-6 candles for breakout patterns.
This is the core of the new strategy for predicting where the market will go.
"""

import numpy as np
from loguru import logger


def analyze_candles(candles: list) -> dict:
    """
    Analyze a list of candles and return a comprehensive analysis.
    Each candle should have: {open, high, low, close, volume, timestamp}
    """
    if len(candles) < 3:
        return {"analysis": "Insufficient data", "score": 0.0, "patterns": []}
    
    try:
        # Convert to numpy arrays for easier calculations
        opens = np.array([c["open"] for c in candles])
        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])
        closes = np.array([c["close"] for c in candles])
        volumes = np.array([c["volume"] for c in candles])
        
        analysis = {
            "bullish_breakout": detect_bullish_breakout(candles, opens, highs, lows, closes, volumes),
            "volume_accumulation": detect_volume_accumulation(candles, volumes, closes),
            "upward_trend": detect_upward_trend(candles, highs, lows),
            "rejection_patterns": detect_rejection_patterns(candles, opens, highs, lows, closes),
            "positive_momentum": detect_positive_momentum(candles, opens, closes),
            "consolidation_breakout": detect_consolidation_breakout(candles, opens, highs, lows, closes, volumes),
            "wick_analysis": analyze_wicks(candles, opens, highs, lows, closes),
            "volume_profile": analyze_volume_profile(candles, volumes, closes),
        }
        
        # Calculate overall score (0.0 to 1.0)
        score = calculate_candle_score(analysis)
        
        # Identify specific patterns
        patterns = identify_patterns(analysis)
        
        return {
            "analysis": analysis,
            "score": score,
            "patterns": patterns,
            "recommendation": get_recommendation(score, patterns)
        }
        
    except Exception as e:
        logger.error(f"Candle analysis failed: {e}")
        return {"analysis": "Error", "score": 0.0, "patterns": [], "error": str(e)}


def detect_bullish_breakout(candles: list, opens: np.ndarray, highs: np.ndarray, 
                           lows: np.ndarray, closes: np.ndarray, volumes: np.ndarray) -> bool:
    """Detect bullish breakout from consolidation."""
    if len(candles) < 5:
        return False
    
    # Calculate consolidation range (last 3-4 candles before current)
    consolidation_period = min(4, len(candles) - 1)
    consolidation_high = np.max(highs[-consolidation_period-1:-1])
    consolidation_low = np.min(lows[-consolidation_period-1:-1])
    consolidation_range = consolidation_high - consolidation_low
    
    if consolidation_range <= 0:
        return False
    
    # Current candle should break above consolidation high with volume
    current = candles[-1]
    current_close = closes[-1]
    current_volume = volumes[-1]
    
    # Breakout condition: close > consolidation high
    if current_close > consolidation_high:
        # Check if volume is higher than average
        avg_volume = np.mean(volumes[-consolidation_period-1:-1])
        volume_confirmation = current_volume > avg_volume * 1.5
        
        # Check if breakout is significant (at least 2% above consolidation high)
        breakout_strength = (current_close - consolidation_high) / consolidation_high
        
        return volume_confirmation and breakout_strength > 0.02
    
    return False


def detect_volume_accumulation(candles: list, volumes: np.ndarray, closes: np.ndarray) -> bool:
    """Detect volume accumulation pattern."""
    if len(candles) < 5:
        return False
    
    # Look for increasing volume on up days
    up_days = []
    for i in range(len(candles)):
        if closes[i] > candles[i]["open"]:
            up_days.append(i)
    
    if len(up_days) < 3:
        return False
    
    # Check if volume is increasing on up days
    up_day_volumes = volumes[up_days]
    return all(up_day_volumes[i] < up_day_volumes[i+1] for i in range(len(up_day_volumes)-1))


def detect_upward_trend(candles: list, highs: np.ndarray, lows: np.ndarray) -> bool:
    """Detect higher highs and higher lows pattern."""
    if len(candles) < 5:
        return False
    
    # Check for higher highs
    recent_highs = highs[-5:]
    higher_highs = all(recent_highs[i] < recent_highs[i+1] for i in range(len(recent_highs)-1))
    
    # Check for higher lows
    recent_lows = lows[-5:]
    higher_lows = all(recent_lows[i] < recent_lows[i+1] for i in range(len(recent_lows)-1))
    
    return higher_highs and higher_lows


def detect_rejection_patterns(candles: list, opens: np.ndarray, highs: np.ndarray,
                             lows: np.ndarray, closes: np.ndarray) -> bool:
    """Detect rejection of lows (hammer-like patterns)."""
    if len(candles) < 3:
        return False
    
    # Look for candles with long lower wicks
    for i in range(-3, 0):  # Check last 3 candles
        candle = candles[i]
        body_size = abs(closes[i] - opens[i])
        wick_size = lows[i] - min(opens[i], closes[i])
        
        # Hammer pattern: long lower wick, small body, close > open
        if wick_size > body_size * 2 and closes[i] > opens[i]:
            return True
    
    return False


def detect_positive_momentum(candles: list, opens: np.ndarray, closes: np.ndarray) -> bool:
    """Check for basic positive momentum."""
    if len(candles) < 3:
        return False
    
    # Check if recent candles are mostly green
    recent_candles = candles[-3:]
    green_candles = sum(1 for c in recent_candles if c["close"] > c["open"])
    
    # Check if price is above the opening of the first candle in the period
    first_open = opens[-3]
    current_close = closes[-1]
    
    return green_candles >= 2 and current_close > first_open


def detect_consolidation_breakout(candles: list, opens: np.ndarray, highs: np.ndarray,
                                 lows: np.ndarray, closes: np.ndarray, volumes: np.ndarray) -> bool:
    """Detect consolidation breakout with volume confirmation."""
    if len(candles) < 6:
        return False
    
    # Define consolidation period (last 4-5 candles)
    consolidation_period = min(5, len(candles) - 1)
    consolidation_highs = highs[-consolidation_period-1:-1]
    consolidation_lows = lows[-consolidation_period-1:-1]
    
    # Calculate consolidation range
    consolidation_range = np.max(consolidation_highs) - np.min(consolidation_lows)
    if consolidation_range <= 0:
        return False
    
    # Current candle analysis
    current = candles[-1]
    current_close = closes[-1]
    current_volume = volumes[-1]
    
    # Breakout conditions
    breakout_up = current_close > np.max(consolidation_highs)
    breakout_down = current_close < np.min(consolidation_lows)
    
    if breakout_up:
        # Volume confirmation for bullish breakout
        avg_volume = np.mean(volumes[-consolidation_period-1:-1])
        volume_confirmation = current_volume > avg_volume * 2.0
        return volume_confirmation
    
    elif breakout_down:
        # Volume confirmation for bearish breakout
        avg_volume = np.mean(volumes[-consolidation_period-1:-1])
        volume_confirmation = current_volume > avg_volume * 1.5
        return volume_confirmation
    
    return False


def analyze_wicks(candles: list, opens: np.ndarray, highs: np.ndarray,
                 lows: np.ndarray, closes: np.ndarray) -> dict:
    """Analyze wick patterns for market sentiment."""
    if len(candles) < 3:
        return {"analysis": "Insufficient data"}
    
    # Calculate wick sizes for recent candles
    upper_wicks = highs - np.maximum(opens, closes)
    lower_wicks = np.minimum(opens, closes) - lows
    body_sizes = np.abs(closes - opens)
    
    # Normalize wicks by body size (avoid division by zero)
    upper_wick_ratios = np.where(body_sizes > 0, upper_wicks / body_sizes, 0)
    lower_wick_ratios = np.where(body_sizes > 0, lower_wicks / body_sizes, 0)
    
    recent_upper_wicks = upper_wick_ratios[-3:]
    recent_lower_wicks = lower_wick_ratios[-3:]
    
    # Analysis
    long_upper_wicks = np.sum(recent_upper_wicks > 2.0)
    long_lower_wicks = np.sum(recent_lower_wicks > 2.0)
    bullish_rejections = np.sum((recent_lower_wicks > 2.0) & (closes[-3:] > opens[-3:]))
    bearish_rejections = np.sum((recent_upper_wicks > 2.0) & (closes[-3:] < opens[-3:]))
    
    return {
        "long_upper_wicks": int(long_upper_wicks),
        "long_lower_wicks": int(long_lower_wicks),
        "bullish_rejections": int(bullish_rejections),
        "bearish_rejections": int(bearish_rejections),
        "sentiment": "bullish" if bullish_rejections > bearish_rejections else "bearish" if bearish_rejections > bullish_rejections else "neutral"
    }


def analyze_volume_profile(candles: list, volumes: np.ndarray, closes: np.ndarray) -> dict:
    """Analyze volume profile for support/resistance levels."""
    if len(candles) < 5:
        return {"analysis": "Insufficient data"}
    
    # Calculate volume-weighted average price (VWAP)
    vwap = np.sum(closes * volumes) / np.sum(volumes) if np.sum(volumes) > 0 else 0
    
    # Volume concentration analysis
    price_range = np.max(closes) - np.min(closes)
    if price_range <= 0:
        return {"vwap": vwap, "concentration": "flat"}
    
    # Volume concentration around VWAP
    vwap_tolerance = price_range * 0.02  # 2% tolerance
    vwap_volume = np.sum(volumes[np.abs(closes - vwap) <= vwap_tolerance])
    total_volume = np.sum(volumes)
    concentration_ratio = vwap_volume / total_volume if total_volume > 0 else 0
    
    return {
        "vwap": float(vwap),
        "concentration_ratio": float(concentration_ratio),
        "concentration": "high" if concentration_ratio > 0.3 else "medium" if concentration_ratio > 0.15 else "low"
    }


def calculate_candle_score(analysis: dict) -> float:
    """Calculate overall candle analysis score (0.0 to 1.0)."""
    weights = {
        "bullish_breakout": 0.25,
        "volume_accumulation": 0.20,
        "upward_trend": 0.20,
        "rejection_patterns": 0.15,
        "positive_momentum": 0.10,
        "consolidation_breakout": 0.15
    }
    
    score = 0.0
    for key, weight in weights.items():
        if key in analysis:
            score += analysis[key] * weight
    
    # Normalize to 0-1 range
    return min(1.0, max(0.0, score))


def identify_patterns(analysis: dict) -> list:
    """Identify specific candle patterns based on analysis."""
    patterns = []
    
    if analysis.get("bullish_breakout", False):
        patterns.append("Bullish Breakout")
    
    if analysis.get("volume_accumulation", False):
        patterns.append("Volume Accumulation")
    
    if analysis.get("upward_trend", False):
        patterns.append("Higher Highs & Lows")
    
    if analysis.get("rejection_patterns", False):
        patterns.append("Bullish Rejection")
    
    if analysis.get("positive_momentum", False):
        patterns.append("Positive Momentum")
    
    if analysis.get("consolidation_breakout", False):
        patterns.append("Consolidation Breakout")
    
    return patterns


def get_recommendation(score: float, patterns: list) -> str:
    """Get trading recommendation based on candle analysis."""
    if score >= 0.8:
        return "STRONG BUY - Multiple bullish patterns detected"
    elif score >= 0.6:
        return "BUY - Bullish patterns present"
    elif score >= 0.4:
        return "HOLD - Mixed signals"
    elif score >= 0.2:
        return "SELL - Bearish patterns present"
    else:
        return "STRONG SELL - Multiple bearish patterns detected"


def is_early_token(candles: list, age_minutes: float) -> bool:
    """Determine if token is in early stage (first 10-15 minutes)."""
    return len(candles) < 6 or age_minutes < 15


def get_early_token_strategy(candles: list, analysis: dict) -> str:
    """Get strategy recommendation for early tokens."""
    if len(candles) < 3:
        return "WAIT - Insufficient data"
    
    # For early tokens, focus on breakout patterns and volume
    if analysis.get("bullish_breakout", False) or analysis.get("consolidation_breakout", False):
        return "AGGRESSIVE ENTRY - Early breakout detected"
    elif analysis.get("volume_accumulation", False) and analysis.get("positive_momentum", False):
        return "CAUTIOUS ENTRY - Accumulation with momentum"
    elif analysis.get("rejection_patterns", False):
        return "WATCH - Potential support forming"
    else:
        return "WAIT - No clear early pattern"