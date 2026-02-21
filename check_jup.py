
import asyncio
import aiohttp
import os
from dotenv import load_dotenv

async def check_price():
    addr = "7w46eV6gRX3m1z9yWpa7mKHy6yqpump" # Just a guess on the full address
    url = f"https://price.jup.ag/v4/price?ids={addr}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            print(data)

if __name__ == "__main__":
    asyncio.run(check_price())
