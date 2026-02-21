
import asyncio
import aiohttp
import sys
import os
from loguru import logger

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from early_detector.collector import fetch_token_metrics, fetch_new_tokens
from early_detector.db import get_pool, close_pool, get_tracked_tokens

# Config logging
logger.remove()
logger.add(sys.stderr, level="DEBUG")

async def debug_collector():
    print("--- Debugging Collector ---")
    
    async with aiohttp.ClientSession() as session:
        # 1. Test fetch_new_tokens
        print("\n1. Testing fetch_new_tokens (Birdeye)...")
        try:
            new_tokens = await fetch_new_tokens(session, limit=5)
            print(f"fetch_new_tokens result: {len(new_tokens)} tokens found.")
            if new_tokens:
                print(f"Sample: {new_tokens[0]}")
        except Exception as e:
            print(f"fetch_new_tokens FAILED: {e}")

        # 2. Test fetch_token_metrics for a known token (SOL)
        print("\n2. Testing fetch_token_metrics for SOL...")
        sol_addr = "So11111111111111111111111111111111111111112"
        try:
            metrics = await fetch_token_metrics(session, sol_addr)
            if metrics:
                print(f"Metrics found for SOL: Price={metrics.get('price')}, Liq={metrics.get('liquidity')}")
                if metrics.get('holders'):
                     print(f"Holders: {metrics.get('holders')}")
                else:
                     print("Holders missing!")
            else:
                print("Metrics for SOL returned None!")
        except Exception as e:
            print(f"fetch_token_metrics (SOL) FAILED: {e}")

        # 3. Test fetch_token_metrics for a tracked token from DB
        print("\n3. Testing fetch_token_metrics for a tracked token...")
        try:
            await get_pool()
            tracked = await get_tracked_tokens(limit=1)
            if tracked:
                addr = tracked[0]
                print(f"Testing tracked token: {addr}")
                metrics = await fetch_token_metrics(session, addr)
                if metrics:
                    print(f"Metrics found: Price={metrics.get('price')}")
                else:
                    print(f"Metrics for {addr} returned None!")
            else:
                print("No tracked tokens found in DB (last 24h).")
        except Exception as e:
             print(f"DB/Tracked test FAILED: {e}")
        finally:
            await close_pool()

if __name__ == "__main__":
    asyncio.run(debug_collector())
