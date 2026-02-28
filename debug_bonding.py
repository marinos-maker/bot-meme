import asyncio
import aiohttp

async def fetch():
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        # get tokens completing recently? well let's just use pump.fun/coins/latest
        # but let's query the specific tokens user mentioned
        addrs = []
        # Let's search Dexscreener for "Centaur" and "Peaceman" to get exact tokens
        async def search(q):
            async with session.get(f"https://api.dexscreener.com/latest/dex/search?q={q}") as r:
                return await r.json()
                
        c = await search("Centaur")
        for p in c.get('pairs', []):
            if p['baseToken']['symbol'].lower() == 'centaur' and p['chainId'] == 'solana':
                addrs.append(p['baseToken']['address'])
                print(f"Centaur on DEX: {p['baseToken']['address']} MC: {p.get('fdv')}")
                break
                
        for addr in addrs:
            async with session.get(f"https://frontend-api.pump.fun/coins/{addr}") as r:
                if r.status == 200:
                    d = await r.json()
                    print(f"PumpFun {addr}: vSOL={d.get('virtual_sol_reserves')} vTOK={d.get('virtual_token_reserves')} Complete={d.get('complete')}")
                    
if __name__ == "__main__":
    asyncio.run(fetch())
