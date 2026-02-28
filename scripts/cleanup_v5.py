"""
Cleanup Script V5.0 — Prune trash tokens, metrics, and old signals from DB.

Removes:
1. Tokens that NEVER reached $500 Liquidity OR $5,000 MCap.
2. Signals with confidence < 0.35 (noise).
3. Metric history for these trash tokens.
4. Protects ANY token that has been actually TRADED.

Usage:
    python scripts/cleanup_v5.py
"""

import asyncio
from loguru import logger
from early_detector.db import get_pool, close_pool

async def main():
    logger.info("Starting Database Cleanup V5.0...")
    pool = await get_pool()

    # 1. Identify "Gold Tokens" (those we have traded)
    # We MUST NOT delete these.
    try:
        traded_token_ids = await pool.fetch("SELECT DISTINCT token_id FROM trades")
        gold_ids = [r['token_id'] for r in traded_token_ids if r['token_id']]
        logger.info(f"Protecting {len(gold_ids)} traded tokens.")
    except Exception as e:
        logger.warning(f"Could not fetch trades (table might be empty): {e}")
        gold_ids = []

    # 2. Count before
    total_t = await pool.fetchval("SELECT COUNT(*) FROM tokens")
    total_s = await pool.fetchval("SELECT COUNT(*) FROM signals")
    total_m = await pool.fetchval("SELECT COUNT(*) FROM token_metrics_timeseries")
    
    logger.info(f"Initial State: {total_t} tokens, {total_s} signals, {total_m} metrics.")

    # 3. Delete trash signals first (noise)
    # Confidence < 0.35 or MCap < 5000 is trash for V5.0
    s_deleted = await pool.execute(
        "DELETE FROM signals WHERE (confidence < 0.35 OR marketcap < 5000) AND NOT (token_id = ANY($1))",
        gold_ids
    )
    logger.info(f"Deleted trash signals: {s_deleted}")

    # 4. Identify trash tokens
    # Criteria: 
    # - Never had a metric row with liq > 500 or mcap > 5000
    # - Not a gold token
    trash_token_ids_rows = await pool.fetch(
        """
        SELECT id FROM tokens t
        WHERE NOT (t.id = ANY($1))
        AND NOT EXISTS (
            SELECT 1 FROM token_metrics_timeseries m
            WHERE m.token_id = t.id AND (m.marketcap >= 5000 OR m.liquidity >= 500)
        )
        """,
        gold_ids
    )
    trash_ids = [r['id'] for r in trash_token_ids_rows]
    logger.info(f"Found {len(trash_ids)} trash tokens to prune.")

    if trash_ids:
        # Delete metrics for these tokens first to avoid FK issues
        m_deleted = await pool.execute(
            "DELETE FROM token_metrics_timeseries WHERE token_id = ANY($1)",
            trash_ids
        )
        logger.info(f"Deleted {m_deleted} metrics for trash tokens.")

        # Delete any remaining signals for them
        s_trash_deleted = await pool.execute(
            "DELETE FROM signals WHERE token_id = ANY($1)",
            trash_ids
        )
        logger.info(f"Deleted {s_trash_deleted} orphaned signals.")

        # Finally delete tokens
        t_deleted = await pool.execute(
            "DELETE FROM tokens WHERE id = ANY($1)",
            trash_ids
        )
        logger.info(f"Deleted {t_deleted} trash tokens.")

    # 6. Wallet Cleanup
    # Delete wallets with ROI=1.0 and WR=0.0 (unverified) and trades < 5 or older than 3 days
    w_deleted = await pool.execute(
        """
        DELETE FROM wallet_performance
        WHERE avg_roi = 1.0 AND win_rate = 0.0
          AND (total_trades < 5 OR last_active < NOW() - INTERVAL '3 days')
        """
    )
    logger.info(f"Pruned {w_deleted} noise wallets from performance table.")

    # 7. Final Count
    final_t = await pool.fetchval("SELECT COUNT(*) FROM tokens")
    final_w = await pool.fetchval("SELECT COUNT(*) FROM wallet_performance")
    logger.info(f"Cleanup Complete. Tokens: {final_t}, Wallets: {final_w}.")
    
    await close_pool()

if __name__ == "__main__":
    asyncio.run(main())
