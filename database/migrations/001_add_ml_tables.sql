-- ============================================================================
-- V3 Edge Auto-Trader: ML Tables Migration
-- Run with: sqlite3 data/soulwinners.db < database/migrations/001_add_ml_tables.sql
-- ============================================================================

-- =============================================================================
-- PHASE 0: PERSONALIZED ALGORITHM SYSTEM TABLES
-- =============================================================================

-- User algorithm configuration for personalized wallet feeds
CREATE TABLE IF NOT EXISTS user_algo_config (
    user_id INTEGER PRIMARY KEY,
    risk_tolerance TEXT DEFAULT 'balanced',  -- 'conservative', 'balanced', 'aggressive'
    preferred_win_rate REAL DEFAULT 0.65,    -- Target win rate (0.5-0.9)
    preferred_roi REAL DEFAULT 100.0,        -- Target ROI % per trade
    max_token_age_hours REAL DEFAULT 24.0,   -- Max age of tokens to trade
    max_mcap REAL DEFAULT 10000000.0,        -- Max market cap to trade ($10M default)
    min_liquidity REAL DEFAULT 10000.0,      -- Minimum liquidity required ($10K default)
    feed_size INTEGER DEFAULT 150,           -- Number of wallets in personalized feed
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_rebalanced TIMESTAMP
);

-- User's personalized wallet feed (subset of global pool)
CREATE TABLE IF NOT EXISTS user_wallet_feed (
    user_id INTEGER NOT NULL,
    wallet_address TEXT NOT NULL,
    selection_score REAL,        -- Score for why this wallet was selected
    match_reason TEXT,           -- 'risk_match', 'roi_match', 'win_rate_match', etc.
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_performance_check TIMESTAMP,
    PRIMARY KEY (user_id, wallet_address)
);

-- Global pool of all quality wallets (656 qualified + insiders)
CREATE TABLE IF NOT EXISTS wallet_global_pool (
    wallet_address TEXT PRIMARY KEY,
    tier TEXT,                   -- 'Elite', 'High-Quality', 'Mid-Tier', 'Insider'
    quality_score REAL,          -- Overall quality score 0-100
    win_rate REAL,               -- Historical win rate
    avg_roi REAL,                -- Average ROI per trade
    consistency REAL,            -- Consistency score (std dev of returns)
    specialization TEXT,         -- 'meme', 'defi', 'general', 'early_buyer', etc.
    last_30d_performance REAL,   -- Recent performance indicator
    total_trades_30d INTEGER,    -- Trade count in last 30 days
    avg_hold_time_hours REAL,    -- Average hold time
    risk_score REAL,             -- Risk score (higher = riskier trades)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_wallet_global_pool_tier ON wallet_global_pool(tier);
CREATE INDEX IF NOT EXISTS idx_wallet_global_pool_score ON wallet_global_pool(quality_score DESC);
CREATE INDEX IF NOT EXISTS idx_user_wallet_feed_user ON user_wallet_feed(user_id);

-- =============================================================================
-- PHASE 1: HISTORICAL DATA COLLECTION TABLES
-- =============================================================================

-- Core trade events table (target: 1M+ events from 90 days)
CREATE TABLE IF NOT EXISTS trade_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    wallet_type TEXT,            -- 'qualified', 'insider', 'both'
    wallet_tier TEXT,            -- 'Elite', 'High-Quality', 'Mid-Tier', 'Insider'
    token_address TEXT NOT NULL,
    token_symbol TEXT,
    token_name TEXT,
    timestamp INTEGER NOT NULL,  -- Unix timestamp
    trade_type TEXT NOT NULL,    -- 'buy' or 'sell'
    sol_amount REAL,
    token_amount REAL,
    price_per_token REAL,
    -- Token metrics at trade time
    token_age_hours REAL,
    marketcap_at_trade REAL,
    liquidity_at_trade REAL,
    volume_24h_at_trade REAL,
    holder_count_at_trade INTEGER,
    buy_sell_ratio_at_trade REAL,
    -- Outcome tracking (filled after trade closes)
    max_mc_after_entry REAL,
    max_drawdown_percent REAL,
    time_to_peak_hours REAL,
    final_roi_percent REAL,
    outcome TEXT,                -- 'runner' (2x+), 'sideways', 'rug' (-80%+)
    outcome_filled_at TIMESTAMP,
    -- Metadata
    tx_signature TEXT,
    dex TEXT,                    -- 'pumpfun', 'raydium', 'jupiter'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(wallet_address, token_address, timestamp)
);

-- Token lifecycle tracking (for outcome labeling)
CREATE TABLE IF NOT EXISTS token_lifecycle (
    token_address TEXT PRIMARY KEY,
    token_symbol TEXT,
    token_name TEXT,
    first_seen_at INTEGER,       -- Unix timestamp
    launch_mcap REAL,
    peak_mcap REAL,
    peak_mcap_at INTEGER,        -- Unix timestamp
    current_mcap REAL,
    is_rugged INTEGER DEFAULT 0,
    rug_detected_at INTEGER,
    liquidity_removed_percent REAL,
    dev_sold_percent REAL,
    total_buys INTEGER DEFAULT 0,
    total_sells INTEGER DEFAULT 0,
    insider_buy_count INTEGER DEFAULT 0,
    elite_buy_count INTEGER DEFAULT 0,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ML features table (pre-computed features for training)
CREATE TABLE IF NOT EXISTS ml_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_event_id INTEGER,
    -- Token features
    mc_to_liq_ratio REAL,        -- Market cap / liquidity
    token_age_normalized REAL,   -- Normalized hours since creation
    price_velocity REAL,         -- Recent momentum
    volume_acceleration REAL,    -- Volume trend
    buy_sell_ratio REAL,         -- Buying pressure
    holder_growth_rate REAL,     -- Holder count change rate
    -- Wallet confluence features
    insider_count INTEGER,       -- Insider wallets in token
    elite_count INTEGER,         -- Elite wallets in token
    high_quality_count INTEGER,  -- High-Quality wallets in token
    total_smart_money INTEGER,   -- Total tracked wallets in token
    -- Risk features
    dev_sold INTEGER,            -- Developer activity (0/1)
    liquidity_removed INTEGER,   -- LP removal check (0/1)
    large_holder_concentration REAL,  -- % held by top 10
    -- Target variable
    outcome_label INTEGER,       -- 0=rug, 1=sideways, 2=runner
    roi_label REAL,              -- Actual ROI achieved
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trade_event_id) REFERENCES trade_events(id)
);

-- ML model versions and performance tracking
CREATE TABLE IF NOT EXISTS ml_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version TEXT NOT NULL,
    model_type TEXT,             -- 'xgboost', 'lightgbm'
    training_date TIMESTAMP,
    training_samples INTEGER,
    -- Performance metrics
    accuracy REAL,
    precision_runner REAL,
    recall_runner REAL,
    f1_runner REAL,
    precision_rug REAL,
    recall_rug REAL,
    f1_rug REAL,
    auc_roc REAL,
    -- Model path
    model_path TEXT,
    feature_importance_json TEXT,
    is_active INTEGER DEFAULT 0, -- Currently deployed model
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- AI trading decisions log
CREATE TABLE IF NOT EXISTS ai_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_event_id INTEGER,
    wallet_address TEXT,
    token_address TEXT,
    -- AI prediction
    prob_runner REAL,
    prob_sideways REAL,
    prob_rug REAL,
    expected_roi REAL,
    confidence_score REAL,
    -- Decision
    decision TEXT,               -- 'approve', 'reject', 'flag'
    decision_reason TEXT,
    position_size_pct REAL,      -- Recommended position size %
    -- Execution
    executed INTEGER DEFAULT 0,
    execution_price REAL,
    execution_time TIMESTAMP,
    -- Outcome tracking
    actual_outcome TEXT,
    actual_roi REAL,
    outcome_checked_at TIMESTAMP,
    -- Metadata
    model_version TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (trade_event_id) REFERENCES trade_events(id)
);

-- Auto-trader execution log
CREATE TABLE IF NOT EXISTS auto_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    ai_decision_id INTEGER,
    wallet_address TEXT,         -- Copied wallet
    token_address TEXT,
    token_symbol TEXT,
    -- Trade details
    trade_type TEXT,             -- 'buy' or 'sell'
    sol_amount REAL,
    token_amount REAL,
    -- Execution
    status TEXT,                 -- 'pending_confirmation', 'confirmed', 'executed', 'failed'
    telegram_confirmation_msg_id INTEGER,
    confirmed_at TIMESTAMP,
    tx_signature TEXT,
    execution_price REAL,
    execution_time TIMESTAMP,
    -- Fees
    fee_amount_sol REAL,
    -- Outcome
    exit_price REAL,
    exit_time TIMESTAMP,
    exit_tx_signature TEXT,
    pnl_sol REAL,
    pnl_percent REAL,
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ai_decision_id) REFERENCES ai_decisions(id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_trade_events_wallet ON trade_events(wallet_address);
CREATE INDEX IF NOT EXISTS idx_trade_events_token ON trade_events(token_address);
CREATE INDEX IF NOT EXISTS idx_trade_events_timestamp ON trade_events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_trade_events_outcome ON trade_events(outcome);
CREATE INDEX IF NOT EXISTS idx_token_lifecycle_mcap ON token_lifecycle(peak_mcap DESC);
CREATE INDEX IF NOT EXISTS idx_ml_features_event ON ml_features(trade_event_id);
CREATE INDEX IF NOT EXISTS idx_ai_decisions_token ON ai_decisions(token_address);
CREATE INDEX IF NOT EXISTS idx_ai_decisions_decision ON ai_decisions(decision);
CREATE INDEX IF NOT EXISTS idx_auto_trades_user ON auto_trades(user_id);
CREATE INDEX IF NOT EXISTS idx_auto_trades_status ON auto_trades(status);

-- =============================================================================
-- ADD AUTOTRADER SETTINGS TO SETTINGS TABLE
-- =============================================================================
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('ai_gate_enabled', 'false'),
    ('autotrader_enabled', 'false'),
    ('autotrader_min_prob_runner', '0.60'),
    ('autotrader_max_prob_rug', '0.30'),
    ('autotrader_require_confirmation', 'true'),
    ('autotrader_max_position_sol', '0.5'),
    ('autotrader_daily_trade_limit', '10'),
    ('ml_model_version', 'v1.0.0');

-- Add autotrader cron state
INSERT OR IGNORE INTO cron_states (cron_name, enabled) VALUES
    ('autotrader', 0),
    ('ml_training', 0),
    ('outcome_labeling', 1);

-- =============================================================================
-- ANTHROPIC AI ADVISOR TABLES
-- =============================================================================

-- Track per-user AI API usage for cost control
CREATE TABLE IF NOT EXISTS user_ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    month TEXT NOT NULL,              -- 'YYYY-MM' format
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cached_tokens INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0.0,
    request_count INTEGER DEFAULT 0,
    last_request_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, month)
);

-- AI conversation history for context
CREATE TABLE IF NOT EXISTS ai_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    conversation_type TEXT,           -- 'onboarding', 'trade_explain', 'strategy', 'review'
    messages_json TEXT,               -- JSON array of messages
    summary TEXT,                     -- Cached summary for prompt caching
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP              -- For cleanup
);

-- AI-generated trade explanations (cached)
CREATE TABLE IF NOT EXISTS ai_trade_explanations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ai_decision_id INTEGER,
    token_address TEXT,
    explanation TEXT,
    confidence_reasoning TEXT,
    risk_factors TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ai_decision_id) REFERENCES ai_decisions(id)
);

-- Weekly AI performance reviews
CREATE TABLE IF NOT EXISTS ai_weekly_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    week_start DATE NOT NULL,
    review_text TEXT,
    suggestions_json TEXT,
    performance_summary_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, week_start)
);

CREATE INDEX IF NOT EXISTS idx_ai_usage_user_month ON user_ai_usage(user_id, month);
CREATE INDEX IF NOT EXISTS idx_ai_conversations_user ON ai_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_explanations_token ON ai_trade_explanations(token_address);

-- AI budget settings
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('ai_advisor_enabled', 'false'),
    ('ai_budget_free_usd', '0.30'),
    ('ai_budget_paid_usd', '5.00'),
    ('ai_max_tokens_response', '500');
