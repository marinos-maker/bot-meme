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


def passes_trigger(token: dict, threshold: float) -> bool:
    """
    Check if a token meets ALL trigger conditions (V4.1 - More permissive):
    - II > dynamic threshold
    - dII/dt > -0.5 (allow slight cooling or stability)
    - price compression (vol_shift < 2.0)
    - liquidity > LIQUIDITY_MIN
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
    
    # 2. Condition: dII/dt > -0.5 (Permissive Momentum) 
    # Catch tokens even if they are slightly stabilizing after a peak
    if delta_ii < -0.5:
        logger.info(f"Trigger rejected: Sharp falling instability (II={ii:.3f}, dII={delta_ii:.3f}) for {token.get('symbol')}")
        return False
        
    # 3. Condition: Price Compression (vol_shift < 2.0)
    # Be more permissive with recent price action
    if vol_shift >= 2.0 and ii < (threshold * 1.5):
        logger.info(f"Trigger rejected: Extreme Volatility expansion (vol_shift={vol_shift:.2f}) for {token.get('symbol')}")
        return False
    
    # 4. Condition: Liquidity check
    # V4.2 Exception: Allow low reported liquidity if II is high AND MCAP is reasonable
    # (Matches new Pump tokens where DexScreener reports 0 liq temporarily)
    if liq < LIQUIDITY_MIN:
        # CRITICAL V4.6: If liquidity is literally 0 or negative, REJECT immediately.
        # $0 liquidity tokens are untradable or already rugged.
        if liq <= 0:
            logger.info(f"Trigger rejected: ZERO Liquidity for {token.get('symbol') or token.get('address')}")
            return False

        # Relaxed exception: allow low liquidity (but > $100) if II is very high and it's a new small cap
        if ii > (threshold * 2.0) and mcap < 150000 and liq >= 100:
            logger.info(f"Trigger exception: High II ({ii:.3f}) for new low-liquidity token {token.get('symbol') or token.get('address')} (Liq: {liq:.0f})")
        else:
            logger.info(f"Trigger rejected: Low Liquidity ({liq:.0f} < {LIQUIDITY_MIN}) for {token.get('symbol') or token.get('address')}")
            return False
        
    if mcap > MCAP_MAX:
        logger.info(f"Trigger rejected: MarketCap too High ({mcap:.0f} > {MCAP_MAX}) for {token.get('symbol') or token.get('address')}")
        return False

    return True


def passes_safety_filters(token: dict) -> bool:
    """
    Stricter Safety Filters (V4.5) to prevent rug pulls:
    - REJECT if Mint Authority is still enabled.
    - REJECT if Freeze Authority is still enabled.
    - REJECT if Top 10 Holders ratio > TOP10_MAX_RATIO.
    - REJECT if Insider Probability (PSI) > 0.65 (down from 0.85).
    - REJECT if Creator Risk Score > 0.5 (down from 0.7).
    - REJECT if Price Spike > 5x in 5m.
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
    elif top10_ratio > 45.0: # Increased from 35% to 45% as many legit meme coins are concentrated early
        logger.info(f"Safety: Top 10 concentration too high ({top10_ratio:.1f}%) — REJECTED")
        return False

    # 3. Behavioral Risk
    insider_psi = (token.get("insider_psi") or 0.0)
    if insider_psi > 0.65:
        logger.info(f"Safety: High Insider Probability ({insider_psi:.2f}) — REJECTED")
        return False
        
    creator_risk = (token.get("creator_risk_score") or 0.1)
    if creator_risk > 0.5:
        logger.info(f"Safety: High Creator Risk ({creator_risk:.2f}) — REJECTED")
        return False

    # 4. Momentum Spike check
    price_change_5m = (token.get("price_change_5m") or 0.0)
    from early_detector.config import SPIKE_THRESHOLD
    if price_change_5m and price_change_5m >= SPIKE_THRESHOLD:
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
    if liq < 300:
        logger.info(f"Quality Gate: REJECTED {token_data.get('symbol')} - Liquidity too low (${liq:.0f})")
        return False

    # 2. Age Filter (Avoid instant launches without high AI validation)
    # pair_created_at is in ms from DexScreener
    created_at = token_data.get("pair_created_at")
    import time
    if created_at:
        now_ms = time.time() * 1000
        age_min = (now_ms - created_at) / (1000 * 60)
        
        # If less than 15 minutes old, require DECENT Ai degen score
        if age_min < 15:
            degen_score = ai_result.get("degen_score") or 0
            if degen_score < 65:
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

        # AI Analyst disabled by USER request
        signal["degen_score"] = None
        signal["ai_summary"] = "AI Analyst disabled"
        signal["ai_analysis"] = None
        
        # V4.6 Stability Quality Gate - modified to use empty ai_result
        if not passes_quality_gate(signal, {}):
             continue

        # Save to DB
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

        # Send notification
        await send_telegram_alert(signal)

        signals.append(signal)
        logger.info(
            f"🚨 SIGNAL: {signal['symbol']} ({signal['name']}) — "
            f"II={signal['instability_index']:.3f}, "
            f"Price={signal['price']}, MCap={signal['marketcap']:.0f}"
        )

    return signals


# ── Telegram Notifications ────────────────────────────────────────────────────

async def send_telegram_alert(signal: dict) -> None:
    """Send a signal alert to the configured Telegram chat."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — skipping alert")
        return

    text = (
        f"🚨 <b>EARLY DETECTOR SIGNAL (V4.0)</b>\n\n"
        f"🪙 <b>{signal['symbol']}</b> — {signal['name']}\n"
        f"📊 Instability Index: <code>{signal['instability_index']:.3f}</code>\n"
        f"💰 Price: <code>${signal['price']:.8f}</code>\n"
        f"💧 Liquidity: <code>${signal['liquidity']:,.0f}</code>\n"
        f"📈 Market Cap: <code>${signal['marketcap']:,.0f}</code>\n"
        f"\n"
        f"🎯 <b>Probability Score:</b> <code>{signal['confidence']:.1%}</code>\n"
        f"⚖️ <b>Recommended Size:</b> <code>{signal['kelly_size']:.1%} of Wallet</code>\n"
        f"🔥 <b>Insider Risk:</b> <code>{signal['insider_psi']:.2f}</code>\n"
        f"\n"
        f"🧠 <b>EXIT STRATEGY:</b>\n"
        f"🛑 Hard Stop: <code>${signal.get('hard_stop', 0):.8f}</code> (-15%)\n"
        f"💰 Target TP1: <code>${signal.get('tp_1', 0):.8f}</code> (+40%)\n"
        f"🔄 Then: Trailing Stop 20%\n"
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
