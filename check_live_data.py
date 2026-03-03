import asyncio
from early_detector.db import get_pool, close_pool
from datetime import datetime, timedelta

async def check_signals():
    pool = await get_pool()
    # Check signals from the last 10 minutes
    now = datetime.utcnow()
    ten_mins_ago = now - timedelta(minutes=10)
    
    rows = await pool.fetch("""
        SELECT s.timestamp, t.symbol, s.instability_index, s.degen_score, s.confidence
        FROM signals s
        JOIN tokens t ON s.token_id = t.id
        WHERE s.timestamp > $1
        ORDER BY s.timestamp DESC
    """, ten_mins_ago)
    
    print(f"--- Signals in the last 10 minutes: {len(rows)} ---")
    for r in rows:
        print(f"[{r['timestamp']}] {r['symbol']}: II={r['instability_index']:.2f}, Score={r['degen_score']}, Conf={r['confidence']:.2f}")
    
    # Check trades too
    rows_trades = await pool.fetch("""
        SELECT created_at, token_address, amount_sol, side, status
        FROM trades
        WHERE created_at > $1
        ORDER BY created_at DESC
    """, ten_mins_ago)
    
    print(f"\n--- Trades in the last 10 minutes: {len(rows_trades)} ---")
    for r in rows_trades:
        print(f"[{r['created_at']}] {r['side']} {r['token_address'][:8]}... Amount: {r['amount_sol']} SOL, Status: {r['status']}")

    await close_pool()

if __name__ == "__main__":
    asyncio.run(check_signals())
