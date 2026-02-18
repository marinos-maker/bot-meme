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
    Check if a token meets ALL trigger conditions:
    - instability_index > dynamic threshold (percentile 95)
    - liquidity > 40k
    - marketcap < 3M
    - top10 holder ratio < 35%
    """
    ii = token.get("instability", 0)
    liq = token.get("liquidity", 0) or 0
    mcap = token.get("marketcap", float("inf")) or float("inf")
    top10 = token.get("top10_ratio")
    
    delta_ii = token.get("delta_instability", 0)

    if ii <= threshold:
        return False
    
    # Momentum Check: Only trigger if instability is RISING
    if delta_ii <= 0:
        logger.debug(f"Trigger rejected: Falling instability (dII={delta_ii:.3f})")
        return False

    if liq < LIQUIDITY_MIN:
        return False
    if mcap > MCAP_MAX:
        return False
    if top10 is not None and top10 > TOP10_MAX_RATIO:
        return False

    return True


def passes_safety_filters(token: dict) -> bool:
    """
    Safety filters — reject token if:
    - High Insider Probability (> 0.8)
    - Top 5 holders > 40%
    - Dev wallet active in last 10 min (placeholder — requires on-chain data)
    - Sudden 3x spike in 5 min (too late)
    """
    # Insider Risk Check
    insider_psi = token.get("insider_psi", 0.0)
    if insider_psi > 0.8:
        logger.info(f"Safety: High Insider Probability ({insider_psi:.2f}) — REJECTED")
        return False
        
    # Creator Risk Check
    creator_risk = token.get("creator_risk_score", 0.5)
    if creator_risk > 0.4:
        logger.info(f"Safety: High Creator Risk ({creator_risk:.2f}) — REJECTED")
        return False

    top10 = token.get("top10_ratio")
    if top10 is not None and top10 > MAX_TOP5_HOLDER_RATIO:
        logger.debug(f"Safety: holder concentration too high ({top10:.1%})")
        return False

    # Spike check: if price moved 3x+ in 5 min, we're late
    price_change_5m = token.get("price_change_5m", 0)
    if price_change_5m and price_change_5m >= SPIKE_THRESHOLD:
        logger.debug(f"Safety: price spike {price_change_5m:.1f}x in 5m — too late")
        return False
        
    # Security: Mint Authority & Freeze Authority
    # If these keys exist and are NOT None, it means the authority is enabled (risk of rug/freeze)
    mint_auth = token.get("mint_authority")
    freeze_auth = token.get("freeze_authority")
    
    if mint_auth:
        logger.debug(f"Safety: Mint Authority enabled ({mint_auth})")
        return False
        
    if freeze_auth:
        logger.debug(f"Safety: Freeze Authority enabled ({freeze_auth})")
        return False

    return True


async def process_signals(scored_df, threshold: float) -> list[dict]:
    """
    Evaluate all scored tokens and generate signals for qualifying ones.

    Returns list of signal dicts for further processing.
    """
    signals = []

    for _, row in scored_df.iterrows():
        token_data = row.to_dict()

        if not passes_trigger(token_data, threshold):
            continue

        if not passes_safety_filters(token_data):
            continue

        # Prevent duplicate signals if one was already sent recently (e.g. 60m)
        token_id = str(token_data.get("token_id"))
        if await has_recent_signal(token_id, minutes=60):
            continue

        # ── Alpha Optimization (Phase 10) ──
        # Calculate Bayesian Confidence
        # Base prior from II (e.g. 0.3-0.7 scale)
        prior = np.clip(token_data.get("instability", 0) / 5.0, 0.3, 0.7)
        
        # Likelihoods based on security and momentum
        likelihoods = []
        if token_data.get("creator_risk_score", 0.5) < 0.2: likelihoods.append(1.5)
        if token_data.get("insider_psi", 0.0) < 0.1: likelihoods.append(1.3)
        if token_data.get("accel_liq", 0) > 0: likelihoods.append(1.2)
        
        confidence = AlphaEngine.calculate_bayesian_confidence(prior, likelihoods)
        
        # Calculate Kelly Size (assuming 2.0x avg win, 0.25 fractional kelly)
        kelly_size = AlphaEngine.calculate_kelly_size(
            win_prob=confidence, 
            avg_win_multiplier=2.0, 
            fractional_kelly=0.25
        )

        signal = {
            "token_id": token_data.get("token_id"),
            "address": token_data.get("address", ""),
            "name": token_data.get("name", "Unknown"),
            "symbol": token_data.get("symbol", "???"),
            "instability_index": token_data.get("instability", 0),
            "price": token_data.get("price", 0),
            "liquidity": token_data.get("liquidity", 0),
            "marketcap": token_data.get("marketcap", 0),
            "confidence": confidence,
            "kelly_size": kelly_size,
            "insider_psi": token_data.get("insider_psi", 0.0),
            "creator_risk": token_data.get("creator_risk_score", 0.0),
        }

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
        f"🚨 <b>EARLY DETECTOR SIGNAL</b>\n\n"
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
