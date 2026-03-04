import asyncio
import aiohttp
from early_detector.trader import get_sol_balance
from early_detector.config import WALLET_PUBLIC_KEY

async def check():
    async with aiohttp.ClientSession() as session:
        balance = await get_sol_balance(session)
        print(f"Wallet: {WALLET_PUBLIC_KEY}")
        print(f"Current Balance: {balance:.6f} SOL")

if __name__ == "__main__":
    asyncio.run(check())
