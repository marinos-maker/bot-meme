
import asyncio
import aiohttp
from early_detector.db import get_pool
from early_detector.collector import fetch_pumpportal_metadata

async def fix_names():
    pool = await get_pool()
    async with aiohttp.ClientSession() as session:
        # Fetch tokens with bad names/symbols
        rows = await pool.fetch("SELECT address FROM tokens WHERE symbol IS NULL OR symbol = '???' OR name = 'Unknown'")
        print(f"Healing {len(rows)} tokens...")
        
        for r in rows:
            addr = r['address']
            print(f"   Searching for {addr[:8]}...")
            meta = await fetch_pumpportal_metadata(session, addr)
            if meta and meta.get('symbol'):
                print(f"   Found: {meta['symbol']} - {meta['name']}")
                await pool.execute(
                    "UPDATE tokens SET name = $1, symbol = $2 WHERE address = $3",
                    meta['name'], meta['symbol'], addr
                )
            else:
                print(f"   No meta found for {addr[:8]}")
            await asyncio.sleep(0.5) # Throttle to be nice to PumpPortal
            
    await pool.close()

if __name__ == "__main__":
    asyncio.run(fix_names())
