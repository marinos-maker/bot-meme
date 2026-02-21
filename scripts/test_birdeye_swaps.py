
import asyncio
import aiohttp
from early_detector.config import BIRDEYE_API_KEY, BIRDEYE_BASE_URL
from early_detector.db import get_tracked_tokens

async def test_birdeye():
    headers = {
        "X-API-Key": BIRDEYE_API_KEY,
        "x-chain": "solana"
    }
    async with aiohttp.ClientSession() as session:
        tokens = await get_tracked_tokens(limit=1)
        if not tokens: return
        addr = tokens[0]
        print(f"Testing Birdeye swaps for {addr}...")
        url = f"{BIRDEYE_BASE_URL}/defi/txs/token?address={addr}&offset=0&limit=50"
        async with session.get(url, headers=headers) as resp:
            print(f"Status: {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                items = data.get("data", {}).get("items", [])
                print(f"Found {len(items)} transactions")
                if items:
                    print(items[0])
            else:
                print(await resp.text())

if __name__ == "__main__":
    asyncio.run(test_birdeye())
