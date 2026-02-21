
import asyncio
import aiohttp
import json
from early_detector.config import HELIUS_RPC_URL

async def test_pump_holders():
    # A very new pump token from the user's list
    token_address = "2aW9T2WkStAnV7jC7vS7hnc4kHXjrnb1ktjDVCs1FsGx6" 
    payload = {
        "jsonrpc": "2.0",
        "id": "test",
        "method": "getTokenLargestAccounts",
        "params": [token_address]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(HELIUS_RPC_URL, json=payload) as resp:
            data = await resp.json()
            print(json.dumps(data, indent=2))

if __name__ == "__main__":
    asyncio.run(test_pump_holders())
