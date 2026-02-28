import asyncio
import aiohttp
import json

async def check_shiro():
    # Shiro address from user: 5EPt...pump (searching for it)
    # Actually let's find it in the DB first to get the full address
    import asyncpg
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"))
    row = await conn.fetchrow("SELECT address FROM tokens WHERE symbol ILIKE 'Shiro' LIMIT 1")
    if not row:
         print("Shiro not found in DB")
         await conn.close()
         return
    
    addr = row['address']
    print(f"Checking Shiro: {addr}")
    
    async with aiohttp.ClientSession() as session:
        url = f"https://frontend-api.pump.fun/coins/{addr}"
        async with session.get(url) as resp:
            data = await resp.json()
            print("Raw Pump.fun data:")
            print(json.dumps(data, indent=2))
            
            v_sol = float(data.get("virtual_sol_reserves", 0)) / 1e9
            v_tokens = float(data.get("virtual_token_reserves", 0)) / 1e6
            complete = data.get("complete")
            print(f"\nVirtual SOL: {v_sol} SOL")
            print(f"Virtual Tokens: {v_tokens}M")
            print(f"Complete: {complete}")
            
            # Progress based on SOL (Target 85 SOL total, starting 30 SOL)
            # Some curves end at 84 or 86 SOL. Let's assume 85.
            if complete:
                prog = 100.0
            else:
                prog = ((v_sol - 30) / 55) * 100
            print(f"Calculated Progress (SOL method): {prog:.2f}%")
            
    await conn.close()

if __name__ == "__main__":
    asyncio.run(check_shiro())
