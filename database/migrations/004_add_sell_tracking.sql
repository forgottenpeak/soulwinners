-- Migration 004: Add sell tracking and momentum metrics
-- Run: sqlite3 data/soulwinners.db < database/migrations/004_add_sell_tracking.sql

-- ============================================================
-- 1. Create wallet_exits table for tracking elite wallet sells
-- ============================================================
CREATE TABLE IF NOT EXISTS wallet_exits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Link to position
    position_id INTEGER NOT NULL,

    -- Exit identification
    wallet_address TEXT NOT NULL,
    token_address TEXT NOT NULL,

    -- Exit data
    exit_timestamp INTEGER NOT NULL,
    sell_sol_received REAL NOT NULL,
    exit_mc REAL,                          -- Market cap at time of exit

    -- Calculated fields
    hold_duration_hours REAL,              -- Hours from entry to exit
    roi_at_exit REAL,                      -- ROI when this wallet sold

    -- Deduplication
    signature TEXT UNIQUE,                 -- Transaction signature

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (position_id) REFERENCES position_lifecycle(id)
);

-- Indexes for wallet_exits
CREATE INDEX IF NOT EXISTS idx_wallet_exits_position ON wallet_exits(position_id);
CREATE INDEX IF NOT EXISTS idx_wallet_exits_token ON wallet_exits(token_address);
CREATE INDEX IF NOT EXISTS idx_wallet_exits_wallet ON wallet_exits(wallet_address);
CREATE INDEX IF NOT EXISTS idx_wallet_exits_timestamp ON wallet_exits(exit_timestamp DESC);


-- ============================================================
-- 2. Add momentum/tracking columns to position_lifecycle
-- ============================================================

-- Elite wallet tracking (how many elites bought/exited this token)
ALTER TABLE position_lifecycle ADD COLUMN elite_exit_count INTEGER DEFAULT 0;
ALTER TABLE position_lifecycle ADD COLUMN elite_still_holding INTEGER DEFAULT 0;
ALTER TABLE position_lifecycle ADD COLUMN first_elite_exit_timestamp INTEGER;

-- Momentum metrics (calculated during hourly updates)
ALTER TABLE position_lifecycle ADD COLUMN momentum_score REAL DEFAULT 0;
ALTER TABLE position_lifecycle ADD COLUMN momentum_trend TEXT DEFAULT 'neutral';  -- up, down, neutral

-- Volume tracking
ALTER TABLE position_lifecycle ADD COLUMN volume_trend TEXT DEFAULT 'stable';  -- up, down, stable
ALTER TABLE position_lifecycle ADD COLUMN volume_change_1h REAL DEFAULT 0;      -- % change in last hour
ALTER TABLE position_lifecycle ADD COLUMN volume_change_24h REAL DEFAULT 0;     -- % change in 24h

-- Holder tracking
ALTER TABLE position_lifecycle ADD COLUMN new_holders_24h INTEGER DEFAULT 0;
ALTER TABLE position_lifecycle ADD COLUMN holder_change_rate REAL DEFAULT 0;    -- % change per hour

-- MC history for momentum calculation (JSON array of {timestamp, mc} objects)
ALTER TABLE position_lifecycle ADD COLUMN mc_samples TEXT DEFAULT '[]';

-- Previous values for rate calculation
ALTER TABLE position_lifecycle ADD COLUMN prev_volume_1h REAL DEFAULT 0;
ALTER TABLE position_lifecycle ADD COLUMN prev_holder_count INTEGER DEFAULT 0;


-- ============================================================
-- 3. Create view for positions with exit data
-- ============================================================
CREATE VIEW IF NOT EXISTS v_position_exits AS
SELECT
    pl.id as position_id,
    pl.token_address,
    pl.token_symbol,
    pl.entry_timestamp,
    pl.entry_mc,
    pl.peak_mc,
    pl.current_mc,
    pl.outcome,
    pl.elite_exit_count,
    pl.elite_still_holding,
    pl.momentum_score,
    pl.volume_trend,
    COUNT(we.id) as total_exits,
    MIN(we.exit_timestamp) as first_exit,
    MAX(we.exit_timestamp) as last_exit,
    AVG(we.roi_at_exit) as avg_exit_roi
FROM position_lifecycle pl
LEFT JOIN wallet_exits we ON we.position_id = pl.id
GROUP BY pl.id;


-- ============================================================
-- 4. Create view for active token tracking (for webhook)
-- ============================================================
CREATE VIEW IF NOT EXISTS v_active_tokens AS
SELECT DISTINCT
    token_address,
    token_symbol,
    COUNT(DISTINCT wallet_address) as tracking_wallets,
    MIN(entry_timestamp) as first_entry,
    MAX(entry_timestamp) as last_entry
FROM position_lifecycle
WHERE outcome IS NULL OR outcome = 'open'
GROUP BY token_address;


-- ============================================================
-- 5. Index for efficient duplicate checking
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_position_lifecycle_dup_check
ON position_lifecycle(wallet_address, token_address, entry_timestamp);

-- Index for finding positions by token (for sell matching)
CREATE INDEX IF NOT EXISTS idx_position_lifecycle_token_open
ON position_lifecycle(token_address, outcome) WHERE outcome IS NULL OR outcome = 'open';

COMMIT;
