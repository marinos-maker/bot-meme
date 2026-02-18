"""Unit tests for the scoring engine."""

import numpy as np
import pandas as pd
import pytest
from early_detector.scoring import zscore, compute_instability, get_signal_threshold


class TestZScore:
    def test_standard_zscore(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = zscore(s)
        # Mean should be ~0, std should be ~1
        assert result.mean() == pytest.approx(0.0, abs=1e-6)
        assert result.std() == pytest.approx(1.0, rel=0.01)

    def test_constant_series(self):
        s = pd.Series([5.0, 5.0, 5.0])
        result = zscore(s)
        # All values same → z-score ~0
        assert all(abs(v) < 1e-3 for v in result)


class TestComputeInstability:
    def test_basic_computation(self):
        df = pd.DataFrame({
            "sa": [1.0, 2.0, 3.0, 4.0, 5.0],
            "holder_acc": [0.5, 1.0, 1.5, 2.0, 2.5],
            "vol_shift": [0.8, 1.2, 0.9, 1.5, 1.1],
            "swr": [0.1, 0.2, 0.3, 0.4, 0.5],
            "sell_pressure": [0.6, 0.4, 0.3, 0.2, 0.1],
        })
        result = compute_instability(df)
        assert "instability" in result.columns
        assert len(result) == 5
        # Higher sa, holder_acc, swr and lower sell_pressure → higher instability
        assert result.iloc[-1]["instability"] > result.iloc[0]["instability"]

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["sa", "holder_acc", "vol_shift", "swr", "sell_pressure"])
        result = compute_instability(df)
        assert "instability" in result.columns
        assert len(result) == 0

    def test_custom_weights(self):
        df = pd.DataFrame({
            "sa": [1.0, 5.0],
            "holder_acc": [1.0, 1.0],
            "vol_shift": [1.0, 1.0],
            "swr": [1.0, 1.0],
            "sell_pressure": [0.5, 0.5],
        })
        weights = {"w_sa": 10.0, "w_holder": 0.0, "w_vs": 0.0, "w_swr": 0.0, "w_sell": 0.0}
        result = compute_instability(df, weights=weights)
        # With only SA weight, token with sa=5 should score higher
        assert result.iloc[1]["instability"] > result.iloc[0]["instability"]


class TestSignalThreshold:
    def test_percentile_95(self):
        series = pd.Series(range(100))
        threshold = get_signal_threshold(series, percentile=0.95)
        assert threshold == pytest.approx(94.05, rel=0.02)

    def test_empty_series(self):
        series = pd.Series(dtype=float)
        threshold = get_signal_threshold(series)
        assert threshold == float("inf")
