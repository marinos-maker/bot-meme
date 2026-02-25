import asyncio
import os
import json
from dotenv import load_dotenv
from loguru import logger

# Mocking parts of the system to test the logic
load_dotenv()

from early_detector.db import get_pool
from early_detector.analyst import analyze_token_signal

async def test_analyze(address):
    print(f"Testing analysis for {address}")
    pool = await get_pool()
    
    # Get latest metrics
    latest_row = await pool.fetchrow(
        """
        SELECT t.id, t.address, t.symbol, t.name, t.narrative,
               m.price, m.marketcap, m.liquidity, m.holders,
               m.volume_5m, m.buys_5m, m.sells_5m, m.instability_index,
               m.insider_psi, m.creator_risk_score, m.top10_ratio
        FROM tokens t
        JOIN token_metrics_timeseries m ON m.token_id = t.id
        WHERE t.address = $1
        ORDER BY (m.instability_index IS NOT NULL) DESC, m.timestamp DESC
        LIMIT 1
        """,
        address,
    )
    
    if not latest_row:
        print("Token not found in DB")
        return

    token_data = dict(latest_row)
    
    # Get history
    history_rows = await pool.fetch(
        """
        SELECT holders, price, timestamp
        FROM token_metrics_timeseries
        WHERE token_id = $1
        ORDER BY timestamp DESC
        LIMIT 10
        """,
        token_data["id"],
    )
    
    history = [dict(r) for r in history_rows]
    
    # Convert Decimals to float
    for k, v in token_data.items():
        if hasattr(v, '__float__') and not isinstance(v, (int, float)):
            token_data[k] = float(v)
            
    print("Executing analyze_token_signal...")
    try:
        analysis = await analyze_token_signal(token_data, history)
        print("Analysis result type:", type(analysis))
        print("Analysis result:", json.dumps(analysis, indent=2))
    except Exception as e:
        print(f"Error in analyze_token_signal: {e}")
        import traceback
        traceback.print_exc()

async def main():
    address = "2La6ipseWTpnkKesEi6Vje5kzswbv4egSWJcqpF2xZnY"
    await test_analyze(address)

if __name__ == "__main__":
    asyncio.run(main())
