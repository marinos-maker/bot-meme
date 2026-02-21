
import asyncio
import aiohttp
import json
from early_detector.config import HELIUS_RPC_URL

async def test_get_asset():
    token_address = "C6Y8W5CeVzVzFADgc9Yme3cdqjPUgAnZwySYomnMpump" # PEPALIEN
    payload = {
        "jsonrpc": "2.0",
        "id": "test",
        "method": "getAsset",
        "params": {
            "id": token_address
        }
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(HELIUS_RPC_URL, json=payload) as resp:
            data = await resp.json()
            print(json.dumps(data, indent=2))

if __name__ == "__main__":
    asyncio.run(test_get_asset())
