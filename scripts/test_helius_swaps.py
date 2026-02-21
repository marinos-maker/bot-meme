
import asyncio
import aiohttp
from early_detector.helius_client import fetch_token_swaps
from early_detector.config import HELIUS_API_KEY

async def test_helius_swaps():
    # A known active token (e.g., SOL or a trending meme)
    # Using a recent one from the user's explosive volume list if possible
    # 3gRQ...AHbB was #1
    token_addr = "3gRQ6jWkP8H3r6tJgH3b9c8v8H3r6tJgH3b9c8v8H3r" # Dummy if I don't have full
    # Let's use something generic like the one in my previous test
    token_addr = "C6Y8W5CeVzVzFADgc9Yme3cdqjPUgAnZwySYomnMpump" # PEPALIEN from gecko test
    
    async with aiohttp.ClientSession() as session:
        print(f"Testing Helius Swaps for {token_addr}")
        trades = await fetch_token_swaps(session, token_addr)
        print(f"Found {len(trades)} trades")
        if trades:
            print(f"Sample Trade: {trades[0]}")
        else:
            # Check if it was rate limited or empty
            print("No trades found. Checking Helius URL directly...")
            url = f"https://api.helius.xyz/v0/addresses/{token_addr}/transactions?api-key={HELIUS_API_KEY}&type=SWAP"
            async with session.get(url) as resp:
                print(f"Direct Response Status: {resp.status}")
                if resp.status == 200:
                    json_data = await resp.json()
                    print(f"Direct Response Count: {len(json_data)}")
                    if json_data:
                        print(f"Sample JSON: {json_data[0].get('description')}")
                        print(f"Sample Transfers: {len(json_data[0].get('tokenTransfers', []))}")

if __name__ == "__main__":
    asyncio.run(test_helius_swaps())
