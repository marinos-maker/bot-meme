"""
Database module — async PostgreSQL connection pool and CRUD helpers.
"""

import asyncpg
from decimal import Decimal
from loguru import logger
from early_detector.config import SUPABASE_DB_URL

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Return (and lazily create) a shared connection pool."""
    global _pool
    if _pool is None:
        logger.info("Creating database connection pool…")
        _pool = await asyncpg.create_pool(
            SUPABASE_DB_URL, 
            min_size=1, 
            max_size=2,
            statement_cache_size=0
        )
        logger.info("Database pool created.")
    return _pool


async def close_pool() -> None:
    """Gracefully close the connection pool."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed.")


# ── Token helpers ─────────────────────────────────────────────────────────────

async def upsert_token(address: str, name: str | None = None,
                       symbol: str | None = None, narrative: str | None = None,
                       creator_address: str | None = None,
                       mint_authority: str | None = None,
                       freeze_authority: str | None = None) -> str:
    """Insert a token if it doesn't exist; return its UUID."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO tokens (address, name, symbol, narrative, creator_address)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (address) DO UPDATE SET 
            name = CASE 
                WHEN tokens.name IS NULL OR tokens.name = 'Unknown' OR tokens.name = '' OR tokens.name LIKE 'Token #%'
                THEN COALESCE(NULLIF($2, 'Unknown'), tokens.name)
                ELSE tokens.name 
            END,
            symbol = CASE 
                WHEN tokens.symbol IS NULL OR tokens.symbol = '???' OR tokens.symbol = '' OR tokens.symbol LIKE 'TOK%'
                THEN COALESCE(NULLIF($3, '???'), tokens.symbol)
                ELSE tokens.symbol 
            END,
            narrative = COALESCE(NULLIF($4, 'GENERIC'), tokens.narrative),
            creator_address = COALESCE($5, tokens.creator_address),
            mint_authority = COALESCE($6, tokens.mint_authority),
            freeze_authority = COALESCE($7, tokens.freeze_authority)
        RETURNING id
        """,
        address, name, symbol, narrative, creator_address, mint_authority, freeze_authority,
    )
    return str(row["id"])


async def get_token_creator(address: str) -> str | None:
    """Retrieve the creator address for a given token address."""
    pool = await get_pool()
    return await pool.fetchval("SELECT creator_address FROM tokens WHERE address = $1", address)


# ── Creator helpers ───────────────────────────────────────────────────────────

async def upsert_creator_stats(creator_address: str, stats: dict) -> None:
    """Track creator history: rug_ratio, avg_lifespan, etc."""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO creator_performance (creator_address, rug_ratio, avg_lifespan, total_tokens)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (creator_address) DO UPDATE
            SET rug_ratio = $2, 
                avg_lifespan = $3, 
                total_tokens = creator_performance.total_tokens + $4
        """,
        creator_address,
        stats.get("rug_ratio", 0.0),
        stats.get("avg_lifespan", 0.0),
        stats.get("total_tokens", 1),
    )


async def get_creator_stats(creator_address: str) -> dict | None:
    """Retrieve creator historical performance."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM creator_performance WHERE creator_address = $1",
        creator_address
    )
    return dict(row) if row else None


async def get_creators_to_analyze() -> list[str]:
    """Retrieve creators who launched tokens at least 2 hours ago for rug analysis."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT DISTINCT creator_address 
        FROM tokens 
        WHERE creator_address IS NOT NULL 
          AND created_at < NOW() - INTERVAL '2 hours'
        """
    )
    return [r["creator_address"] for r in rows]


async def get_creator_tokens(creator_address: str) -> list[dict]:
    """Retrieve all tokens launched by a creator with their age in hours."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT address, 
               EXTRACT(EPOCH FROM (NOW() - created_at))/3600 AS hours_since_creation
        FROM tokens 
        WHERE creator_address = $1
        """,
        creator_address
    )
    return [dict(r) for r in rows]


# ── Metrics helpers ───────────────────────────────────────────────────────────

async def insert_metrics(token_id: str, data: dict) -> None:
    """Insert a row into token_metrics_timeseries."""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO token_metrics_timeseries
            (token_id, price, marketcap, liquidity, holders,
             volume_5m, volume_1h, buys_5m, sells_5m,
             top10_ratio, smart_wallets_active, instability_index,
             insider_psi, creator_risk_score, mint_authority, freeze_authority)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
        """,
        token_id,
        data.get("price"),
        data.get("marketcap"),
        data.get("liquidity"),
        data.get("holders"),
        data.get("volume_5m"),
        data.get("volume_1h"),
        data.get("buys_5m"),
        data.get("sells_5m"),
        data.get("top10_ratio"),
        data.get("smart_wallets_active", 0),
        data.get("instability_index"),
        data.get("insider_psi", 0.0),
        data.get("creator_risk_score", 0.0),
        data.get("mint_authority"),
        data.get("freeze_authority"),
    )


async def get_recent_metrics(token_id: str, minutes: int = 60) -> list[dict]:
    """Fetch recent metric rows for a token within the last N minutes."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM token_metrics_timeseries
        WHERE token_id = $1
          AND timestamp > NOW() - ($2 || ' minutes')::INTERVAL
        ORDER BY timestamp DESC
        """,
        token_id, str(minutes),
    )
    # Convert Decimal values to float for numpy/math compatibility
    result = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, Decimal):
                d[k] = float(v)
        result.append(d)
    return result


async def get_all_recent_instability(minutes: int = 60) -> list[dict]:
    """Fetch the latest instability_index for all tokens active in the last N minutes."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT DISTINCT ON (token_id)
            token_id, instability_index, price, marketcap, liquidity,
            holders, top10_ratio, timestamp
        FROM token_metrics_timeseries
        WHERE timestamp > NOW() - ($1 || ' minutes')::INTERVAL
          AND instability_index IS NOT NULL
        ORDER BY token_id, timestamp DESC
        """,
        str(minutes),
    )
    return [dict(r) for r in rows]


# ── Signal helpers ────────────────────────────────────────────────────────────

async def insert_signal(token_id: str, instability_index: float,
                        entry_price: float, liquidity: float,
                        marketcap: float, confidence: float = 0.5,
                        kelly_size: float = 0.0, insider_psi: float = 0.0,
                        creator_risk: float = 0.0,
                        hard_stop: float | None = None,
                        tp_1: float | None = None,
                        degen_score: int | None = None,
                        ai_summary: str | None = None,
                        ai_analysis: dict | None = None,
                        mint_authority: str | None = None,
                        freeze_authority: str | None = None) -> None:
    """Record a generated signal."""
    import json
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO signals (token_id, instability_index, entry_price, 
                            liquidity, marketcap, confidence, kelly_size, 
                            insider_psi, creator_risk, hard_stop, tp_1,
                            degen_score, ai_summary, ai_analysis,
                            mint_authority, freeze_authority)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
        """,
        token_id, instability_index, entry_price, liquidity, marketcap, 
        confidence, kelly_size, insider_psi, creator_risk, hard_stop, tp_1,
        degen_score, ai_summary, json.dumps(ai_analysis) if ai_analysis else None,
        mint_authority, freeze_authority
    )
    logger.info(f"Signal saved for token {token_id} — II={instability_index:.3f}, Degen={degen_score}")


async def has_recent_signal(token_id: str, minutes: int = 60) -> bool:
    """Check if a signal was already generated for this token recently."""
    pool = await get_pool()
    val = await pool.fetchval(
        """
        SELECT 1 FROM signals
        WHERE token_id = $1
          AND timestamp > NOW() - ($2 || ' minutes')::INTERVAL
        LIMIT 1
        """,
        token_id, str(minutes),
    )
    return val is not None


# ── Wallet helpers ────────────────────────────────────────────────────────────

async def upsert_wallet(wallet: str, stats: dict) -> None:
    """Insert or update wallet performance stats cumulatively."""
    pool = await get_pool()
    # Check if wallet exists to calculate cumulative stats
    row = await pool.fetchrow("SELECT total_trades, avg_roi, win_rate FROM wallet_performance WHERE wallet = $1", wallet)
    
    new_trades = stats.get("total_trades", 0)
    new_roi = stats.get("avg_roi", 1.0)
    new_wr = stats.get("win_rate", 0.0)
    cluster = stats.get("cluster_label", "unknown")

    if row:
        old_trades = row["total_trades"] or 0
        old_roi = float(row["avg_roi"] or 1.0)
        old_wr = float(row["win_rate"] or 0.0)
        
        total_trades = old_trades + new_trades
        if total_trades > 0:
            # Weighted average
            updated_roi = (old_roi * old_trades + new_roi * new_trades) / total_trades
            updated_wr = (old_wr * old_trades + new_wr * new_trades) / total_trades
        else:
            updated_roi = new_roi
            updated_wr = new_wr
            
        await pool.execute(
            """
            UPDATE wallet_performance 
            SET avg_roi = $2, total_trades = $3, win_rate = $4,
                cluster_label = $5, last_active = NOW()
            WHERE wallet = $1
            """,
            wallet, updated_roi, total_trades, updated_wr, cluster
        )
    else:
        await pool.execute(
            """
            INSERT INTO wallet_performance (wallet, avg_roi, total_trades, win_rate, cluster_label, last_active)
            VALUES ($1, $2, $3, $4, $5, NOW())
            """,
            wallet, new_roi, new_trades, new_wr, cluster
        )


async def increment_wallet_trades(wallet: str, cluster: str = "retail") -> None:
    """Increment trade count for a wallet without touching its calculated ROI/WR."""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO wallet_performance (wallet, avg_roi, total_trades, win_rate, cluster_label, last_active)
        VALUES ($1, 1.0, 1, 0.0, $2, NOW())
        ON CONFLICT (wallet) DO UPDATE SET 
            total_trades = wallet_performance.total_trades + 1,
            last_active = NOW(),
            cluster_label = CASE WHEN wallet_performance.cluster_label = 'new' THEN $2 ELSE wallet_performance.cluster_label END
        """,
        wallet, cluster
    )


async def touch_wallet(wallet: str) -> None:
    """Update the last_active timestamp for a wallet without changing stats."""
    pool = await get_pool()
    await pool.execute(
        "UPDATE wallet_performance SET last_active = NOW() WHERE wallet = $1",
        wallet
    )

async def get_all_wallet_performance() -> list[dict]:
    """Retrieve all wallet performance rows for global re-clustering."""
    pool = await get_pool()
    rows = await pool.fetch("SELECT wallet, avg_roi, total_trades, win_rate FROM wallet_performance")
    return [dict(r) for r in rows]


async def get_smart_wallets_stats() -> dict[str, dict]:
    """Return a dictionary of {wallet_address: {stats}} for verified smart wallets."""
    from early_detector.config import SW_MIN_ROI, SW_MIN_TRADES, SW_MIN_WIN_RATE
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT wallet, avg_roi, total_trades, win_rate, cluster_label 
        FROM wallet_performance
        WHERE (avg_roi > $1 AND total_trades >= $2 AND win_rate > $3)
           OR (avg_roi > 10.0 AND total_trades >= 3)
           OR (cluster_label IN ('sniper', 'insider'))
        """,
        SW_MIN_ROI, SW_MIN_TRADES, SW_MIN_WIN_RATE
    )
    return {r["wallet"]: dict(r) for r in rows}


async def get_smart_wallets() -> list[str]:
    """Deprecated: use get_smart_wallets_stats for better signal quality."""
    stats = await get_smart_wallets_stats()
    return list(stats.keys())


async def get_tracked_tokens(limit: int = 500) -> list[str]:
    """Return addresses of recently active tokens and signals for refresh."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        WITH recent_signals AS (
            SELECT DISTINCT t.address, MAX(s.timestamp) as last_sig
            FROM tokens t
            JOIN signals s ON s.token_id = t.id
            WHERE s.timestamp > NOW() - INTERVAL '12 hours'
            GROUP BY t.address
        ),
        recent_metrics AS (
            SELECT DISTINCT t.address, MAX(m.timestamp) as last_met
            FROM tokens t
            JOIN token_metrics_timeseries m ON m.token_id = t.id
            WHERE m.timestamp > NOW() - INTERVAL '4 hours'
            GROUP BY t.address
        )
        SELECT address FROM (
            SELECT address, last_sig as sort_time FROM recent_signals
            UNION
            SELECT address, last_met as sort_time FROM recent_metrics
        ) combined
        ORDER BY sort_time DESC
        LIMIT $1
        """,
        limit,
    )
    return [r["address"] for r in rows]

async def log_market_regime(total_volume: float, regime_label: str) -> None:
    """Log the current market regime for historical analysis."""
    pool = await get_pool()
    await pool.execute(
        "INSERT INTO market_regime (total_volume_5m, regime_label) VALUES ($1, $2)",
        total_volume, regime_label
    )


async def get_avg_volume_history(minutes: int = 120) -> float:
    """Calculate average historical batch volume."""
    pool = await get_pool()
    val = await pool.fetchval(
        "SELECT AVG(total_volume_5m) FROM market_regime WHERE timestamp > NOW() - ($1 || ' minutes')::INTERVAL",
        str(minutes)
    )
    return float(val or 0.0)


async def get_unprocessed_tokens(limit: int = 20) -> list[str]:
    """Return addresses of tokens that exist in DB but have no metrics yet.
    These are typically tokens discovered via Helius webhooks that haven't
    been passed through the processor pipeline."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT t.address
        FROM tokens t
        LEFT JOIN token_metrics_timeseries m ON m.token_id = t.id
        WHERE m.id IS NULL
          AND t.created_at > NOW() - INTERVAL '2 hours'
        ORDER BY t.created_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [r["address"] for r in rows]


# ── Trades (V5.0) ───────────────────────────────────────────────────────────

async def insert_trade(token_address: str, side: str, amount_sol: float,
                       amount_token: float, price_entry: float,
                       tp_pct: float, sl_pct: float, tx_hash: str) -> int | None:
    """Insert a new trade record. Returns the trade ID."""
    pool = await get_pool()
    # Get or create token
    token_id = await pool.fetchval(
        "SELECT id FROM tokens WHERE address = $1", token_address
    )
    if not token_id:
        token_id = await pool.fetchval(
            "INSERT INTO tokens (address) VALUES ($1) ON CONFLICT (address) DO UPDATE SET address = $1 RETURNING id",
            token_address
        )
    
    trade_id = await pool.fetchval(
        """
        INSERT INTO trades (token_id, token_address, side, amount_sol, amount_token,
                           price_entry, tp_pct, sl_pct, tx_hash_buy, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'OPEN')
        RETURNING id
        """,
        token_id, token_address, side, amount_sol, amount_token,
        price_entry, tp_pct, sl_pct, tx_hash
    )
    return trade_id


async def get_open_trades() -> list[dict]:
    """Get all open trade positions."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT t.id, t.token_address, t.amount_sol, t.amount_token,
               t.price_entry, t.tp_pct, t.sl_pct, t.roi_pct, t.tx_hash_buy,
               t.created_at, tk.symbol, tk.name
        FROM trades t
        LEFT JOIN tokens tk ON tk.id = t.token_id
        WHERE t.status = 'OPEN' AND t.side = 'BUY'
        ORDER BY t.created_at DESC
        """
    )
    return [dict(r) for r in rows]


async def close_trade(trade_id: int, status: str, exit_price: float,
                      roi_pct: float, tx_hash_sell: str) -> None:
    """Close a trade with final status."""
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE trades 
        SET status = $1, price_exit = $2, roi_pct = $3, 
            tx_hash_sell = $4, closed_at = NOW()
        WHERE id = $5
        """,
        status, exit_price, roi_pct, tx_hash_sell, trade_id
    )


async def get_trade_history(limit: int = 50) -> list[dict]:
    """Get closed trades history."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT t.id, t.token_address, t.side, t.amount_sol,
               t.price_entry, t.price_exit, t.tp_pct, t.sl_pct,
               t.roi_pct, t.status, t.tx_hash_buy, t.tx_hash_sell,
               t.created_at, t.closed_at, tk.symbol, tk.name
        FROM trades t
        LEFT JOIN tokens tk ON tk.id = t.token_id
        WHERE t.status != 'OPEN'
        ORDER BY t.closed_at DESC
        LIMIT $1
        """,
        limit
    )
    return [dict(r) for r in rows]


async def get_positions_with_roi() -> list[dict]:
    """Get open positions with latest price for ROI calculation."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT t.id, t.token_address, t.amount_sol, t.amount_token,
               t.price_entry, t.tp_pct, t.sl_pct, t.roi_pct,
               t.created_at, tk.symbol, tk.name,
               (SELECT m.price FROM token_metrics_timeseries m 
                WHERE m.token_id = t.token_id 
                ORDER BY m.timestamp DESC LIMIT 1) as current_price
        FROM trades t
        LEFT JOIN tokens tk ON tk.id = t.token_id
        WHERE t.status = 'OPEN' AND t.side = 'BUY'
        ORDER BY t.created_at DESC
        """
    )
    return [dict(r) for r in rows]


async def cleanup_old_data(days: int = 7) -> int:
    """
    Maintenance: Delete metrics older than N days and orphaned tokens.
    """
    pool = await get_pool()
    try:
        # 1. Clean metrics (Time-Series)
        await pool.execute(
            "DELETE FROM token_metrics_timeseries WHERE timestamp < NOW() - ($1 || ' days')::INTERVAL",
            str(days)
        )
        
        # 2. Clean signals
        await pool.execute(
            "DELETE FROM signals WHERE timestamp < NOW() - ($1 || ' days')::INTERVAL",
            str(days)
        )
        
        # 3. Clean orphaned tokens 
        # (Tokens with no metrics and not linked to any trade)
        res = await pool.execute(
            """
            DELETE FROM tokens 
            WHERE id NOT IN (SELECT DISTINCT token_id FROM token_metrics_timeseries)
            AND id NOT IN (SELECT DISTINCT token_id FROM trades)
            AND id NOT IN (SELECT DISTINCT token_id FROM signals)
            """
        )
        
        deleted_count = 0
        if res and "DELETE" in res:
            deleted_count = int(res.split()[-1])
            
        logger.info(f"🧹 Database Cleanup: Removed metrics older than {days} days and {deleted_count} orphaned tokens.")
        return deleted_count
    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}")
        return 0

