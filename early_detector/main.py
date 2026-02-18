"""
Main loop — async orchestrator for the Solana Early Detector.

Cycle (every 60 seconds):
  1. Discover new/active tokens
  2. Fetch metrics for each token
  3. Compute features
  4. Compute cross-sectional instability index
  5. Detect signals and send alerts
"""

import asyncio
import aiohttp
import numpy as np
import pandas as pd
from loguru import logger

from early_detector.config import SCAN_INTERVAL, LOG_FILE, LOG_ROTATION, LOG_LEVEL
from early_detector.collector import fetch_new_tokens, fetch_token_metrics
from early_detector.db import (
    get_pool, close_pool, upsert_token, insert_metrics,
    get_recent_metrics, get_smart_wallets, get_tracked_tokens, upsert_wallet,
)
from early_detector.features import compute_all_features
from early_detector.smart_wallets import compute_swr, cluster_wallets
from early_detector.scoring import compute_instability, get_signal_threshold
from early_detector.signals import process_signals
from early_detector.helius_client import fetch_token_swaps, compute_wallet_performance


# ── Logging Setup ─────────────────────────────────────────────────────────────
logger.add(LOG_FILE, rotation=LOG_ROTATION, level=LOG_LEVEL,
           format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")


async def scan_cycle(session: aiohttp.ClientSession,
                     smart_wallet_list: list[str]) -> None:
    """Execute one full scan cycle."""
    # 1. Discover tokens
    new_tokens = await fetch_new_tokens(session, limit=25)
    logger.info(f"Discovered {len(new_tokens)} tokens to scan")

    if not new_tokens:
        return

    features_rows = []

    for tok in new_tokens:
        address = tok["address"]

        # 2. Upsert token in DB
        token_id = await upsert_token(address, tok.get("name"), tok.get("symbol"))

        # 3. Fetch current metrics
        metrics = await fetch_token_metrics(session, address)
        if metrics is None:
            continue

        # 4. Get historical data for feature computation
        history = await get_recent_metrics(token_id, minutes=30)

        # Extract holder timeline for acceleration
        holders_series = [(r.get("holders") or 0) for r in history]
        h_t = metrics.get("holders") or 0
        h_t10 = holders_series[min(10, len(holders_series)-1)] if len(holders_series) > 1 else h_t
        h_t20 = holders_series[min(20, len(holders_series)-1)] if len(holders_series) > 2 else h_t10

        # Price series for volatility
        price_history = [(r.get("price") or 0) for r in history if r.get("price")]
        current_price = metrics.get("price") or 0
        price_20m = np.array(price_history[:20]) if len(price_history) >= 2 else np.array([current_price])
        price_5m = np.array(price_history[:5]) if len(price_history) >= 2 else np.array([current_price])

        # Accumulation stats from history
        buys_20m = sum((r.get("buys_5m") or 0) for r in history[:4])
        sells_20m = sum((r.get("sells_5m") or 0) for r in history[:4])
        unique_buyers = buys_20m  # approximation (exact count requires tx-level data)

        # Smart Wallet Rotation
        swr = compute_swr(
            active_wallets=[],  # placeholder — requires on-chain tx data
            smart_wallet_list=smart_wallet_list,
            global_active_smart=len(smart_wallet_list),
        )

        # 5. Compute features
        features = compute_all_features(
            h_t=h_t, h_t10=h_t10, h_t20=h_t20,
            unique_buyers=unique_buyers,
            sells_20m=sells_20m, buys_20m=buys_20m,
            price_series_20m=price_20m,
            price_series_5m=price_5m,
            sells_5m=metrics.get("sells_5m", 0) or 0,
            buys_5m=metrics.get("buys_5m", 0) or 0,
            swr=swr,
        )

        # Add metadata
        features["token_id"] = token_id
        features["address"] = address
        features["name"] = tok.get("name", "Unknown")
        features["symbol"] = tok.get("symbol", "???")
        features["price"] = current_price
        features["liquidity"] = metrics.get("liquidity") or 0
        features["marketcap"] = metrics.get("marketcap") or 0
        features["top10_ratio"] = metrics.get("top10_ratio")

        features_rows.append(features)

        # Save metrics to timeseries
        metrics["instability_index"] = None  # set after scoring
        metrics["smart_wallets_active"] = 0
        await insert_metrics(token_id, metrics)

    if not features_rows:
        logger.debug("No features computed this cycle")
        return

    # 6. Cross-sectional scoring
    feat_df = pd.DataFrame(features_rows)
    scored_df = compute_instability(feat_df)

    # 7. Signal detection
    threshold = get_signal_threshold(scored_df["instability"])
    signals = await process_signals(scored_df, threshold)

    if signals:
        logger.info(f"🚨 {len(signals)} signal(s) generated this cycle!")
    else:
        logger.debug("No signals this cycle")


async def run() -> None:
    """Main entry point — runs the scan loop indefinitely."""
    logger.info("=" * 60)
    logger.info("🚀 Solana Early Detector starting…")
    logger.info("=" * 60)

    # Ensure DB pool is ready
    await get_pool()

    # Load smart wallet list
    smart_wallet_list = await get_smart_wallets()
    logger.info(f"Loaded {len(smart_wallet_list)} smart wallets from DB")

    try:
        async with aiohttp.ClientSession() as session:
            cycle = 0
            while True:
                cycle += 1
                logger.info(f"── Cycle {cycle} ─────────────────────────────")
                try:
                    await scan_cycle(session, smart_wallet_list)
                except Exception as e:
                    logger.error(f"Cycle {cycle} error: {e}")

                # Update wallet profiles and refresh smart wallets every 10 cycles (~20 min)
                if cycle % 10 == 0:
                    try:
                        await update_wallet_profiles(session)
                    except Exception as e:
                        logger.error(f"Wallet profile update error: {e}")
                    smart_wallet_list = await get_smart_wallets()
                    logger.info(f"Refreshed smart wallet list: {len(smart_wallet_list)}")

                await asyncio.sleep(SCAN_INTERVAL)
    finally:
        await close_pool()
        logger.info("Detector stopped.")


async def update_wallet_profiles(session: aiohttp.ClientSession) -> None:
    """Fetch recent swaps for tracked tokens and update wallet_performance."""
    logger.info("Updating wallet profiles from on-chain data...")

    token_addrs = await get_tracked_tokens(limit=15)
    if not token_addrs:
        logger.debug("No tracked tokens for wallet profiling")
        return

    all_trades = []
    for addr in token_addrs:
        trades = await fetch_token_swaps(session, addr, limit=50)
        all_trades.extend(trades)
        await asyncio.sleep(0.2)

    if not all_trades:
        logger.debug("No trades collected for wallet profiling")
        return

    wallet_stats = compute_wallet_performance(all_trades)
    if not wallet_stats:
        return

    # Cluster wallets
    stats_df = pd.DataFrame.from_dict(wallet_stats, orient="index")
    stats_df.index.name = "wallet"
    clustered = cluster_wallets(stats_df)

    # Save to DB
    saved = 0
    for wallet_addr in clustered.index:
        row = clustered.loc[wallet_addr]
        await upsert_wallet(wallet_addr, {
            "avg_roi": float(row["avg_roi"]),
            "total_trades": int(row["total_trades"]),
            "win_rate": float(row["win_rate"]),
            "cluster_label": row.get("cluster_label", "unknown"),
        })
        saved += 1

    logger.info(f"Updated {saved} wallet profiles")


if __name__ == "__main__":
    asyncio.run(run())
