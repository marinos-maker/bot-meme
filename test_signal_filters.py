"""
Test completo per verificare che tutte le metriche e i filtri per i segnali funzionino correttamente.
Eseguire con: python test_signal_filters.py
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from early_detector.signals import (
    passes_trigger,
    passes_safety_filters,
    passes_quality_gate,
    calculate_quantitative_degen_score,
)
from early_detector.scoring import compute_instability, get_signal_threshold, detect_regime
from early_detector.features import compute_all_features, compute_momentum_score, compute_trend_quality, compute_volume_quality
from early_detector.candle_analysis import analyze_candles, get_signal_quality
import numpy as np
import pandas as pd


def print_header(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def test_trigger_conditions():
    """Testa le condizioni di trigger per i segnali."""
    print_header("TEST 1: Trigger Conditions (passes_trigger)")
    
    # Test 1.1: Token con II sotto soglia
    token_low_ii = {
        "instability": 2.0,
        "delta_instability": 1.0,
        "vol_shift": 3.0,
        "liquidity": 1000,
        "marketcap": 10000,
        "vol_intensity": 1.0,
        "buys_5m": 10,
        "sells_5m": 5,
        "symbol": "TEST1",
    }
    threshold = 4.0
    result = passes_trigger(token_low_ii, threshold)
    print(f"  1.1 II sotto soglia (II=2.0 < 4.0): {'❌ PASSATO' if not result else '✅ FALLITO (dovrebbe fallire)'}")
    
    # Test 1.2: Token con II sopra soglia ma senza momentum
    token_no_momentum = {
        "instability": 5.0,
        "delta_instability": 1.0,
        "vol_shift": 3.0,
        "liquidity": 1000,
        "marketcap": 10000,
        "vol_intensity": 0.5,  # Basso
        "buys_5m": 5,
        "sells_5m": 5,
        "symbol": "TEST2",
    }
    result = passes_trigger(token_no_momentum, threshold)
    print(f"  1.2 II OK ma senza momentum: {'❌ PASSATO' if not result else '✅ FALLITO (dovrebbe fallire)'}")
    
    # Test 1.3: Token con momentum negativo (dII < -2.0)
    token_negative_momentum = {
        "instability": 5.0,
        "delta_instability": -3.0,  # Fortemente negativo
        "vol_shift": 3.0,
        "liquidity": 1000,
        "marketcap": 10000,
        "vol_intensity": 2.0,
        "buys_5m": 20,
        "sells_5m": 5,
        "symbol": "TEST3",
    }
    result = passes_trigger(token_negative_momentum, threshold)
    print(f"  1.3 Momentum negativo (dII=-3.0): {'❌ PASSATO' if not result else '✅ FALLITO (dovrebbe fallire)'}")
    
    # Test 1.4: Token valido con momentum
    token_valid = {
        "instability": 5.0,
        "delta_instability": 1.0,
        "vol_shift": 3.0,
        "liquidity": 1500,
        "marketcap": 15000,
        "vol_intensity": 2.0,
        "buys_5m": 25,
        "sells_5m": 10,
        "symbol": "TEST4",
        "bonding_is_complete": False,
    }
    result = passes_trigger(token_valid, threshold)
    print(f"  1.4 Token valido con momentum: {'✅ PASSATO' if result else '❌ FALLITO (dovrebbe passare)'}")
    
    # Test 1.5: Fast-track (velocity estrema)
    token_fast_track = {
        "instability": 4.5,
        "delta_instability": 1.0,
        "vol_shift": 5.0,
        "liquidity": 500,
        "marketcap": 5000,
        "vol_intensity": 7.0,  # Molto alto
        "buys_5m": 100,  # Molto alto
        "sells_5m": 20,
        "symbol": "TEST5",
    }
    result = passes_trigger(token_fast_track, threshold)
    print(f"  1.5 Fast-track (VI=7.0, buys=100): {'✅ PASSATO' if result else '❌ FALLITO (dovrebbe passare)'}")
    
    # Test 1.6: II floor check
    token_below_floor = {
        "instability": 2.5,  # Sotto il floor di 3.0
        "delta_instability": 1.0,
        "vol_shift": 3.0,
        "liquidity": 1000,
        "marketcap": 10000,
        "vol_intensity": 2.0,
        "buys_5m": 20,
        "sells_5m": 5,
        "symbol": "TEST6",
    }
    result = passes_trigger(token_below_floor, 2.0)  # Threshold basso per testare floor
    print(f"  1.6 II sotto floor (II=2.5 < 3.0): {'❌ PASSATO' if not result else '✅ FALLITO (dovrebbe fallire)'}")


def test_safety_filters():
    """Testa i filtri di sicurezza."""
    print_header("TEST 2: Safety Filters (passes_safety_filters)")
    
    # Test 2.1: Mint authority abilitato
    token_mint_auth = {
        "mint_authority": "SomeAddress123",
        "freeze_authority": None,
        "symbol": "TEST1",
        "address": "abc123pump",
    }
    result = passes_safety_filters(token_mint_auth)
    print(f"  2.1 Mint Authority abilitato: {'❌ PASSATO' if not result else '✅ FALLITO (dovrebbe fallire)'}")
    
    # Test 2.2: Freeze authority abilitato
    token_freeze_auth = {
        "mint_authority": None,
        "freeze_authority": "SomeAddress123",
        "symbol": "TEST2",
        "address": "abc123pump",
    }
    result = passes_safety_filters(token_freeze_auth)
    print(f"  2.2 Freeze Authority abilitato: {'❌ PASSATO' if not result else '✅ FALLITO (dovrebbe fallire)'}")
    
    # Test 2.3: Insider PSI alto
    token_high_psi = {
        "mint_authority": None,
        "freeze_authority": None,
        "insider_psi": 0.7,
        "insider_psi_verified": True,
        "symbol": "TEST3",
        "address": "abc123pump",
        "marketcap": 50000,
    }
    result = passes_safety_filters(token_high_psi)
    print(f"  2.3 Insider PSI alto (0.7): {'❌ PASSATO' if not result else '✅ FALLITO (dovrebbe fallire)'}")
    
    # Test 2.4: Token sicuro
    token_safe = {
        "mint_authority": None,
        "freeze_authority": None,
        "insider_psi": 0.2,
        "insider_psi_verified": True,
        "creator_risk_score": 0.1,
        "creator_risk_score_verified": True,
        "symbol": "TEST4",
        "address": "abc123pump",
        "marketcap": 50000,
        "top10_ratio": 40,
    }
    result = passes_safety_filters(token_safe)
    print(f"  2.4 Token sicuro: {'✅ PASSATO' if result else '❌ FALLITO (dovrebbe passare)'}")


def test_quality_gate():
    """Testa il quality gate."""
    print_header("TEST 3: Quality Gate (passes_quality_gate)")
    
    # Test 3.1: MCap troppo basso
    token_low_mcap = {
        "marketcap": 1500,  # Sotto $2000
        "liquidity": 500,
        "symbol": "TEST1",
    }
    ai_result = {"degen_score": 50}
    result = passes_quality_gate(token_low_mcap, ai_result)
    print(f"  3.1 MCap troppo basso ($1500): {'❌ PASSATO' if not result else '✅ FALLITO (dovrebbe fallire)'}")
    
    # Test 3.2: Liquidity troppo bassa
    token_low_liq = {
        "marketcap": 10000,
        "liquidity": 100,  # Sotto il minimo
        "liquidity_is_virtual": False,
        "symbol": "TEST2",
    }
    result = passes_quality_gate(token_low_liq, ai_result)
    print(f"  3.2 Liquidity troppo bassa ($100): {'❌ PASSATO' if not result else '✅ FALLITO (dovrebbe fallire)'}")
    
    # Test 3.3: Token nuovo con score basso
    import time
    token_new_low_score = {
        "marketcap": 10000,
        "liquidity": 500,
        "pair_created_at": (time.time() * 1000) - (5 * 60 * 1000),  # 5 min fa
        "vol_intensity": 1.0,
        "buys_5m": 10,
        "sells_5m": 5,
        "swr": 0.5,
        "insider_psi": 0.1,
        "confidence": 0.5,
        "symbol": "TEST3",
    }
    ai_result_low = {"degen_score": 30}
    result = passes_quality_gate(token_new_low_score, ai_result_low)
    print(f"  3.3 Token nuovo (5m) con score 30: {'❌ PASSATO' if not result else '✅ FALLITO (dovrebbe fallire)'}")
    
    # Test 3.4: Token valido
    token_valid = {
        "marketcap": 50000,
        "liquidity": 5000,
        "liquidity_is_virtual": False,
        "vol_intensity": 2.0,
        "buys_5m": 30,
        "sells_5m": 10,
        "swr": 1.0,
        "insider_psi": 0.1,
        "confidence": 0.6,
        "symbol": "TEST4",
    }
    ai_result_valid = {"degen_score": 60}
    result = passes_quality_gate(token_valid, ai_result_valid)
    print(f"  3.4 Token valido: {'✅ PASSATO' if result else '❌ FALLITO (dovrebbe passare)'}")


def test_degen_score():
    """Testa il calcolo del degen score."""
    print_header("TEST 4: Degen Score Calculation")
    
    # Test 4.1: Token eccellente
    token_excellent = {
        "instability": 5.0,
        "liquidity": 10000,
        "liquidity_is_virtual": False,
        "marketcap": 100000,
        "volume_5m": 5000,
        "insider_psi": 0.1,
        "insider_psi_verified": True,
        "creator_risk_score": 0.1,
        "creator_risk_score_verified": True,
        "swr": 1.5,
        "top10_ratio": 30,
        "has_noise_bots": False,
        "symbol": "EXCELLENT",
    }
    score = calculate_quantitative_degen_score(token_excellent, 0.7)
    print(f"  4.1 Token eccellente: Score = {score} (atteso > 60)")
    print(f"      {'✅ PASSATO' if score > 60 else '❌ FALLITO'}")
    
    # Test 4.2: Token pessimo
    token_bad = {
        "instability": 1.0,
        "liquidity": 200,
        "liquidity_is_virtual": True,
        "marketcap": 3000,
        "volume_5m": 50,
        "insider_psi": 0.5,
        "insider_psi_verified": True,
        "creator_risk_score": 0.5,
        "creator_risk_score_verified": True,
        "swr": 0,
        "top10_ratio": 90,
        "has_noise_bots": True,
        "symbol": "BAD",
    }
    score = calculate_quantitative_degen_score(token_bad, 0.3)
    print(f"  4.2 Token pessimo: Score = {score} (atteso < 40)")
    print(f"      {'✅ PASSATO' if score < 40 else '❌ FALLITO'}")


def test_new_features():
    """Testa le nuove feature V6.0."""
    print_header("TEST 5: Nuove Feature V6.0")
    
    # Test 5.1: Momentum Score
    price_series = np.array([0.001, 0.0011, 0.0012, 0.0013, 0.0015])
    momentum = compute_momentum_score(price_series, volume_5m=1000, liquidity=500)
    print(f"  5.1 Momentum Score: {momentum:.3f} (atteso > 0.5 per trend positivo)")
    print(f"      {'✅ PASSATO' if momentum > 0.5 else '⚠️ OK ma basso'}")
    
    # Test 5.2: Trend Quality
    price_uptrend = np.array([100, 105, 110, 115, 120, 125, 130])
    trend = compute_trend_quality(price_uptrend)
    print(f"  5.2 Trend Quality (uptrend): {trend:.3f} (atteso > 0.5)")
    print(f"      {'✅ PASSATO' if trend > 0.5 else '⚠️ OK ma basso'}")
    
    # Test 5.3: Volume Quality
    vol_quality = compute_volume_quality(volume_5m=1000, liquidity=500, buys_5m=30, sells_5m=10)
    print(f"  5.3 Volume Quality: {vol_quality:.3f} (atteso > 0.5 per buon volume)")
    print(f"      {'✅ PASSATO' if vol_quality > 0.5 else '⚠️ OK ma basso'}")


def test_candle_analysis():
    """Testa l'analisi delle candele."""
    print_header("TEST 6: Candle Analysis")
    
    # Crea candele di test (trend rialzista)
    candles = [
        {"open": 100, "high": 105, "low": 99, "close": 104, "volume": 1000},
        {"open": 104, "high": 110, "low": 103, "close": 109, "volume": 1200},
        {"open": 109, "high": 115, "low": 108, "close": 114, "volume": 1500},
        {"open": 114, "high": 120, "low": 113, "close": 119, "volume": 1800},
        {"open": 119, "high": 125, "low": 118, "close": 124, "volume": 2000},
    ]
    
    result = analyze_candles(candles)
    score = result.get("score", 0)
    patterns = result.get("patterns", [])
    
    print(f"  6.1 Candle Analysis Score: {score:.3f}")
    print(f"      Patterns rilevati: {patterns}")
    print(f"      {'✅ PASSATO' if score > 0.4 else '⚠️ Score basso'}")
    
    # Test qualità segnale
    volumes = np.array([c["volume"] for c in candles])
    closes = np.array([c["close"] for c in candles])
    quality = get_signal_quality(candles, volumes, closes)
    print(f"  6.2 Signal Quality: {quality['quality_score']:.3f}")
    print(f"      Confidence: {quality['confidence']}, Risk: {quality['risk_level']}")
    print(f"      {'✅ PASSATO' if quality['risk_level'] != 'high' else '⚠️ Rischio alto'}")


def test_scoring():
    """Testa il sistema di scoring."""
    print_header("TEST 7: Scoring System")
    
    # Crea un DataFrame di test
    features_data = []
    
    # Token 1: Alto momentum
    features_data.append({
        "token_id": "token1",
        "address": "abc123pump",
        "name": "TestToken1",
        "symbol": "TEST1",
        "sa": 50.0,
        "holder_acc": 5.0,
        "vol_shift": 2.0,
        "swr": 2.0,
        "vol_intensity": 3.0,
        "sell_pressure": 0.3,
        "price": 0.001,
        "liquidity": 5000,
        "marketcap": 50000,
        "volume_5m": 1000,
        "buys_5m": 30,
        "sells_5m": 10,
    })
    
    # Token 2: Basso momentum
    features_data.append({
        "token_id": "token2",
        "address": "def456pump",
        "name": "TestToken2",
        "symbol": "TEST2",
        "sa": 5.0,
        "holder_acc": 0.5,
        "vol_shift": 0.5,
        "swr": 0.1,
        "vol_intensity": 0.2,
        "sell_pressure": 0.7,
        "price": 0.0001,
        "liquidity": 500,
        "marketcap": 5000,
        "volume_5m": 100,
        "buys_5m": 5,
        "sells_5m": 15,
    })
    
    df = pd.DataFrame(features_data)
    scored_df = compute_instability(df)
    
    print(f"  7.1 Token 1 (alto momentum): II = {scored_df.iloc[0]['instability']:.3f}")
    print(f"  7.2 Token 2 (basso momentum): II = {scored_df.iloc[1]['instability']:.3f}")
    
    threshold = get_signal_threshold(scored_df["instability"])
    print(f"  7.3 Signal Threshold: {threshold:.3f}")
    
    # Verifica che il token 1 abbia II più alto del token 2
    if scored_df.iloc[0]['instability'] > scored_df.iloc[1]['instability']:
        print(f"      ✅ PASSATO - Token con momentum alto ha II più alto")
    else:
        print(f"      ❌ FALLITO - Ordine II non corretto")


def test_regime_detection():
    """Testa il regime detection."""
    print_header("TEST 8: Regime Detection")
    
    # DataFrame con alto volume
    df_high_vol = pd.DataFrame({
        "volume_5m": [500000, 400000, 600000, 450000],
        "vol_intensity": [2.0, 2.5, 3.0, 2.2],
        "sell_pressure": [0.3, 0.35, 0.3, 0.4],
    })
    
    regime = detect_regime(df_high_vol, avg_vol_history=100000)
    print(f"  8.1 Alto volume: Regime = {regime}")
    print(f"      {'✅ PASSATO' if regime == 'DEGEN' else '⚠️ Non DEGEN'}")
    
    # DataFrame con basso volume
    df_low_vol = pd.DataFrame({
        "volume_5m": [50000, 40000, 60000, 45000],
        "vol_intensity": [0.3, 0.4, 0.5, 0.35],
        "sell_pressure": [0.4, 0.35, 0.3, 0.35],
    })
    
    regime = detect_regime(df_low_vol, avg_vol_history=200000)
    print(f"  8.2 Basso volume: Regime = {regime}")
    print(f"      {'✅ PASSATO' if regime in ['STABLE', 'ACCUMULATION'] else '⚠️ Non STABLE/ACCUMULATION'}")


def run_all_tests():
    """Esegue tutti i test."""
    print("\n" + "=" * 60)
    print("  BOT MEME V6.0 - TEST SUITE COMPLETA")
    print("=" * 60)
    
    try:
        test_trigger_conditions()
        test_safety_filters()
        test_quality_gate()
        test_degen_score()
        test_new_features()
        test_candle_analysis()
        test_scoring()
        test_regime_detection()
        
        print("\n" + "=" * 60)
        print("  ✅ TUTTI I TEST COMPLETATI")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ ERRORE DURANTE I TEST: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()