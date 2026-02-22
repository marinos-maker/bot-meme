
import asyncio
import aiohttp
from early_detector.trader import get_sol_balance

async def check():
    async with aiohttp.ClientSession() as session:
        balance = await get_sol_balance(session)
        print(f"Current SOL Balance: {balance:.8f} SOL")

if __name__ == "__main__":
    asyncio.run(check())
