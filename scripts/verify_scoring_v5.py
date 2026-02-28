import asyncio
import numpy as np
from early_detector.scoring import compute_instability
from early_detector.signals import calculate_quantitative_degen_score
from early_detector.smart_wallets import compute_swr
import pandas as pd

async def test_scoring_v5():
    print("=== TESTING SCORING ENGINE V5.1 ===")
    
    # Simuliamo alcuni Smart Wallet verificati (ROI alto, WinRate alto)
    # E un bot di rumore (Noise Bot)
    smart_wallet_stats = {
        "INSIDER_1": {"avg_roi": 55.4, "win_rate": 0.8, "cluster_label": "insider"},
        "SNIPER_1": {"avg_roi": 3.5, "win_rate": 0.6, "cluster_label": "sniper"},
        "NOISE_BOT": {"avg_roi": 1.0, "win_rate": 0.1, "cluster_label": "high_volume_noise"}
    }
    
    # Calcolo del global_q_score (come avviene nel main.py)
    global_q_score = sum(np.log1p(max(0, s.get("avg_roi", 1.0) - 1.0)) * (s.get("win_rate", 0.0) + 0.1) 
                         for s in smart_wallet_stats.values())
    print(f"Global Smart Wallet Quality Score: {global_q_score:.4f}")

    # Scenario A: Token con Insider reale
    active_a = ["INSIDER_1"]
    swr_a = compute_swr(active_a, smart_wallet_stats, global_q_score)
    
    # Scenario B: Token con solo Noise Bot
    active_b = ["NOISE_BOT"]
    swr_b = compute_swr(active_b, smart_wallet_stats, global_q_score)
    
    print(f"Scenario A (Insider): SWR = {swr_a:.4f}")
    print(f"Scenario B (Noise Bot): SWR = {swr_b:.4f}")

    # Test Degen Score
    token_data_a = {
        "symbol": "ALPHA",
        "swr": swr_a,
        "liquidity": 2500,
        "marketcap": 45000,
        "instability": 12.5,
        "has_noise_bots": False
    }
    
    token_data_b = {
        "symbol": "SCAM",
        "swr": swr_b,
        "liquidity": 1500,
        "marketcap": 120000,
        "instability": 2.0,
        "has_noise_bots": True
    }

    score_a = calculate_quantitative_degen_score(token_data_a, 0.6)
    score_b = calculate_quantitative_degen_score(token_data_b, 0.4)

    print(f"\nFINAL DEGEN SCORES:")
    print(f"Token ALPHA (Insider driven): {score_a} / 100")
    print(f"Token SCAM (Bot manipulated): {score_b} / 100")
    
    if score_a > score_b:
        print("\n✅ VERIFICA SUPERATA: Il sistema distingue correttamente gli insider dai bot.")
    else:
        print("\n❌ VERIFICA FALLITA: Il bilanciamento dei pesi non è ottimale.")

if __name__ == "__main__":
    asyncio.run(test_scoring_v5())
