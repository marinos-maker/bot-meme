"""
Debug script per verificare perché non arrivano segnali.
Eseguire con: python debug_signals.py
"""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import aiohttp
import pandas as pd
from loguru import logger

from early_detector.collector import fetch_token_metrics
from early_detector.features import compute_all_features
from early_detector.scoring import compute_instability, get_signal_threshold
from early_detector.signals import passes_trigger, passes_safety_filters, passes_quality_gate, calculate_quantitative_degen_score


async def debug_signal_flow():
    """Analizza il flusso completo di generazione segnali."""
    
    print("\n" + "=" * 70)
    print("  DEBUG SIGNAL FLOW - Analisi completa")
    print("=" * 70)
    
    # Token di test reali (presi dal log)
    test_tokens = [
        "6CadYeQkXYVfNQ6NhLN9nqLaGE5aJdLQvWvNLpqLpump",  # Peace Coin
        "DXVSXsmQzJkVKVnLshL2HuKwD9bQqEwJqbUzNvPFpump",  # The Safest Asset
        "3mSkYG7UqqKphzN7g5WwXVQZvMzFbKbT1R8P9LxEpump",  # My First War
        "5yw9KETDcGvJPHQqkZmWkVbFwLnTpXsYhR9UfMvApump",  # The Honey Badger
    ]
    
    async with aiohttp.ClientSession() as session:
        for token in test_tokens:
            print(f"\n{'='*70}")
            print(f"  TOKEN: {token[:12]}...")
            print("=" * 70)
            
            # Step 1: Fetch metrics
            print("\n[STEP 1] Fetching metrics...")
            metrics = await fetch_token_metrics(session, token)
            
            if not metrics:
                print("  ❌ BLOCCATO: Metrics = None (token morto o API error)")
                continue
            
            print(f"  ✅ Metrics OK:")
            print(f"     - Price: ${metrics.get('price', 0):.8f}")
            print(f"     - Market Cap: ${metrics.get('marketcap', 0):,.0f}")
            print(f"     - Liquidity: ${metrics.get('liquidity', 0):,.0f}")
            print(f"     - Volume 5m: ${metrics.get('volume_5m', 0):,.0f}")
            print(f"     - Buys/Sells 5m: {metrics.get('buys_5m', 0)}/{metrics.get('sells_5m', 0)}")
            
            # Step 2: Compute features
            print("\n[STEP 2] Computing features...")
            try:
                features = compute_all_features(metrics, {})
                if not features:
                    print("  ❌ BLOCCATO: Features = None")
                    continue
                print(f"  ✅ Features OK:")
                print(f"     - Vol Intensity: {features.get('vol_intensity', 0):.3f}")
                print(f"     - SWR: {features.get('swr', 0):.3f}")
                print(f"     - Vol Shift: {features.get('vol_shift', 0):.3f}")
                print(f"     - Sell Pressure: {features.get('sell_pressure', 0):.3f}")
            except Exception as e:
                print(f"  ❌ BLOCCATO: Feature error: {e}")
                continue
            
            # Step 3: Compute instability
            print("\n[STEP 3] Computing instability...")
            try:
                df = pd.DataFrame([features])
                df_scored = compute_instability(df)
                ii = df_scored.iloc[0].get('instability', 0)
                delta_ii = df_scored.iloc[0].get('delta_instability', 0)
                print(f"  ✅ Instability: II={ii:.3f}, dII={delta_ii:.3f}")
                features['instability'] = ii
                features['delta_instability'] = delta_ii
            except Exception as e:
                print(f"  ❌ BLOCCATO: Scoring error: {e}")
                continue
            
            # Step 4: Check threshold
            threshold = get_signal_threshold(df_scored['instability'])
            print(f"\n[STEP 4] Threshold check: II={ii:.3f} vs Threshold={threshold:.3f}")
            if ii < threshold:
                print(f"  ❌ BLOCCATO: II sotto threshold")
                continue
            print(f"  ✅ Sopra threshold")
            
            # Step 5: Trigger check
            print(f"\n[STEP 5] Trigger check...")
            trigger_result = passes_trigger(features, threshold)
            if not trigger_result:
                print(f"  ❌ BLOCCATO: Trigger fallito")
                continue
            print(f"  ✅ Trigger passato")
            
            # Step 6: Safety filters
            print(f"\n[STEP 6] Safety filters check...")
            print(f"     - Mint Authority: {metrics.get('mint_authority', 'None')}")
            print(f"     - Freeze Authority: {metrics.get('freeze_authority', 'None')}")
            print(f"     - Insider PSI: {features.get('insider_psi', 0):.3f}")
            print(f"     - Top10 Ratio: {features.get('top10_ratio', 0):.1f}%")
            print(f"     - Holders: {metrics.get('holders', 0)}")
            
            safety_result = passes_safety_filters(metrics)
            if not safety_result:
                print(f"  ❌ BLOCCATO: Safety filters falliti")
                continue
            print(f"  ✅ Safety filters passati")
            
            # Step 7: Degen score
            print(f"\n[STEP 7] Degen score...")
            degen_score = calculate_quantitative_degen_score(metrics, 0.5)
            print(f"     Degen Score: {degen_score}")
            ai_result = {"degen_score": degen_score}
            
            # Step 8: Quality gate
            print(f"\n[STEP 8] Quality gate check...")
            quality_result = passes_quality_gate(metrics, ai_result)
            if not quality_result:
                print(f"  ❌ BLOCCATO: Quality gate fallito")
                continue
            print(f"  ✅ Quality gate passato")
            
            # Final
            print(f"\n{'='*70}")
            print(f"  🎉 SEGNALE VALIDO! Token: {token[:12]}...")
            print(f"     II={ii:.3f}, Degen={degen_score}")
            print("=" * 70)


if __name__ == "__main__":
    asyncio.run(debug_signal_flow())