-- ============================================================================
-- Wallet Importance Scoring Migration
-- Dynamic scoring based on lifecycle outcomes
-- Run with: sqlite3 data/soulwinners.db < database/migrations/003_add_wallet_importance.sql
-- ============================================================================

-- =============================================================================
-- ADD IMPORTANCE SCORE TO WALLET GLOBAL POOL
-- =============================================================================
ALTER TABLE wallet_global_pool ADD COLUMN importance_score REAL DEFAULT 0.0;
ALTER TABLE wallet_global_pool ADD COLUMN importance_updated_at TIMESTAMP;

-- Track outcome counts for transparency
ALTER TABLE wallet_global_pool ADD COLUMN runner_count INTEGER DEFAULT 0;
ALTER TABLE wallet_global_pool ADD COLUMN rug_count INTEGER DEFAULT 0;
ALTER TABLE wallet_global_pool ADD COLUMN sideways_count INTEGER DEFAULT 0;

-- Track multi-bagger achievements from lifecycle
ALTER TABLE wallet_global_pool ADD COLUMN tokens_2x_plus INTEGER DEFAULT 0;
ALTER TABLE wallet_global_pool ADD COLUMN tokens_3x_plus INTEGER DEFAULT 0;
ALTER TABLE wallet_global_pool ADD COLUMN tokens_5x_plus INTEGER DEFAULT 0;
ALTER TABLE wallet_global_pool ADD COLUMN tokens_10x_plus INTEGER DEFAULT 0;

-- =============================================================================
-- IMPORTANCE SCORE INDEX
-- =============================================================================
CREATE INDEX IF NOT EXISTS idx_wallet_global_pool_importance
    ON wallet_global_pool(importance_score DESC);

-- =============================================================================
-- ADD IMPORTANCE TRACKING CRON STATE
-- =============================================================================
INSERT OR IGNORE INTO cron_states (cron_name, enabled) VALUES
    ('wallet_importance', 1);

-- =============================================================================
-- SETTINGS FOR IMPORTANCE SCORING
-- =============================================================================
INSERT OR IGNORE INTO settings (key, value) VALUES
    ('importance_10x_points', '5'),
    ('importance_5x_points', '3'),
    ('importance_3x_points', '2'),
    ('importance_2x_points', '1'),
    ('importance_rug_penalty', '-1');
