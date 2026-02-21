
import asyncio
import aiohttp
import json
from early_detector.config import HELIUS_API_KEY, HELIUS_BASE_URL
from early_detector.db import get_tracked_tokens

async def test():
    async with aiohttp.ClientSession() as session:
        tokens = await get_tracked_tokens(limit=1)
        if not tokens:
            print("No tokens to test")
            return
        addr = tokens[0]
        print(f"Testing swaps for {addr}...")
        url = f"{HELIUS_BASE_URL}/v0/addresses/{addr}/transactions"
        params = {"api-key": HELIUS_API_KEY, "type": "SWAP", "limit": "5"}
        
        async with session.get(url, params=params) as resp:
            if resp.status == 200:
                txns = await resp.json()
                print(f"Found {len(txns)} RAW transactions")
                if txns:
                    # Print first one nicely
                    print(json.dumps(txns[0], indent=2))
            else:
                print(f"Error: {resp.status}")

if __name__ == "__main__":
    asyncio.run(test())
