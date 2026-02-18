import pytest
from early_detector.smart_wallets import compute_insider_score
from early_detector.signals import passes_trigger, passes_safety_filters

# ── Insider Score Tests ────────────────────────────────────────────────

def test_insider_score_fresh_early():
    # Fresh wallet (empty stats) + Early entry (< 2 min) + Pair created
    wallet_stats = {}
    pair_created = 1700000000000 # ms
    first_trade = 1700000000 + 60 # sec (1 min later)
    
    score = compute_insider_score(wallet_stats, first_trade, pair_created)
    # Expect: 0.4 (early < 2m) + 0.3 (fresh < 5 trades) = 0.7
    assert score == 0.7

def test_insider_score_late_active():
    # Active wallet (> 5 trades) + Late entry (> 5 min)
    wallet_stats = {"total_trades": 10}
    pair_created = 1700000000000 # ms
    first_trade = 1700000000 + 600 # sec (10 min later)
    
    score = compute_insider_score(wallet_stats, first_trade, pair_created)
    # Expect: 0.0
    assert score == 0.0

def test_insider_score_fresh_mid_entry():
    # Fresh wallet + Entry 3 min later
    wallet_stats = {}
    pair_created = 1700000000000 # ms
    first_trade = 1700000000 + 180 # sec (3 min later)
    
    score = compute_insider_score(wallet_stats, first_trade, pair_created)
    # Expect: 0.2 (2-5 min) + 0.3 (fresh) = 0.5
    assert score == 0.5

# ── Momentum Tests ─────────────────────────────────────────────────────

def test_trigger_rising_momentum():
    # High II + Positive Delta
    token = {
        "instability": 2.5,
        "delta_instability": 0.5,
        "liquidity": 50000,
        "marketcap": 100000,
        "top10_ratio": 0.1
    }
    threshold = 2.0
    assert passes_trigger(token, threshold) is True

def test_trigger_falling_momentum():
    # High II + Negative Delta (Peaking)
    token = {
        "instability": 2.5,
        "delta_instability": -0.1,
        "liquidity": 50000,
        "marketcap": 100000,
        "top10_ratio": 0.1
    }
    threshold = 2.0
    assert passes_trigger(token, threshold) is False

def test_trigger_low_ii():
    # Low II + Positive Delta
    token = {
        "instability": 1.5,
        "delta_instability": 0.5,
        "liquidity": 50000,
        "marketcap": 100000,
        "top10_ratio": 0.1
    }
    threshold = 2.0
    assert passes_trigger(token, threshold) is False

# ── Insider Safety Filter Tests ────────────────────────────────────────

def test_safety_high_insider_risk():
    token = {
        "insider_psi": 0.85,
        "top10_ratio": 0.1
    }
    assert passes_safety_filters(token) is False

def test_safety_low_insider_risk():
    token = {
        "insider_psi": 0.4,
        "top10_ratio": 0.1
    }
    assert passes_safety_filters(token) is True
