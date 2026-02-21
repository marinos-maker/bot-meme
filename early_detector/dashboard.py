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
from typing import Any

from fastapi import FastAPI, BackgroundTasks, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from loguru import logger

from early_detector.config import DASHBOARD_PORT, TRADE_AMOUNT_SOL, DEFAULT_TP_PCT, DEFAULT_SL_PCT, SLIPPAGE_BPS
from early_detector.db import get_pool, close_pool, insert_trade, get_open_trades, close_trade, get_trade_history, get_positions_with_roi
from early_detector.analyst import analyze_token_signal
from early_detector.narrative import NarrativeManager
from early_detector.cache import cache
from early_detector.trader import execute_buy, execute_sell, get_sol_balance, get_wallet_address


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    logger.info("=" * 60)
    logger.info("🚀 Solana Early Detector DASHBOARD V4.0.3 (Alpha Engine)")
    logger.info(f"   Listening at http://localhost:{DASHBOARD_PORT}")
    logger.info("=" * 60)
    yield
    await close_pool()


app = FastAPI(title="Solana Early Detector Dashboard", lifespan=lifespan)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every request for 100% visibility."""
    start_time = datetime.now()
    response = await call_next(request)
    duration = (datetime.now() - start_time).total_seconds()
    
    # Quick indicator for POST hits (Webhooks)
    status_icon = "✅" if response.status_code == 200 else "⚠️"
    logger.info(f"{status_icon} REQ: {request.method} {request.url.path} -> {response.status_code} ({duration:.3f}s)")
    return response

@app.get("/api/overview")
async def api_overview():
    """Return overview stats: total tokens, wallets, signals, latest metrics."""
    pool = await get_pool()

    tokens_count = await pool.fetchval("SELECT COUNT(*) FROM tokens")
    wallets_count = await pool.fetchval("SELECT COUNT(*) FROM wallet_performance")
    signals_count = await pool.fetchval("SELECT COUNT(*) FROM signals")
    from early_detector.config import SW_MIN_ROI, SW_MIN_TRADES, SW_MIN_WIN_RATE
    smart_count = await pool.fetchval(
        "SELECT COUNT(*) FROM wallet_performance "
        "WHERE avg_roi > $1 AND total_trades >= $2 AND win_rate > $3",
        SW_MIN_ROI, SW_MIN_TRADES, SW_MIN_WIN_RATE
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
               s.liquidity, s.marketcap, s.confidence, s.kelly_size,
               s.insider_psi, s.creator_risk,
               t.address, t.name, t.symbol
        FROM signals s
        JOIN tokens t ON t.id = s.token_id
        ORDER BY s.timestamp DESC
        LIMIT $1
        """,
        limit,
    )

    import math
    signals = []
    for r in rows:
        ii = float(r["instability_index"] or 0)
        price = float(r["entry_price"] or 0)
        liq = float(r["liquidity"] or 0)
        mcap = float(r["marketcap"] or 0)
        conf = float(r["confidence"] or 0)
        kelly = float(r["kelly_size"] or 0)
        psi = float(r["insider_psi"] or 0)
        risk = float(r["creator_risk"] or 0)

        if not math.isfinite(ii): ii = 0
        if not math.isfinite(price): price = 0
        if not math.isfinite(liq): liq = 0
        if not math.isfinite(mcap): mcap = 0
        if not math.isfinite(conf): conf = 0
        if not math.isfinite(kelly): kelly = 0
        if not math.isfinite(psi): psi = 0
        if not math.isfinite(risk): risk = 0

        signals.append({
            "id": r["id"],
            "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
            "instability_index": ii,
            "entry_price": price,
            "liquidity": liq,
            "marketcap": mcap,
            "confidence": conf,
            "kelly_size": kelly,
            "insider_psi": psi,
            "creator_risk": risk,
            "token_address": r["address"],
            "token_name": r["name"] or "Unknown",
            "token_symbol": r["symbol"] or "???",
            "buy_url": f"https://pump.fun/{r['address']}",
        })

    return {"signals": signals}


@app.get("/api/tokens")
async def api_tokens(limit: int = 50):
    """Return recently tracked tokens with latest metrics (LEFT JOIN for webhook/new discovery)."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (t.address)
            t.address, t.name, t.symbol, t.first_seen_at, t.narrative,
            m.price, m.marketcap, m.liquidity, m.holders,
            m.volume_5m, m.buys_5m, m.sells_5m, m.instability_index,
            m.timestamp as last_metric_at, m.insider_psi, m.creator_risk_score
        FROM tokens t
        LEFT JOIN token_metrics_timeseries m ON m.token_id = t.id
        ORDER BY t.address, m.timestamp DESC NULLS LAST
        LIMIT $1
        """,
        limit,
    )

    import math
    results = []
    for r in rows:
        price = float(r["price"] or 0)
        mcap = float(r["marketcap"] or 0)
        liq = float(r["liquidity"] or 0)
        vol = float(r["volume_5m"] or 0)
        ii = float(r["instability_index"] or 0)
        psi = float(r["insider_psi"] or 0)
        risk = float(r["creator_risk_score"] or 0)
        
        # Sanitize
        if not math.isfinite(price): price = 0
        if not math.isfinite(mcap): mcap = 0
        if not math.isfinite(liq): liq = 0
        if not math.isfinite(vol): vol = 0
        if not math.isfinite(ii): ii = 0
        if not math.isfinite(psi): psi = 0
        if not math.isfinite(risk): risk = 0

        # Fallback for name/symbol
        name = r["name"]
        symbol = r["symbol"]
        if not symbol or symbol == "???":
            symbol = r["address"][:4] + "..."
        if not name or name == "Unknown":
            name = symbol

        results.append({
            "address": r["address"],
            "name": name,
            "symbol": symbol,
            "first_seen": r["first_seen_at"].isoformat() if r["first_seen_at"] else None,
            "price": price,
            "marketcap": mcap,
            "liquidity": liq,
            "holders": r["holders"],
            "volume_5m": vol,
            "buys_5m": r["buys_5m"] or 0,
            "sells_5m": r["sells_5m"] or 0,
            "instability_index": ii,
            "insider_psi": psi,
            "creator_risk": risk,
            "narrative": r["narrative"] or "GENERIC",
            "buy_url": f"https://pump.fun/{r['address']}",
        })
    
    # Final sort: most recently seen first
    results.sort(key=lambda x: x["first_seen"] or "", reverse=True)
    return {"tokens": results}


@app.get("/api/analyze/{address}")
async def api_analyze_token(address: str):
    """Get AI analysis for a specific token."""
    pool = await get_pool()
    
    # Get latest metrics
    latest_row = await pool.fetchrow(
        """
        SELECT t.id, t.address, t.symbol, t.name, t.narrative,
               m.price, m.marketcap, m.liquidity, m.holders,
               m.volume_5m, m.buys_5m, m.sells_5m, m.instability_index,
               m.insider_psi, m.creator_risk_score
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
            
    analysis = cache.get(f"ai_analysis_{address}")
    if analysis:
        logger.info(f"Returning cached AI analysis for {address}")
        return analysis

    analysis = await analyze_token_signal(token_data, history)
    
    # Cache the result if it's not an error or a transient wait
    if analysis.get("verdict") not in ["ERROR", "WAIT"]:
        cache.set(f"ai_analysis_{address}", analysis, ttl_seconds=300)
        
    return analysis


@app.get("/api/wallets")
async def api_wallets(limit: int = 100):
    """Return wallet performance stats."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT wallet, avg_roi, total_trades, win_rate, cluster_label, last_active
        FROM wallet_performance
        ORDER BY last_active DESC, avg_roi DESC
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



@app.get("/api/analytics")
async def api_analytics():
    """
    Return data for visualization:
    1. Heatmap (Instability vs Free Float/Mcap) - using Instability directly.
    2. Explosiveness (Volume/Liquidity Ratio).
    3. Narrative Dominance (Capital Rotation).
    """
    pool = await get_pool()
    
    # Get latest metrics for all active tokens (last 30m, fallback to 4h if none)
    interval = '30 minutes'
    rows = await pool.fetch(
        f"""
        SELECT DISTINCT ON (t.id)
            t.address, t.symbol, t.name,
            m.price, m.marketcap, m.liquidity, 
            m.volume_5m, m.instability_index, m.timestamp
        FROM tokens t
        JOIN token_metrics_timeseries m ON m.token_id = t.id
        WHERE m.timestamp > NOW() - INTERVAL '{interval}'
        ORDER BY t.id, m.timestamp DESC
        """
    )
    
    if not rows:
        interval = '4 hours'
        logger.info(f"No tokens in last 30m, falling back to {interval}")
        rows = await pool.fetch(
            f"""
            SELECT DISTINCT ON (t.id)
                t.address, t.symbol, t.name,
                m.price, m.marketcap, m.liquidity, 
                m.volume_5m, m.instability_index, m.timestamp
            FROM tokens t
            JOIN token_metrics_timeseries m ON m.token_id = t.id
            WHERE m.timestamp > NOW() - INTERVAL '{interval}'
            ORDER BY t.id, m.timestamp DESC
            """
        )
    
    import math
    
    data = []
    for r in rows:
        liq = float(r["liquidity"] or 0)
        vol = float(r["volume_5m"] or 0)
        
        # Calculate Velocity (Turnover)
        velocity = (vol / (liq + 1)) * 100 if liq > 0 else 0
        
        # Sanitize for JSON (no NaN or Inf)
        instability = float(r["instability_index"] or 0)
        mcap = float(r["marketcap"] or 0)
        
        if not math.isfinite(velocity): velocity = 0.0
        if not math.isfinite(instability): instability = 0.0
        if not math.isfinite(liq): liq = 0.0
        if not math.isfinite(mcap): mcap = 0.0
        if not math.isfinite(vol): vol = 0.0
        
        symbol = r["symbol"]
        name = r["name"] or "Unknown"
        
        # UI Fallback: Symbol > Name > Truncated Address
        display_symbol = symbol
        if not display_symbol or display_symbol == "???":
            if name and name != "Unknown":
                display_symbol = name[:8] # Use start of name
            else:
                display_symbol = r["address"][:4] + "..."
            
        data.append({
            "address": r["address"],
            "symbol": display_symbol,
            "name": name,
            "instability_index": instability,
            "liquidity": liq,
            "marketcap": mcap,
            "volume_5m": vol,
            "velocity": velocity
        })
    
    # Narrative Statistics
    narrative_stats = NarrativeManager.get_narrative_stats(data)
    
    # Sorts
    explosive = sorted(data, key=lambda x: x["velocity"], reverse=True)[:10]
    unstable = sorted(data, key=lambda x: x["instability_index"], reverse=True)[:10]
    
    return {
        "heatmap": data,
        "explosive_leaders": explosive,
        "instability_leaders": unstable,
        "narrative_stats": narrative_stats
    }


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
    from early_detector.config import SW_MIN_ROI, SW_MIN_TRADES, SW_MIN_WIN_RATE
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT wallet FROM wallet_performance 
        WHERE avg_roi > $1 AND total_trades >= $2 AND win_rate > $3
        """,
        SW_MIN_ROI, SW_MIN_TRADES, SW_MIN_WIN_RATE
    )
    return {
        "status": "done",
        "smart_wallets": len(rows),
        "message": f"Detected {len(rows)} smart wallets meet criteria.",
        "wallets": [r["wallet"] for r in rows],
    }


# ── Trading Endpoints (V5.0) ─────────────────────────────────────────────────

@app.post("/api/trade/buy")
async def api_trade_buy(request: Request):
    """Execute a BUY trade via Jupiter."""
    import aiohttp
    body = await request.json()
    token_address = body.get("address")
    amount_sol = float(body.get("amount_sol", TRADE_AMOUNT_SOL))
    tp_pct = float(body.get("tp_pct", DEFAULT_TP_PCT))
    sl_pct = float(body.get("sl_pct", DEFAULT_SL_PCT))
    slippage = int(body.get("slippage_bps", SLIPPAGE_BPS))

    if not token_address:
        return JSONResponse({"success": False, "error": "Indirizzo token mancante"}, status_code=400)

    async with aiohttp.ClientSession() as session:
        result = await execute_buy(session, token_address, amount_sol, slippage)

    if result["success"]:
        trade_id = await insert_trade(
            token_address=token_address,
            side="BUY",
            amount_sol=amount_sol,
            amount_token=result.get("amount_token", 0),
            price_entry=result.get("price", 0),
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            tx_hash=result.get("tx_hash", "")
        )
        result["trade_id"] = trade_id
        result["tp_pct"] = tp_pct
        result["sl_pct"] = sl_pct

    return result


@app.post("/api/trade/sell")
async def api_trade_sell(request: Request):
    """Execute a manual SELL trade."""
    import aiohttp
    body = await request.json()
    token_address = body.get("address")
    trade_id = body.get("trade_id")

    if not token_address:
        return JSONResponse({"success": False, "error": "Indirizzo token mancante"}, status_code=400)

    async with aiohttp.ClientSession() as session:
        result = await execute_sell(session, token_address)

    if result["success"] and trade_id:
        await close_trade(
            trade_id=int(trade_id),
            status="MANUAL_CLOSE",
            exit_price=0,
            roi_pct=0,
            tx_hash_sell=result.get("tx_hash", "")
        )

    return result


@app.get("/api/trade/positions")
async def api_trade_positions():
    """Get open positions with live ROI."""
    positions = await get_positions_with_roi()
    safe = []
    for p in positions:
        entry = float(p.get("price_entry") or 0)
        current = float(p.get("current_price") or 0)
        roi = ((current - entry) / entry * 100) if entry > 0 and current > 0 else float(p.get("roi_pct") or 0)
        safe.append({
            "id": p["id"],
            "token_address": p["token_address"],
            "symbol": p.get("symbol") or p["token_address"][:6],
            "name": p.get("name") or "Unknown",
            "amount_sol": float(p.get("amount_sol") or 0),
            "price_entry": entry,
            "current_price": current,
            "roi_pct": round(roi, 2),
            "tp_pct": float(p.get("tp_pct") or 50),
            "sl_pct": float(p.get("sl_pct") or 30),
            "created_at": str(p.get("created_at", "")),
        })
    return {"positions": safe}


@app.get("/api/trade/history")
async def api_trade_history(limit: int = 50):
    """Get closed trades history."""
    trades = await get_trade_history(limit)
    safe = []
    for t in trades:
        safe.append({
            "id": t["id"],
            "token_address": t["token_address"],
            "symbol": t.get("symbol") or t["token_address"][:6],
            "amount_sol": float(t.get("amount_sol") or 0),
            "price_entry": float(t.get("price_entry") or 0),
            "price_exit": float(t.get("price_exit") or 0),
            "roi_pct": float(t.get("roi_pct") or 0),
            "status": t["status"],
            "created_at": str(t.get("created_at", "")),
            "closed_at": str(t.get("closed_at", "")),
        })
    return {"trades": safe}


@app.get("/api/wallet/balance")
async def api_wallet_balance():
    """Get wallet SOL balance."""
    import aiohttp
    wallet = get_wallet_address()
    if not wallet:
        return {"balance": 0, "wallet": None, "error": "Wallet non configurato"}
    async with aiohttp.ClientSession() as session:
        balance = await get_sol_balance(session)
    return {"balance": round(balance, 5), "wallet": wallet}


@app.get("/api/trade/sol-price")
async def api_sol_price():
    """Get SOL price from CoinGecko (reliable fallback)."""
    import aiohttp
    cached = cache.get("sol_price_usd")
    if cached:
        return {"price": cached}
        
    try:
        async with aiohttp.ClientSession() as session:
            url = "https://api.jup.ag/price/v2?ids=So11111111111111111111111111111111111111112"
            # Try CoinGecko as fallback for SOL since Jup V2 might be restricted
            url = "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd"
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    price = float(data["solana"]["usd"])
                    cache.set("sol_price_usd", price, ttl_seconds=60)
                    return {"price": price}
    except Exception as e:
        logger.error(f"SOL price error: {e}")
        
    return {"price": 0.0}


@app.get("/api/logs")
async def api_logs(limit: int = 100):
    """Return the last N lines of the runtime log."""
    from early_detector.config import LOG_FILE
    log_path = Path(LOG_FILE)
    if not log_path.exists():
        return {"logs": "Log file not found."}
    
    try:
        # Simple tail implementation
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return {"logs": "".join(lines[-limit:])}
    except Exception as e:
        return {"logs": f"Error reading logs: {e}"}


@app.get("/api/webhook/helius/test")
async def test_webhook_get():
    """Manual connectivity test via browser."""
    logger.info("MANUAL TEST: Webhook GET route reached!")
    return {"status": "ok", "message": "Manual test OK - Server is reachable!"}


@app.post("/api/webhook/helius")
async def helius_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Handle Helius Webhooks (New Mints or Swaps).
    Immediate response (200 OK) to prevent timeouts.
    """
    try:
        # Read raw body immediately
        body = await request.body()
        logger.info(f"📥 Received Webhook from Helius: {len(body)} bytes")
        
        # Offload parsing and DB work to background
        background_tasks.add_task(process_helius_payload, body)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook receiver error: {e}")
        return {"status": "error"}


async def process_helius_payload(body: bytes):
    """Background task to parse JSON and upsert tokens."""
    try:
        import json
        if not body:
            return
            
        payload = json.loads(body)
        from early_detector.db import upsert_token
        
        if isinstance(payload, dict):
            events = [payload]
        elif isinstance(payload, list):
            events = payload
        else:
            return

        for event in events:
            e_type = str(event.get("type", "")).upper()
            if e_type in ["MINT", "TOKEN_MINT", "SWAP"]:
                transfers = event.get("tokenTransfers", [])
                for tx in transfers:
                    mint = tx.get("mint")
                    if mint and mint != "So11111111111111111111111111111111111111112":
                        # Only provide name/symbol if we absolutely have to.
                        # Using None for name/symbol in upsert_token will preserve existing values.
                        await upsert_token(mint) 
                        logger.info(f"Helius Webhook: Discovered {mint} via {e_type}")
    except Exception as e:
        logger.error(f"Background webhook error: {e}")


# ── HTML Dashboard ────────────────────────────────────────────────────────────

@app.api_route("/", methods=["GET", "POST"], response_class=HTMLResponse)
async def serve_dashboard(request: Request, background_tasks: BackgroundTasks):
    """Serve the dashboard HTML (GET) or handle misplaced Webhooks (POST)."""
    if request.method == "POST":
        # Fallback to handle Helius hitting the root path
        body = await request.body()
        background_tasks.add_task(process_helius_payload, body)
        return JSONResponse(status_code=200, content={"status": "ok", "note": "Root path fallback"})
    
    html_path = Path(__file__).parent / "static" / "dashboard.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

if __name__ == "__main__":
    uvicorn.run(
        "early_detector.dashboard:app",
        host="0.0.0.0",
        port=DASHBOARD_PORT,
        reload=False,
    )
