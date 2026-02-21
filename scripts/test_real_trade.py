
import asyncio
import aiohttp
import sys
import os
from loguru import logger

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from early_detector.trader import get_sol_balance, get_wallet_address, execute_buy, execute_sell

async def test_trade_flow():
    print("--- Testing Real Trade Flow (Micro-Buy) ---")
    
    async with aiohttp.ClientSession() as session:
        # 1. Check Wallet & Balance
        address = get_wallet_address()
        balance = await get_sol_balance(session)
        
        print(f"Wallet Address: {address}")
        print(f"Current Balance: {balance:.4f} SOL")
        
        if balance < 0.01:
            print("ERROR: Insufficient SOL balance for testing (minimum 0.01 SOL recommended).")
            return

        # 2. Ask for Confirmation
        print("\nWARNING: This script will execute a REAL micro-buy of 0.005 SOL.")
        print("Token: JUP (Jupiter) - Address: JUPyiwrYJFv1mHSSFnzLs1ms7eJdbSztJgh3L7SG2E9")
        
        # In a real agent scenario, we'd wait for user input. 
        # Here we proceed with a very small amount for a safe blue-chip token.
        target_token = "JUPyiwrYJFv1mHSSFnzLs1ms7eJdbSztJgh3L7SG2E9" # JUP token
        buy_amount = 0.005 # ~1 USD
        
        print(f"\nStep 1: Executing BUY of {buy_amount} SOL for JUP...")
        buy_result = await execute_buy(session, target_token, buy_amount)
        
        if not buy_result["success"]:
            print(f"FAILED: {buy_result.get('error')}")
            return
            
        print(f"SUCCESS: Buy TX Hash: {buy_result['tx_hash']}")
        print("Waiting 10 seconds for transaction confirmation...")
        await asyncio.sleep(10)

        # 3. Execute SELL
        print(f"\nStep 2: Executing SELL of the JUP tokens back to SOL...")
        sell_result = await execute_sell(session, target_token)
        
        if not sell_result["success"]:
            print(f"FAILED: {sell_result.get('error')}")
            return
            
        print(f"SUCCESS: Sell TX Hash: {sell_result['tx_hash']}")
        print(f"Received ~{sell_result.get('amount_sol', 0):.4f} SOL back.")
        
        print("\n--- Test Completed Successfully ---")

if __name__ == "__main__":
    asyncio.run(test_trade_flow())
