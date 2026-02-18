"""
Dashboard — FastAPI web server for monitoring the Solana Early Detector.

Run with:  python -m early_detector.dashboard
Opens at:  http://localhost:8050
"""

import asyncio
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from loguru import logger

from early_detector.config import DASHBOARD_PORT
from early_detector.db import get_pool, close_pool
from early_detector.analyst import analyze_token_signal


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    logger.info(f"Dashboard ready at http://localhost:{DASHBOARD_PORT}")
    yield
    await close_pool()


app = FastAPI(title="Solana Early Detector Dashboard", lifespan=lifespan)

@app.get("/api/overview")
async def api_overview():
    """Return overview stats: total tokens, wallets, signals, latest metrics."""
    pool = await get_pool()

    tokens_count = await pool.fetchval("SELECT COUNT(*) FROM tokens")
    wallets_count = await pool.fetchval("SELECT COUNT(*) FROM wallet_performance")
    signals_count = await pool.fetchval("SELECT COUNT(*) FROM signals")
    smart_count = await pool.fetchval(
        "SELECT COUNT(*) FROM wallet_performance "
        "WHERE avg_roi > 2.5 AND total_trades >= 15 AND win_rate > 0.4"
    )

    # Latest metrics timestamp (proxy for last cycle)
    last_cycle = await pool.fetchval(
        "SELECT MAX(timestamp) FROM token_metrics_timeseries"
    )

    # Wallet cluster breakdown
    clusters = await pool.fetch(
        "SELECT cluster_label, COUNT(*) as cnt FROM wallet_performance GROUP BY cluster_label"
    )

    return {
        "tokens_tracked": tokens_count or 0,
        "wallets_profiled": wallets_count or 0,
        "smart_wallets": smart_count or 0,
        "total_signals": signals_count or 0,
        "last_cycle": last_cycle.isoformat() if last_cycle else None,
        "clusters": {r["cluster_label"]: r["cnt"] for r in clusters},
    }


@app.get("/api/signals")
async def api_signals(limit: int = 50):
    """Return recent signals with token info."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT s.id, s.timestamp, s.instability_index, s.entry_price,
               s.liquidity, s.marketcap, t.address, t.name, t.symbol
        FROM signals s
        JOIN tokens t ON t.id = s.token_id
        ORDER BY s.timestamp DESC
        LIMIT $1
        """,
        limit,
    )

    signals = []
    for r in rows:
        signals.append({
            "id": r["id"],
            "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
            "instability_index": float(r["instability_index"] or 0),
            "entry_price": float(r["entry_price"] or 0),
            "liquidity": float(r["liquidity"] or 0),
            "marketcap": float(r["marketcap"] or 0),
            "token_address": r["address"],
            "token_name": r["name"] or "Unknown",
            "token_symbol": r["symbol"] or "???",
            "buy_url": f"https://jup.ag/swap/SOL-{r['address']}",
        })

    return {"signals": signals}


@app.get("/api/tokens")
async def api_tokens(limit: int = 50):
    """Return recently tracked tokens with latest metrics."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (t.address)
            t.address, t.name, t.symbol, t.first_seen_at,
            m.price, m.marketcap, m.liquidity, m.holders,
            m.volume_5m, m.buys_5m, m.sells_5m, m.instability_index,
            m.timestamp
        FROM tokens t
        JOIN token_metrics_timeseries m ON m.token_id = t.id
        ORDER BY t.address, m.timestamp DESC
        LIMIT $1
        """,
        limit,
    )

    tokens = []
    for r in rows:
        tokens.append({
            "address": r["address"],
            "name": r["name"] or "Unknown",
            "symbol": r["symbol"] or "???",
            "first_seen": r["first_seen_at"].isoformat() if r["first_seen_at"] else None,
            "price": float(r["price"] or 0),
            "marketcap": float(r["marketcap"] or 0),
            "liquidity": float(r["liquidity"] or 0),
            "holders": r["holders"] or 0,
            "volume_5m": float(r["volume_5m"] or 0),
            "buys_5m": r["buys_5m"] or 0,
            "sells_5m": r["sells_5m"] or 0,
            "instability_index": float(r["instability_index"] or 0),
            "last_update": r["timestamp"].isoformat() if r["timestamp"] else None,
            "buy_url": f"https://jup.ag/swap/SOL-{r['address']}",
        })

    # Sort by instability_index descending
    tokens.sort(key=lambda x: x["instability_index"], reverse=True)
    return {"tokens": tokens}


@app.get("/api/analyze/{address}")
async def api_analyze_token(address: str):
    """Get AI analysis for a specific token."""
    pool = await get_pool()
    
    # Get latest metrics
    latest_row = await pool.fetchrow(
        """
        SELECT t.id, t.address, t.symbol, t.name,
               m.price, m.marketcap, m.liquidity, m.holders,
               m.volume_5m, m.buys_5m, m.sells_5m, m.instability_index
        FROM tokens t
        JOIN token_metrics_timeseries m ON m.token_id = t.id
        WHERE t.address = $1
        ORDER BY m.timestamp DESC
        LIMIT 1
        """,
        address,
    )
    
    if not latest_row:
        return JSONResponse(status_code=404, content={"message": "Token not found"})
        
    # Get history for growth calculation
    history_rows = await pool.fetch(
        """
        SELECT holders, price, timestamp
        FROM token_metrics_timeseries
        WHERE token_id = $1
        ORDER BY timestamp DESC
        LIMIT 10
        """,
        latest_row["id"],
    )
    
    history = [dict(r) for r in history_rows]
    token_data = dict(latest_row)
    
    # Convert Decimals to float for the analyst
    for k, v in token_data.items():
        if hasattr(v, '__float__') and not isinstance(v, (int, float)):
            token_data[k] = float(v)
            
    analysis = await analyze_token_signal(token_data, history)
    return analysis


@app.get("/api/wallets")
async def api_wallets(limit: int = 100):
    """Return wallet performance stats."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT wallet, avg_roi, total_trades, win_rate, cluster_label, last_active
        FROM wallet_performance
        ORDER BY avg_roi DESC
        LIMIT $1
        """,
        limit,
    )

    wallets = []
    for r in rows:
        wallets.append({
            "wallet": r["wallet"],
            "avg_roi": float(r["avg_roi"] or 0),
            "total_trades": r["total_trades"] or 0,
            "win_rate": float(r["win_rate"] or 0),
            "cluster_label": r["cluster_label"] or "unknown",
            "last_active": r["last_active"].isoformat() if r["last_active"] else None,
        })

    return {"wallets": wallets}


# ── Action Endpoints ──────────────────────────────────────────────────────────

@app.post("/api/actions/seed-wallets")
async def action_seed_wallets(background_tasks: BackgroundTasks):
    """Trigger wallet seed script in background."""
    def run_seed():
        subprocess.run(
            [sys.executable, "-m", "scripts.seed_wallets"],
            cwd=str(Path(__file__).resolve().parent.parent),
        )

    background_tasks.add_task(run_seed)
    return {"status": "started", "message": "Wallet seed script started in background"}


@app.post("/api/actions/refresh-wallets")
async def action_refresh_wallets():
    """Refresh smart wallet list by re-querying the DB."""
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT wallet FROM wallet_performance "
        "WHERE avg_roi > 2.5 AND total_trades >= 15 AND win_rate > 0.4"
    )
    return {
        "status": "done",
        "smart_wallets": len(rows),
        "wallets": [r["wallet"] for r in rows],
    }


# ── HTML Dashboard ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the dashboard HTML."""
    html_path = Path(__file__).parent / "static" / "dashboard.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

if __name__ == "__main__":
    uvicorn.run(
        "early_detector.dashboard:app",
        host="0.0.0.0",
        port=DASHBOARD_PORT,
        reload=False,
    )
