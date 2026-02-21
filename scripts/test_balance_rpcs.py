
import asyncio
import aiohttp
import os
import base58
from solders.keypair import Keypair
from dotenv import load_dotenv

load_dotenv()

HELIUS_RPC_URL = os.getenv("HELIUS_RPC_URL")
# If HELIUS_RPC_URL doesn't have the key, we need to construct it
HELIUS_API_KEY = os.getenv("HELIUS_API_KEY")
if HELIUS_RPC_URL and HELIUS_API_KEY and "?api-key=" not in HELIUS_RPC_URL:
    HELIUS_RPC_URL = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_API_KEY}"

DRPC_RPC_URL = os.getenv("DRPC_RPC_URL")
PUBLIC_SOLANA = "https://api.mainnet-beta.solana.com"
WALLET_PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY")

async def test_balance():
    if not WALLET_PRIVATE_KEY:
        print("WALLET_PRIVATE_KEY not set")
        return

    key_bytes = base58.b58decode(WALLET_PRIVATE_KEY)
    kp = Keypair.from_bytes(key_bytes)
    wallet = str(kp.pubkey())
    print(f"Wallet Address: {wallet}")

    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getBalance",
        "params": [wallet]
    }

    async with aiohttp.ClientSession() as session:
        # 1. Helius
        print(f"\nTesting Helius: {HELIUS_RPC_URL}")
        try:
            async with session.post(HELIUS_RPC_URL, json=payload, timeout=10) as resp:
                print(f"Status: {resp.status}")
                body = await resp.json()
                print(f"Result: {body.get('result')}")
        except Exception as e:
            print(f"Helius error: {e}")

        # 2. dRPC
        if DRPC_RPC_URL:
            print(f"\nTesting dRPC: {DRPC_RPC_URL}")
            try:
                # We know dRPC might need Content-Type
                headers = {"Content-Type": "application/json"}
                async with session.post(DRPC_RPC_URL, json=payload, timeout=10, headers=headers) as resp:
                    print(f"Status: {resp.status}")
                    body = await resp.json()
                    print(f"Result: {body.get('result')}")
            except Exception as e:
                print(f"dRPC error: {e}")

        # 3. Public
        print(f"\nTesting Public: {PUBLIC_SOLANA}")
        try:
            async with session.post(PUBLIC_SOLANA, json=payload, timeout=10) as resp:
                print(f"Status: {resp.status}")
                body = await resp.json()
                print(f"Result: {body.get('result')}")
        except Exception as e:
            print(f"Public error: {e}")

if __name__ == "__main__":
    asyncio.run(test_balance())
