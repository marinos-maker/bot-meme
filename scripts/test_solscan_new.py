import asyncio
import aiohttp
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from early_detector.config import SOLSCAN_API_KEY

async def test_solscan_direct():
    print(f"API KEY PRESENT: {bool(SOLSCAN_API_KEY)}")
    print(f"API KEY: {SOLSCAN_API_KEY[:5]}...")
    token_address = "5tdbhn4gtmhxjpzlx11gp7l4k51eb6e4abewpl3h3tfj"
    headers = {"token": SOLSCAN_API_KEY, "Accept": "application/json"}
    
    async with aiohttp.ClientSession() as session:
        url_meta = f"https://pro-api.solscan.io/v2.0/token/meta?address={token_address}"
        async with session.get(url_meta, headers=headers) as resp:
            print(f"META STATUS: {resp.status}")
            print(await resp.text())
            
        url_holders = f"https://pro-api.solscan.io/v2.0/token/holders?address={token_address}&page=1&page_size=10"
        async with session.get(url_holders, headers=headers) as resp:
            print(f"HOLDERS STATUS: {resp.status}")
            print(await resp.text())

asyncio.run(test_solscan_direct())
