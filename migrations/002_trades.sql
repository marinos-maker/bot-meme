-- ============================================================================
-- V5.0 — Trades table for tracking BUY/SELL positions
-- ============================================================================

CREATE TABLE IF NOT EXISTS trades (
    id             BIGSERIAL PRIMARY KEY,
    token_id       UUID REFERENCES tokens(id) ON DELETE CASCADE,
    token_address  TEXT NOT NULL,
    side           TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    amount_sol     NUMERIC,
    amount_token   NUMERIC,
    price_entry    NUMERIC,
    price_exit     NUMERIC,
    tp_pct         NUMERIC DEFAULT 50,
    sl_pct         NUMERIC DEFAULT 30,
    roi_pct        NUMERIC,
    status         TEXT DEFAULT 'OPEN' CHECK (status IN ('OPEN', 'TP_HIT', 'SL_HIT', 'MANUAL_CLOSE', 'FAILED')),
    tx_hash_buy    TEXT,
    tx_hash_sell   TEXT,
    created_at     TIMESTAMPTZ DEFAULT NOW(),
    closed_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(created_at DESC);
