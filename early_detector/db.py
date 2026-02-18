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
        _pool = await asyncpg.create_pool(SUPABASE_DB_URL, min_size=1, max_size=4)
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
                       symbol: str | None = None, narrative: str | None = None) -> str:
    """Insert a token if it doesn't exist; return its UUID."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO tokens (address, name, symbol, narrative)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (address) DO UPDATE SET name = COALESCE($2, tokens.name),
                                            symbol = COALESCE($3, tokens.symbol),
                                            narrative = COALESCE($4, tokens.narrative)
        RETURNING id
        """,
        address, name, symbol, narrative,
    )
    return str(row["id"])


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
             insider_psi, creator_risk_score)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
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
                        creator_risk: float = 0.0) -> None:
    """Record a generated signal."""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO signals (token_id, instability_index, entry_price, 
                            liquidity, marketcap, confidence, kelly_size, 
                            insider_psi, creator_risk)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        token_id, instability_index, entry_price, liquidity, marketcap, 
        confidence, kelly_size, insider_psi, creator_risk,
    )
    logger.info(f"Signal saved for token {token_id} — II={instability_index:.3f}, PSI={insider_psi:.2f}")


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
    """Insert or update wallet performance stats."""
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO wallet_performance (wallet, avg_roi, total_trades, win_rate, cluster_label, last_active)
        VALUES ($1, $2, $3, $4, $5, NOW())
        ON CONFLICT (wallet) DO UPDATE
            SET avg_roi = $2, total_trades = $3, win_rate = $4,
                cluster_label = $5, last_active = NOW()
        """,
        wallet,
        stats.get("avg_roi"),
        stats.get("total_trades"),
        stats.get("win_rate"),
        stats.get("cluster_label"),
    )


async def get_smart_wallets() -> list[str]:
    """Return list of wallet addresses classified as 'smart'."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT wallet FROM wallet_performance
        WHERE avg_roi > 2.5 AND total_trades >= 15 AND win_rate > 0.4
        """
    )
    return [r["wallet"] for r in rows]


async def get_tracked_tokens(limit: int = 20) -> list[str]:
    """Return addresses of recently active tokens for wallet profiling."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT DISTINCT t.address
        FROM tokens t
        JOIN token_metrics_timeseries m ON m.token_id = t.id
        WHERE m.timestamp > NOW() - INTERVAL '24 hours'
        ORDER BY t.address
        LIMIT $1
        """,
        limit,
    )
    return [r["address"] for r in rows]
