import asyncio
import aiohttp
import json

async def fetch():
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        addr = "6PbQDAJEYyyjWzZiCyqMSFBGyWeURE5M1mgYN6iSpump"
        # We can also get another one
        async with session.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}") as r:
            print("DEX:")
            data = await r.json()
            if data and data.get('pairs'):
                pair = data['pairs'][0]
                print(f"Price: {pair['priceUsd']}")
                print(f"FDV: {pair['fdv']}")

if __name__ == "__main__":
    asyncio.run(fetch())
