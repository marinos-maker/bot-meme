
import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("BIRDEYE_API_KEY")

async def test_birdeye_sol():
    url = "https://public-api.birdeye.so/defi/price?address=So11111111111111111111111111111111111111112"
    headers = {"X-API-Key": API_KEY, "x-chain": "solana"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            print(f"Status: {resp.status}")
            data = await resp.json()
            print(f"Data: {data}")

if __name__ == "__main__":
    asyncio.run(test_birdeye_sol())
