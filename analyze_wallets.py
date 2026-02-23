#!/usr/bin/env python3
"""
Script per analizzare la distribuzione dei wallet e capire perché solo 18 su 29.285 sono considerati smart wallet.
"""

import asyncio
import sys
from pathlib import Path
from loguru import logger

# Aggiungi il percorso del progetto
sys.path.insert(0, str(Path(__file__).parent))

from early_detector.db import get_pool
from early_detector.config import SW_MIN_ROI, SW_MIN_TRADES, SW_MIN_WIN_RATE


async def analyze_wallets_distribution():
    """Analizza la distribuzione dei wallet per ROI e win rate."""
    
    logger.info("🔍 Analizzando la distribuzione dei wallet...")
    
    pool = await get_pool()
    
    # 1. Recupera tutte le statistiche dei wallet
    logger.info("📊 Recuperando statistiche dei wallet...")
    
    rows = await pool.fetch(
        """
        SELECT wallet, avg_roi, total_trades, win_rate, cluster_label, last_active
        FROM wallet_performance
        ORDER BY avg_roi DESC
        """
    )
    
    if not rows:
        logger.error("❌ Nessun wallet trovato nel database")
        return
    
    logger.info(f"✅ Trovati {len(rows)} wallet nel database")
    
    # 2. Analizza la distribuzione
    import numpy as np
    import math
    
    rois = []
    trades = []
    win_rates = []
    smart_count = 0
    
    for r in rows:
        roi = float(r["avg_roi"] or 0)
        trade_count = r["total_trades"] or 0
        win_rate = float(r["win_rate"] or 0)
        
        if not math.isfinite(roi): roi = 0
        if not math.isfinite(win_rate): win_rate = 0
        
        rois.append(roi)
        trades.append(trade_count)
        win_rates.append(win_rate)
        
        # Conta quanti soddisfano i criteri attuali
        if roi > SW_MIN_ROI and trade_count >= SW_MIN_TRADES and win_rate > SW_MIN_WIN_RATE:
            smart_count += 1
    
    logger.info(f"🎯 Smart wallet attuali: {smart_count}/{len(rows)} ({smart_count/len(rows)*100:.2f}%)")
    logger.info(f"   Criteri: ROI > {SW_MIN_ROI}, Trade >= {SW_MIN_TRADES}, Win Rate > {SW_MIN_WIN_RATE*100}%")
    
    # 3. Analizza distribuzione ROI
    logger.info("\n📈 Distribuzione ROI:")
    roi_thresholds = [0.5, 0.8, 1.0, 1.1, 1.2, 1.5, 2.0, 3.0, 5.0, 10.0]
    for threshold in roi_thresholds:
        count = sum(1 for roi in rois if roi > threshold)
        percentage = count / len(rois) * 100
        logger.info(f"   ROI > {threshold:4.1f}x: {count:5d} ({percentage:5.1f}%)")
    
    # 4. Analizza distribuzione Win Rate
    logger.info("\n🎯 Distribuzione Win Rate:")
    wr_thresholds = [0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    for threshold in wr_thresholds:
        count = sum(1 for wr in win_rates if wr > threshold)
        percentage = count / len(win_rates) * 100
        logger.info(f"   Win Rate > {threshold:4.1f}: {count:5d} ({percentage:5.1f}%)")
    
    # 5. Analizza distribuzione Trade Count
    logger.info("\n📊 Distribuzione Trade Count:")
    trade_thresholds = [1, 2, 3, 5, 10, 20, 50, 100, 500, 1000]
    for threshold in trade_thresholds:
        count = sum(1 for t in trades if t >= threshold)
        percentage = count / len(trades) * 100
        logger.info(f"   Trade >= {threshold:4d}: {count:5d} ({percentage:5.1f}%)")
    
    # 6. Analizza combinazioni di criteri
    logger.info("\n🔍 Analisi combinazioni di criteri:")
    
    # Criteri più flessibili
    flexible_criteria = [
        (1.0, 2, 0.2),   # ROI > 1.0x, Trade >= 2, Win Rate > 20%
        (1.0, 1, 0.25),  # ROI > 1.0x, Trade >= 1, Win Rate > 25%
        (0.8, 2, 0.25),  # ROI > 0.8x, Trade >= 2, Win Rate > 25%
        (1.1, 1, 0.2),   # ROI > 1.1x, Trade >= 1, Win Rate > 20%
        (1.2, 2, 0.3),   # ROI > 1.2x, Trade >= 2, Win Rate > 30%
    ]
    
    for roi_min, trade_min, wr_min in flexible_criteria:
        count = sum(1 for i in range(len(rois)) 
                   if rois[i] > roi_min and trades[i] >= trade_min and win_rates[i] > wr_min)
        percentage = count / len(rois) * 100
        logger.info(f"   ROI > {roi_min:3.1f}x, Trade >= {trade_min}, WR > {wr_min*100:3.0f}%: {count:5d} ({percentage:5.1f}%)")
    
    # 7. Analisi cluster
    logger.info("\n🏷️ Analisi per cluster:")
    cluster_stats = {}
    for r in rows:
        cluster = r["cluster_label"] or "unknown"
        if cluster not in cluster_stats:
            cluster_stats[cluster] = {"count": 0, "smart": 0, "avg_roi": 0, "avg_wr": 0}
        
        cluster_stats[cluster]["count"] += 1
        cluster_stats[cluster]["avg_roi"] += float(r["avg_roi"] or 0)
        cluster_stats[cluster]["avg_wr"] += float(r["win_rate"] or 0)
        
        roi = float(r["avg_roi"] or 0)
        trade_count = r["total_trades"] or 0
        win_rate = float(r["win_rate"] or 0)
        
        if roi > SW_MIN_ROI and trade_count >= SW_MIN_TRADES and win_rate > SW_MIN_WIN_RATE:
            cluster_stats[cluster]["smart"] += 1
    
    for cluster, stats in cluster_stats.items():
        count = stats["count"]
        smart = stats["smart"]
        avg_roi = stats["avg_roi"] / count if count > 0 else 0
        avg_wr = stats["avg_wr"] / count if count > 0 else 0
        percentage = smart / count * 100 if count > 0 else 0
        
        logger.info(f"   {cluster:8s}: {count:5d} total, {smart:3d} smart ({percentage:4.1f}%), avg ROI: {avg_roi:.2f}x, avg WR: {avg_wr:.2f}")
    
    # 8. Statistiche generali
    logger.info("\n📊 Statistiche generali:")
    logger.info(f"   Wallet totali: {len(rows)}")
    logger.info(f"   ROI medio: {np.mean(rois):.2f}x")
    logger.info(f"   ROI mediano: {np.median(rois):.2f}x")
    logger.info(f"   ROI max: {max(rois):.2f}x")
    logger.info(f"   Trade medio: {np.mean(trades):.1f}")
    logger.info(f"   Trade mediano: {np.median(trades):.1f}")
    logger.info(f"   Win Rate medio: {np.mean(win_rates):.2f}")
    logger.info(f"   Win Rate mediano: {np.median(win_rates):.2f}")
    
    # 9. Proposta di criteri più flessibili
    logger.info("\n💡 Proposta di criteri più flessibili:")
    logger.info("   Attuali: ROI > 1.1x, Trade >= 2, Win Rate > 25%")
    logger.info("   Alternative:")
    logger.info("   - Opzione A: ROI > 1.0x, Trade >= 2, Win Rate > 20%")
    logger.info("   - Opzione B: ROI > 0.8x, Trade >= 2, Win Rate > 25%")
    logger.info("   - Opzione C: ROI > 1.0x, Trade >= 1, Win Rate > 25%")
    logger.info("   - Opzione D: ROI > 1.2x, Trade >= 2, Win Rate > 30% (più conservativa)")


async def main():
    """Funzione principale."""
    await analyze_wallets_distribution()


if __name__ == "__main__":
    asyncio.run(main())