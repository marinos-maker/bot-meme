"""
Backtest Engine — minute-by-minute historical replay with multiple exit strategies.
"""

import numpy as np
import pandas as pd
from loguru import logger
from early_detector.features import compute_all_features
from early_detector.scoring import zscore


class BacktestEngine:
    """
    Replays historical data minute-by-minute, simulating the Early Detector
    signals and measuring performance with different exit strategies.
    """

    def __init__(self, exit_strategy: str = "A", percentile: float = 0.95):
        """
        Args:
            exit_strategy: "A" (TP 100%/SL -30%), "B" (trailing 40%), "C" (smart wallet exit)
            percentile: signal trigger percentile (default 95th)
        """
        self.exit_strategy = exit_strategy
        self.percentile = percentile
        self.trades: list[dict] = []
        self.equity_curve: list[float] = []

    def run(self, historical_df: pd.DataFrame,
            smart_wallet_sells: pd.DataFrame | None = None) -> pd.DataFrame:
        """
        Run backtest on historical data.

        Args:
            historical_df: DataFrame sorted by timestamp with columns:
                [token_id, timestamp, price, holders, buys_5m, sells_5m,
                 unique_buyers_20m, sells_20m, buys_20m, price_20m_list,
                 price_5m_list, swr, liquidity, marketcap, top10_ratio]
            smart_wallet_sells: DataFrame with [token_id, timestamp] of SW sells
                (used for exit strategy C)

        Returns:
            DataFrame of trades with performance metrics.
        """
        logger.info(f"Starting backtest — strategy={self.exit_strategy}, "
                    f"percentile={self.percentile}")

        tokens = historical_df["token_id"].unique()
        open_positions: dict[str, dict] = {}
        equity = 1.0
        self.equity_curve = [equity]

        # Group by timestamp for cross-sectional scoring
        for ts, group in historical_df.groupby("timestamp"):
            features_list = []

            for _, row in group.iterrows():
                price_20m = np.array(row.get("price_20m_list", [row["price"]]))
                price_5m = np.array(row.get("price_5m_list", [row["price"]]))

                feat = compute_all_features(
                    h_t=row.get("holders", 0),
                    h_t10=row.get("holders_t10", 0),
                    h_t20=row.get("holders_t20", 0),
                    unique_buyers=row.get("unique_buyers_20m", 0),
                    sells_20m=row.get("sells_20m", 0),
                    buys_20m=row.get("buys_20m", 0),
                    price_series_20m=price_20m,
                    price_series_5m=price_5m,
                    sells_5m=row.get("sells_5m", 0),
                    buys_5m=row.get("buys_5m", 0),
                    swr=row.get("swr", 0),
                )
                feat["token_id"] = row["token_id"]
                feat["price"] = row["price"]
                feat["liquidity"] = row.get("liquidity", 0)
                feat["marketcap"] = row.get("marketcap", 0)
                feat["top10_ratio"] = row.get("top10_ratio", 0)
                feat["timestamp"] = ts
                features_list.append(feat)

            if not features_list:
                continue

            feat_df = pd.DataFrame(features_list)

            # Cross-sectional z-scores
            for col in ["sa", "holder_acc", "vol_shift", "swr", "sell_pressure"]:
                feat_df[f"z_{col}"] = zscore(feat_df[col])

            # Instability Index
            feat_df["instability"] = (
                2 * feat_df["z_sa"]
                + 1.5 * feat_df["z_holder_acc"]
                + 1.5 * feat_df["z_vol_shift"]
                + 2 * feat_df["z_swr"]
                - 2 * feat_df["z_sell_pressure"]
            )

            # Dynamic threshold
            threshold = np.percentile(feat_df["instability"].dropna(),
                                      self.percentile * 100)

            # Check entries
            for _, tok in feat_df.iterrows():
                tid = tok["token_id"]

                # Check exits for open positions
                if tid in open_positions:
                    pos = open_positions[tid]
                    pnl = self._check_exit(pos, tok, smart_wallet_sells, ts)
                    if pnl is not None:
                        trade = {**pos, "exit_price": tok["price"],
                                 "exit_time": ts, "pnl_pct": pnl}
                        self.trades.append(trade)
                        equity *= (1 + pnl)
                        del open_positions[tid]

                # Check new entries
                elif (tok["instability"] > threshold
                      and tok.get("liquidity", 0) > 40000
                      and tok.get("marketcap", float("inf")) < 3_000_000
                      and tok.get("top10_ratio", 0) < 0.35):
                    open_positions[tid] = {
                        "token_id": tid,
                        "entry_price": tok["price"],
                        "entry_time": ts,
                        "peak_price": tok["price"],
                        "instability": tok["instability"],
                    }

            self.equity_curve.append(equity)

        logger.info(f"Backtest complete — {len(self.trades)} trades")
        return pd.DataFrame(self.trades) if self.trades else pd.DataFrame()

    def _check_exit(self, position: dict, current: pd.Series,
                    sw_sells: pd.DataFrame | None, ts) -> float | None:
        """
        Check exit conditions based on the selected strategy.
        Returns PnL percentage if exit triggered, None otherwise.
        """
        entry = position["entry_price"]
        price = current["price"]
        pnl = (price - entry) / entry

        # Update peak
        position["peak_price"] = max(position["peak_price"], price)
        peak = position["peak_price"]

        if self.exit_strategy == "A":
            # TP 100% / SL -30%
            if pnl >= 1.0:
                return pnl
            if pnl <= -0.3:
                return pnl

        elif self.exit_strategy == "B":
            # Trailing stop 40% from peak
            drawdown = (peak - price) / peak if peak > 0 else 0
            if drawdown >= 0.4:
                return pnl

        elif self.exit_strategy == "C":
            # Exit when smart wallets start selling
            if sw_sells is not None:
                tid = position["token_id"]
                sw_exit = sw_sells[
                    (sw_sells["token_id"] == tid)
                    & (sw_sells["timestamp"] == ts)
                ]
                if not sw_exit.empty:
                    return pnl

        return None

    def compute_metrics(self) -> dict:
        """Compute comprehensive performance metrics from completed trades."""
        if not self.trades:
            return {"error": "No trades to evaluate"}

        df = pd.DataFrame(self.trades)
        pnls = df["pnl_pct"]

        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]

        gross_profit = wins.sum() if len(wins) > 0 else 0
        gross_loss = abs(losses.sum()) if len(losses) > 0 else 0

        # Sharpe ratio (annualised assuming ~525,600 minutes/year)
        if pnls.std() > 0:
            sharpe = (pnls.mean() / pnls.std()) * np.sqrt(365 * 24)
        else:
            sharpe = 0.0

        # Max drawdown from equity curve
        eq = np.array(self.equity_curve)
        peak_eq = np.maximum.accumulate(eq)
        drawdowns = (peak_eq - eq) / peak_eq
        max_dd = float(drawdowns.max())

        metrics = {
            "total_trades": len(df),
            "win_rate": float(len(wins) / len(df)) if len(df) > 0 else 0,
            "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
            "max_drawdown": max_dd,
            "sharpe_ratio": float(sharpe),
            "avg_pnl": float(pnls.mean()),
            "median_pnl": float(pnls.median()),
            "best_trade": float(pnls.max()),
            "worst_trade": float(pnls.min()),
            "pct_2x": float((pnls >= 1.0).mean()),
        }

        logger.info(
            f"📊 Backtest Results (Strategy {self.exit_strategy}):\n"
            + "\n".join(f"  {k}: {v}" for k, v in metrics.items())
        )
        return metrics
