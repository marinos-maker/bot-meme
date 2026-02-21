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
        # Relaxed exception: allow low liquidity if II is very high and it's a new small cap
        if ii > (threshold * 2.0) and mcap < 150000:
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

    # 2. Supply Concentration
    top10_ratio = (token.get("top10_ratio") or 0.0)
    from early_detector.config import TOP10_MAX_RATIO
    if top10_ratio > (TOP10_MAX_RATIO * 100): # config is likely 0.35, metrics might be 0-100 or 0-1
        # Let's check collector.py to see how top10_ratio is stored
        # After check, it's (top_sum / supply) * 100.0
        if top10_ratio > 35.0: # 35%
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


async def process_signals(scored_df, threshold: float, regime_label: str = "UNKNOWN") -> list[dict]:
    """
    Evaluate all scored tokens and generate signals for qualifying ones.
    Includes Position Sizing (Quarter Kelly).
    """
    signals = []

    for _, row in scored_df.iterrows():
        token_data = row.to_dict()

        if not passes_trigger(token_data, threshold):
            continue

        if not passes_safety_filters(token_data):
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
        }

        # ── Exit Strategy (V4.0) ──
        from early_detector.exits import ExitStrategy
        exit_levels = ExitStrategy.calculate_levels(signal["price"])
        signal["hard_stop"] = exit_levels.get("hard_stop")
        signal["tp_1"] = exit_levels.get("tp_1")

        # ── Quantitative Diary (V4.0) ──
        from early_detector.diary import log_trade_signal
        log_trade_signal(signal, regime_label)

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
            tp_1=signal["tp_1"]
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
