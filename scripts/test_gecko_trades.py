
import asyncio
import aiohttp

async def test_gecko_trades():
    # Pool address for PEPALIEN/SOL from earlier test: 
    # C6Y8W5CeVzVzFADgc9Yme3cdqjPUgAnZwySYomnMpump + SOL
    # I need a real pool address. 
    # Let's find one first.
    
    async with aiohttp.ClientSession() as session:
        # 1. Get new pools to find a real address
        url = "https://api.geckoterminal.com/api/v2/networks/solana/new_pools"
        async with session.get(url) as resp:
            if resp.status != 200:
                print(f"Failed to get pools: {resp.status}")
                return
            pools = (await resp.json()).get("data", [])
            if not pools:
                print("No pools found")
                return
            pool_addr = pools[0].get("attributes", {}).get("address")
            print(f"Testing trades for Pool: {pool_addr}")

        # 2. Get trades for this pool
        trades_url = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool_addr}/trades"
        async with session.get(trades_url) as resp:
            print(f"Trades Status: {resp.status}")
            if resp.status == 200:
                data = await resp.json()
                trades = data.get("data", [])
                print(f"Found {len(trades)} trades")
                if trades:
                    attr = trades[0].get("attributes", {})
                    print(f"Sample: {attr.get('kind')} by {attr.get('from_address')} volume={attr.get('volume_in_usd')}")

if __name__ == "__main__":
    asyncio.run(test_gecko_trades())
