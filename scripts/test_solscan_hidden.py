import asyncio
import aiohttp

async def test_solscan_hidden():
    async with aiohttp.ClientSession() as session:
        url = "https://api.solscan.io/v2/account/v1/token/info?address=So11111111111111111111111111111111111111112"
        h = {"User-Agent": "Mozilla/5.0", "Origin": "https://solscan.io", "Referer": "https://solscan.io/"}
        async with session.get(url, headers=h) as resp:
            print(f"Meta status: {resp.status}")
            if resp.status == 200:
                print(await resp.json())

        url2 = "https://api.solscan.io/v2/account/v1/token/holders?address=So11111111111111111111111111111111111111112&offset=0&size=10"
        async with session.get(url2, headers=h) as resp:
            print(f"Holders status: {resp.status}")
            if resp.status == 200:
                print((await resp.json())['data']['total'])

asyncio.run(test_solscan_hidden())
