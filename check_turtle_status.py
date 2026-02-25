
import asyncio
from early_detector.db import get_pool

async def check_turtle():
    pool = await get_pool()
    addr = "7BQx1p1izEfG9d6XmQpY45YV9T3L2yT8pD6vV2Wpump"
    row = await pool.fetchrow("""
        SELECT t.name, t.symbol, m.timestamp, m.marketcap, m.liquidity
        FROM tokens t
        JOIN token_metrics_timeseries m ON m.token_id = t.id
        WHERE t.address = $1
        ORDER BY m.timestamp DESC
        LIMIT 1
    """, addr)
    if row:
        print(f"Token: {row['name']} ({row['symbol']})")
        print(f"Last Update: {row['timestamp']}")
        print(f"MCap: ${float(row['marketcap'] or 0):,.2f}")
        print(f"Liq: ${float(row['liquidity'] or 0):,.2f}")
    else:
        print("Turtle token not found in DB.")

if __name__ == "__main__":
    asyncio.run(check_turtle())
