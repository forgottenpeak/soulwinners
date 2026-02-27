# Scan From Birth (0-24 Hours) - No Minimum Age

## Overview

Pipeline now scans tokens **from birth (0 minutes to 24 hours old)** with NO minimum age restriction. This captures:
- **Insiders** (0-5 min) - highest alpha
- **Dev team** connections
- **Fastest snipers** (5-15 min)
- **Early buyers** (15-30 min)
- **All other buyers** up to 24 hours

## Key Change

### Before (10-Minute Minimum)
```python
# Avoided 0-10 minute buyers
if cutoff_old < launch_time < cutoff_recent:  # 10min-24h
```

### After (From Birth)
```python
# Get ALL buyers from token creation
if launch_time > cutoff:  # 0-24h from birth
```

## Why Scan From Birth?

### Insider Wallets = Highest Alpha

**0-5 minutes (BEST):**
- Insiders with advance knowledge
- Dev team and their connections
- Friends/family of creators
- Early access bots
- **These wallets know before public launch**

**5-15 minutes:**
- Fastest snipers
- Advanced monitoring systems
- Quick reaction traders

**15-30 minutes:**
- Early discovery
- Still ahead of the curve

**30+ minutes:**
- Regular early buyers
- Trending followers

## Buyer Classification Strategy

Get ALL buyers, then classify by timing and performance:

### Tier 1: Insiders (0-5 min)
- **Signal**: Knows before launch
- **Edge**: Maximum information advantage
- **Risk**: May be dev, may dump
- **Filter**: Track performance across multiple launches

### Tier 2: Fast Snipers (5-15 min)
- **Signal**: Fastest reaction time
- **Edge**: Advanced monitoring
- **Risk**: May chase pumps
- **Filter**: Win rate on fresh launches

### Tier 3: Early Buyers (15-30 min)
- **Signal**: Early discovery
- **Edge**: Ahead of trending
- **Risk**: Slower than snipers
- **Filter**: Consistency across tokens

### Tier 4+: Regular (30+ min)
- **Signal**: Following momentum
- **Edge**: Trend identification
- **Risk**: Later to the party
- **Filter**: Overall performance

## Performance Filtering (Not Time Filtering)

Instead of excluding insiders by time, we:

1. **Collect ALL buyers** (0-24 hours)
2. **Track patterns** across multiple launches
3. **Calculate metrics**:
   - Win rate on fresh launches
   - Consistency (how many launches they catch)
   - Average entry timing
   - ROI patterns
4. **Filter by quality**, not by time

### Quality Metrics

**Good Insider/Fast Sniper:**
- ✅ High win rate (60%+)
- ✅ Consistent entries across many tokens
- ✅ Good exit discipline
- ✅ Positive ROI pattern

**Bad Insider/Dev Wallet:**
- ❌ Low win rate (dumps on others)
- ❌ Only 1-2 tokens (their own projects)
- ❌ Poor exit timing
- ❌ Negative ROI overall

## Files Modified

### 1. collectors/launch_tracker.py

**Removed min_age_minutes parameter:**
```python
def __init__(self, max_age_hours: int = 24):
    # No more min_age_minutes
```

**Changed filter to scan from birth:**
```python
cutoff = datetime.now() - timedelta(hours=self.max_age_hours)
# Scan from birth (0 min) to 24 hours
if launch_time > cutoff:
```

**Updated get_first_buyers default:**
```python
async def get_first_buyers(self, token_address: str, limit: int = 100,
                           min_minutes: int = 0,  # Changed from 10 to 0
                           max_minutes: int = 30):
```

### 2. collectors/pumpfun.py

**Removed min_age_minutes parameter:**
```python
async def get_fresh_pumpfun_launches(self, max_age_hours: int = 24):
    # No more min_age_minutes
```

**Changed filter:**
```python
cutoff = datetime.now() - timedelta(hours=max_age_hours)
# Scan from birth
if launch_time > cutoff:
```

### 3. pipeline/orchestrator.py

**Updated comment:**
```python
# Use fresh launches from birth (0-24 hours old)
# Get insiders, dev team, fastest snipers!
```

## Deployment

### Quick Deploy

```bash
cd /Users/APPLE/Desktop/Soulwinners
bash deployment/deploy_fresh_launch_fix.sh root@your-vps-ip
```

### Verify Changes

```bash
# Should NOT find "min_age_minutes: int = 10"
grep "min_age_minutes" collectors/launch_tracker.py

# Should find "min_minutes: int = 0"
grep "min_minutes: int = 0" collectors/launch_tracker.py

# Should find "Scan from birth"
grep "Scan from birth" collectors/launch_tracker.py
```

## Expected Log Output

```
Found 80 fresh tokens (0-24h old)
Found 60 fresh Pump.fun launches (0-24h from birth)
Collected 450 pump.fun wallets from fresh launches
PUMP123: Found 87 buyers (0-30min window)
```

## Buyer Distribution Example

For a token launched 2 hours ago:

```
Total buyers: 250
├── 0-5 min:   15 buyers (insiders, dev team)      ⭐⭐⭐⭐⭐
├── 5-15 min:  35 buyers (fast snipers)            ⭐⭐⭐⭐
├── 15-30 min: 50 buyers (early discovery)         ⭐⭐⭐
├── 30-60 min: 60 buyers (early followers)         ⭐⭐
└── 1-2h:      90 buyers (regular buyers)          ⭐
```

We collect the **first 100 buyers**, which includes:
- All 15 insiders (0-5 min) ✅
- All 35 fast snipers (5-15 min) ✅
- All 50 early buyers (15-30 min) ✅

## Performance Expectations

### Token Collection
- **Before (10-min minimum)**: 30-50 tokens
- **After (from birth)**: 60-100 tokens

### Wallet Collection
- **Before**: 200-400 wallets
- **After**: 400-800 wallets

### Quality Distribution
- **Insiders (0-5 min)**: 10-20% of buyers
- **Fast snipers (5-15 min)**: 25-35% of buyers
- **Early (15-30 min)**: 35-45% of buyers

### Filter Later By Performance
After collecting, analyze:
- Wallets with 70%+ win rate → Elite tier
- Wallets appearing in 10+ launches → Consistent hunters
- Wallets with <40% win rate → Exclude

## Monitoring

### Check Buyer Timing Distribution

```bash
sqlite3 data/soulwinners.db "
SELECT
  CASE
    WHEN entry_time_min < 5 THEN '0-5min (Insiders)'
    WHEN entry_time_min < 15 THEN '5-15min (Fast Snipers)'
    WHEN entry_time_min < 30 THEN '15-30min (Early)'
    ELSE '30min+ (Regular)'
  END as timing_tier,
  COUNT(*) as count,
  AVG(win_rate) as avg_win_rate,
  AVG(roi_pct) as avg_roi
FROM qualified_wallets
WHERE source = 'pumpfun'
GROUP BY timing_tier
"
```

Expected output:
```
0-5min (Insiders)      | 85  | 0.72 | 245.3
5-15min (Fast Snipers) | 140 | 0.68 | 198.7
15-30min (Early)       | 180 | 0.61 | 156.2
30min+ (Regular)       | 95  | 0.54 | 112.8
```

### Check for Dev Wallets

Dev wallets typically:
- Only buy 1-2 tokens (their own)
- Buy at 0-2 minutes
- Large initial position
- Never sell or dump immediately

```bash
sqlite3 data/soulwinners.db "
SELECT wallet_address,
       COUNT(DISTINCT token_address) as unique_tokens,
       AVG(entry_time_min) as avg_entry_time,
       win_rate
FROM wallet_trades
WHERE entry_time_min < 5
GROUP BY wallet_address
HAVING unique_tokens < 3  -- Potential dev wallets
"
```

## Success Criteria

✅ **Deployment successful if:**

1. No min_age_minutes parameter in code
2. Logs show "0-24h from birth"
3. Buyer window starts at 0 minutes (not 10)
4. More wallets collected per scan
5. Getting buyers with <5 min entry times
6. Token collection increased

## Advantages

### Highest Alpha Possible
- Catching THE earliest buyers
- Insider knowledge signal
- Dev team connections
- Fastest reaction times

### More Data
- Larger wallet pool
- Better statistical analysis
- More patterns to detect
- Earlier trend identification

### Competitive Edge
- Others filter insiders out
- We collect and analyze them
- Performance-based filtering is smarter
- Quality > arbitrary time cutoffs

## Risks & Mitigation

### Risk: Dev Wallets Dumping
**Mitigation**: Track performance across multiple launches. Real traders trade many tokens, devs only trade theirs.

### Risk: Low Quality Insiders
**Mitigation**: Filter by win rate. Good insiders have 60%+ win rate, bad ones don't.

### Risk: One-Time Pumpers
**Mitigation**: Require consistency. Must appear in 5+ launches to qualify.

### Risk: Coordinated Pump Groups
**Mitigation**: Cluster analysis. Detect and analyze groups separately.

## Rollback

If too many low-quality wallets:

```python
# In collectors/launch_tracker.py get_first_buyers()
async def get_first_buyers(self, token_address: str, limit: int = 100,
                           min_minutes: int = 5,  # Change back to 5 or 10
                           max_minutes: int = 30):
```

---

**🎯 Scan From Birth v1.0**

No minimum age = Maximum alpha

**Status: Ready for Production** ✅
