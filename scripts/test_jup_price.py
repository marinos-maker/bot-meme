
import asyncio
import aiohttp

async def test_jup_price():
    url = "https://api.jup.ag/price/v2?ids=So11111111111111111111111111111111111111112"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            print(f"Status: {resp.status}")
            data = await resp.json()
            print(f"Data: {data}")

if __name__ == "__main__":
    asyncio.run(test_jup_price())
