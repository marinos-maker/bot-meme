
import asyncio
import aiohttp

async def test_gecko():
    url = "https://api.geckoterminal.com/api/v2/networks/solana/new_pools"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            print(f"Status: {resp.status}")
            if resp.status == 200:
                body = await resp.json()
                data = body.get("data", [])
                print(f"Found {len(data)} pools")
                if data:
                    pool = data[0]
                    attr = pool.get("attributes", {})
                    print(f"Sample Pool: {attr.get('name')}")
                    # tokens are usually in relationships
                    rels = pool.get("relationships", {})
                    base_token = rels.get("base_token", {}).get("data", {}).get("id", "")
                    print(f"Base Token ID: {base_token}")

if __name__ == "__main__":
    asyncio.run(test_gecko())
