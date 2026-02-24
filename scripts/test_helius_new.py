import asyncio
import aiohttp
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from early_detector.config import HELIUS_API_KEY
from early_detector.helius_client import get_token_largest_accounts, get_asset

async def test_helius_direct():
    print(f"API KEY PRESENT: {bool(HELIUS_API_KEY)}")
    if HELIUS_API_KEY:
        print(f"API KEY: {HELIUS_API_KEY[:5]}...")
        
    token_address = "So11111111111111111111111111111111111111112"
    url = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"
    
    async with aiohttp.ClientSession() as session:
        payload = {"jsonrpc": "2.0", "id": 1, "method": "getTokenLargestAccounts", "params": [token_address]}
        async with session.post(url, json=payload, timeout=5) as resp:
            print(f"HOLDERS STATUS: {resp.status}")
            print(await resp.text())
            
        payload2 = {"jsonrpc": "2.0", "id": 1, "method": "getAsset", "params": {"id": token_address}}
        async with session.post(url, json=payload2, timeout=5) as resp:
            print(f"DAS STATUS: {resp.status}")
            print(await resp.text())

asyncio.run(test_helius_direct())
