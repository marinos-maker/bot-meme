
import asyncio
import aiohttp
import json

async def test_gecko_holders():
    pool_address = "3ygwcbRnW5qJv8xsRqGcANQib8BvvVviBtbX4euDd4gJ"
    url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool_address}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            print(json.dumps(data, indent=2))

if __name__ == "__main__":
    asyncio.run(test_gecko_holders())
