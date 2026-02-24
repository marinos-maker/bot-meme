
import asyncio
import sys
import os
from loguru import logger

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from early_detector.signals import send_telegram_alert

async def test_telegram():
    print("--- Testing Telegram Integration ---")
    
    # Dummy signal for testing
    dummy_signal = {
        "symbol": "TEST",
        "name": "Telegram Test Token",
        "instability_index": 0.852,
        "price": 0.00004567,
        "liquidity": 150000,
        "marketcap": 1200000,
        "confidence": 0.65,
        "kelly_size": 0.15,
        "insider_psi": 0.12,
        "address": "So11111111111111111111111111111111111111112", # SOL for the links
        "hard_stop": 0.00003882,
        "tp_1": 0.00006394,
        "creator_risk": 0.05,
        "top10_ratio": 12.5,
        "degen_score": 88,
        "ai_summary": "Ottimo slancio iniziale, basso rischio di creator rug e insider, potenziale breakout parabolico in atto."
    }

    print("Sending test signal to Telegram...")
    await send_telegram_alert(dummy_signal)
    print("Done. Check your Telegram chat!")

if __name__ == "__main__":
    asyncio.run(test_telegram())
