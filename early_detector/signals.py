"""
Signal Detection — trigger logic, safety filters, and Telegram notifications.
"""

import aiohttp
from loguru import logger
from early_detector.config import (
    LIQUIDITY_MIN,
    MCAP_MIN,
    MCAP_MAX,
    TOP10_MAX_RATIO,
    MAX_TOP5_HOLDER_RATIO,
    SPIKE_THRESHOLD,
    HOLDERS_MIN,
    MAX_KELLY_MICROCAP,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from early_detector.db import insert_signal, has_recent_signal
from early_detector.optimization import AlphaEngine


def _has_real_data(token_data: dict, field: str) -> bool:
    """
    Check if a risk field contains REAL calculated data vs default/missing.
    V5.0: Distinguishes between 'data not available' and 'data is genuinely low'.
    """
    val = token_data.get(field)
    if val is None:
        return False
    # Check if the value was explicitly set by a calculation (not a fallback default)
    has_data_flag = token_data.get(f"{field}_verified", False)
    if has_data_flag:
        return True
    # Heuristic: values exactly 0.0, 0.1, or 0.15 are likely defaults
    if field == "insider_psi" and val == 0.0:
        return False
    if field == "creator_risk_score" and val in (0.0, 0.1, 0.15):
        return False
    return True


def calculate_quantitative_degen_score(token_data: dict, confidence: float) -> int:
    """
    Calculate a quantitative degen score based on available metrics.
    V5.0: Missing data is PENALIZED, not rewarded.
    """
    symbol = token_data.get('symbol', 'UNKNOWN')
    logger.debug(f"Calculating quantitative degen score for token: {symbol}")
    
    # Base score from confidence (0-100)
    score = confidence * 100
    logger.debug(f"Base score from confidence: {score}")
    
    # Instability Index multiplier (higher II = higher score)
    ii = token_data.get("instability", 0) or 0
    if ii > 0:
        ii_score = min(ii * 0.5, 50)
        score += ii_score
        logger.debug(f"Added II score: {ii_score}, total: {score}")
    
    # Liquidity modifier — PENALIZE virtual liquidity
    liq = token_data.get("liquidity", 0) or 0
    is_virtual_liq = token_data.get("liquidity_is_virtual", False)
    if is_virtual_liq:
        score -= 15  # Heavy penalty for unverified liquidity
        logger.debug(f"Virtual liquidity penalty: -15, total: {score}")
    elif liq > 5000:  # Strong real liquidity
        score += 10
    elif liq > 1500:  # Good real liquidity
        score += 5
    elif liq > 500:  # Weak liquidity
        score -= 5
    else:
        score -= 10
        
    # Velocity modifier (Volume compared to Liquidity)
    vol = token_data.get("volume_5m", 0) or 0
    velocity = 0
    if liq > 0:
        velocity = (vol / liq) * 100
        if velocity > 50:
            score += 15
        elif velocity > 20:
            score += 10
        elif velocity > 5:
            score += 5
    
    # Market Cap modifier
    mcap = token_data.get("marketcap", 0) or 0
    if mcap < 5000:  # Dust token — PENALTY
        score -= 15
        logger.debug(f"Dust MCap penalty: -15, total: {score}")
    elif mcap < 50000:
        score += 5  # Reduced from +10 — small cap is higher risk
    elif mcap < 200000:
        score += 5
    elif mcap > 1000000:
        score -= 5
    
    # Insider Risk modifier — ONLY reward if data is REAL
    psi = token_data.get("insider_psi", 0) or 0
    if _has_real_data(token_data, "insider_psi"):
        if psi < 0.2 and velocity > 5:
            score += 10
            logger.debug(f"Real low insider risk bonus: +10")
        elif psi > 0.5:
            score -= 15
            logger.debug(f"High insider risk penalty: -15")
    else:
        # Data missing — penalty for unknown risk
        score -= 5
        logger.debug(f"Insider risk UNKNOWN — penalty: -5")
    
    # Creator Risk modifier — ONLY reward if data is REAL
    creator_risk = token_data.get("creator_risk_score", 0) or 0
    if _has_real_data(token_data, "creator_risk_score"):
        if creator_risk < 0.2:
            score += 5
        elif creator_risk > 0.5:
            score -= 10
    else:
        # Data missing — penalty for unknown creator
        score -= 5
        logger.debug(f"Creator risk UNKNOWN — penalty: -5")
    
    swr = token_data.get("swr", 0) or 0
    if swr > 0:
        # SWR is now weighted, so a high SWR means high-quality smart activity
        swr_bonus = min(swr * 40, 25)
        score += swr_bonus
        logger.debug(f"Smart Wallet weighted bonus: +{swr_bonus:.1f}, total: {score}")
    
    # Noise penalty from clusters
    has_noise = token_data.get("has_noise_bots", False)
    if has_noise:
        score -= 20
        logger.debug(f"High-volume noise detection penalty: -20, total: {score}")

    # Top10 concentration penalty
    top10 = token_data.get("top10_ratio", 0) or 0
    if top10 > 90:
        score -= 20
        logger.debug(f"Extreme Top10 concentration ({top10}%) penalty: -20")
    elif top10 > 70:
        score -= 10
    
    # Candle analysis modifier (if available)
    candle_score = token_data.get("candle_score", 0) or 0
    if candle_score > 0.5:
        score += 10
    elif candle_score > 0.3:
        score += 5
    
    # Cap the score to 0-100 range
    score = max(0, min(100, score))
    final_score = int(round(score))
    logger.info(f"Final quantitative degen score for {symbol}: {final_score}")
    
    return final_score


def passes_trigger(token: dict, threshold: float) -> bool:
    """
    Check if a token meets ALL trigger conditions (V4.1 - More permissive):
    - II > dynamic threshold
    - dII/dt > -1.0 (more permissive momentum)
    - price compression (vol_shift < 3.0)
    - liquidity > LIQUIDITY_MIN
    - NEW: Analyze first 5-6 candles for breakout patterns
    """
    ii = (token.get("instability") or 0.0)
    delta_ii = (token.get("delta_instability") or 0.0)
    vol_shift = (token.get("vol_shift") or 1.0)
    
    liq = (token.get("liquidity", 0) or 0)
    mcap = (token.get("marketcap", float("inf")) or float("inf"))

    # 1. Condition II > P-Threshold
    if ii < threshold:
        return False
        
    # Extra check: if all scores are 0, reject (no variance in batch)
    if ii == 0 and threshold == 0:
        return False
        
    # NOTE: We do NOT add a hard floor here — new pump tokens legitimately start at II=0
    # and build up momentum over cycles. The dynamic threshold above handles minimum II.
    
    # 2. Condition: Prevent buying into massive dumps, but allow minor dips on high-momentum tokens
    if delta_ii < -2.5:
        # If absolute index is very high, allow larger dips before rejecting
        if ii < (threshold * 2.0) or (delta_ii < -15.0):
            logger.info(f"Trigger rejected: Sharp falling instability (II={ii:.3f}, dII={delta_ii:.3f}) for {token.get('symbol')}")
            return False
        
    # 3. Condition: Price Compression
    # Be more permissive with recent price action (Increased from 5.0 to 12.0)
    if vol_shift >= 12.0 and ii < (threshold * 1.8):
        logger.info(f"Trigger rejected: Extreme Volatility expansion (vol_shift={vol_shift:.2f}) for {token.get('symbol')}")
        return False
    
    # ── Momentum Fast-Track V5.5 ──
    # If velocity is EXTREME (> 500% turnover) and buys > 50, 
    # we bypass standard candle analysis and lower the II bar.
    vol_intensity = token.get("vol_intensity") or 0.0
    buys_5m = token.get("buys_5m") or 0
    if vol_intensity > 5.0 and buys_5m > 50:
        logger.info(f"🚀 Momentum Fast-Track: HIGH Velocity ({vol_intensity:.1f}) and participation ({buys_5m}) detected for {token.get('symbol')}")
        return True # Bypass candle check

    # 4. Condition: Liquidity check
    is_virtual_liq = token.get("liquidity_is_virtual", False)
    if liq < LIQUIDITY_MIN:
        if liq <= 0:
            logger.info(f"Trigger rejected: ZERO Liquidity for {token.get('symbol') or token.get('address')}")
            return False

        # Allow exception even for virtual liquidity if momentum is insane (Fast-Track)
        if vol_intensity > 3.0 and ii > threshold:
             logger.info(f"Trigger exception: High momentum ({vol_intensity:.1f}) on micro-liquidity (${liq:.0f}) for {token.get('symbol')}")
        else:
             # Standard rejection
             logger.info(f"Trigger rejected: Low Liquidity ({liq:.0f} < {LIQUIDITY_MIN}, virtual={is_virtual_liq}) for {token.get('symbol')}")
             return False
    
    # 4b. MCap minimum check (Lowered to allow the user's micro-caps)
    # Allows Pump.fun tokens that naturally start at ~$2200
    if mcap < 2000:
        logger.info(f"Trigger rejected: MCap extremely low (${mcap:,.0f}) for {token.get('symbol')}")
        return False
        
    # 5. NEW: First 5-6 Candles Analysis (Early Breakout Detection)
    if not passes_candle_analysis(token):
        logger.info(f"Trigger rejected: Failed candle analysis for {token.get('symbol') or token.get('address')}")
        return False

    return True


def passes_candle_analysis(token: dict) -> bool:
    """
    Analyze the first 5-6 candles for breakout patterns.
    This is the core of the new strategy for predicting where the market will go.
    """
    # Get candle data
    candles = token.get("candles", [])
    age_minutes = token.get("age_minutes", 0)
    
    if len(candles) < 3:
        # If we don't have enough candles yet, be more permissive for very new tokens
        if age_minutes < 10:  # Less than 10 minutes old
            # For very new tokens, rely more on other metrics
            logger.info(f"Candle Analysis: Very new token ({age_minutes}m), using other metrics for {token.get('symbol')}")
            return True
        return False
    
    # Use the new comprehensive candle analysis module
    try:
        from early_detector.candle_analysis import analyze_candles, is_early_token, get_early_token_strategy
        
        # Perform comprehensive candle analysis
        analysis_result = analyze_candles(candles)
        
        if analysis_result.get("score", 0) >= 0.6:
            logger.info(f"Candle Analysis: Strong bullish signal (score: {analysis_result.get('score', 0):.2f}) for {token.get('symbol')}")
            return True
        elif analysis_result.get("score", 0) >= 0.4:
            logger.info(f"Candle Analysis: Moderate bullish signal (score: {analysis_result.get('score', 0):.2f}) for {token.get('symbol')}")
            return True
        elif is_early_token(candles, age_minutes):
            strategy = get_early_token_strategy(candles, analysis_result.get("analysis", {}))
            if strategy.startswith(("AGGRESSIVE ENTRY", "CAUTIOUS ENTRY")):
                logger.info(f"Candle Analysis: Early token strategy ({strategy}) for {token.get('symbol')}")
                return True
        
        # Log patterns detected even if not strong enough
        patterns = analysis_result.get("patterns", [])
        if patterns:
            logger.info(f"Candle Analysis: Patterns detected ({', '.join(patterns)}) for {token.get('symbol')}")
            
        return False
        
    except Exception as e:
        logger.warning(f"Candle analysis failed for {token.get('symbol')}: {e}")
        # If candle analysis fails, don't reject - be permissive
        return True




def passes_safety_filters(token: dict) -> bool:
    """
    Safety Filters V5.0 — Fail-Closed approach for missing data:
    - REJECT if Mint/Freeze Authority is enabled.
    - REJECT if Top 10 Holders ratio > 90% for ALL pump tokens (bonding curve or not).
    - REJECT if Top 10 > TOP10_MAX_RATIO for graduated tokens.
    - REJECT if Insider/Creator Risk is genuinely high.
    - REJECT if Price Spike > 5x in 5m.
    - REJECT if MCap < MCAP_MIN (dust tokens).
    """
    symbol = token.get('symbol', 'UNKNOWN')
    address = token.get("address", "")
    is_pump = address.endswith("pump")
    mcap = token.get("marketcap") or 0
    
    # 1. On-chain Authorities (Critical)
    mint_auth = token.get("mint_authority")
    if mint_auth is not None:
        logger.info(f"Safety: Mint Authority ENABLED ({mint_auth[:8]}...) — REJECTED")
        return False
        
    freeze_auth = token.get("freeze_authority")
    if freeze_auth is not None:
        logger.info(f"Safety: Freeze Authority ENABLED ({freeze_auth[:8]}...) — REJECTED")
        return False

    # 2. Supply Concentration — V5.0 STRICT for pump tokens
    top10_ratio = token.get("top10_ratio")
    threshold_percent = TOP10_MAX_RATIO * 100  # e.g. 50%
    
    if top10_ratio is None or top10_ratio == 0:
        if mcap > 50000:
            logger.info(f"Safety: Top 10 concentration UNKNOWN for cap ({mcap:,.0f}) — REJECTED {symbol}")
            return False
        else:
            logger.info(f"Safety Grace: Top 10 UNKNOWN for micro cap ({mcap:,.0f}) — PROCEEDING {symbol}")
    
    if not is_pump:
        # Graduated tokens: enforce TOP10_MAX_RATIO strictly
        if top10_ratio and top10_ratio > threshold_percent:
            logger.info(f"Safety: High Top 10 concentration ({top10_ratio:.1f}% > {threshold_percent}%) — REJECTED {symbol}")
            return False

    # 2b. Holder Count Filter
    holders = token.get("holders") or 0
    if holders < HOLDERS_MIN and mcap > 30000:
        logger.info(f"Safety: Too few holders ({holders} < {HOLDERS_MIN}) — REJECTED {symbol}")
        return False

    # 3. Behavioral Risk (Only reject on REAL high values)
    insider_psi = (token.get("insider_psi") or 0.0)
    if _has_real_data(token, "insider_psi") and insider_psi > 0.60:
        logger.info(f"Safety: High Insider Probability ({insider_psi:.2f}) — REJECTED {symbol}")
        return False
        
    creator_risk = (token.get("creator_risk_score") or 0.0)
    if _has_real_data(token, "creator_risk_score") and creator_risk > 0.55:
        logger.info(f"Safety: High Creator Risk ({creator_risk:.2f}) — REJECTED {symbol}")
        return False

    # 4. Momentum Spike check
    price_change_5m = (token.get("price_change_5m") or 0.0)
    if price_change_5m and price_change_5m >= 5.0:
        logger.info(f"Safety: Price Spike detected ({price_change_5m:.2f}x) — REJECTED {symbol}")
        return False
        
    return True


def passes_quality_gate(token_data: dict, ai_result: dict) -> bool:
    """
    Final Quality Check V5.0 — Stronger bar for entry:
    - MCap minimum enforced
    - Virtual liquidity penalized
    - Age + Degen Score gate
    - Quiet token confidence gate
    """
    symbol = token_data.get('symbol', 'UNKNOWN')
    
    # 1. MCap Floor (Start tracking around $2k for Pump)
    mcap = token_data.get("marketcap") or 0
    if mcap < 2000:
        logger.info(f"Quality Gate: REJECTED {symbol} - MCap too low (${mcap:,.0f} < $2,000)")
        return False
    
    # 2. Liquidity Floor — virtual liquidity gets a HIGHER bar, but reasonable for micro-caps
    liq = token_data.get("liquidity") or 0
    is_virtual_liq = token_data.get("liquidity_is_virtual", False)
    min_liq = 300 if is_virtual_liq else 200
    if liq < min_liq:
        logger.info(f"Quality Gate: REJECTED {symbol} - Liquidity too low (${liq:.0f}, virtual={is_virtual_liq})")
        return False

    # 3. Age Filter
    created_at = token_data.get("pair_created_at")
    import time
    if created_at:
        now_ms = time.time() * 1000
        age_min = (now_ms - created_at) / (1000 * 60)
        
        # If less than 15 minutes old, require BETTER degen score
        if age_min < 15:
            degen_score = ai_result.get("degen_score") or token_data.get("degen_score") or 0
            if degen_score < 40:
                logger.info(f"Quality Gate: REJECTED {symbol} - Too new ({age_min:.1f}m) and low score ({degen_score})")
                return False
                
    # 4. High Confidence Requirement for "Quiet" tokens
    swr = token_data.get("swr") or 0
    psi = token_data.get("insider_psi") or 0
    if swr == 0 and psi < 0.2:
        conf = token_data.get("confidence") or 0
        if conf < 0.50:  # Raised from 0.45
            logger.info(f"Quality Gate: REJECTED {symbol} - Low conviction (Conf: {conf:.2f}, No SWR)")
            return False

    return True


async def process_signals(scored_df, threshold: float, regime_label: str = "UNKNOWN") -> list[dict]:
    """
    Evaluate all scored tokens and generate signals for qualifying ones.
    Includes Position Sizing (Quarter Kelly).
    """
    signals = []

    logger.info(f"📊 Evaluating {len(scored_df)} tokens against threshold {threshold:.4f}...")
    for _, row in scored_df.iterrows():
        token_data = row.to_dict()

        if not passes_trigger(token_data, threshold):
            continue

        if not passes_safety_filters(token_data):
            logger.info(f"🛡️ {token_data.get('symbol')} failed safety filters")
            continue

        token_id = str(token_data.get("token_id"))
        if await has_recent_signal(token_id, minutes=60):
            continue

        # ── Bayesian Win Probability V5.0 ──
        # Conservative prior — token must EARN confidence through real data
        prior = 0.35  # Lowered from 0.5 — skeptical by default
        likelihoods = []

        # 1. Regime context
        if regime_label == "DEGEN":
            likelihoods.append(1.1)

        # 2. Risk Metrics — V5.0: ONLY boost if data is REAL
        creator_risk = token_data.get("creator_risk_score") or 0.0
        if _has_real_data(token_data, "creator_risk_score"):
            if creator_risk < 0.15:
                likelihoods.append(1.3)  # Verified low risk creator
            elif creator_risk > 0.5:
                likelihoods.append(0.6)  # Verified risky creator
        else:
            # Unknown creator = slight penalty (not a bonus!)
            likelihoods.append(0.85)

        insider_psi = token_data.get("insider_psi") or 0.0
        if _has_real_data(token_data, "insider_psi"):
            if insider_psi < 0.1:
                likelihoods.append(1.3)  # Verified clean insider profile
            elif insider_psi > 0.5:
                likelihoods.append(0.6)
        else:
            # Unknown insider risk = slight penalty
            likelihoods.append(0.85)

        # 3. Momentum & Intensity
        ii = token_data.get("instability_index") or token_data.get("instability") or 0
        if threshold > 0 and ii > 0 and (ii / threshold) > 1.5:
            likelihoods.append(1.25)

        delta_ii = (token_data.get("delta_instability") or 0.0)
        if delta_ii > 20:
            likelihoods.append(1.2)
        elif delta_ii < -10:
            likelihoods.append(0.8)

        # 4. Smart Wallet Rotation (SWR)
        swr = token_data.get("swr") or 0
        if swr > 0:
            likelihoods.append(1.5)

        # 5. Virtual Liquidity penalty
        if token_data.get("liquidity_is_virtual", False):
            likelihoods.append(0.80)

        # 6. Top10 concentration penalty in Bayesian
        top10 = token_data.get("top10_ratio") or 0
        if top10 > 80:
            likelihoods.append(0.70)
        elif top10 > 60:
            likelihoods.append(0.85)

        base_confidence = AlphaEngine.calculate_bayesian_confidence(prior, likelihoods)

        # Quarter Kelly sizing with MCap-based cap
        kelly_size = AlphaEngine.calculate_kelly_size(
            win_prob=base_confidence,
            avg_win_multiplier=0.40,   # Slightly reduced from 0.45
            avg_loss_multiplier=0.15,
            fractional_kelly=0.25
        )

        # V5.0: Cap Kelly size for micro-cap tokens
        mcap = token_data.get("marketcap") or 0
        if mcap < 50000:
            kelly_size = min(kelly_size, MAX_KELLY_MICROCAP)
            logger.debug(f"Kelly capped to {MAX_KELLY_MICROCAP:.0%} for micro-cap ({mcap:,.0f})")

        # Size reduction for moderate insider risk
        insider_psi = (token_data.get("insider_psi") or 0.0)
        if _has_real_data(token_data, "insider_psi") and 0.4 <= insider_psi <= 0.60:
            kelly_size *= 0.5
            logger.info(f"Risk Adjustment: Reducing size by 50% due to moderate insider risk ({insider_psi:.2f})")

        if kelly_size <= 0.01:
            continue

        signal = {
            "token_id": token_data.get("token_id"),
            "address": token_data.get("address", ""),
            "name": token_data.get("name", "Unknown"),
            "symbol": token_data.get("symbol", "???"),
            "instability_index": token_data.get("instability", 0),
            "price": token_data.get("price", 0),
            "liquidity": token_data.get("liquidity", 0),
            "liquidity_is_virtual": token_data.get("liquidity_is_virtual", False),
            "marketcap": token_data.get("marketcap", 0),
            "confidence": base_confidence,
            "kelly_size": kelly_size,
            "insider_psi": insider_psi,
            "insider_psi_verified": token_data.get("insider_psi_verified", False),
            "creator_risk": token_data.get("creator_risk_score", 0.1),
            "creator_risk_score": token_data.get("creator_risk_score", 0.1),
            "creator_risk_score_verified": token_data.get("creator_risk_score_verified", False),
            "swr": token_data.get("swr", 0),
            "mint_authority": token_data.get("mint_authority"),
            "freeze_authority": token_data.get("freeze_authority"),
            "top10_ratio": token_data.get("top10_ratio", 0.0),
            "pair_created_at": token_data.get("pair_created_at"),
        }

        # ── Exit Strategy (V4.0) ──
        from early_detector.exits import ExitStrategy
        exit_levels = ExitStrategy.calculate_levels(signal["price"])
        signal["hard_stop"] = exit_levels.get("hard_stop")
        signal["tp_1"] = exit_levels.get("tp_1")

        # ── Quantitative Diary (V4.0) ──
        from early_detector.diary import log_trade_signal
        log_trade_signal(signal, regime_label)

        # ── AI Analysis (Z.AI OpenRouter) ──
        from early_detector.analyst import analyze_token_signal
        
        logger.info(f"🧠 Prompting AI Analyst for {signal.get('symbol')}...")
        # Since history is difficult to reconstruct fully here, we pass empty list.
        # Analyst.py uses token_data and handles empty history gracefully.
        ai_result = await analyze_token_signal(token_data, [])
        
        degen_score = ai_result.get("degen_score")
        if degen_score is None:
            degen_score = calculate_quantitative_degen_score(token_data, base_confidence)
            
        signal["degen_score"] = degen_score
        signal["ai_summary"] = ai_result.get("summary", f"Score: {degen_score}")
        signal["ai_analysis"] = ai_result

        # V4.6 Stability Quality Gate
        if not passes_quality_gate(signal, ai_result):
             continue

        # Save to DB
        logger.debug(f"Saving signal to database: symbol={signal.get('symbol')}, degen_score={signal.get('degen_score')}")
        await insert_signal(
            token_id=signal["token_id"],
            instability_index=signal["instability_index"],
            entry_price=signal["price"],
            liquidity=signal["liquidity"],
            marketcap=signal["marketcap"],
            confidence=signal["confidence"],
            kelly_size=signal["kelly_size"],
            insider_psi=signal["insider_psi"],
            creator_risk=signal["creator_risk"],
            hard_stop=signal["hard_stop"],
            tp_1=signal["tp_1"],
            degen_score=signal.get("degen_score"),
            ai_summary=signal.get("ai_summary"),
            ai_analysis=signal.get("ai_analysis"),
            mint_authority=signal.get("mint_authority"),
            freeze_authority=signal.get("freeze_authority")
        )
        logger.info(f"Signal saved successfully: {signal.get('symbol')} with degen_score={signal.get('degen_score')}")

        # Send notification
        await send_telegram_alert(signal)

        signals.append(signal)
        logger.info(
            f"🚨 SIGNAL: {signal.get('symbol', 'UNKNOWN')} ({signal.get('name', 'Unknown')}) — "
            f"II={signal['instability_index']:.3f}, "
            f"Price={signal['price']}, MCap={signal['marketcap']:.0f}"
        )

    return signals


# ── Telegram Notifications ────────────────────────────────────────────────────

async def send_telegram_alert(signal: dict) -> None:
    """Send a signal alert to the configured Telegram chat."""
    logger.debug(f"send_telegram_alert called with signal: {signal.get('symbol')} - {signal.get('name')}")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — skipping alert")
        logger.warning(f"TELEGRAM_BOT_TOKEN: {'Set' if TELEGRAM_BOT_TOKEN else 'Not set'}")
        logger.warning(f"TELEGRAM_CHAT_ID: {'Set' if TELEGRAM_CHAT_ID else 'Not set'}")
        return

    # Improved fallback logic for name and symbol
    symbol = signal.get('symbol', 'UNKNOWN')
    name = signal.get('name', 'Unknown Token')
    
    # If symbol is "???" or "UNKNOWN", try to use address as symbol
    if symbol in ['???', 'UNKNOWN', '']:
        symbol = signal.get('address', 'UNKNOWN')[:8] + '...'
    
    # If name is "Unknown Token" or empty, try to use address as name
    if name in ['Unknown Token', '']:
        name = f"Token {signal.get('address', 'UNKNOWN')[:8]}..."

    # Fix potential zero division or None prices
    price = signal.get('price') or 0.0
    hard_stop = signal.get('hard_stop') or 0.0
    tp_1 = signal.get('tp_1') or 0.0
    
    # Safe float formatting to avoid TypeErrors
    ii = float(signal.get('instability_index', 0.0))
    liq = float(signal.get('liquidity', 0.0))
    mcap = float(signal.get('marketcap', 0.0))
    conf = float(signal.get('confidence', 0.0))
    k_size = float(signal.get('kelly_size', 0.0))
    i_psi = float(signal.get('insider_psi', 0.0))
    c_risk = float(signal.get('creator_risk', 0.0))
    t10_ratio = float(signal.get('top10_ratio', 0.0))
    d_score = signal.get('degen_score', 'N/A')
    
    # Clean up AI summary avoiding None output
    ai_sum = signal.get('ai_summary')
    if not ai_sum or ai_sum.strip() == "":
        ai_sum = "Nessuna analisi AI disponibile"

    # V5.0: Data quality indicators
    is_virtual_liq = signal.get('liquidity_is_virtual', False)
    insider_verified = signal.get('insider_psi_verified', False)
    creator_verified = signal.get('creator_risk_score_verified', False)
    
    liq_label = f"${liq:,.0f}" + (" ⚠️ VIRTUAL" if is_virtual_liq else "")
    psi_label = f"{i_psi:.2f}" if insider_verified else "N/D ⚠️"
    cr_label = f"{c_risk:.2f}" if creator_verified else "N/D ⚠️"
    
    # Build warnings
    warnings = []
    if is_virtual_liq:
        warnings.append("⚠️ Liquidità stimata (non verificata on-chain)")
    if not insider_verified:
        warnings.append("⚠️ Insider Risk non calcolato (dati insufficienti)")
    if not creator_verified:
        warnings.append("⚠️ Creator Risk non verificato (nuovo creator)")
    if t10_ratio > 80:
        warnings.append(f"⚠️ Alta concentrazione Top 10: {t10_ratio:.1f}%")
    
    warning_text = "\n".join(warnings) if warnings else "✅ Tutti i dati verificati"

    text = (
        f"🚨 <b>EARLY DETECTOR SIGNAL (V5.0)</b>\n\n"
        f"🪙 <b>{symbol}</b> — {name}\n"
        f"📍 <b>Address:</b> <code>{signal.get('address', 'UNKNOWN')}</code>\n"
        f"📊 Instability Index: <code>{ii:.3f}</code>\n"
        f"💰 Price: <code>${price:.10f}</code>\n"
        f"💧 Liquidity: <code>{liq_label}</code>\n"
        f"📈 Market Cap: <code>${mcap:,.0f}</code>\n"
        f"👥 Top 10 Holders: <code>{t10_ratio:.1f}%</code>\n"
        f"\n"
        f"🎯 <b>Probability Score:</b> <code>{conf:.1%}</code>\n"
        f"⚖️ <b>Recommended Size:</b> <code>{k_size:.1%} of Wallet</code>\n"
        f"🔥 <b>Insider Risk:</b> <code>{psi_label}</code>\n"
        f"⚠️ <b>Creator Risk:</b> <code>{cr_label}</code>\n"
        f"🤖 <b>AI Degen Score:</b> <code>{d_score}</code>\n"
        f"\n"
        f"🧠 <b>EXIT STRATEGY:</b>\n"
        f"🛑 Hard Stop: <code>${hard_stop:.10f}</code> (-15%)\n"
        f"💰 Target TP1: <code>${tp_1:.10f}</code> (+40%)\n"
        f"🔄 Then: Trailing Stop 20%\n"
        f"\n"
        f"📋 <b>AI Summary:</b>\n<i>{ai_sum}</i>\n"
        f"\n"
        f"🔍 <b>Data Quality:</b>\n{warning_text}\n"
        f"\n"
        f"🔗 <a href='https://birdeye.so/token/{signal.get('address', '')}?chain=solana'>Birdeye</a>"
        f" | <a href='https://dexscreener.com/solana/{signal.get('address', '')}'>DexScreener</a>"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    logger.debug("Telegram alert sent successfully")
                else:
                    body = await resp.text()
                    logger.error(f"Telegram error {resp.status}: {body}")
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
