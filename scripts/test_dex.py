import asyncio
import aiohttp

async def test_dexscreener_profiles():
    async with aiohttp.ClientSession() as session:
        url = "https://api.dexscreener.com/token-profiles/latest/v1"
        async with session.get(url) as resp:
            data = await resp.json()
            if data and isinstance(data, list):
                print(f"Profiles count: {len(data)}")
                print(data[0])
            else:
                print(data)

asyncio.run(test_dexscreener_profiles())
