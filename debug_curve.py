import asyncio
import asyncpg
import os
import aiohttp
import json
from dotenv import load_dotenv

async def check_curve():
    load_dotenv()
    conn = await asyncpg.connect(os.getenv("SUPABASE_DB_URL"), statement_cache_size=0)
    
    # Try to find the token address starting with 6PbQ and ending with pump
    row = await conn.fetchrow("SELECT address FROM tokens WHERE address LIKE '6PbQ%pump' LIMIT 1")
    
    # If not found, let's just grab the latest few pump tokens
    if not row:
        rows = await conn.fetch("SELECT address FROM tokens WHERE address LIKE '%pump' ORDER BY created_at DESC LIMIT 5")
        addresses = [r['address'] for r in rows]
    else:
        addresses = [row['address']]
        
    await conn.close()
    
    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0"}) as session:
        for addr in addresses:
            url = f"https://frontend-api.pump.fun/coins/{addr}"
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"\nAddress: {addr}")
                    v_sol = float(data.get("virtual_sol_reserves") or 0) / 1e9
                    v_tok = float(data.get("virtual_token_reserves") or 0) / 1e6
                    mcap = float(data.get("usd_market_cap") or 0)
                    print(f"Virtual SOL: {v_sol:,.2f}")
                    print(f"Virtual Tokens: {v_tok:,.2f}M")
                    print(f"MCap: ${mcap:,.2f}")
                    
                    # Original logic token sold
                    sold = 1073 - v_tok
                    prog1 = (sold / 800) * 100
                    
                    # New logic SOL gathered
                    prog2 = ((v_sol - 30) / 55) * 100
                    
                    print(f"Progress (Token Sold logic): {prog1:.2f}%")
                    print(f"Progress (SOL 30->85 logic): {prog2:.2f}%")
                else:
                    print(f"Error {resp.status} for {addr}")

if __name__ == "__main__":
    asyncio.run(check_curve())
