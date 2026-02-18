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
from early_detector.db import insert_signal


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

    if ii <= threshold:
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
    - Top 5 holders > 40%
    - Dev wallet active in last 10 min (placeholder — requires on-chain data)
    - Sudden 3x spike in 5 min (too late)
    """
    top10 = token.get("top10_ratio")
    if top10 is not None and top10 > MAX_TOP5_HOLDER_RATIO:
        logger.debug(f"Safety: holder concentration too high ({top10:.1%})")
        return False

    # Spike check: if price moved 3x+ in 5 min, we're late
    price_change_5m = token.get("price_change_5m", 0)
    if price_change_5m and price_change_5m >= SPIKE_THRESHOLD:
        logger.debug(f"Safety: price spike {price_change_5m:.1f}x in 5m — too late")
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

        signal = {
            "token_id": token_data.get("token_id"),
            "address": token_data.get("address", ""),
            "name": token_data.get("name", "Unknown"),
            "symbol": token_data.get("symbol", "???"),
            "instability_index": token_data.get("instability", 0),
            "price": token_data.get("price", 0),
            "liquidity": token_data.get("liquidity", 0),
            "marketcap": token_data.get("marketcap", 0),
        }

        # Save to DB
        await insert_signal(
            token_id=signal["token_id"],
            instability_index=signal["instability_index"],
            entry_price=signal["price"],
            liquidity=signal["liquidity"],
            marketcap=signal["marketcap"],
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
