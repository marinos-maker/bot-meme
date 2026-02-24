import asyncio
import aiohttp

async def test_solscan():
    token = "So11111111111111111111111111111111111111112" # Wrapped SOL (for test)
    urls = [
        f"https://api.solscan.io/token/holders?token={token}&offset=0&size=10",
        f"https://api.solscan.io/token/meta?token={token}",
        f"https://pro-api.solscan.io/v2.0/token/holders?address={token}&page=1&page_size=10",
        f"https://pro-api.solscan.io/v2.0/token/meta?address={token}",
        f"https://public-api.solscan.io/token/holders?tokenAddress={token}&offset=0&limit=10"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json"
    }

    async with aiohttp.ClientSession() as session:
        for url in urls:
            try:
                async with session.get(url, headers=headers) as resp:
                    print(f"[{resp.status}] {url}")
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"  Success! Keys: {data.keys() if isinstance(data, dict) else type(data)}")
            except Exception as e:
                print(f"[Error] {url}: {e}")

asyncio.run(test_solscan())
