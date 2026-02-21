
import asyncio
import aiohttp
from early_detector.helius_client import fetch_token_swaps
from early_detector.db import get_tracked_tokens

async def test():
    async with aiohttp.ClientSession() as session:
        tokens = await get_tracked_tokens(limit=1)
        if not tokens:
            print("No tokens to test")
            return
        addr = tokens[0]
        print(f"Testing swaps for {addr}...")
        trades = await fetch_token_swaps(session, addr, limit=50)
        print(f"Found {len(trades)} trades")
        for t in trades[:3]:
            print(t)

if __name__ == "__main__":
    asyncio.run(test())
