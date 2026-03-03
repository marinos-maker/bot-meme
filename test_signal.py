import asyncio
import aiohttp
from loguru import logger
from early_detector.db import get_pool, close_pool, upsert_token
from early_detector.signals import process_signals
import pandas as pd

async def test_signal_generation():
    print("Starting signal generation test...")
    await get_pool()
    
    # Create a fake healthy token
    address = "TEST_TOKEN_" + str(int(asyncio.get_event_loop().time()))
    token_id = await upsert_token(address, "Test Token", "TEST", narrative="AI")
    
    # Mock some healthy features
    # SWR high, Liquidity real, Low risks
    token_data = {
        "address": address,
        "token_id": token_id,
        "symbol": "TEST",
        "name": "Test Token",
        "instability": 15.0,
        "price": 0.0001,
        "liquidity": 5000.0,
        "marketcap": 50000.0,
        "holders": 150,
        "top10_ratio": 30.0,
        "swr": 2.5,
        "insider_psi": 0.05,
        "insider_psi_verified": True,
        "creator_risk_score": 0.05,
        "creator_risk_score_verified": True,
        "vol_intensity": 1.2,
        "buys_5m": 25,
        "sells_5m": 5,
        "sa": 2.0,
        "holder_acc": 3.0,
        "vol_shift": 1.5,
        "sell_pressure": 0.1,
        "liquidity_is_virtual": False,
        "delta_instability": 5.0
    }
    
    df = pd.DataFrame([token_data])
    threshold = 5.0
    
    print(f"Testing signal for {address} with threshold {threshold}...")
    signals = await process_signals(df, threshold, regime_label="STABLE")
    
    if signals:
        print(f"SUCCESS: Generated {len(signals)} signals!")
        for s in signals:
            print(f"Signal: {s['symbol']} - Conf: {s['confidence']:.2%}, Kelly: {s['kelly_size']:.2%}")
    else:
        print("FAILED: No signals generated. Check Quality Gate or Bayesian logic.")

    await close_pool()

if __name__ == "__main__":
    asyncio.run(test_signal_generation())
