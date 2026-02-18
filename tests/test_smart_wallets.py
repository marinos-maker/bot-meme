"""Unit tests for the smart wallet engine."""

import pandas as pd
import pytest
from early_detector.smart_wallets import (
    compute_wallet_stats,
    detect_smart_wallets,
    cluster_wallets,
    compute_swr,
)


class TestComputeWalletStats:
    def test_basic_stats(self):
        df = pd.DataFrame({
            "wallet": ["A", "A", "B", "B"],
            "entry_price": [1.0, 2.0, 1.0, 1.0],
            "exit_price": [3.0, 4.0, 0.5, 1.5],
        })
        stats = compute_wallet_stats(df)
        assert "A" in stats.index
        assert "B" in stats.index
        assert stats.loc["A", "total_trades"] == 2
        assert stats.loc["B", "total_trades"] == 2

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["wallet", "entry_price", "exit_price"])
        stats = compute_wallet_stats(df)
        assert len(stats) == 0


class TestDetectSmartWallets:
    def test_detects_smart(self):
        stats = pd.DataFrame({
            "avg_roi": [3.0, 1.0, 5.0],
            "total_trades": [20, 5, 30],
            "win_rate": [0.6, 0.3, 0.8],
        }, index=["smart1", "retail1", "smart2"])
        result = detect_smart_wallets(stats)
        assert "smart1" in result
        assert "smart2" in result
        assert "retail1" not in result

    def test_no_smart_wallets(self):
        stats = pd.DataFrame({
            "avg_roi": [1.0, 0.5],
            "total_trades": [3, 2],
            "win_rate": [0.2, 0.1],
        }, index=["w1", "w2"])
        result = detect_smart_wallets(stats)
        assert len(result) == 0

    def test_empty_input(self):
        stats = pd.DataFrame(columns=["avg_roi", "total_trades", "win_rate"])
        result = detect_smart_wallets(stats)
        assert len(result) == 0


class TestClusterWallets:
    def test_clusters_three_groups(self):
        stats = pd.DataFrame({
            "avg_roi": [0.5, 0.6, 0.4, 2.0, 2.5, 1.8, 5.0, 6.0, 4.5],
            "total_trades": [100, 90, 80, 50, 40, 60, 10, 15, 12],
            "win_rate": [0.3, 0.25, 0.35, 0.5, 0.55, 0.45, 0.8, 0.85, 0.75],
        }, index=[f"w{i}" for i in range(9)])
        result = cluster_wallets(stats)
        assert "cluster_label" in result.columns
        labels = set(result["cluster_label"])
        assert labels == {"retail", "sniper", "insider"}

    def test_too_few_wallets(self):
        stats = pd.DataFrame({
            "avg_roi": [2.0],
            "total_trades": [10],
            "win_rate": [0.5],
        }, index=["w0"])
        result = cluster_wallets(stats)
        assert result.loc["w0", "cluster_label"] == "unknown"


class TestComputeSWR:
    def test_some_overlap(self):
        active = ["w1", "w2", "w3"]
        smart = ["w2", "w3", "w4"]
        result = compute_swr(active, smart, global_active_smart=10)
        # 2 overlap / 10 = 0.2
        assert result == pytest.approx(0.2, rel=1e-3)

    def test_no_overlap(self):
        result = compute_swr(["w1"], ["w5", "w6"], global_active_smart=5)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_zero_global(self):
        result = compute_swr(["w1"], ["w1"], global_active_smart=0)
        # Division by epsilon → very large number
        assert result > 0
