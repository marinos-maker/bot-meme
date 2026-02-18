
import asyncio
import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import pandas as pd
import numpy as np
from loguru import logger
from early_detector.db import get_pool

class Backtester:
    def __init__(self, days: int = 1, ii_threshold: float = 2.0, 
                 take_profit: float = 0.5, stop_loss: float = 0.2):
        self.days = days
        self.ii_threshold = ii_threshold
        self.take_profit = take_profit
        self.stop_loss = stop_loss
        self.results = []
        self.trades = []

    async def fetch_data(self):
        """Fetch historical token metrics."""
        pool = await get_pool()
        logger.info(f"Fetching data for the last {self.days} days...")
        
        # We need a continuous stream of metrics for all tokens that had HIGH instability at some point
        # Optimization: First find tokens that trigger the II threshold
        target_tokens = await pool.fetch(
            """
            SELECT DISTINCT token_id 
            FROM token_metrics_timeseries 
            WHERE instability_index >= $1 
              AND timestamp > NOW() - ($2 || ' days')::INTERVAL
            """,
            self.ii_threshold, str(self.days)
        )
        
        token_ids = [str(r['token_id']) for r in target_tokens]
        logger.info(f"Found {len(token_ids)} active tokens matching criteria.")
        
        if not token_ids:
            return {}

        # Now fetch full history for these tokens to simulate the trade
        # usage of ANY($1) for array input
        limit_date = datetime.now() - timedelta(days=self.days)
        records = await pool.fetch(
            """
            SELECT token_id, timestamp, price, liquidity, instability_index
            FROM token_metrics_timeseries
            WHERE token_id = ANY($1::uuid[])
              AND timestamp >= $2
            ORDER BY token_id, timestamp ASC
            """,
            token_ids, limit_date
        )
        
        # Organize by token
        data = {}
        for r in records:
            tid = str(r['token_id'])
            if tid not in data:
                data[tid] = []
            
            data[tid].append({
                'ts': r['timestamp'],
                'price': float(r['price']) if r['price'] else 0.0,
                'liq': float(r['liquidity']) if r['liquidity'] else 0.0,
                'ii': float(r['instability_index']) if r['instability_index'] else 0.0
            })
            
        logger.info(f"Loaded metrics for {len(data)} tokens.")
        return data

    def simulate(self, data):
        """Run the simulation loop."""
        logger.info("Starting simulation...")
        
        for tid, history in data.items():
            in_trade = False
            entry_price = 0.0
            entry_ts = None
            
            for i in range(len(history)):
                candle = history[i]
                
                # ENTRY CONDITION
                if not in_trade:
                    if candle['ii'] >= self.ii_threshold and candle['liq'] > 1000:
                        in_trade = True
                        entry_price = candle['price']
                        entry_ts = candle['ts']
                        # logger.debug(f"BUY {tid} @ {entry_price} (II: {candle['ii']})")
                
                # EXIT CONDITIONS
                elif in_trade:
                    current_price = candle['price']
                    if entry_price == 0: continue # Should not happen
                    
                    roi = (current_price - entry_price) / entry_price
                    duration = (candle['ts'] - entry_ts).total_seconds() / 60
                    
                    # 1. Take Profit
                    if roi >= self.take_profit:
                        self.close_trade(tid, entry_ts, candle['ts'], roi, "TP")
                        in_trade = False
                    
                    # 2. Stop Loss
                    elif roi <= -self.stop_loss:
                        self.close_trade(tid, entry_ts, candle['ts'], roi, "SL")
                        in_trade = False
                        
                    # 3. Time Limit (e.g. 4 hours)
                    elif duration > 240:
                        self.close_trade(tid, entry_ts, candle['ts'], roi, "TIME")
                        in_trade = False

    def close_trade(self, tid, start, end, roi, reason):
        self.trades.append({
            'token': tid,
            'start': start,
            'end': end,
            'roi': roi,
            'reason': reason
        })

    def report(self):
        """Generate performance report."""
        if not self.trades:
            logger.warning("No trades executed.")
            return

        df = pd.DataFrame(self.trades)
        wins = df[df['roi'] > 0]
        losses = df[df['roi'] <= 0]
        
        win_rate = len(wins) / len(df) * 100
        avg_roi = df['roi'].mean() * 100
        total_roi = df['roi'].sum() * 100
        
        print("\n" + "="*40)
        print(f" BACKTEST REPORT (Last {self.days} days)")
        print(f" II Threshold: {self.ii_threshold} | TP: {self.take_profit*100}% | SL: {self.stop_loss*100}%")
        print("="*40)
        print(f" Total Trades:   {len(df)}")
        print(f" Win Rate:       {win_rate:.2f}%")
        print(f" Avg ROI:        {avg_roi:.2f}%")
        print(f" Cumulative ROI: {total_roi:.2f}%")
        print(f" Best Trade:     {df['roi'].max()*100:.2f}%")
        print(f" Worst Trade:    {df['roi'].min()*100:.2f}%")
        print("-" * 40)
        print(f" TP Hits:        {len(df[df['reason']=='TP'])}")
        print(f" SL Hits:        {len(df[df['reason']=='SL'])}")
        print(f" Timed Out:      {len(df[df['reason']=='TIME'])}")
        print("="*40 + "\n")

async def run_backtest():
    parser = argparse.ArgumentParser(description="Solana Early Detector Backtester")
    parser.add_argument("--days", type=int, default=1, help="Days of history to test")
    parser.add_argument("--ii", type=float, default=2.0, help="Instability Index Threshold")
    parser.add_argument("--tp", type=float, default=0.5, help="Take Profit (0.5 = 50%)")
    parser.add_argument("--sl", type=float, default=0.2, help="Stop Loss (0.2 = 20%)")
    
    args = parser.parse_args()
    
    tester = Backtester(days=args.days, ii_threshold=args.ii, 
                        take_profit=args.tp, stop_loss=args.sl)
    
    data = await tester.fetch_data()
    if data:
        tester.simulate(data)
        tester.report()

if __name__ == "__main__":
    try:
        asyncio.run(run_backtest())
    except KeyboardInterrupt:
        pass
