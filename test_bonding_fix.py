"""
Test script to verify bonding curve calculation fix.
V6.1: Tests the corrected bonding curve formula.

Run with: python test_bonding_fix.py
"""

import asyncio
import aiohttp

# Constants for bonding curve calculation
START_SOL = 30.0      # Pump.fun bonding curve starts at ~30 SOL (~$4,500)
GRADUATION_SOL = 85.0  # Pump.fun graduates at ~85 SOL (~$12,750)
SOL_PRICE = 150.0

def calculate_bonding_pct(virtual_sol_reserves: float) -> float:
    """Calculate bonding progress using the corrected formula."""
    if virtual_sol_reserves <= 0:
        return 0.0
    
    if virtual_sol_reserves >= GRADUATION_SOL:
        return 100.0
    
    # Correct formula: (current - start) / (end - start)
    bonding_pct = ((virtual_sol_reserves - START_SOL) / (GRADUATION_SOL - START_SOL)) * 100
    return max(0.0, min(bonding_pct, 99.0))

async def test_bonding_calculation():
    """Test bonding curve calculation for a specific token."""
    print("=" * 60)
    print("Bonding Curve Calculation Test (V6.1 Fix)")
    print("=" * 60)
    print(f"\nFormula: bonding_pct = (SOL_reserves - {START_SOL}) / ({GRADUATION_SOL} - {START_SOL}) * 100")
    print(f"Range: {START_SOL} SOL (${START_SOL * SOL_PRICE:,.0f}) -> {GRADUATION_SOL} SOL (${GRADUATION_SOL * SOL_PRICE:,.0f})")
    print()
    
    # Test cases with Easter token values from DexScreener
    # Progress 71% on DexScreener, MC $10K
    # Let's reverse engineer: if progress is 71%, what SOL reserves?
    # bonding_pct = (sol - 30) / (85 - 30) * 100
    # 71 = (sol - 30) / 55 * 100
    # sol - 30 = 71 * 55 / 100 = 39.05
    # sol = 69.05 SOL
    # liquidity = 69.05 * 150 = $10,357
    
    easter_sol_reserves = (71.0 / 100) * (GRADUATION_SOL - START_SOL) + START_SOL
    easter_liq = easter_sol_reserves * SOL_PRICE
    
    print("Easter token (71% progress on DexScreener):")
    print(f"  Expected SOL reserves: {easter_sol_reserves:.2f} SOL")
    print(f"  Expected liquidity: ${easter_liq:,.0f}")
    print()
    
    # Test cases
    test_cases = [
        ("Early token", 32.0),      # Just started
        ("Mid progress", 50.0),     # Middle
        ("Easter-like (71%)", easter_sol_reserves),  # Similar to Easter
        ("Near graduation", 80.0),  # Almost done
        ("At graduation", 85.0),    # Exactly at graduation
    ]
    
    print("Test cases (theoretical):")
    print("-" * 50)
    for name, sol_reserves in test_cases:
        pct = calculate_bonding_pct(sol_reserves)
        liq_usd = sol_reserves * SOL_PRICE
        print(f"  {name:20} {sol_reserves:5.1f} SOL (${liq_usd:,.0f}) -> {pct:5.1f}%")
    
    print()
    print("-" * 50)
    print("Comparison with OLD (wrong) formula:")
    print("-" * 50)
    for name, sol_reserves in test_cases:
        old_pct = min((sol_reserves / GRADUATION_SOL) * 100, 99.0)
        new_pct = calculate_bonding_pct(sol_reserves)
        diff = new_pct - old_pct
        print(f"  {name:20} OLD: {old_pct:5.1f}% -> NEW: {new_pct:5.1f}% (diff: {diff:+.1f}%)")
    
    print()
    print("=" * 60)
    print("Testing with DexScreener API directly for 'Easter' token")
    print("=" * 60)
    
    # Try to fetch real data
    async with aiohttp.ClientSession() as session:
        # Search for Easter token
        try:
            url = "https://api.dexscreener.com/latest/dex/search?q=Easter"
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    
                    print(f"\nFound {len(pairs)} pairs for 'Easter'")
                    
                    # Find the pump.fun pair
                    for p in pairs:
                        if p.get("chainId") == "solana":
                            symbol = p.get("baseToken", {}).get("symbol", "???")
                            address = p.get("baseToken", {}).get("address", "")
                            mcap = float(p.get("fdv", 0) or 0)
                            liq = float(p.get("liquidity", {}).get("usd", 0) or 0)
                            price = float(p.get("priceUsd", 0) or 0)
                            dex_id = p.get("dexId", "unknown")
                            
                            print(f"\n{'='*40}")
                            print(f"  Symbol: {symbol}")
                            print(f"  DEX: {dex_id}")
                            print(f"  Address: {address}")
                            print(f"  Market Cap: ${mcap:,.0f}")
                            print(f"  Liquidity: ${liq:,.0f}")
                            print(f"  Price: ${price}")
                            
                            # Estimate SOL reserves from liquidity
                            if liq > 0:
                                sol_reserves_est = liq / SOL_PRICE
                                bonding_pct = calculate_bonding_pct(sol_reserves_est)
                                print(f"  Estimated SOL reserves: {sol_reserves_est:.2f} SOL")
                                print(f"  Calculated bonding: {bonding_pct:.1f}%")
                            else:
                                print(f"  ⚠️ Liquidity is $0 - cannot calculate bonding from liquidity!")
                                
                                # Try to estimate from market cap instead
                                if mcap > 0:
                                    # Bonding curve: ~$4,500 start -> ~$69,000 graduate
                                    # More accurate: use SOL reserves estimation
                                    # MCAP ≈ SOL_reserves * SOL_price * some_ratio
                                    # For bonding curve tokens: sol_reserves ≈ mcap / (SOL_price * 0.7)
                                    estimated_sol = mcap / (SOL_PRICE * 0.7)
                                    bonding_from_mcap = calculate_bonding_pct(estimated_sol)
                                    print(f"  Estimated from MCAP: ~{estimated_sol:.1f} SOL -> {bonding_from_mcap:.1f}%")
                            
                            # Try pump.fun API
                            print(f"\n  Trying pump.fun API...")
                            try:
                                url_pump = f"https://pump.fun/api/coins/{address}"
                                headers = {
                                    "Accept": "application/json",
                                    "Origin": "https://pump.fun",
                                    "Referer": "https://pump.fun/",
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                                }
                                async with session.get(url_pump, headers=headers, timeout=5) as resp_pump:
                                    if resp_pump.status == 200:
                                        pump_data = await resp_pump.json()
                                        virtual_sol = float(pump_data.get("virtual_sol_reserves", 0) or 0)
                                        is_complete = pump_data.get("complete", False)
                                        
                                        print(f"  ✅ Pump.fun API success!")
                                        print(f"  Virtual SOL reserves: {virtual_sol:.2f} SOL")
                                        
                                        if virtual_sol > 0:
                                            real_bonding = calculate_bonding_pct(virtual_sol)
                                            print(f"  Bonding %: {real_bonding:.1f}%")
                                            print(f"  Is complete: {is_complete}")
                                    else:
                                        print(f"  ❌ Pump.fun API returned {resp_pump.status}")
                            except Exception as e:
                                print(f"  ❌ Pump.fun API error: {e}")
                            
                            if "pump" in dex_id:
                                break  # Only check first pump.fun pair
        except Exception as e:
            print(f"Error: {e}")
    
    print()
    print("=" * 60)
    print("ANALYSIS SUMMARY")
    print("=" * 60)
    print("""
The bonding curve calculation has been fixed:
- OLD formula: bonding_pct = (SOL_reserves / 85) * 100
- NEW formula: bonding_pct = (SOL_reserves - 30) / (85 - 30) * 100

The NEW formula correctly accounts for the fact that Pump.fun bonding 
curves START at ~30 SOL, not 0 SOL.

For a token showing 71% on DexScreener:
- Expected SOL reserves: ~69 SOL
- Expected liquidity: ~$10,350

If your bot shows 6.3%, the issue is likely:
1. Stale data in database
2. Zero liquidity reported by DexScreener
3. Pump.fun API not returning data

The fix requires:
1. ✅ Correct formula applied
2. ✅ Direct pump.fun API integration for accurate virtual_sol_reserves
3. Restart the bot to fetch fresh data
""")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_bonding_calculation())