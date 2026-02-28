"""
Candle Analysis Module — Analyze the first 5-6 candles for breakout patterns.
This is the core of the new strategy for predicting where the market will go.
V6.0 OPTIMIZED: More flexible pattern detection, volume-weighted analysis, momentum confirmation.
"""

import numpy as np
from loguru import logger


def analyze_candles(candles: list) -> dict:
    """
    Analyze a list of candles and return a comprehensive analysis.
    Each candle should have: {open, high, low, close, volume, timestamp}
    V6.0: Enhanced with momentum confirmation and volume-weighted scoring.
    """
    if len(candles) < 2:
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
            # V6.0: New enhanced indicators
            "momentum_confirmation": check_momentum_confirmation(candles, opens, closes, volumes),
            "volume_price_divergence": check_volume_price_divergence(candles, volumes, closes),
            "buy_pressure_ratio": calculate_buy_pressure(candles, volumes, closes),
            "trend_strength": calculate_trend_strength(candles, highs, lows, closes, volumes),
        }
        
        # V6.0: Enhanced scoring with momentum confirmation
        score = calculate_candle_score_v6(analysis, candles, volumes, closes)
        
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


# ═══════════════════════════════════════════════════════════════════════════════
# V6.0 ENHANCED INDICATORS - Nuove funzioni per analisi avanzata
# ═══════════════════════════════════════════════════════════════════════════════

def check_momentum_confirmation(candles: list, opens: np.ndarray, closes: np.ndarray, 
                                 volumes: np.ndarray) -> float:
    """
    V6.0: Momentum Confirmation Score.
    
    Verifica che il momentum sia confermato da volume e prezzo.
    Ritorna un punteggio 0.0-1.0.
    
    Logica:
    - Prezzo in aumento nelle ultime 3 candele
    - Volume in aumento nelle ultime 3 candele
    - Close > Open nelle ultime candele
    """
    if len(candles) < 3:
        return 0.5  # Neutro per token molto nuovi
    
    score = 0.0
    
    # 1. Price momentum: close crescente nelle ultime 3 candele
    recent_closes = closes[-3:]
    if recent_closes[-1] > recent_closes[0]:
        price_change = (recent_closes[-1] - recent_closes[0]) / (recent_closes[0] + 1e-12)
        score += min(0.3, price_change * 10)  # Max 0.3 per price momentum
    
    # 2. Volume momentum: volume crescente
    recent_volumes = volumes[-3:]
    if recent_volumes[-1] > recent_volumes[0]:
        vol_change = (recent_volumes[-1] - recent_volumes[0]) / (recent_volumes[0] + 1e-12)
        score += min(0.3, vol_change * 0.5)  # Max 0.3 per volume momentum
    
    # 3. Green candles ratio
    green_count = sum(1 for i in range(-3, 0) if closes[i] > opens[i])
    score += (green_count / 3) * 0.4  # Max 0.4 per candle color
    
    return min(1.0, score)


def check_volume_price_divergence(candles: list, volumes: np.ndarray, 
                                   closes: np.ndarray) -> str:
    """
    V6.0: Rileva divergenze tra volume e prezzo.
    
    - "bullish": Prezzo sale con volume crescente (conferma)
    - "weak_bullish": Prezzo sale ma volume scende (attenzione)
    - "bearish": Prezzo scende con volume crescente (distribuzione)
    - "neutral": Nessun pattern chiaro
    """
    if len(candles) < 4:
        return "neutral"
    
    # Calcola trend prezzo e volume
    price_start = np.mean(closes[-4:-2])
    price_end = np.mean(closes[-2:])
    
    vol_start = np.mean(volumes[-4:-2])
    vol_end = np.mean(volumes[-2:])
    
    price_up = price_end > price_start * 1.01
    price_down = price_end < price_start * 0.99
    vol_up = vol_end > vol_start * 1.1
    vol_down = vol_end < vol_start * 0.9
    
    if price_up and vol_up:
        return "bullish"  # Conferma - forte segnale
    elif price_up and vol_down:
        return "weak_bullish"  # Divergenza debole - attenzione
    elif price_down and vol_up:
        return "bearish"  # Distribuzione - evitare
    else:
        return "neutral"


def calculate_buy_pressure(candles: list, volumes: np.ndarray, 
                           closes: np.ndarray) -> float:
    """
    V6.0: Calcola la pressione di acquisto basata su candle analysis.
    
    Ritorna un rapporto 0.0-1.0 dove:
    - > 0.6 = forte pressione acquisto
    - < 0.4 = forte pressione vendita
    - 0.5 = neutro
    """
    if len(candles) < 2:
        return 0.5
    
    total_buy_volume = 0.0
    total_volume = 0.0
    
    for i, candle in enumerate(candles):
        vol = volumes[i]
        open_p = candle.get("open", closes[i])
        close_p = closes[i]
        
        # Stima il volume di buy vs sell dalla direzione della candle
        if close_p >= open_p:
            # Green candle: maggioranza buy
            body_ratio = (close_p - open_p) / (max(candle.get("high", close_p), close_p) - min(candle.get("low", open_p), open_p) + 1e-12)
            buy_vol = vol * (0.5 + body_ratio * 0.4)  # 50-90% buy
        else:
            # Red candle: maggioranza sell
            body_ratio = (open_p - close_p) / (max(candle.get("high", open_p), open_p) - min(candle.get("low", close_p), close_p) + 1e-12)
            buy_vol = vol * (0.5 - body_ratio * 0.4)  # 10-50% buy
        
        total_buy_volume += buy_vol
        total_volume += vol
    
    if total_volume == 0:
        return 0.5
    
    return total_buy_volume / total_volume


def calculate_trend_strength(candles: list, highs: np.ndarray, lows: np.ndarray,
                             closes: np.ndarray, volumes: np.ndarray) -> float:
    """
    V6.0: Calcola la forza del trend usando Average Directional Index semplificato.
    
    Ritorna un punteggio 0.0-1.0 dove:
    - > 0.7 = trend forte
    - 0.4-0.7 = trend moderato
    - < 0.4 = trend debole o laterale
    """
    if len(candles) < 3:
        return 0.5
    
    # Calcola True Range e Directional Movement
    true_ranges = []
    plus_dm = []
    minus_dm = []
    
    for i in range(1, len(candles)):
        high = highs[i]
        low = lows[i]
        prev_close = closes[i-1]
        prev_high = highs[i-1]
        prev_low = lows[i-1]
        
        # True Range
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
        
        # Directional Movement
        up_move = high - prev_high
        down_move = prev_low - low
        
        if up_move > down_move and up_move > 0:
            plus_dm.append(up_move)
            minus_dm.append(0)
        elif down_move > up_move and down_move > 0:
            plus_dm.append(0)
            minus_dm.append(down_move)
        else:
            plus_dm.append(0)
            minus_dm.append(0)
    
    if not true_ranges or sum(true_ranges) == 0:
        return 0.5
    
    # Calcola DI+ e DI-
    avg_tr = np.mean(true_ranges)
    avg_plus_dm = np.mean(plus_dm)
    avg_minus_dm = np.mean(minus_dm)
    
    if avg_tr == 0:
        return 0.5
    
    plus_di = avg_plus_dm / avg_tr
    minus_di = avg_minus_dm / avg_tr
    
    # DX e ADX semplificato
    dx = abs(plus_di - minus_di) / (plus_di + minus_di + 1e-12)
    
    # Normalizza a 0-1
    return float(np.clip(dx, 0.0, 1.0))


def calculate_candle_score_v6(analysis: dict, candles: list, 
                               volumes: np.ndarray, closes: np.ndarray) -> float:
    """
    V6.0: Enhanced candle scoring con pesi dinamici.
    
    Il punteggio base viene calcolato dai pattern tradizionali,
    poi viene modificato dai nuovi indicatori di momentum e volume.
    """
    # Pesi per pattern tradizionali (aggiornati)
    weights = {
        "bullish_breakout": 0.20,
        "volume_accumulation": 0.15,
        "upward_trend": 0.15,
        "rejection_patterns": 0.10,
        "positive_momentum": 0.10,
        "consolidation_breakout": 0.10
    }
    
    base_score = 0.0
    for key, weight in weights.items():
        if key in analysis and analysis[key]:
            base_score += weight
    
    # V6.0: Applica modificatori dai nuovi indicatori
    
    # 1. Momentum Confirmation Modifier (fino a +0.2)
    momentum = analysis.get("momentum_confirmation", 0.5)
    momentum_bonus = (momentum - 0.5) * 0.4  # -0.2 a +0.2
    base_score += momentum_bonus
    
    # 2. Volume-Price Divergence Modifier
    divergence = analysis.get("volume_price_divergence", "neutral")
    if divergence == "bullish":
        base_score += 0.15
    elif divergence == "weak_bullish":
        base_score += 0.05
    elif divergence == "bearish":
        base_score -= 0.20  # Penalità forte per distribuzione
    
    # 3. Buy Pressure Modifier
    buy_pressure = analysis.get("buy_pressure_ratio", 0.5)
    if buy_pressure > 0.65:
        base_score += 0.10
    elif buy_pressure < 0.35:
        base_score -= 0.10
    
    # 4. Trend Strength Modifier
    trend_strength = analysis.get("trend_strength", 0.5)
    if trend_strength > 0.6 and buy_pressure > 0.5:
        base_score += 0.10
    elif trend_strength < 0.3:
        base_score -= 0.05
    
    # 5. Wick Analysis Modifier
    wick_analysis = analysis.get("wick_analysis", {})
    wick_sentiment = wick_analysis.get("sentiment", "neutral")
    if wick_sentiment == "bullish":
        base_score += 0.05
    elif wick_sentiment == "bearish":
        base_score -= 0.05
    
    # Normalizza a 0-1
    return float(np.clip(base_score, 0.0, 1.0))


def get_signal_quality(candles: list, volumes: np.ndarray, 
                       closes: np.ndarray) -> dict:
    """
    V6.0: Valuta la qualità complessiva del segnale.
    
    Ritorna un dict con:
    - quality_score: 0.0-1.0
    - confidence: "high", "medium", "low"
    - risk_level: "low", "medium", "high"
    - warnings: lista di avvisi
    """
    if len(candles) < 2:
        return {
            "quality_score": 0.0,
            "confidence": "low",
            "risk_level": "high",
            "warnings": ["Dati insufficienti per analisi affidabile"]
        }
    
    warnings = []
    score = 0.0
    
    # 1. Data Quality Check
    if len(candles) >= 5:
        score += 0.25
    elif len(candles) >= 3:
        score += 0.15
        warnings.append("Solo 3-4 candele disponibili - analisi limitata")
    else:
        warnings.append("Meno di 3 candele - segnale ad alto rischio")
    
    # 2. Volume Consistency
    vol_std = np.std(volumes) / (np.mean(volumes) + 1e-12)
    if vol_std < 0.5:  # Volume stabile
        score += 0.15
    elif vol_std > 2.0:  # Volume molto volatile
        warnings.append("Volume molto volatile - possibile manipolazione")
    else:
        score += 0.10
    
    # 3. Price Consistency
    price_std = np.std(closes) / (np.mean(closes) + 1e-12)
    if price_std < 0.1:  # Prezzo stabile
        score += 0.15
    elif price_std > 0.5:  # Prezzo molto volatile
        warnings.append("Alta volatilità del prezzo - rischio elevato")
    else:
        score += 0.10
    
    # 4. Trend Direction
    if len(closes) >= 3:
        if closes[-1] > closes[-3]:  # Trend positivo
            score += 0.20
        elif closes[-1] < closes[-3]:  # Trend negativo
            warnings.append("Trend prezzo negativo")
    
    # 5. Volume Trend
    if len(volumes) >= 3:
        if volumes[-1] > volumes[-3]:  # Volume crescente
            score += 0.15
        else:
            warnings.append("Volume in calo")
    
    # Determina confidence e risk level
    if score >= 0.7:
        confidence = "high"
        risk_level = "low"
    elif score >= 0.4:
        confidence = "medium"
        risk_level = "medium"
    else:
        confidence = "low"
        risk_level = "high"
    
    return {
        "quality_score": float(np.clip(score, 0.0, 1.0)),
        "confidence": confidence,
        "risk_level": risk_level,
        "warnings": warnings
    }
