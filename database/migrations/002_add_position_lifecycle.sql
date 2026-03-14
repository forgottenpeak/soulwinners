-- ============================================================================
-- Position Lifecycle Tracking Migration
-- Real-time tracking of positions from entry to exit
-- Run with: sqlite3 data/soulwinners.db < database/migrations/002_add_position_lifecycle.sql
-- ============================================================================

-- =============================================================================
-- POSITION LIFECYCLE TABLE
-- Tracks trades from buy to sell with real-time updates
-- Comprehensive tracking for ML training
-- =============================================================================
CREATE TABLE IF NOT EXISTS position_lifecycle (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Link to trade_events for ML integration
    buy_event_id INTEGER,

    -- Position identification
    wallet_address TEXT NOT NULL,
    token_address TEXT NOT NULL,
    token_symbol TEXT,

    -- Entry data
    entry_timestamp INTEGER NOT NULL,       -- Unix timestamp of buy
    entry_mc REAL,                          -- Market cap at entry
    entry_liquidity REAL,                   -- Liquidity at entry
    buy_sol_amount REAL NOT NULL,           -- SOL spent on buy
    token_age_at_entry REAL,                -- Token age in hours at entry

    -- Exit data (NULL if position still open - tracking continues!)
    sell_event_id INTEGER,
    exit_timestamp INTEGER,                 -- Unix timestamp of sell
    exit_mc REAL,                           -- Market cap at exit
    sell_sol_received REAL,                 -- SOL received from sell

    -- Lifecycle metrics (updated hourly for 48h)
    peak_mc REAL,                           -- Highest MC observed
    peak_timestamp INTEGER,                 -- When peak was observed
    time_to_peak_hours REAL,                -- Hours from entry to peak
    current_mc REAL,                        -- Most recent MC check
    last_checked_timestamp INTEGER,         -- Last hourly update
    check_count INTEGER DEFAULT 0,          -- Number of hourly checks

    -- MOMENTUM TRACKING (hourly updates)
    volume_5m REAL,                         -- 5-minute volume
    volume_1h REAL,                         -- 1-hour volume
    volume_24h REAL,                        -- 24-hour volume
    volume_acceleration REAL,               -- (vol_5m*12 - vol_1h) / vol_1h
    price_velocity REAL,                    -- % change per hour
    buy_sell_ratio REAL,                    -- Buys / Total txs

    -- WALLET CONFLUENCE (updated hourly - CRITICAL!)
    insider_wallet_count INTEGER DEFAULT 0, -- How many insiders in this token
    elite_wallet_count INTEGER DEFAULT 0,   -- How many elites in this token
    repeated_buyer_count INTEGER DEFAULT 0, -- Wallets buying multiple times
    new_wallet_influx INTEGER DEFAULT 0,    -- New unique buyers last hour

    -- HOLDER DYNAMICS (hourly)
    holder_count INTEGER,                   -- Current holder count
    holder_growth_rate REAL,                -- % change per hour
    top10_concentration REAL,               -- % owned by top 10
    holder_velocity REAL,                   -- Rate of holder change

    -- DEV WALLET TRACKING (CRITICAL for rug detection!)
    dev_wallet_address TEXT,
    dev_initial_holdings REAL,
    dev_current_holdings REAL,
    dev_sold INTEGER DEFAULT 0,             -- Boolean: did dev sell >50%?
    dev_sell_timestamp INTEGER,
    dev_sell_amount REAL,
    liquidity_removed INTEGER DEFAULT 0,    -- Boolean: was LP removed?
    liquidity_removal_timestamp INTEGER,

    -- Final outcome (labeled after 48h based on TOKEN lifecycle)
    final_roi_percent REAL,                 -- Token peak ROI (not wallet exit)
    hold_duration_hours REAL,               -- Total tracking time
    outcome TEXT,                           -- 'runner', 'rug', 'sideways', 'open'
    outcome_labeled_at TIMESTAMP,           -- When outcome was finalized

    -- Source tracking
    wallet_type TEXT,                       -- 'qualified', 'insider', 'watchlist'
    wallet_tier TEXT,                       -- 'Elite', 'High-Quality', 'Mid-Tier', etc.
    alert_sent INTEGER DEFAULT 0,           -- Was alert sent for this position?
    alert_message_id INTEGER,               -- Telegram message ID of alert

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Constraints
    FOREIGN KEY (buy_event_id) REFERENCES trade_events(id),
    FOREIGN KEY (sell_event_id) REFERENCES trade_events(id),
    UNIQUE(wallet_address, token_address, entry_timestamp)
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================

-- Query open positions for hourly monitoring
CREATE INDEX IF NOT EXISTS idx_position_lifecycle_open
    ON position_lifecycle(outcome) WHERE outcome IS NULL OR outcome = 'open';

-- Query by wallet for sell matching
CREATE INDEX IF NOT EXISTS idx_position_lifecycle_wallet
    ON position_lifecycle(wallet_address, token_address);

-- Query for ML training (labeled outcomes only)
CREATE INDEX IF NOT EXISTS idx_position_lifecycle_outcome
    ON position_lifecycle(outcome) WHERE outcome IS NOT NULL AND outcome != 'open';

-- Query for recent positions
CREATE INDEX IF NOT EXISTS idx_position_lifecycle_entry
    ON position_lifecycle(entry_timestamp DESC);

-- Query by token for analysis
CREATE INDEX IF NOT EXISTS idx_position_lifecycle_token
    ON position_lifecycle(token_address);

-- =============================================================================
-- HELPER VIEWS
-- =============================================================================

-- View for open positions needing monitoring
CREATE VIEW IF NOT EXISTS v_open_positions AS
SELECT
    pl.*,
    (strftime('%s', 'now') - pl.entry_timestamp) / 3600.0 as age_hours,
    CASE
        WHEN pl.peak_mc > 0 AND pl.entry_mc > 0
        THEN ((pl.peak_mc - pl.entry_mc) / pl.entry_mc * 100)
        ELSE 0
    END as peak_roi_percent
FROM position_lifecycle pl
WHERE pl.outcome IS NULL OR pl.outcome = 'open';

-- View for labeled positions (ML training)
CREATE VIEW IF NOT EXISTS v_labeled_positions AS
SELECT
    pl.*,
    te.token_age_hours as entry_token_age,
    te.volume_24h_at_trade as entry_volume_24h,
    te.holder_count_at_trade as entry_holder_count,
    te.buy_sell_ratio_at_trade as entry_buy_sell_ratio
FROM position_lifecycle pl
LEFT JOIN trade_events te ON pl.buy_event_id = te.id
WHERE pl.outcome IS NOT NULL AND pl.outcome != 'open';

-- =============================================================================
-- ADD CRON STATE FOR LIFECYCLE TRACKING
-- =============================================================================
INSERT OR IGNORE INTO cron_states (cron_name, enabled) VALUES
    ('lifecycle_tracking', 1);

-- =============================================================================
-- ADD SETTINGS FOR LIFECYCLE TRACKING
-- =============================================================================
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('lifecycle_check_hours', '48'),
    ('lifecycle_runner_threshold', '100'),
    ('lifecycle_rug_threshold', '-80');
