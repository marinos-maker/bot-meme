
import asyncio
import aiohttp
import os
from dotenv import load_dotenv

load_dotenv()
ALCHEMY_RPC_URL = os.getenv("ALCHEMY_RPC_URL")
WALLET = os.getenv("WALLET_PUBLIC_KEY")

async def check_balances():
    if not ALCHEMY_RPC_URL or not WALLET:
        print("Missing RPC or Wallet")
        return

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            WALLET,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"}
        ]
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(ALCHEMY_RPC_URL, json=payload) as resp:
            data = await resp.json()
            if "result" in data:
                accounts = data["result"]["value"]
                print(f"Found {len(accounts)} token accounts.")
                for acc in accounts:
                    mint = acc["account"]["data"]["parsed"]["info"]["mint"]
                    amount = acc["account"]["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"]
                    if amount > 0:
                        print(f"Mint: {mint}, Amount: {amount}")
            else:
                print(f"Error or no result: {data}")

if __name__ == "__main__":
    asyncio.run(check_balances())
