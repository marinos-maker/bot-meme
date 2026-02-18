import pytest
from early_detector.signals import passes_safety_filters

def test_safety_high_creator_risk():
    token = {
        "creator_risk_score": 0.9,
        "instability": 2.5
    }
    assert passes_safety_filters(token) is False

def test_safety_low_creator_risk():
    token = {
        "creator_risk_score": 0.1,
        "instability": 2.5
    }
    assert passes_safety_filters(token) is True

def test_safety_mint_auth_enabled():
    token = {
        "mint_authority": "SomeAddress",
        "creator_risk_score": 0.1
    }
    assert passes_safety_filters(token) is False
