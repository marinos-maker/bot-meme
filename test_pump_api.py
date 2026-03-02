"""
Test script to find the correct pump.fun API endpoint for bonding curve data.
"""
import asyncio
import aiohttp

async def test_pump_apis():
    """Test different pump.fun API endpoints."""
    
    # SEN token address
    token_address = "5VAwWVPdjQJjGQbgqEwE4QV7yFvNnGpLPbZXF1Qpump"
    
    async with aiohttp.ClientSession() as session:
        # Test 1: pump.fun/api/coins (current)
        print("=" * 60)
        print("Test 1: pump.fun/api/coins/{address}")
        print("=" * 60)
        try:
            url = f"https://pump.fun/api/coins/{token_address}"
            headers = {
                "Accept": "application/json",
                "Origin": "https://pump.fun",
                "Referer": "https://pump.fun/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            async with session.get(url, headers=headers, timeout=10) as resp:
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Keys: {list(data.keys())}")
                    print(f"virtual_sol_reserves: {data.get('virtual_sol_reserves')}")
                    print(f"complete: {data.get('complete')}")
                else:
                    text = await resp.text()
                    print(f"Response: {text[:200]}")
        except Exception as e:
            print(f"Error: {e}")
        
        # Test 2: pump.fun/coin/{address} (frontend page - parse HTML)
        print("\n" + "=" * 60)
        print("Test 2: pump.fun/coin/{address} (frontend)")
        print("=" * 60)
        try:
            url = f"https://pump.fun/coin/{token_address}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            async with session.get(url, headers=headers, timeout=10) as resp:
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    text = await resp.text()
                    
                    # Check what's in the page
                    print(f"Page length: {len(text)} chars")
                    
                    # Look for bonding curve data in the HTML/JS
                    if "virtual_sol_reserves" in text:
                        print("✅ Found virtual_sol_reserves in response!")
                    if "bonding" in text.lower():
                        print("✅ Found 'bonding' in response!")
                    
                    # Find __NEXT_DATA__ or similar
                    import json
                    import re
                    
                    if "__NEXT_DATA__" in text:
                        print("✅ Found __NEXT_DATA__!")
                        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', text, re.DOTALL)
                        if match:
                            try:
                                data = json.loads(match.group(1))
                                print(f"__NEXT_DATA__ keys: {list(data.keys())}")
                                props = data.get("props", {}).get("pageProps", {})
                                print(f"pageProps keys: {list(props.keys())}")
                                if "coin" in props:
                                    coin = props["coin"]
                                    print(f"\n✅ COIN DATA FOUND!")
                                    print(f"  virtual_sol_reserves: {coin.get('virtual_sol_reserves')}")
                                    print(f"  complete: {coin.get('complete')}")
                                    print(f"  usd_market_cap: {coin.get('usd_market_cap')}")
                            except json.JSONDecodeError as je:
                                print(f"JSON parse error: {je}")
                    else:
                        print("❌ __NEXT_DATA__ not found")
                        
                    # Try to find any JSON with virtual_sol_reserves
                    json_pattern = re.compile(r'\{[^{}]*"virtual_sol_reserves"[^{}]*\}', re.DOTALL)
                    matches = json_pattern.findall(text)
                    if matches:
                        print(f"\n✅ Found {len(matches)} JSON objects with virtual_sol_reserves!")
                        for m in matches[:1]:  # Show first match
                            try:
                                data = json.loads(m)
                                print(f"  virtual_sol_reserves: {data.get('virtual_sol_reserves')}")
                                print(f"  complete: {data.get('complete')}")
                            except:
                                print(f"  Raw match: {m[:200]}...")
                    
                    # Try to find "bonding_curve" or similar patterns
                    if "bonding_curve" in text:
                        print("\n✅ Found 'bonding_curve' in text!")
                    
                    # Search for SOL reserves number pattern (e.g., "46,681 SOL")
                    sol_pattern = re.compile(r'[\d,]+\s*SOL\s+in\s+bonding', re.IGNORECASE)
                    sol_matches = sol_pattern.findall(text)
                    if sol_matches:
                        print(f"\n✅ Found SOL in bonding pattern: {sol_matches}")
                    
                    # Search for graduation threshold
                    grad_pattern = re.compile(r'\$[\d,]+\s+to\s+graduate', re.IGNORECASE)
                    grad_matches = grad_pattern.findall(text)
                    if grad_matches:
                        print(f"\n✅ Found graduation pattern: {grad_matches}")
                    
                    # Search for progress percentage (e.g., "83.0%")
                    progress_pattern = re.compile(r'Progress[^<]*?(\d+\.?\d*%)', re.IGNORECASE)
                    progress_matches = progress_pattern.findall(text)
                    if progress_matches:
                        print(f"\n✅ Found progress: {progress_matches}")
                    
                    # Print a snippet around "bonding" keyword
                    bonding_idx = text.lower().find("bonding")
                    if bonding_idx > 0:
                        snippet = text[max(0, bonding_idx-100):bonding_idx+200]
                        print(f"\n📝 Snippet around 'bonding':")
                        print(f"  {snippet[:300]}")
        except Exception as e:
            print(f"Error: {e}")
        
        # Test 3: frontend-api.pump.fun
        print("\n" + "=" * 60)
        print("Test 3: frontend-api.pump.fun/coins/{address}")
        print("=" * 60)
        try:
            url = f"https://frontend-api.pump.fun/coins/{token_address}"
            headers = {
                "Accept": "application/json",
                "Origin": "https://pump.fun",
                "Referer": "https://pump.fun/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            async with session.get(url, headers=headers, timeout=10) as resp:
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Keys: {list(data.keys())}")
                    print(f"\n✅ DATA FOUND!")
                    print(f"  virtual_sol_reserves: {data.get('virtual_sol_reserves')}")
                    print(f"  virtual_token_reserves: {data.get('virtual_token_reserves')}")
                    print(f"  complete: {data.get('complete')}")
                    print(f"  usd_market_cap: {data.get('usd_market_cap')}")
                    
                    # Calculate bonding progress
                    virtual_sol = float(data.get('virtual_sol_reserves', 0) or 0)
                    START_SOL = 30.0
                    GRADUATION_SOL = 85.0
                    if virtual_sol > 0:
                        bonding_pct = ((virtual_sol - START_SOL) / (GRADUATION_SOL - START_SOL)) * 100
                        print(f"\n  Calculated bonding: {bonding_pct:.1f}%")
                else:
                    text = await resp.text()
                    print(f"Response: {text[:200]}")
        except Exception as e:
            print(f"Error: {e}")
        
        # Test 4: Try with different coin ID format
        print("\n" + "=" * 60)
        print("Test 4: frontend-api.pump.fun/coin/{address} (singular)")
        print("=" * 60)
        try:
            url = f"https://frontend-api.pump.fun/coin/{token_address}"
            headers = {
                "Accept": "application/json",
                "Origin": "https://pump.fun",
                "Referer": "https://pump.fun/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            async with session.get(url, headers=headers, timeout=10) as resp:
                print(f"Status: {resp.status}")
                if resp.status == 200:
                    data = await resp.json()
                    print(f"Keys: {list(data.keys())}")
                    print(f"  virtual_sol_reserves: {data.get('virtual_sol_reserves')}")
                    print(f"  complete: {data.get('complete')}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_pump_apis())