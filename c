"""
Test script to check if DexScreener provides bonding curve progress.
"""
import asyncio
import aiohttp
import json

async def test_dexscreener_bonding():
    """Check if DexScreener provides bonding curve progress data."""
    
    # SEN token address
    token_address = "5VAwWVPdjQJjGQbgqEwE4QV7yFvNnGpLPbZXF1Qpump"
    
    async with aiohttp.ClientSession() as session:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        
        async with session.get(url, timeout=10) as resp:
            if resp.status == 200:
                data = await resp.json()
                pairs = data.get("pairs", [])
                
                print("=" * 60)
                print("DexScreener Data Analysis")
                print("=" * 60)
                
                for p in pairs:
                    if p.get("chainId") == "solana":
                        print(f"\nPair: {p.get('dexId')}")
                        print(f"Symbol: {p.get('baseToken', {}).get('symbol')}")
                        print(f"Market Cap: ${p.get('fdv', 0):,.0f}")
                        print(f"Liquidity: ${p.get('liquidity', {}).get('usd', 0):,.0f}")
                        
                        # Check for profile data
                        profile = p.get("profile")
                        if profile:
                            print(f"\n✅ Profile data found!")
                            print(f"Profile keys: {list(profile.keys())}")
                            print(json.dumps(profile, indent=2)[:500])
                        
                        # Check for info data
                        info = p.get("info")
                        if info:
                            print(f"\n✅ Info data found!")
                            print(f"Info keys: {list(info.keys())}")
                        
                        # Print all keys to find bonding curve data
                        print(f"\nAll pair keys: {list(p.keys())}")
                        
                        # Check for any bonding-related fields
                        for key in p.keys():
                            if "bond" in key.lower() or "curve" in key.lower() or "progress" in key.lower():
                                print(f"Found key: {key} = {p[key]}")
                        
                        # Check priceNative vs priceUsd for SOL price estimation
                        price_native = p.get("priceNative", {})
                        print(f"\npriceNative: {price_native}")
                        
                        break

if __name__ == "__main__":
    asyncio.run(test_dexscreener_bonding())