"""
TP/SL Monitor — Watches open positions and auto-sells on TP or SL triggers.
"""

import asyncio
import aiohttp
from loguru import logger

from early_detector.db import get_open_trades, close_trade
from early_detector.trader import execute_sell
from early_detector.collector import fetch_dexscreener_pair


CHECK_INTERVAL = 10  # seconds between price checks


async def tp_sl_worker(session: aiohttp.ClientSession) -> None:
    """
    Background worker: checks open positions every 10s.
    If price hits TP → auto sell. If price hits SL → auto sell.
    """
    logger.info("📊 TP/SL Monitor started")
    
    while True:
        try:
            open_trades = await get_open_trades()
            
            if not open_trades:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            for trade in open_trades:
                trade_id = trade["id"]
                token_address = trade["token_address"]
                entry_price = float(trade["price_entry"] or 0)
                tp_pct = float(trade["tp_pct"] or 50)
                sl_pct = float(trade["sl_pct"] or 30)

                if entry_price <= 0:
                    continue

                # Get current price from DexScreener
                metrics = await fetch_dexscreener_pair(session, token_address)
                if not metrics or not metrics.get("price"):
                    continue

                current_price = float(metrics["price"])
                roi_pct = ((current_price - entry_price) / entry_price) * 100

                # Update ROI in DB
                await update_trade_roi(trade_id, roi_pct, current_price)

                # Check TP
                if roi_pct >= tp_pct:
                    logger.info(f"🎯 TP HIT! {token_address[:8]}... ROI: {roi_pct:+.1f}% (target: +{tp_pct}%)")
                    result = await execute_sell(session, token_address)
                    if result["success"]:
                        await close_trade(trade_id, "TP_HIT", current_price, roi_pct, result.get("tx_hash", ""))
                        logger.info(f"✅ TP sell executed for {token_address[:8]}...")
                    else:
                        error_msg = result.get('error')
                        logger.warning(f"⚠️ TP sell failed: {error_msg}")
                        if result.get("reason") == "ZERO_BALANCE":
                            logger.info(f"🧹 Closing trade {trade_id} as MANUAL_CLOSE (no tokens found in wallet)")
                            await close_trade(trade_id, "MANUAL_CLOSE", current_price, roi_pct, "N/A")

                # Check SL
                elif roi_pct <= -sl_pct:
                    logger.info(f"🛑 SL HIT! {token_address[:8]}... ROI: {roi_pct:+.1f}% (limit: -{sl_pct}%)")
                    result = await execute_sell(session, token_address)
                    if result["success"]:
                        await close_trade(trade_id, "SL_HIT", current_price, roi_pct, result.get("tx_hash", ""))
                        logger.info(f"✅ SL sell executed for {token_address[:8]}...")
                    else:
                        error_msg = result.get('error')
                        logger.warning(f"⚠️ SL sell failed: {error_msg}")
                        if result.get("reason") == "ZERO_BALANCE":
                            logger.info(f"🧹 Closing trade {trade_id} as MANUAL_CLOSE (no tokens found in wallet)")
                            await close_trade(trade_id, "MANUAL_CLOSE", current_price, roi_pct, "N/A")

        except Exception as e:
            logger.error(f"TP/SL monitor error: {e}")
        
        await asyncio.sleep(CHECK_INTERVAL)


async def update_trade_roi(trade_id: int, roi_pct: float, current_price: float) -> None:
    """Update the real-time ROI of an open trade."""
    from early_detector.db import get_pool
    pool = await get_pool()
    await pool.execute(
        "UPDATE trades SET roi_pct = $1 WHERE id = $2",
        roi_pct, trade_id
    )
