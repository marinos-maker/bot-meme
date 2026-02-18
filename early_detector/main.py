
"""
Main loop — async orchestrator for the Solana Early Detector.

Architecture (v3.0):
  - Producer: 'discovery_worker' finds new tokens and pushes to Queue.
  - Consumers: 'processor_workers' (x5) pull tokens, fetch metrics, computed features/scores.
  - Periodic: 'cleanup_worker' (optional) or just reliant on DB.
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
from early_detector.smart_wallets import compute_swr, cluster_wallets, compute_insider_score
from early_detector.scoring import compute_instability, get_signal_threshold
from early_detector.signals import process_signals
from early_detector.helius_client import fetch_token_swaps, compute_wallet_performance
from early_detector.narrative import NarrativeManager

# ── Logging Setup ─────────────────────────────────────────────────────────────
logger.add(LOG_FILE, rotation=LOG_ROTATION, level=LOG_LEVEL,
           format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

# ── Global State ──────────────────────────────────────────────────────────────
token_queue: asyncio.Queue = asyncio.Queue()
smart_wallet_list: list[str] = []


async def discovery_worker(session: aiohttp.ClientSession) -> None:
    """Producer: Finds new tokens and pushes them to the queue."""
    logger.info("🕵️ Discovery worker started")
    while True:
        try:
            # 1. Discover tokens
            new_tokens = await fetch_new_tokens(session, limit=25)
            if new_tokens:
                logger.info(f"Discovered {len(new_tokens)} tokens")
                # Push the whole batch for Cross-Sectional Scoring
                await token_queue.put(new_tokens)
            
            # Also re-scan recently active tokens? 
            # For this simple version, we mainly trust `fetch_new_tokens` (Birdeye new listings)
            # In a pro version, we'd also query DB for "active but not signaled" tokens to re-check.
            
        except Exception as e:
            logger.error(f"Discovery error: {e}")
        
        await asyncio.sleep(SCAN_INTERVAL)


async def processor_worker(worker_id: int, session: aiohttp.ClientSession) -> None:
    """Consumer: Processes tokens from the queue."""
    logger.info(f"⚙️ Processor-{worker_id} started")
    while True:
        try:
            # Block until a token is available
            tok = await token_queue.get()
            
            address = tok["address"]
            name = tok.get("name")
            symbol = tok.get("symbol")
            
            # Process the token
            await process_single_token(session, address, name, symbol)
            
            # Rate limit politeness per worker
            await asyncio.sleep(0.5)
            
            token_queue.task_done()
            
        except Exception as e:
            logger.error(f"Processor-{worker_id} error: {e}")
            # Ensure task_done is called even on error to prevent queue join hanging (if we used join)
            try:
                token_queue.task_done()
            except ValueError:
                pass


async def process_single_token(session: aiohttp.ClientSession, 
                               address: str, name: str, symbol: str) -> None:
    """Core logic for a single token: fetch -> feature -> score -> signal."""
    
    # 2. Upsert token in DB
    token_id = await upsert_token(address, name, symbol)

    # 3. Fetch current metrics
    metrics = await fetch_token_metrics(session, address)
    if metrics is None:
        return

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
    
    # Use real unique buyers if available
    unique_buyers_real = metrics.get("unique_buyers_50tx", 0)
    unique_buyers = unique_buyers_real if unique_buyers_real > 0 else buys_20m

    # Smart Wallet Rotation (SWR)
    # Note: accessing global smart_wallet_list
    swr = compute_swr(
        active_wallets=[],
        smart_wallet_list=smart_wallet_list,
        global_active_smart=len(smart_wallet_list),
    )

    # ── Insider Probability Calculation ───────────────────────────────────
    buyers_data = metrics.get("buyers_data", [])
    pair_created_at = metrics.get("pair_created_at")
    
    insider_scores = []
    if buyers_data and pair_created_at:
        for b in buyers_data:
            s = compute_insider_score({}, b["first_trade_time"], pair_created_at)
            insider_scores.append(s)
    
    token_insider_psi = max(insider_scores) if insider_scores else 0.0

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

    # 6. Scoring (Single Token) - Adapted from cross-sectional
    # We create a 1-row DataFrame to reuse the scoring logic
    f_row = features.copy()
    f_row["token_id"] = token_id
    f_row["address"] = address
    f_row["name"] = name or "Unknown"
    f_row["symbol"] = symbol or "???"
    f_row["price"] = current_price
    f_row["liquidity"] = metrics.get("liquidity") or 0
    f_row["marketcap"] = metrics.get("marketcap") or 0
    f_row["top10_ratio"] = metrics.get("top10_ratio")
    f_row["insider_psi"] = token_insider_psi
    f_row["creator_risk_score"] = metrics.get("creator_risk_score")
    
    # Momentum: last II
    last_ii = 0.0
    for r in history:
        if r.get("instability_index") is not None:
            last_ii = float(r["instability_index"])
            break
    f_row["last_instability"] = last_ii

    # Compute II
    # Note: Z-scores in `compute_instability` are designed for a BATCH (cross-sectional).
    # Running on a SINGLE token makes Z-score = NaN (std dev of 1 item is 0).
    # 
    # CRITICAL FIX for v3:
    # We must either:
    # A) Accumulate a batch in the consumer before scoring.
    # B) Use fixed reference stats (mean/std from historical db) for Z-score.
    # 
    # For this iteration, let's use a "Rolling Batch" approach or simply skip Z-scoring 
    # and just use raw weighted features if we can't batch.
    # 
    # Better approach: The `processor_worker` should act on batches or we pass a batch to `compute_instability`.
    # But since we are processing 1 by 1... 
    # 
    # Let's apply a "Global Reference" hack:
    # Assume we know approx mean/std of features from normal market conditions.
    # OR: just return the raw score for now and let the system evolve.
    #
    # To keep it simple and robust: We will create a fake "reference batch" using the history of THIS token 
    # plus robust defaults, or we revert to a simpler score for the single-mode.
    #
    # DECISION: We will modify `compute_instability` to handle single-row gracefully 
    # by assuming standard deviations if they are 0.
    # However, `zscore` of a single value 5 is (5-5)/0 = NaN.
    #
    # Workaround: We will fetch the previous batch's stats from DB? Too complex.
    # 
    # FAST FIX: passing a synthetic batch of "average meme coins" to normalize against?
    # NO. 
    # 
    # Let's modify `compute_instability` to use provided stats if available, 
    # or just accept that Z-scores are 0 for a single item (which breaks the model).
    #
    # ACTUALLY: The original `scan_cycle` processed a batch of 25 tokens. 
    # The Queue processes 1 by 1. This BREAKS the Cross-Sectional Z-Score model.
    # 
    # To fix this properly for v3 Asynchronous:
    # We need to buffer accumulated tokens and process them in mini-batches.
    
    # Buffer implementation inside processor? No.
    # Let's make the `discovery_worker` push *batches* or have a `batch_processor`.
    
    # Let's keep `scan_cycle` logic but run it in a worker? 
    # No, that defeats the purpose of queue.
    # 
    # Let's use PRE-CALCULATED global stats (mean/std) for Z-scores.
    # Since I don't have them, I will use a simple workaround:
    # Compare against the token's own history? No.
    #
    # Okay, I will implement a miniature "accumulator" in the worker.
    # It waits for 5 items or 5 seconds, then processes.
    pass

    # Since I cannot easily rewrite the Math for Single-Item Z-Score in this step without new config,
    # I will revert the "Queue" plan to a "Parallel Batch Scanners" plan?
    # Or simply gather a batch in the worker. 
    
    # Let's stick to processing, but since `compute_instability` expects a DataFrame,
    # I will create a DataFrame with 1 row and dummy rows to simulate a distribution? 
    # No, that's messy.
    #
    # I will manually compute the score using FIXED weights on RAW values for now, 
    # bypassing the Z-score relative nature.
    # `II = 2*SA + ...` -> `II = 2 * (SA - mean)/std`.
    # I'll treat mean=0, std=1 for raw normalized inputs (heuristic).
    #
    # Actually, `fetch_new_tokens` returns ~50 tokens. 
    # `discovery_worker` can just process them in a batch!
    # The queue can hold *batches* of tokens, not single tokens.
    # 
    # REVISED PLAN: `token_queue` holds Lists of Tokens (batches).
    # `processor_worker` takes a LIST, processes them in parallel (fetching), then scores the BATCH.
    
    # This preserves the Cross-Sectional Math!
    pass


async def processor_worker_batch(worker_id: int, session: aiohttp.ClientSession) -> None:
    """Consumer: Processes BATCHES of tokens to preserve Cross-Sectional Scoring."""
    logger.info(f"⚙️ Processor-{worker_id} started")
    while True:
        try:
            # Get a batch (list of dicts)
            token_batch = await token_queue.get()
            
            features_rows = []
            
            # Fetch details for all in parallel
            # We can use asyncio.gather for the batch
            tasks = [process_token_to_features(session, t) for t in token_batch]
            results = await asyncio.gather(*tasks)
            
            for res in results:
                if res:
                    features_rows.append(res)
            
            if features_rows:
                # Score the batch
                feat_df = pd.DataFrame(features_rows)
                scored_df = compute_instability(feat_df)
                
                # Signal logic
                # Calculate delta_instability
                if "last_instability" in scored_df.columns:
                    scored_df["delta_instability"] = scored_df["instability"] - scored_df["last_instability"]
                else:
                    scored_df["delta_instability"] = 0.0

                threshold = get_signal_threshold(scored_df["instability"])
                signals = await process_signals(scored_df, threshold)
                if signals:
                    logger.info(f"🚨 Worker-{worker_id} generated {len(signals)} signals")

            token_queue.task_done()
            
        except Exception as e:
            logger.error(f"Worker-{worker_id} error: {e}")
            try:
                token_queue.task_done()
            except:
                pass


async def process_token_to_features(session, tok) -> dict | None:
    """Fetch metrics and compute features for a single token. Returns feature dict."""
    try:
        address = tok["address"]
        name = tok.get("name", "Unknown")
        symbol = tok.get("symbol", "???")
        
        # Phase 11: Narrative Classification
        narrative = NarrativeManager.classify(name, symbol)
        token_id = await upsert_token(address, name, symbol, narrative=narrative)
        
        metrics = await fetch_token_metrics(session, address)
        if metrics is None:
            return None

        # History
        history = await get_recent_metrics(token_id, minutes=30)
        
        # ... (Same logic as original scan_cycle)
        # Re-implementing feature extraction briefly for compactness
        holders_series = [(r.get("holders") or 0) for r in history]
        h_t = metrics.get("holders") or 0
        h_t10 = holders_series[min(10, len(holders_series)-1)] if len(holders_series) > 1 else h_t
        h_t20 = holders_series[min(20, len(holders_series)-1)] if len(holders_series) > 2 else h_t10

        price_history = [(r.get("price") or 0) for r in history if r.get("price")]
        current_price = metrics.get("price") or 0
        price_20m = np.array(price_history[:20]) if len(price_history) >= 2 else np.array([current_price])
        price_5m = np.array(price_history[:5]) if len(price_history) >= 2 else np.array([current_price])

        buys_20m = sum((r.get("buys_5m") or 0) for r in history[:4])
        sells_20m = sum((r.get("sells_5m") or 0) for r in history[:4])
        unique_buyers_real = metrics.get("unique_buyers_50tx", 0)
        unique_buyers = unique_buyers_real if unique_buyers_real > 0 else buys_20m

        swr = compute_swr([], smart_wallet_list, len(smart_wallet_list))

        # Insider & Advanced Volume Features
        buyers_data = metrics.get("buyers_data", [])
        pair_created_at = metrics.get("pair_created_at")
        
        # Phase 2 Cleanup: Detect Coordinated Entry
        from early_detector.smart_wallets import detect_coordinated_entry
        coordinated_wallets = detect_coordinated_entry(buyers_data)
        
        insider_scores = []
        buyers_volumes = []
        
        if buyers_data:
            for b in buyers_data:
                # Insider Score
                if pair_created_at:
                    is_coordinated = b["wallet"] in coordinated_wallets
                    s = compute_insider_score({}, b["first_trade_time"], 
                                              pair_created_at, is_coordinated=is_coordinated)
                    insider_scores.append(s)
                
                # Volume for HHI
                buyers_volumes.append(b.get("volume", 0))

        token_insider_psi = max(insider_scores) if insider_scores else 0.0

        # Liquidity Series for Acceleration
        liquidity_series = np.array([(r.get("liquidity") or 0) for r in history])
        if len(liquidity_series) < 2:
            liquidity_series = np.array([metrics.get("liquidity") or 0])

        features = compute_all_features(
            h_t=h_t, h_t10=h_t10, h_t20=h_t20, unique_buyers=unique_buyers,
            sells_20m=sells_20m, buys_20m=buys_20m, price_series_20m=price_20m,
            price_series_5m=price_5m, sells_5m=metrics.get("sells_5m", 0) or 0,
            buys_5m=metrics.get("buys_5m", 0) or 0, 
            liquidity_series=liquidity_series,
            buyers_volumes=buyers_volumes,
            swr=swr,
        )

        features["token_id"] = token_id
        features["address"] = address
        features["name"] = tok.get("name", "Unknown")
        features["symbol"] = tok.get("symbol", "???")
        features["price"] = current_price
        features["liquidity"] = metrics.get("liquidity") or 0
        features["marketcap"] = metrics.get("marketcap") or 0
        features["top10_ratio"] = metrics.get("top10_ratio")
        features["insider_psi"] = token_insider_psi
        features["creator_risk_score"] = metrics.get("creator_risk_score")
        
        last_ii = 0.0
        for r in history:
            if r.get("instability_index") is not None:
                last_ii = float(r["instability_index"])
                break
        features["last_instability"] = last_ii
        
        # Save metrics
        metrics["instability_index"] = None
        metrics["smart_wallets_active"] = 0
        metrics["insider_psi"] = token_insider_psi
        metrics["creator_risk_score"] = features["creator_risk_score"]
        await insert_metrics(token_id, metrics)
        
        return features

    except Exception as e:
        logger.error(f"Error processing {tok.get('address')}: {e}")
        return None


async def update_wallet_profiles_job(session):
    """Periodic job to update wallet profiles."""
    global smart_wallet_list
    while True:
        await asyncio.sleep(600) # every 10 min
        logger.info("Updating wallet profiles...")
        try:
             await update_wallet_profiles(session)
             smart_wallet_list = await get_smart_wallets()
             logger.info(f"Refreshed smart wallet list: {len(smart_wallet_list)}")
        except Exception as e:
            logger.error(f"Wallet update error: {e}")


async def update_wallet_profiles(session: aiohttp.ClientSession) -> None:
    """
    Update/upsert profile stats for all smart wallets.
    """
    logger.info("Updating wallet profiles...")
    for wallet in smart_wallet_list:
        try:
            perf = await compute_wallet_performance(session, wallet)
            if perf:
                await upsert_wallet(wallet, perf)
        except Exception as e:
            logger.error(f"Error updating wallet {wallet}: {e}")
            
    # Re-cluster (optional / expensive)
    # await cluster_wallets()

async def run() -> None:
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("🚀 Solana Early Detector v3.0 (Async Architecture) starting…")
    logger.info("=" * 60)

    global smart_wallet_list
    await get_pool()
    smart_wallet_list = await get_smart_wallets()
    logger.info(f"Loaded {len(smart_wallet_list)} smart wallets")

    async with aiohttp.ClientSession() as session:
        # Start Workers
        producers = [asyncio.create_task(discovery_worker(session))]
        consumers = [asyncio.create_task(processor_worker_batch(i, session)) for i in range(3)]
        cron_jobs = [asyncio.create_task(update_wallet_profiles_job(session))]
        
        await asyncio.gather(*producers, *consumers, *cron_jobs)



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
