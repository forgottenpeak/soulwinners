# Complete Pipeline Changes - Summary

## Overview

This document summarizes ALL changes made to the SoulWinners pipeline system.

---

## Change 1: Scan From Birth (0-24 Hours) ✅

**Status:** COMPLETE

**Purpose:** Scan tokens from creation (0 min) instead of 10-minute minimum to capture insiders and dev wallets.

### Files Modified
- `collectors/launch_tracker.py`
- `collectors/pumpfun.py`
- `pipeline/orchestrator.py`

### Key Changes
1. **Removed min_age_minutes parameter** - No minimum age restriction
2. **Changed filter logic** - `if launch_time > cutoff` (not `cutoff_old < launch_time < cutoff_recent`)
3. **Updated buyer window** - Default 0-30 min (not 10-30 min)
4. **New API endpoint** - `/coins/latest` instead of `/coins/king-of-the-hill`
5. **Increased buyer limit** - 100 buyers per token (not 20)

### Benefits
- ✅ Captures insiders (0-5 min) = highest alpha
- ✅ Gets dev team wallets
- ✅ Tracks fastest snipers (5-15 min)
- ✅ No artificial time cutoffs
- ✅ Filter by performance later, not by time

### Deployment
```bash
bash deployment/deploy_fresh_launch_fix.sh root@vps-ip
```

---

## Change 2: Airdrop Tracking ✅

**Status:** COMPLETE

**Purpose:** Detect team members and insiders via airdrop recipients (0 SOL cost transfers).

### Files Modified
- `collectors/launch_tracker.py` - Added AirdropTracker class
- `pipeline/insider_detector.py` - Added airdrop integration

### New Components

#### 1. AirdropRecipient Dataclass
```python
@dataclass
class AirdropRecipient:
    wallet_address: str
    token_address: str
    token_symbol: str
    received_time: datetime
    time_since_launch_min: int
    token_amount: float
    token_value_sol: float
    percent_of_supply: float
    has_sold: bool
    sold_amount: float
    sold_at: datetime
    hold_duration_min: int
    pattern: str = "Airdrop Insider"
```

#### 2. AirdropTracker Class
**Methods:**
- `detect_airdrops()` - Find airdrop recipients (0 SOL cost)
- `_extract_airdrop_recipient()` - Parse transaction for airdrops
- `track_airdrop_sells()` - Monitor when they sell
- `save_airdrop_recipient()` - Save to database
- `generate_sell_alert()` - Alert when insiders dump

#### 3. Database Table
```sql
CREATE TABLE airdrop_insiders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wallet_address TEXT NOT NULL,
    token_address TEXT NOT NULL,
    token_symbol TEXT,
    received_time TIMESTAMP,
    time_since_launch_min INTEGER,
    token_amount REAL,
    token_value_sol REAL DEFAULT 0,
    percent_of_supply REAL DEFAULT 0,
    has_sold INTEGER DEFAULT 0,
    sold_amount REAL DEFAULT 0,
    sold_at TIMESTAMP,
    hold_duration_min INTEGER DEFAULT 0,
    pattern TEXT DEFAULT 'Airdrop Insider',
    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(wallet_address, token_address)
);
```

#### 4. InsiderScanner Integration
- Scans for airdrops on every fresh token
- Auto-adds airdrop wallets to pool (no screening)
- Tracks sell behavior
- Generates alerts when insiders dump

#### 5. InsiderDetector Integration
- `_check_airdrop_history()` - Check wallet's airdrop count
- `get_airdrop_stats()` - Get airdrop statistics
- Adds airdrop count to behavior signals

### Alert Format
```
🚨 INSIDER SELL DETECTED
💰 Airdrop wallet dumped 20000 tokens
🪙 $PUMP
⏰ Hold duration: 45 minutes
👤 Wallet: 7xKXtg2CW5UL...
⚠️ Caution: Insiders taking profit
```

### Benefits
- ✅ Detects team members via airdrops
- ✅ Tracks insider sell behavior
- ✅ Generates exit signals when insiders dump
- ✅ Auto-adds to pool (airdrop = insider proof)
- ✅ No screening needed

### Deployment
```bash
bash deployment/deploy_airdrop_tracking.sh root@vps-ip
```

---

## Combined Pipeline Flow

### Phase 1: Token Discovery (Every scan cycle)
```
1. Scan Pump.fun /coins/latest API
   └─> Get tokens 0-24 hours old

2. Filter tokens
   └─> No minimum age (scan from birth)
   └─> Includes brand new tokens (<10 min old)
```

### Phase 2: Buyer Collection (Per token)
```
3. Get first 100 buyers
   └─> Time window: 0-30 minutes from launch
   └─> Includes:
       - Insiders (0-5 min)
       - Fast snipers (5-15 min)
       - Early buyers (15-30 min)

4. Analyze each buyer
   └─> Track patterns across launches
   └─> Calculate win rates
   └─> Add to insider_pool if qualified
```

### Phase 3: Airdrop Detection (Per token)
```
5. Scan token transactions
   └─> Find token transfers with 0 SOL cost
   └─> Identify airdrop recipients

6. For each airdrop recipient:
   a. Save to airdrop_insiders table
   b. Add to insider_pool immediately
   c. Add to qualified_wallets (tier: Elite)
   d. Track their sell behavior
   e. Generate alert if they dump
```

### Phase 4: Promotion
```
7. Check for promotion to main pool
   └─> High-confidence insiders (>70%)
   └─> Good win rate (>60%)
   └─> Promote to qualified_wallets
```

---

## Data Flow

```
Pump.fun API (/coins/latest)
    ↓
Fresh Tokens (0-24h old)
    ↓
    ├─> First 100 Buyers (0-30 min)
    │   ├─> Analyze patterns
    │   └─> Add to insider_pool
    │
    └─> Airdrop Recipients (0 SOL cost)
        ├─> Save to airdrop_insiders
        ├─> Add to insider_pool
        ├─> Add to qualified_wallets
        └─> Track sells → Generate alerts
```

---

## Database Tables

### 1. qualified_wallets (Main Pool)
- Contains all qualified trading wallets
- Tiers: Elite, High, Medium, Low
- Sources: pumpfun, dexscreener, insider, **airdrop_insider**

### 2. insider_pool (Insider Detection)
- Wallets with insider patterns
- Patterns: Migration Sniper, Early Bird, Launch Sniper, **Airdrop Insider**
- Promoted to qualified_wallets when proven

### 3. airdrop_insiders (NEW - Airdrop Tracking)
- Wallets that received airdrops
- Tracks: amount, sell behavior, hold duration
- Generates sell alerts

---

## Log Output Examples

### Fresh Launch Scanning
```
Found 45 fresh tokens (0-24h old)
Found 38 fresh Pump.fun launches (0-24h from birth)
PUMP: Found 73 buyers (0-30min window)
  Insider detected: 7xKXtg2CW... - Launch Sniper
```

### Airdrop Detection
```
Scanning for airdrop recipients...
Airdrop detected: 9vY8Rp3Qm... received 50000 tokens at 2.5 min
Found 4 airdrop recipients
Added airdrop wallet to pool: 9vY8Rp3Qm...
```

### Sell Alerts
```
🚨 INSIDER SELL DETECTED
💰 Airdrop wallet dumped 20000 tokens
🪙 $PUMP
⏰ Hold duration: 45 minutes
👤 Wallet: 9vY8Rp3Qm...
⚠️ Caution: Insiders taking profit
```

---

## Deployment Scripts

### 1. deploy_fresh_launch_fix.sh
Deploys scan-from-birth changes:
- collectors/launch_tracker.py
- collectors/pumpfun.py
- pipeline/orchestrator.py

### 2. deploy_airdrop_tracking.sh
Deploys airdrop tracking:
- collectors/launch_tracker.py (AirdropTracker)
- pipeline/insider_detector.py (airdrop integration)
- Creates airdrop_insiders table

### 3. deploy_new_commands.sh
Deploys new Telegram bot commands:
- /insiders - Insider pool stats
- /clusters - Wallet clusters
- /early_birds - Fresh launch snipers

---

## Complete Deployment

### Option 1: Deploy All Changes
```bash
cd /Users/APPLE/Desktop/Soulwinners

# Deploy fresh launch scanning
bash deployment/deploy_fresh_launch_fix.sh root@vps-ip

# Deploy airdrop tracking
bash deployment/deploy_airdrop_tracking.sh root@vps-ip

# Deploy new bot commands
bash deployment/deploy_new_commands.sh root@vps-ip
```

### Option 2: Manual Deployment
```bash
# Copy all modified files
scp collectors/launch_tracker.py root@vps:/root/Soulwinners/collectors/
scp collectors/pumpfun.py root@vps:/root/Soulwinners/collectors/
scp pipeline/orchestrator.py root@vps:/root/Soulwinners/pipeline/
scp pipeline/insider_detector.py root@vps:/root/Soulwinners/pipeline/
scp bot/commands.py root@vps:/root/Soulwinners/bot/

# SSH to VPS
ssh root@vps

# Create airdrop_insiders table
sqlite3 /root/Soulwinners/data/soulwinners.db < deployment/create_airdrop_table.sql

# Restart services
systemctl restart soulwinners

# Monitor
tail -f /root/Soulwinners/logs/pipeline.log
```

---

## Testing

### Run Test Suites
```bash
# Test fresh launch scanning
python3 deployment/test_fresh_launch.py

# Test airdrop tracking
python3 deployment/test_airdrop_tracking.py
```

---

## Monitoring

### Key Metrics to Watch

**Token Collection:**
- Tokens per scan: 40-80 (up from 20-30)
- Age range: 0-24 hours (not 10min-24h)

**Buyer Collection:**
- Buyers per token: 60-100 (up from 10-20)
- Time range: 0-30 min (not 10-30 min)
- Insiders captured: 5-15 per token (0-5 min buyers)

**Airdrop Detection:**
- Airdrops per day: 50-200
- Recipients per token: 2-8 (team size)
- Auto-added to pool: All airdrop recipients

**Sell Alerts:**
- Alerts per day: 20-80 (when insiders dump)
- Average hold time: 30-120 minutes

### Database Queries

**Check pipeline status:**
```sql
-- Recent pipeline runs
SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 5;

-- Pool size by source
SELECT source, COUNT(*) FROM qualified_wallets GROUP BY source;

-- Airdrop insiders
SELECT COUNT(*) FROM airdrop_insiders;

-- Recent airdrops
SELECT * FROM airdrop_insiders ORDER BY received_time DESC LIMIT 10;

-- Insider sells
SELECT * FROM airdrop_insiders WHERE has_sold = 1 ORDER BY sold_at DESC LIMIT 10;
```

---

## Expected Results

### Before Changes
```
✗ Tokens: 20-30 trending (old news)
✗ Buyers: 10-20 per token (late)
✗ No insider detection
✗ No airdrop tracking
✗ No team member detection
✗ No sell signals
```

### After Changes
```
✅ Tokens: 40-80 fresh (0-24h from birth)
✅ Buyers: 60-100 per token (includes insiders)
✅ Insiders: 5-15 per token (0-5 min)
✅ Airdrops: 50-200 per day (team members)
✅ Sell tracking: Real-time insider dumps
✅ Alerts: Exit signals when insiders dump
```

---

## Success Criteria

✅ **All changes deployed successfully if:**

1. **Fresh Launch Scanning**
   - Logs show "0-24h from birth"
   - Buyer window is 0-30 min
   - Using /coins/latest endpoint
   - No min_age_minutes parameter

2. **Airdrop Tracking**
   - AirdropTracker class exists
   - airdrop_insiders table created
   - Logs show "Airdrop detected"
   - Sell alerts generated

3. **Database**
   - qualified_wallets has airdrop_insider source
   - airdrop_insiders table populated
   - insider_pool has Airdrop Insider pattern

4. **Performance**
   - More tokens collected per scan
   - More wallets in pool
   - Higher quality insiders
   - Real-time sell signals

---

## Documentation Files

1. **SCAN_FROM_BIRTH.md** - Fresh launch scanning guide
2. **AIRDROP_TRACKING.md** - Airdrop detection guide
3. **COMPLETE_PIPELINE_CHANGES.md** (this file) - Complete summary
4. **deploy_fresh_launch_fix.sh** - Deployment script
5. **deploy_airdrop_tracking.sh** - Deployment script
6. **test_fresh_launch.py** - Test suite
7. **test_airdrop_tracking.py** - Test suite

---

**🎯 Complete Pipeline v2.0**

Maximum alpha: Birth scanning + Airdrop tracking + Insider detection

**Status: Ready for Production** ✅
