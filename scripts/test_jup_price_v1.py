
import asyncio
import aiohttp

async def test_jup_price_v1():
    url = "https://price.jup.ag/v4/price?ids=SOL"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            print(f"Status: {resp.status}")
            data = await resp.json()
            print(f"Data: {data}")

if __name__ == "__main__":
    asyncio.run(test_jup_price_v1())
