
import asyncio
import aiohttp
from early_detector.helius_client import check_token_security

async def test_helius():
    async with aiohttp.ClientSession() as session:
        # A known pump.fun token
        addr = "2CmemgrYpaJCQ1kapMv6PpfePzNZVFmNo53skziVpump"
        print(f"Testing Helius for {addr}...")
        sec = await check_token_security(session, addr)
        print(f"Result: {sec}")

if __name__ == "__main__":
    asyncio.run(test_helius())
