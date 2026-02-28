import asyncio
import asyncpg
from early_detector.config import SUPABASE_DB_URL

async def find_token():
    conn = await asyncpg.connect(SUPABASE_DB_URL)
    row = await conn.fetchrow("SELECT * FROM tokens WHERE address LIKE 'HcKP%'")
    if row:
        print(f"Token found: {row['symbol']} ({row['address']}) - ID: {row['id']}")
        
        # Check metrics
        metrics = await conn.fetch("SELECT * FROM token_metrics_timeseries WHERE token_id = $1 ORDER BY timestamp DESC LIMIT 5", row['id'])
        for m in metrics:
            print(f"Metrics: TS: {m['timestamp']}, Price: {m['price']}, Mcap: {m['marketcap']}, Liq: {m['liquidity']}, II: {m['instability_index']}, SW: {m['smart_wallets_active']}")
            
        # Check if signal exists
        signal = await conn.fetchrow("SELECT * FROM signals WHERE token_id = $1", row['id'])
        if signal:
            print(f"Signal EXISTS! Score: {signal['degen_score']}, Created: {signal['timestamp']}")
        else:
            print("Signal NOT found in DB.")
    else:
        print("Token HcKP% not found in database.")
    await conn.close()

if __name__ == '__main__':
    asyncio.run(find_token())
