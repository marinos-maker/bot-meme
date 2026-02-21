
import asyncio
import aiohttp
import json

async def test_gecko_token():
    token_address = "C6Y8W5CeVzVzFADgc9Yme3cdqjPUgAnZwySYomnMpump"
    url = f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{token_address}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            print(json.dumps(data, indent=2))

if __name__ == "__main__":
    asyncio.run(test_gecko_token())
