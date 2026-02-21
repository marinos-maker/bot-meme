
import asyncio
import aiohttp

async def test_dex_sol():
    url = "https://api.dexscreener.com/latest/dex/tokens/So11111111111111111111111111111111111111112"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            print(f"Status: {resp.status}")
            data = await resp.json()
            pairs = data.get("pairs", [])
            if pairs:
                # Get price from the first pair (usually highest liq)
                print(f"Price: {pairs[0].get('priceUsd')}")

if __name__ == "__main__":
    asyncio.run(test_dex_sol())
