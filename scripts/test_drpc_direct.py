
import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()

DRPC_RPC_URL = os.getenv("DRPC_RPC_URL")

async def test_drpc():
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "getSlot",
        "params": []
    }

    async with aiohttp.ClientSession() as session:
        # 1. Public
        url = "https://solana.drpc.org"
        print(f"Testing Public dRPC: {url}")
        async with session.post(url, json=payload, headers=headers) as resp:
            print(f"Status: {resp.status}")
            try:
                print(f"Body: {await resp.json()}")
            except:
                print(f"Text: {await resp.text()}")

        # 2. User Private
        if DRPC_RPC_URL:
            print(f"\nTesting User Private dRPC: {DRPC_RPC_URL}")
            async with session.post(DRPC_RPC_URL, json=payload, headers=headers) as resp:
                print(f"Status: {resp.status}")
                try:
                    print(f"Body: {await resp.json()}")
                except:
                    print(f"Text: {await resp.text()}")

if __name__ == "__main__":
    asyncio.run(test_drpc())
