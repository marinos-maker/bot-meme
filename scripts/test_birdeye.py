
import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

async def debug_birdeye():
    api_key = os.getenv("BIRDEYE_API_KEY")
    headers = {
        "X-API-KEY": api_key,
        "x-chain": "solana",
        "accept": "application/json"
    }
    
    url = "https://public-api.birdeye.so/defi/tokenlist"
    params = {
        "sort_by": "v24hUSD",
        "sort_type": "desc",
        "offset": 0,
        "limit": 10
    }
    
    async with aiohttp.ClientSession() as session:
        print(f"Testing Birdeye Tokenlist with Headers: {headers}")
        async with session.get(url, headers=headers, params=params) as resp:
            print(f"Status: {resp.status}")
            body = await resp.text()
            print(f"Response Body: {body}")

        url_overview = "https://public-api.birdeye.so/defi/token_overview"
        test_addr = "8bqVBCy267GrVmWffMrM2iJBuQTJ2w5WTiedafNkmoon"
        params_ov = {"address": test_addr}
        
        print(f"\nTesting Birdeye Overview for {test_addr}...")
        async with session.get(url_overview, headers=headers, params=params_ov) as resp:
            print(f"Status: {resp.status}")
            body = await resp.text()
            print(f"Response Body: {body}")

if __name__ == "__main__":
    asyncio.run(debug_birdeye())
