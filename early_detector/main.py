
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

from early_detector.config import SCAN_INTERVAL, LOG_FILE, LOG_ROTATION, LOG_LEVEL, AUTO_TRADE_ENABLED, TRADE_AMOUNT_SOL, DEFAULT_TP_PCT, DEFAULT_SL_PCT, SLIPPAGE_BPS
from early_detector.collector import fetch_token_metrics
from early_detector.db import (
    get_pool, close_pool, upsert_token, insert_metrics,
    get_recent_metrics, get_smart_wallets, get_tracked_tokens, upsert_wallet,
    get_unprocessed_tokens, insert_trade,
)
from early_detector.features import compute_all_features
from early_detector.smart_wallets import compute_swr, cluster_wallets, compute_insider_score
from early_detector.scoring import compute_instability, get_signal_threshold, detect_regime
from early_detector.signals import process_signals
from early_detector.narrative import NarrativeManager
from early_detector.trader import execute_buy
from early_detector.tp_sl_monitor import tp_sl_worker
from early_detector.pumpportal import pumpportal_worker
from early_detector.creator_monitor import creator_performance_job

# ── Logging Setup ─────────────────────────────────────────────────────────────
logger.add(LOG_FILE, rotation=LOG_ROTATION, level=LOG_LEVEL,
           format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

# ── Global State ──────────────────────────────────────────────────────────────
token_queue: asyncio.Queue = asyncio.Queue()
smart_wallet_list: list[str] = []

# Fallback experts to ensure SWR works even on cold start
EXPERT_SEED_WALLETS = [
    "3UHUXhT3a5KcebcrsNqrKDBar8Xf6fjkBiMvpAarEHtR",
    "35eovnQrLjTAjXVxXD1himGNfsx1D5LZmNGAnFHGtnhX",
    "2uNRrZ2SAMHtW9UFL8Dtf2pMnt1T3pwnDEsiGN6KzAaZ",
    "rWZaju2cGkcTQLGT79Vg3TyfsSZSGkRKTrqAu5szmTs",
    "2c5L6znNQjuTbZssZgkTqEmqga3zde7pKDwkEsdYbETd"
]


async def discovery_worker(session: aiohttp.ClientSession) -> None:
    """Producer: Finds new tokens and pushes them to the queue."""
    logger.info("🕵️ Discovery worker started (PumpPortal mode)")
    seen_addrs = set()
    last_clear = asyncio.get_event_loop().time()
    
    while True:
        try:
            batch = []
            
            # Periodically clear seen_addrs every 2 hours
            if asyncio.get_event_loop().time() - last_clear > 7200:
                seen_addrs.clear()
                last_clear = asyncio.get_event_loop().time()
                logger.debug("Cleared seen_addrs cache in discovery_worker")

            # 1. Pick up tokens discovered by PumpPortal that have NO metrics yet
            unprocessed = await get_unprocessed_tokens(limit=50)
            if unprocessed:
                for addr in unprocessed:
                    if addr not in seen_addrs:
                        batch.append({"address": addr})
                        seen_addrs.add(addr)

            # 2. Re-scan recently tracked tokens to keep data fresh
            tracked_addrs = await get_tracked_tokens(limit=100)
            if tracked_addrs:
                for addr in tracked_addrs:
                    if addr not in seen_addrs:
                        batch.append({"address": addr})
                        seen_addrs.add(addr)

            if batch:
                # V4.2 Anti-Jammed Queue
                qsize = token_queue.qsize()
                if qsize > 15:
                    logger.warning(f"⚠️ Processors jammed (Queue size: {qsize}). Skipping discovery cycle.")
                else:
                    logger.info(f"📦 Sending batch of {len(batch)} tokens to processors")
                    await token_queue.put(batch)
            
        except Exception as e:
            logger.error(f"Discovery error: {e}")
        
        await asyncio.sleep(SCAN_INTERVAL)


async def processor_worker_batch(worker_id: int, session: aiohttp.ClientSession) -> None:
    """Consumer: Processes BATCHES of tokens to preserve Cross-Sectional Scoring."""
    logger.info(f"⚙️ Processor-{worker_id} started")
    while True:
        try:
            # Get a batch (list of dicts)
            token_batch = await token_queue.get()
            
            features_rows = []
            
            # Process tokens with limited concurrency
            # to avoid overwhelming free-tier APIs and credit exhaustion
            results = []
            batch_sem = asyncio.Semaphore(5) # Increase to 5 concurrent tasks per worker
            async def _throttled(tok):
                async with batch_sem:
                    res = await process_token_to_features(session, tok)
                    await asyncio.sleep(0.5) # Reduced from 1.0s for better throughput
                    return res
            tasks = [_throttled(t) for t in token_batch]
            results = await asyncio.gather(*tasks)
            
            for res in results:
                if res:
                    features_rows.append(res)
            
            if features_rows:
                # ── Market Regime V4.0 ──
                from early_detector.db import get_avg_volume_history, log_market_regime
                avg_vol_hist = await get_avg_volume_history(minutes=120)
                
                # Score the batch
                feat_df = pd.DataFrame(features_rows)
                scored_df = compute_instability(feat_df, avg_vol_history=avg_vol_hist)
                
                # Log Regime for history
                total_batch_vol = feat_df["volume_5m"].sum() if "volume_5m" in feat_df.columns else 0
                regime_label = detect_regime(feat_df, avg_vol_history=avg_vol_hist)
                await log_market_regime(total_batch_vol, regime_label)
                
                # Signal logic
                # Calculate delta_instability
                if "last_instability" in scored_df.columns:
                    scored_df["delta_instability"] = scored_df["instability"] - scored_df["last_instability"]
                else:
                    scored_df["delta_instability"] = 0.0

                # ── SAVE SCORED METRICS TO DB ──
                for idx, row in scored_df.iterrows():
                    token_id = row["token_id"]
                    # Find original metrics in results
                    original_metrics = None
                    for res in results:
                        if res and res.get("token_id") == token_id:
                            original_metrics = res.get("_metrics_raw")
                            break
                    
                    if original_metrics:
                        inst_val = row["instability"]
                        if pd.isna(inst_val):
                            inst_val = 0.0
                        original_metrics["instability_index"] = float(inst_val)
                        await insert_metrics(token_id, original_metrics)

                max_inst = scored_df["instability"].max()
                logger.info(f"Scoring results: Batch size {len(scored_df)}, Max II: {max_inst:.4f}")
                threshold = get_signal_threshold(scored_df["instability"])
                signals = await process_signals(scored_df, threshold, regime_label=regime_label)
                if signals:
                    logger.info(f"🚨 Worker-{worker_id} generated {len(signals)} signals")
                    
                    # Auto-trade on signals
                    if AUTO_TRADE_ENABLED:
                        from early_detector.trader import get_sol_balance
                        balance = await get_sol_balance(session)
                        
                        for sig in signals:
                            # AI Guard disabled by USER request
                            # (Signals are already filtered by quantitative quality gate in process_signals)

                            if balance < TRADE_AMOUNT_SOL:
                                logger.warning(f"⚠️ Saldo insufficiente ({balance:.4f} SOL) per tradare {TRADE_AMOUNT_SOL} SOL. Salto.")
                                break
                                
                            sig_addr = sig.get("address") or sig.get("token_address")
                            if sig_addr:
                                logger.info(f"🤖 Auto-trade: BUY {TRADE_AMOUNT_SOL} SOL → {sig_addr[:8]}...")
                                result = await execute_buy(session, sig_addr, TRADE_AMOUNT_SOL, SLIPPAGE_BPS)
                                if result["success"]:
                                    await insert_trade(
                                        token_address=sig_addr,
                                        side="BUY",
                                        amount_sol=TRADE_AMOUNT_SOL,
                                        amount_token=result.get("amount_token", 0),
                                        price_entry=result.get("price", 0),
                                        tp_pct=DEFAULT_TP_PCT,
                                        sl_pct=DEFAULT_SL_PCT,
                                        tx_hash=result.get("tx_hash", "")
                                    )
                                    logger.info(f"✅ Auto-trade BUY salvato per {sig_addr[:8]}...")
                                    balance -= TRADE_AMOUNT_SOL # Hypothetical, actual refresh next loop
                                else:
                                    logger.warning(f"⚠️ Auto-trade fallito: {result.get('error')}")

            logger.info(f"✅ Processor-{worker_id} finished batch of {len(token_batch)} tokens")
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
        name = tok.get("name") # Can be None
        symbol = tok.get("symbol") # Can be None
        
        # Phase 11: Narrative Classification
        narrative = NarrativeManager.classify(name or "", symbol or "")
        token_id = await upsert_token(address, name, symbol, narrative=narrative)
        
        metrics = await fetch_token_metrics(session, address)
        if metrics is None:
            # fetch_token_metrics (V4.2+) should return a minimal record, 
            # but we keep this guard just in case to avoid crashes.
            logger.warning(f"⚠️ Metrics failed for {address}")
            return None

        # ── Step 1: Attempt to Resolve Metadata ──
        # Prioritize Metrics, then fallback to current values
        m_name = (metrics.get("name") or metrics.get("dex_name"))
        m_symbol = (metrics.get("symbol") or metrics.get("dex_symbol"))
        
        logger.debug(f"process_token_to_features for {address[:8]}: original name={name}, symbol={symbol}, metrics name={m_name}, symbol={m_symbol}")
        
        if m_name and (not name or name == "Unknown" or name == "???" or name.startswith("Token #")): 
            name = m_name
            logger.debug(f"Updated name to: {name}")
        if m_symbol and (not symbol or symbol == "???" or symbol == "Unknown" or symbol.startswith("TOK")): 
            symbol = m_symbol
            logger.debug(f"Updated symbol to: {symbol}")

        # Re-classify narrative with new info
        narrative = NarrativeManager.classify(name or "", symbol or "")
            
        # Re-upsert with potentially better name/symbol and narrative
        creator_address = metrics.get("creator_address")
        mint_auth = metrics.get("mint_authority")
        freeze_auth = metrics.get("freeze_authority")
        token_id = await upsert_token(
            address, name, symbol, 
            narrative=narrative, 
            creator_address=creator_address,
            mint_authority=mint_auth,
            freeze_authority=freeze_auth
        )
        logger.debug(f"upsert_token called for {address[:8]} with name={name}, symbol={symbol}, creator={creator_address}")
        
        # History
        history = await get_recent_metrics(token_id, minutes=30)
        
        # ── Step 2: Extract Time-Series Features ──
        try:
            # Re-implementing feature extraction briefly for compactness
            holders_series = [(r.get("holders") or 0) for r in history]
            h_t = metrics.get("holders") or 0
            
            # Safe index for holders
            h_t10 = h_t
            if len(holders_series) > 1:
                idx10 = min(10, len(holders_series) - 1)
                h_t10 = holders_series[idx10]
                
            h_t20 = h_t10
            if len(holders_series) > 2:
                idx20 = min(20, len(holders_series) - 1)
                h_t20 = holders_series[idx20]

            price_history = [(r.get("price") or 0) for r in history if r.get("price")]
            current_price = metrics.get("price") or 0
            
            # Use at least [0] and [0] if history is empty
            p_hist_np = np.array(price_history) if len(price_history) >= 2 else np.array([current_price, current_price])
            price_20m = p_hist_np[:20]
            price_5m = p_hist_np[:5]

            buys_20m = sum((r.get("buys_5m") or 0) for r in history[:4])
            sells_20m = sum((r.get("sells_5m") or 0) for r in history[:4])

            # Insider & Advanced Volume Features
            buyers_data = metrics.get("buyers_data", [])
            pair_created_at = metrics.get("pair_created_at")
            
            # ── Smart Wallet Rotation (SWR) ──
            active_wallets = [b["wallet"] for b in buyers_data] if buyers_data else []
            swr = compute_swr(active_wallets, smart_wallet_list, len(smart_wallet_list))

            unique_buyers_real = metrics.get("unique_buyers_50tx", 0)
            unique_buyers = unique_buyers_real if unique_buyers_real > 0 else buys_20m
            
            # Phase 2 Cleanup: Detect Coordinated Entry
            from early_detector.smart_wallets import detect_coordinated_entry
            coordinated_wallets = detect_coordinated_entry(buyers_data)
            
            # Calculate buy_ratio_120s (V4.0)
            buy_ratio_120s = 0.0
            if buyers_data and pair_created_at:
                created_sec = pair_created_at / 1000 if pair_created_at > 1e11 else pair_created_at
                early_buys = [b for b in buyers_data if (b.get("first_trade_time", 0) - created_sec) <= 120]
                buy_ratio_120s = len(early_buys) / len(buyers_data)

            insider_scores = []
            buyers_volumes = []
            
            if buyers_data:
                for b in buyers_data:
                    # Insider Score (V4.0 Sigmoid)
                    if pair_created_at:
                        is_coordinated = b["wallet"] in coordinated_wallets
                        s = compute_insider_score(
                            {}, b.get("first_trade_time", 0), pair_created_at, 
                            is_coordinated=is_coordinated,
                            buy_ratio_120s=buy_ratio_120s,
                            holder_delta=0.0 # simplified for now
                        )
                        insider_scores.append(s)
                    
                    # Volume for HHI
                    buyers_volumes.append(b.get("volume", 0))

            token_insider_psi = max(insider_scores) if insider_scores else 0.0
        except Exception as fe:
            logger.error(f"❌ Feature extraction error for {address}: {fe}")
            return None

        # Liquidity Series for Acceleration
        liquidity_series = np.array([(r.get("liquidity") or 0) for r in history])
        if len(liquidity_series) < 2:
            liquidity_series = np.array([metrics.get("liquidity") or 0])

        # Calculate price change 5m (V4.0 Safety)
        price_change_5m = 0.0
        if len(price_5m) > 1:
            old_p = price_5m[0]
            if old_p > 0:
                price_change_5m = (current_price - old_p) / old_p

        features = compute_all_features(
            h_t=h_t, h_t10=h_t10, h_t20=h_t20, unique_buyers=unique_buyers,
            sells_20m=sells_20m, buys_20m=buys_20m, price_series_20m=price_20m,
            price_series_5m=price_5m, sells_5m=metrics.get("sells_5m", 0) or 0,
            buys_5m=metrics.get("buys_5m", 0) or 0, 
            vol_5m=metrics.get("volume_5m", 0) or 0,
            liquidity=metrics.get("liquidity", 0) or 0,
            liquidity_series=liquidity_series,
            buyers_volumes=buyers_volumes,
            swr=swr,
        )

        features["token_id"] = token_id
        features["address"] = address
        features["name"] = name
        features["symbol"] = symbol
        features["price"] = current_price
        features["price_change_5m"] = price_change_5m
        features["liquidity"] = metrics.get("liquidity") or 0
        features["marketcap"] = metrics.get("marketcap") or 0
        features["top10_ratio"] = metrics.get("top10_ratio")
        features["insider_psi"] = token_insider_psi
        metrics["insider_psi"] = token_insider_psi
        
        # ── Applicazione Reale del Creator Risk Score ──
        from early_detector.db import get_token_creator, get_creator_stats
        creator_risk_score = 0.15 # Default neutral risk for new creators
        creator_address = await get_token_creator(address)
        if creator_address:
            creator_stats = await get_creator_stats(creator_address)
            if creator_stats:
                # Il "Rug Ratio" storico diventa il punteggio di rischio effettivo usato dall'algoritmo
                creator_risk_score = float(creator_stats.get("rug_ratio", 0.0))
        
        metrics["creator_risk_score"] = creator_risk_score
        features["creator_risk_score"] = creator_risk_score
        
        features["mint_authority"] = metrics.get("mint_authority")
        features["freeze_authority"] = metrics.get("freeze_authority")
        
        last_ii = 0.0
        for r in history:
            if r.get("instability_index") is not None:
                last_ii = float(r["instability_index"])
                break
        features["last_instability"] = last_ii
        
        # Save raw metrics for later insertion (with score)
        features["_metrics_raw"] = metrics
        
        return features

    except Exception as e:
        logger.error(f"Error processing {tok.get('address')}: {e}")
        return None


async def update_wallet_profiles_job(session):
    """Periodic job to refresh smart wallet list."""
    global smart_wallet_list
    while True:
        try:
             # Just reload from DB as PumpPortal worker updates stats in real-time
             smart_wallet_list = await get_smart_wallets()
             logger.info(f"Refreshed smart wallet list from DB: {len(smart_wallet_list)}")
        except Exception as e:
            logger.error(f"Wallet list refresh error: {e}")
        
        await asyncio.sleep(60) # every minute


async def db_maintenance_job():
    """Periodic job to clean up old data (daily)."""
    from early_detector.db import cleanup_old_data
    while True:
        try:
            await cleanup_old_data(days=7)
        except Exception as e:
            logger.error(f"Maintenance error: {e}")
        
        # Sleep for 24 hours
        await asyncio.sleep(86400)



async def run() -> None:
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("🚀 Solana Early Detector v4.0 (PumpPortal Only) starting…")
    logger.info("=" * 60)

    global smart_wallet_list
    await get_pool()
    smart_wallet_list = await get_smart_wallets()
    
    async with aiohttp.ClientSession() as session:
        # Start Workers
        producers = [
            asyncio.create_task(discovery_worker(session)),
            asyncio.create_task(pumpportal_worker(token_queue, smart_wallet_list))
        ]
        consumers = [asyncio.create_task(processor_worker_batch(i, session)) for i in range(4)]
        cron_jobs = [
            asyncio.create_task(update_wallet_profiles_job(session)),
            asyncio.create_task(db_maintenance_job()),
            asyncio.create_task(creator_performance_job(session))
        ]
        monitors = [asyncio.create_task(tp_sl_worker(session))]
        
        try:
            await asyncio.gather(*producers, *consumers, *cron_jobs, *monitors)
        finally:
            from early_detector.db import close_pool
            await close_pool()



# Removed update_wallet_profiles – Helius RPC disabled.


if __name__ == "__main__":
    asyncio.run(run())
