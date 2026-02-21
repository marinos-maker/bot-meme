
import asyncio
import asyncpg
from early_detector.config import SUPABASE_DB_URL
from loguru import logger

async def check_token(address):
    conn = await asyncpg.connect(SUPABASE_DB_URL)
    try:
        # Check tokens table
        token = await conn.fetchrow("SELECT * FROM tokens WHERE address = $1", address)
        if not token:
            print(f"Token {address} NOT FOUND in 'tokens' table.")
            return

        print(f"Token found: {dict(token)}")
        token_id = token['id']

        # Check metrics
        metrics = await conn.fetch("SELECT * FROM token_metrics_timeseries WHERE token_id = $1 ORDER BY timestamp ASC", token_id)
        print(f"Found {len(metrics)} metric entries for this token.")
        for m in metrics:
            print(f"TS: {m['timestamp']} | Price: {m['price']} | MC: {m['marketcap']} | Liq: {m['liquidity']} | II: {m['instability_index']}")

        # Check signals
        signals = await conn.fetch("SELECT * FROM signals WHERE token_id = $1", token_id)
        print(f"Found {len(signals)} signals for this token.")
        for s in signals:
            print(f"Signal TS: {s['timestamp']} | II: {s['instability_index']} | Conf: {s['confidence']}")

    finally:
        await conn.close()

if __name__ == "__main__":
    addr = "6jfRbgs3B1KrhohSZ7KbhJckHZektQs1rRUSwWeZpump"
    asyncio.run(check_token(addr))
