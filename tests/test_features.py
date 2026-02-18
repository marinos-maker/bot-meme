"""Unit tests for the feature engineering module."""

import numpy as np
import pytest
from early_detector.features import (
    holder_acceleration,
    stealth_accumulation,
    volatility_shift,
    sell_pressure,
    compute_all_features,
)


class TestHolderAcceleration:
    def test_positive_acceleration(self):
        # holders: 100, 90, 85 → v1=10, v2=5 → acc=5/101 ≈ 0.0495
        result = holder_acceleration(100, 90, 85)
        assert result == pytest.approx(5 / 101, rel=1e-5)

    def test_negative_acceleration(self):
        # holders: 100, 95, 85 → v1=5, v2=10 → acc=-5/101
        result = holder_acceleration(100, 95, 85)
        assert result == pytest.approx(-5 / 101, rel=1e-5)

    def test_zero_acceleration(self):
        # holders: 100, 90, 80 → v1=10, v2=10 → acc=0
        result = holder_acceleration(100, 90, 80)
        assert result == pytest.approx(0.0, abs=1e-9)

    def test_zero_holders(self):
        result = holder_acceleration(0, 0, 0)
        assert result == pytest.approx(0.0, abs=1e-9)


class TestStealthAccumulation:
    def test_perfect_accumulation(self):
        # 10 buyers, 0 sells, 5 buys, stable price
        prices = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
        result = stealth_accumulation(10, 0, 5, prices)
        # sell_ratio = 0, stability = 1.0 → SA = 10 * 1 * 1 = 10
        assert result == pytest.approx(10.0, rel=1e-3)

    def test_high_sell_ratio(self):
        prices = np.array([1.0, 1.0, 1.0])
        result = stealth_accumulation(10, 5, 5, prices)
        # sell_ratio = 1.0 → SA = 10 * 0 * 1 = 0
        assert result == pytest.approx(0.0, abs=1e-3)

    def test_unstable_price(self):
        prices = np.array([1.0, 2.0, 0.5, 3.0, 0.2])
        result = stealth_accumulation(10, 0, 5, prices)
        # High std → low stability → low SA
        assert result < 10.0


class TestVolatilityShift:
    def test_compression_breakout(self):
        price_20m = np.array([1.0, 1.0, 1.0, 1.0, 1.0] * 4)  # flat
        price_5m = np.array([1.0, 1.1, 0.9, 1.2, 0.8])  # volatile
        result = volatility_shift(price_20m, price_5m)
        # std(5m) > std(20m) → VS > 1
        assert result > 1.0

    def test_stable_both(self):
        price_20m = np.array([1.0, 1.0, 1.0, 1.0])
        price_5m = np.array([1.0, 1.0, 1.0])
        result = volatility_shift(price_20m, price_5m)
        assert result < 1.0


class TestSellPressure:
    def test_all_buys(self):
        result = sell_pressure(0, 10)
        assert result == pytest.approx(0.0, abs=1e-3)

    def test_all_sells(self):
        result = sell_pressure(10, 0)
        # 10 / (0 + 10 + 1) = 10/11
        assert result == pytest.approx(10 / 11, rel=1e-3)

    def test_balanced(self):
        result = sell_pressure(5, 5)
        # 5 / (5 + 5 + 1) = 5/11
        assert result == pytest.approx(5 / 11, rel=1e-3)


class TestComputeAllFeatures:
    def test_returns_all_keys(self):
        result = compute_all_features(
            h_t=100, h_t10=90, h_t20=85,
            unique_buyers=10, sells_20m=2, buys_20m=8,
            price_series_20m=np.array([1.0, 1.01, 0.99, 1.0]),
            price_series_5m=np.array([1.0, 1.05]),
            sells_5m=3, buys_5m=7, swr=0.5,
        )
        expected_keys = {"holder_acc", "sa", "vol_shift", "sell_pressure", "swr"}
        assert set(result.keys()) == expected_keys
