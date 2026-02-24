import asyncio
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from early_detector.db import get_pool, close_pool

async def run():
    pool = await get_pool()
    rows = await pool.fetch("SELECT insider_psi, creator_risk, timestamp FROM signals ORDER BY timestamp DESC LIMIT 5")
    for r in rows:
        print(f"Signal: Ins={r.get('insider_psi')}, Cr={r.get('creator_risk')}, Date={r.get('timestamp')}")
        
    print("\nRecent Token Metrics:")
    rows2 = await pool.fetch("SELECT insider_psi, creator_risk_score, top10_ratio, timestamp FROM token_metrics_timeseries ORDER BY timestamp DESC LIMIT 5")
    for r in rows2:
        print(f"Metrics: Ins={r.get('insider_psi')}, Cr={r.get('creator_risk_score')}, Top10={r.get('top10_ratio')}, Date={r.get('timestamp')}")
        
    await close_pool()

asyncio.run(run())
