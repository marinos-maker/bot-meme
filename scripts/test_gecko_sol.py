
import asyncio
import aiohttp

async def test_gecko_sol():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            print(f"Status: {resp.status}")
            data = await resp.json()
            print(f"Data: {data}")

if __name__ == "__main__":
    asyncio.run(test_gecko_sol())
