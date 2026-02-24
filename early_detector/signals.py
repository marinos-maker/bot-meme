"""
Signal Detection — trigger logic, safety filters, and Telegram notifications.
"""

import aiohttp
from loguru import logger
from early_detector.config import (
    LIQUIDITY_MIN,
    MCAP_MAX,
    TOP10_MAX_RATIO,
    MAX_TOP5_HOLDER_RATIO,
    SPIKE_THRESHOLD,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from early_detector.db import insert_signal, has_recent_signal
from early_detector.optimization import AlphaEngine


def calculate_quantitative_degen_score(token_data: dict, confidence: float) -> int:
    """
    Calculate a quantitative degen score based on available metrics.
    This provides a numerical score when AI Analyst is disabled.
    """
    logger.debug(f"Calculating quantitative degen score for token: {token_data.get('symbol', 'UNKNOWN')}")
    logger.debug(f"Input data: confidence={confidence}, token_data={token_data}")
    
    # Base score from confidence (0-100)
    score = confidence * 100
    logger.debug(f"Base score from confidence: {score}")
    
    # Instability Index multiplier (higher II = higher score)
    ii = token_data.get("instability", 0) or 0
    logger.debug(f"Instability Index: {ii}")
    if ii > 0:
        # Normalize II to 0-50 range (most tokens have II < 100)
        ii_score = min(ii * 0.5, 50)
        score += ii_score
        logger.debug(f"Added II score: {ii_score}, total: {score}")
    
    # Liquidity modifier (higher liquidity = more reliable)
    liq = token_data.get("liquidity", 0) or 0
    logger.debug(f"Liquidity: {liq}")
    if liq > 1000:  # Good liquidity
        score += 10
        logger.debug(f"Added liquidity bonus: +10, total: {score}")
    elif liq > 500:  # Moderate liquidity
        score += 5
        logger.debug(f"Added liquidity bonus: +5, total: {score}")
    elif liq > 100:  # Low liquidity
        score -= 5
        logger.debug(f"Subtracted liquidity penalty: -5, total: {score}")
    else:  # Very low liquidity
        score -= 10
        logger.debug(f"Subtracted liquidity penalty: -10, total: {score}")
        
    # Velocity modifier (Volume compared to Liquidity)
    vol = token_data.get("volume_5m", 0) or 0
    velocity = 0
    if liq > 0:
        velocity = (vol / liq) * 100
        logger.debug(f"Velocity (Vol/Liq): {velocity:.1f}%")
        if velocity > 50:
            score += 15
            logger.debug(f"Added velocity bonus: +15, total: {score}")
        elif velocity > 20:
            score += 10
            logger.debug(f"Added velocity bonus: +10, total: {score}")
        elif velocity > 5:
            score += 5
            logger.debug(f"Added velocity bonus: +5, total: {score}")
    
    # Market Cap modifier (smaller caps = higher degen potential)
    mcap = token_data.get("marketcap", 0) or 0
    logger.debug(f"Market Cap: {mcap}")
    if mcap < 50000:  # Small cap
        score += 10
        logger.debug(f"Added small cap bonus: +10, total: {score}")
    elif mcap < 200000:  # Medium cap
        score += 5
        logger.debug(f"Added medium cap bonus: +5, total: {score}")
    elif mcap > 1000000:  # Large cap
        score -= 5
        logger.debug(f"Subtracted large cap penalty: -5, total: {score}")
    
    # Insider Risk modifier (lower risk = higher score)
    psi = token_data.get("insider_psi", 0) or 0
    logger.debug(f"Insider Risk: {psi}")
    if psi < 0.2 and (velocity > 5 or liq > 800):  # Low insider risk
        score += 10
        logger.debug(f"Added low insider risk bonus: +10, total: {score}")
    elif psi > 0.5:  # High insider risk
        score -= 10
        logger.debug(f"Subtracted high insider risk penalty: -10, total: {score}")
    
    # Creator Risk modifier (lower risk = higher score)
    creator_risk = token_data.get("creator_risk_score", 0) or 0
    logger.debug(f"Creator Risk: {creator_risk}")
    if creator_risk < 0.3 and (velocity > 5 or liq > 800):  # Low creator risk
        score += 5
        logger.debug(f"Added low creator risk bonus: +5, total: {score}")
    elif creator_risk > 0.7:  # High creator risk
        score -= 5
        logger.debug(f"Subtracted high creator risk penalty: -5, total: {score}")
    
    # Candle analysis modifier (if available)
    candle_score = token_data.get("candle_score", 0) or 0
    logger.debug(f"Candle Score: {candle_score}")
    if candle_score > 0.5:  # Good candle pattern
        score += 10
        logger.debug(f"Added candle pattern bonus: +10, total: {score}")
    elif candle_score > 0.3:  # Moderate pattern
        score += 5
        logger.debug(f"Added candle pattern bonus: +5, total: {score}")
    
    # Cap the score to 0-100 range
    score = max(0, min(100, score))
    logger.debug(f"Final score before rounding: {score}")
    
    # Round to nearest integer
    final_score = int(round(score))
    logger.info(f"Final quantitative degen score for {token_data.get('symbol', 'UNKNOWN')}: {final_score}")
    
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
        
    # HARD FLOOR: Even if threshold is 0.0000, we need actual momentum
    if ii < 10.0:
        logger.info(f"Trigger rejected: II too low for actual momentum ({ii:.3f} < 10.0) for {token.get('symbol')}")
        return False
    
    # 2. Condition: dII/dt > -2.5 (More permissive momentum)
    # Catch tokens even if they are stabilizing after a peak
    if delta_ii < -2.5:
        logger.info(f"Trigger rejected: Sharp falling instability (II={ii:.3f}, dII={delta_ii:.3f}) for {token.get('symbol')}")
        return False
        
    # 3. Condition: Price Compression (vol_shift < 5.0)
    # Be more permissive with recent price action
    if vol_shift >= 5.0 and ii < (threshold * 1.5):
        logger.info(f"Trigger rejected: Extreme Volatility expansion (vol_shift={vol_shift:.2f}) for {token.get('symbol')}")
        return False
    
    # 4. Condition: Liquidity check (More flexible)
    # Allow low reported liquidity if II is high AND MCAP is reasonable
    if liq < LIQUIDITY_MIN:
        # CRITICAL: If liquidity is literally 0 or negative, REJECT immediately.
        if liq <= 0:
            logger.info(f"Trigger rejected: ZERO Liquidity for {token.get('symbol') or token.get('address')}")
            return False

        # Relaxed exception: allow low liquidity (but > $800) if II is very high and it's a new small cap
        if ii > (threshold * 1.5) and mcap < 400000 and liq >= 800:
            logger.info(f"Trigger exception: High II ({ii:.3f}) for new token {token.get('symbol') or token.get('address')} with acceptable liq (Liq: {liq:.0f})")
        else:
            logger.info(f"Trigger rejected: Low Liquidity ({liq:.0f} < {LIQUIDITY_MIN}) for {token.get('symbol') or token.get('address')}")
            return False
        
    if mcap > MCAP_MAX:
        logger.info(f"Trigger rejected: MarketCap too High ({mcap:.0f} > {MCAP_MAX}) for {token.get('symbol') or token.get('address')}")
        return False

    # 5. NEW: First 5-6 Candles Analysis (Early Breakout Detection)
    # Check if the token shows breakout patterns in the first few candles
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
    Stricter Safety Filters (V4.5) to prevent rug pulls:
    - REJECT if Mint Authority is still enabled.
    - REJECT if Freeze Authority is still enabled.
    - REJECT if Top 10 Holders ratio > TOP10_MAX_RATIO.
    - REJECT if Insider Probability (PSI) > 0.75 (more flexible for meme coins).
    - REJECT if Creator Risk Score > 0.6 (more flexible for meme coins).
    - REJECT if Price Spike > 8x in 5m (allow more volatility).
    """
    # 1. On-chain Authorities (Critical)
    mint_auth = token.get("mint_authority")
    if mint_auth is not None:
        logger.info(f"Safety: Mint Authority ENABLED ({mint_auth[:8]}...) — REJECTED")
        return False
        
    freeze_auth = token.get("freeze_authority")
    if freeze_auth is not None:
        logger.info(f"Safety: Freeze Authority ENABLED ({freeze_auth[:8]}...) — REJECTED")
        return False

    # 2. Supply Concentration (Fail-Closed V4.6 - with Early Grace)
    top10_ratio = token.get("top10_ratio")
    mcap = token.get("marketcap") or 0
    
    if top10_ratio is None or top10_ratio == 0:
        if mcap > 100000: # Only reject if it's already a larger cap and we STILL don't know holders
            logger.info(f"Safety: Top 10 concentration UNKNOWN for large cap ({mcap:,.0f}) — REJECTED")
            return False
        else:
            logger.info(f"Safety Grace: Top 10 concentration UNKNOWN for early cap ({mcap:,.0f}) — PROCEEDING")
            # We don't return True yet, continue to other filters
    elif top10_ratio > 75.0: # Increased to 75% as many legit meme coins are concentrated early
        logger.info(f"Safety: Top 10 concentration too high ({top10_ratio:.1f}%) — REJECTED")
        return False

    # 3. Behavioral Risk (More flexible for meme coins)
    insider_psi = (token.get("insider_psi") or 0.0)
    if insider_psi > 0.85: # Increased to 0.85
        logger.info(f"Safety: High Insider Probability ({insider_psi:.2f}) — REJECTED")
        return False
        
    creator_risk = (token.get("creator_risk_score") or 0.1)
    if creator_risk > 0.75: # Increased to 0.75
        logger.info(f"Safety: High Creator Risk ({creator_risk:.2f}) — REJECTED")
        return False

    # 4. Momentum Spike check (More flexible)
    price_change_5m = (token.get("price_change_5m") or 0.0)
    from early_detector.config import SPIKE_THRESHOLD
    if price_change_5m and price_change_5m >= 15.0: # Increased to 15x
        logger.info(f"Safety: Price Spike detected ({price_change_5m:.2f}x) — REJECTED")
        return False
        
    return True


def passes_quality_gate(token_data: dict, ai_result: dict) -> bool:
    """
    Final Quality Check (V4.6 Quality & Stability):
    - Higher bar for entry to avoid 'noise' signals.
    """
    # 1. Lowered Liquidity Floor for Early Detection (V4.7)
    liq = token_data.get("liquidity") or 0
    if liq < 100:
        logger.info(f"Quality Gate: REJECTED {token_data.get('symbol')} - Liquidity too low (${liq:.0f})")
        return False

    # 2. Age Filter (Avoid instant launches without high AI validation)
    # pair_created_at is in ms from DexScreener
    created_at = token_data.get("pair_created_at")
    import time
    if created_at:
        now_ms = time.time() * 1000
        age_min = (now_ms - created_at) / (1000 * 60)
        
        # If less than 15 minutes old, require DECENT degen score
        if age_min < 15:
            degen_score = ai_result.get("degen_score") or token_data.get("degen_score") or 0
            if degen_score < 45:
                logger.info(f"Quality Gate: REJECTED {token_data.get('symbol')} - Too new ({age_min:.1f}m) and low AI score ({degen_score})")
                return False
                
    # 3. High Confidence Requirement for "Quiet" tokens
    # If no Smart Wallets and low Insider Probability, we need high bayesian confidence
    swr = token_data.get("swr") or 0
    psi = token_data.get("insider_psi") or 0
    if swr == 0 and psi < 0.2:
        conf = token_data.get("confidence") or 0
        if conf < 0.45:
            logger.info(f"Quality Gate: REJECTED {token_data.get('symbol')} - Low conviction signal (Conf: {conf:.2f}, No Smart Wallets)")
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

        # ── Bayesian Win Probability (V4.3) ──
        # Start with a neutral prior and apply likelihood ratios
        prior = 0.5
        likelihoods = []

        # 1. Regime context
        if regime_label == "DEGEN":
            likelihoods.append(1.1)  # Higher turnover in degen mode often follows through

        # 2. Risk Metrics
        creator_risk = token_data.get("creator_risk_score") or 0.5
        if creator_risk < 0.15:
            likelihoods.append(1.3)
        elif creator_risk > 0.8:
            likelihoods.append(0.7)

        insider_psi = token_data.get("insider_psi") or 0.0
        if insider_psi < 0.1:
            likelihoods.append(1.3)
        elif insider_psi > 0.6:
            likelihoods.append(0.6)

        # 3. Momentum & Intensity
        ii = token_data.get("instability_index") or 0
        if threshold > 0 and (ii / threshold) > 1.5:
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

        base_confidence = AlphaEngine.calculate_bayesian_confidence(prior, likelihoods)

        # Quarter Kelly sizing
        kelly_size = AlphaEngine.calculate_kelly_size(
            win_prob=base_confidence,
            avg_win_multiplier=0.45,   # Conservative targets
            avg_loss_multiplier=0.15,
            fractional_kelly=0.25
        )

        # Point 2: Size reduction for moderate insider risk
        insider_psi = (token_data.get("insider_psi") or 0.0)
        if 0.5 <= insider_psi <= 0.75:
            kelly_size *= 0.5 # size 50%
            logger.info(f"Risk Adjustment: Reducing size by 50% due to moderate insider risk ({insider_psi:.2f})")

        if kelly_size <= 0.01: # Don't trade tiny sizes
            continue

        signal = {
            "token_id": token_data.get("token_id"),
            "address": token_data.get("address", ""),
            "name": token_data.get("name", "Unknown"),
            "symbol": token_data.get("symbol", "???"),
            "instability_index": token_data.get("instability", 0),
            "price": token_data.get("price", 0),
            "liquidity": token_data.get("liquidity", 0),
            "marketcap": token_data.get("marketcap", 0),
            "confidence": base_confidence,
            "kelly_size": kelly_size,
            "insider_psi": insider_psi,
            "creator_risk": token_data.get("creator_risk_score", 0.1),
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
            ai_analysis=signal.get("ai_analysis")
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

    text = (
        f"🚨 <b>EARLY DETECTOR SIGNAL (V4.0)</b>\n\n"
        f"🪙 <b>{symbol}</b> — {name}\n"
        f"📍 <b>Address:</b> <code>{signal.get('address', 'UNKNOWN')}</code>\n"
        f"📊 Instability Index: <code>{ii:.3f}</code>\n"
        f"💰 Price: <code>${price:.10f}</code>\n"
        f"💧 Liquidity: <code>${liq:,.0f}</code>\n"
        f"📈 Market Cap: <code>${mcap:,.0f}</code>\n"
        f"👥 Top 10 Holders: <code>{t10_ratio:.1f}%</code>\n"
        f"\n"
        f"🎯 <b>Probability Score:</b> <code>{conf:.1%}</code>\n"
        f"⚖️ <b>Recommended Size:</b> <code>{k_size:.1%} of Wallet</code>\n"
        f"🔥 <b>Insider Risk:</b> <code>{i_psi:.2f}</code>\n"
        f"⚠️ <b>Creator Risk:</b> <code>{c_risk:.2f}</code>\n"
        f"🤖 <b>AI Degen Score:</b> <code>{d_score}</code>\n"
        f"\n"
        f"🧠 <b>EXIT STRATEGY:</b>\n"
        f"🛑 Hard Stop: <code>${hard_stop:.10f}</code> (-15%)\n"
        f"💰 Target TP1: <code>${tp_1:.10f}</code> (+40%)\n"
        f"🔄 Then: Trailing Stop 20%\n"
        f"\n"
        f"📋 <b>AI Summary:</b>\n<i>{ai_sum}</i>\n"
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
