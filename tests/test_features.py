import pytest
import numpy as np
from early_detector.features import compute_liquidity_acceleration, compute_volume_hhi, compute_dip_recovery

def test_hhi_concentration():
    # 1 whale (100% volume) -> HHI = 1.0
    data = [{"volume": 100}]
    assert compute_volume_hhi(data) == 1.0

def test_hhi_distributed():
    # 2 equal buyers -> HHI = 0.5^2 + 0.5^2 = 0.5
    data = [{"volume": 50}, {"volume": 50}]
    assert compute_volume_hhi(data) == 0.5

def test_hhi_diverse():
    # 100 equal buyers -> HHI = 100 * (0.01^2) = 0.01
    data = [{"volume": 1} for _ in range(100)]
    assert abs(compute_volume_hhi(data) - 0.01) < 1e-5

def test_liquidity_acceleration():
    # Linear growth -> 0 acceleration
    # 10, 20, 30
    liq = np.array([10, 20, 30])
    acc = compute_liquidity_acceleration(liq)
    # (30 - 2*20 + 10) = 0
    assert acc == 0.0

    # Exponential growth -> positive acceleration
    # 10, 20, 40
    liq = np.array([10, 20, 40])
    acc = compute_liquidity_acceleration(liq)
    # (40 - 2*20 + 10) = 10 / 40 = 0.25 (approx)
    assert acc > 0

def test_dip_recovery_full():
    # Low was 10, High was 20, Current is 20 -> 1.0
    price = np.array([20, 10, 15, 20])
    assert compute_dip_recovery(price) == 1.0

def test_dip_recovery_none():
    # Low was 10, High was 20, Current is 10 -> 0.0
    price = np.array([20, 15, 10])
    assert compute_dip_recovery(price) == 0.0
