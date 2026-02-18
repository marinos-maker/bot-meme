-- ============================================================================
-- Solana Early Detector — Initial Database Schema
-- Run against your Supabase PostgreSQL instance
-- ============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── tokens ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tokens (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    address       TEXT NOT NULL UNIQUE,
    name          TEXT,
    symbol        TEXT,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    first_seen_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── token_metrics_timeseries ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS token_metrics_timeseries (
    id                   BIGSERIAL PRIMARY KEY,
    token_id             UUID NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    timestamp            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    price                NUMERIC,
    marketcap            NUMERIC,
    liquidity            NUMERIC,
    holders              INTEGER,
    volume_5m            NUMERIC,
    volume_1h            NUMERIC,
    buys_5m              INTEGER,
    sells_5m             INTEGER,
    top10_ratio          NUMERIC,
    smart_wallets_active INTEGER DEFAULT 0,
    instability_index    NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_token_time
    ON token_metrics_timeseries(token_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_metrics_timestamp
    ON token_metrics_timeseries(timestamp DESC);

-- ── wallet_performance ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wallet_performance (
    wallet        TEXT PRIMARY KEY,
    avg_roi       NUMERIC,
    total_trades  INTEGER,
    win_rate      NUMERIC,
    cluster_label TEXT,
    last_active   TIMESTAMPTZ
);

-- ── signals ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS signals (
    id                BIGSERIAL PRIMARY KEY,
    token_id          UUID NOT NULL REFERENCES tokens(id) ON DELETE CASCADE,
    timestamp         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    instability_index NUMERIC,
    entry_price       NUMERIC,
    liquidity         NUMERIC,
    marketcap         NUMERIC
);

CREATE INDEX IF NOT EXISTS idx_signals_time
    ON signals(timestamp DESC);
