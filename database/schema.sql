-- SoulWinners Database Schema
-- Replicates your original 2-table structure + qualified wallets output

-- =============================================================================
-- TABLE 1: WALLET_PERFORMANCE (Pump.fun Wallets)
-- Source: Pump.fun token launches and trading
-- =============================================================================
CREATE TABLE IF NOT EXISTS wallet_performance (
    wallet_address TEXT PRIMARY KEY,
    source TEXT DEFAULT 'pumpfun',
    rank INTEGER,
    last_tx TIMESTAMP,
    total_profit_usd REAL,
    unique_tokens_traded INTEGER,
    tokens_net_profit INTEGER,
    buy_transactions INTEGER,
    sell_transactions INTEGER,
    current_balance_sol REAL,
    total_sol_spent REAL,
    total_sol_earned REAL,
    realized_pnl REAL,
    unrealized_pnl REAL,
    win_rate REAL,
    tokens_less_10x INTEGER DEFAULT 0,
    tokens_10x_plus INTEGER DEFAULT 0,
    tokens_20x_plus INTEGER DEFAULT 0,
    tokens_50x_plus INTEGER DEFAULT 0,
    tokens_100x_plus INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- TABLE 2: WALLET_DETAILS (DEX Wallets)
-- Source: DexScreener (Raydium, Jupiter, Orca, etc.)
-- =============================================================================
CREATE TABLE IF NOT EXISTS wallet_details (
    wallet_address TEXT PRIMARY KEY,
    source TEXT DEFAULT 'dex',
    days_since_first_trade INTEGER,
    pnl_sol REAL,
    roi_percent REAL,
    median_roi_percent REAL,
    median_hold_time_seconds REAL,
    median_first_buy_to_sell_seconds REAL,
    unique_tokens_traded INTEGER,
    tokens_net_profit INTEGER,
    buy_transactions INTEGER,
    sell_transactions INTEGER,
    current_balance_sol REAL,
    total_sol_spent REAL,
    total_sol_earned REAL,
    win_rate REAL,
    tokens_less_10x INTEGER DEFAULT 0,
    tokens_10x_plus INTEGER DEFAULT 0,
    tokens_20x_plus INTEGER DEFAULT 0,
    tokens_50x_plus INTEGER DEFAULT 0,
    tokens_100x_plus INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- TABLE 3: MERGED WALLETS (Combined with calculated metrics)
-- =============================================================================
CREATE TABLE IF NOT EXISTS wallet_metrics (
    wallet_address TEXT PRIMARY KEY,
    source TEXT,  -- 'pumpfun', 'dex', or 'both'

    -- Base Stats
    current_balance_sol REAL,
    total_trades INTEGER,
    buy_transactions INTEGER,
    sell_transactions INTEGER,
    unique_tokens_traded INTEGER,

    -- Performance Metrics (Your calculated metrics)
    roi_pct REAL,
    median_roi_pct REAL,
    profit_token_ratio REAL,  -- Win rate
    trade_frequency REAL,     -- Trades per day
    roi_per_trade REAL,

    -- Multi-bagger Ratios
    x10_ratio REAL,
    x20_ratio REAL,
    x50_ratio REAL,
    x100_ratio REAL,

    -- Behavior Metrics
    median_hold_time REAL,
    profit_per_hold_second REAL,

    -- Clustering Results
    cluster INTEGER,
    cluster_label TEXT,
    cluster_name TEXT,

    -- Scoring & Ranking
    roi_final REAL,
    priority_score REAL,
    tier TEXT,  -- 'Elite', 'High-Quality', 'Mid-Tier', 'Watchlist'
    strategy_bucket TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- TABLE 4: QUALIFIED WALLETS (Final output - your df_ranked.csv format)
-- =============================================================================
CREATE TABLE IF NOT EXISTS qualified_wallets (
    wallet_address TEXT PRIMARY KEY,
    source TEXT,
    roi_pct REAL,
    median_roi_pct REAL,
    profit_token_ratio REAL,
    trade_frequency REAL,
    roi_per_trade REAL,
    x10_ratio REAL,
    x20_ratio REAL,
    x50_ratio REAL,
    x100_ratio REAL,
    median_hold_time REAL,
    profit_per_hold_second REAL,
    cluster INTEGER,
    cluster_label TEXT,
    cluster_name TEXT,
    roi_final REAL,
    priority_score REAL,
    tier TEXT,
    strategy_bucket TEXT,
    current_balance_sol REAL,
    total_trades INTEGER,
    win_rate REAL,
    qualified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_alert_at TIMESTAMP
);

-- =============================================================================
-- TABLE 5: TRANSACTION HISTORY (From Helius)
-- =============================================================================
CREATE TABLE IF NOT EXISTS transactions (
    signature TEXT PRIMARY KEY,
    wallet_address TEXT,
    token_address TEXT,
    token_symbol TEXT,
    tx_type TEXT,  -- 'buy' or 'sell'
    amount_sol REAL,
    amount_tokens REAL,
    price_per_token REAL,
    timestamp TIMESTAMP,
    pnl_sol REAL,
    pnl_percent REAL,
    dex TEXT,  -- 'pumpfun', 'raydium', 'jupiter', etc.
    FOREIGN KEY (wallet_address) REFERENCES qualified_wallets(wallet_address)
);

-- =============================================================================
-- TABLE 6: ALERT HISTORY (Telegram alerts sent)
-- =============================================================================
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT,
    token_address TEXT,
    token_symbol TEXT,
    token_name TEXT,
    token_image_url TEXT,
    tx_signature TEXT,
    alert_type TEXT,  -- 'buy', 'sell'
    tier TEXT,
    strategy TEXT,
    message_id INTEGER,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (wallet_address) REFERENCES qualified_wallets(wallet_address)
);

-- =============================================================================
-- TABLE 7: PIPELINE RUNS (Track daily refreshes)
-- =============================================================================
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    status TEXT,  -- 'running', 'completed', 'failed'
    wallets_collected INTEGER,
    wallets_qualified INTEGER,
    wallets_added INTEGER,
    wallets_removed INTEGER,
    error_message TEXT
);

-- =============================================================================
-- TABLE 8: SETTINGS (Bot configuration)
-- =============================================================================
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Default settings
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('min_buy_amount', '1.0'),
    ('alert_age_limit_min', '5'),
    ('last_5_win_rate', '0.6'),
    ('alerts_enabled', 'true'),
    ('discovery_frequency_min', '10'),
    ('auto_discovery', 'true'),
    ('min_sol_balance', '10'),
    ('min_trades', '15'),
    ('min_win_rate', '0.6'),
    ('min_roi', '0.5'),
    ('poll_interval_sec', '30'),
    ('monitor_enabled', 'true');

-- =============================================================================
-- INDEXES for performance
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_wallet_metrics_tier ON wallet_metrics(tier);
CREATE INDEX IF NOT EXISTS idx_wallet_metrics_priority ON wallet_metrics(priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_qualified_tier ON qualified_wallets(tier);
CREATE INDEX IF NOT EXISTS idx_qualified_priority ON qualified_wallets(priority_score DESC);
CREATE INDEX IF NOT EXISTS idx_transactions_wallet ON transactions(wallet_address);
CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_wallet ON alerts(wallet_address);
CREATE INDEX IF NOT EXISTS idx_alerts_sent ON alerts(sent_at DESC);
