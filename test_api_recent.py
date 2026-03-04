import asyncio
from early_detector.db import get_pool
import math

async def test():
    pool = await get_pool()
    minutes = 10
    rows = await pool.fetch(
        """
        WITH latest_metrics AS (
            SELECT DISTINCT ON (token_id) *
            FROM token_metrics_timeseries
            ORDER BY token_id, timestamp DESC
        )
        SELECT s.id, s.timestamp, s.instability_index, s.entry_price,
               s.kelly_size, s.confidence,
               s.insider_psi, s.creator_risk, s.degen_score, s.ai_summary, s.ai_analysis,
               t.address, t.name, t.symbol,
               m.marketcap as live_marketcap,
               m.liquidity as live_liquidity,
               m.top10_ratio as live_top10_ratio,
               m.price as live_price
        FROM signals s
        JOIN tokens t ON t.id = s.token_id
        LEFT JOIN latest_metrics m ON m.token_id = s.token_id
        WHERE s.timestamp > NOW() - INTERVAL $1
        ORDER BY s.timestamp DESC
        """,
        f"{minutes} minutes",
    )
    print(f"Found {len(rows)} recent signals.")
    for r in rows:
        try:
            # Emulate the processing logic
            ii = float(r["instability_index"] or 0)
            price = float(r["live_price"] or r["entry_price"] or 0)
            # ... and so on
            print(f"OK: {r['symbol']}")
        except Exception as e:
            print(f"ERROR on {r['symbol']}: {e}")

if __name__ == "__main__":
    asyncio.run(test())
