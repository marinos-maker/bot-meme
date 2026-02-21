
import asyncio
import aiohttp

async def test_jupiter():
    addr = "So11111111111111111111111111111111111111112"
    url = f"https://api.jup.ag/price/v2?ids={addr}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            print(f"Status: {resp.status}")
            if resp.status == 200:
                body = await resp.json()
                print(f"Body: {body}")

if __name__ == "__main__":
    asyncio.run(test_jupiter())
