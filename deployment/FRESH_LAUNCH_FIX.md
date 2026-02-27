# Fresh Launch Pipeline Fix - Complete Guide

## Overview

This fix transforms the SoulWinners pipeline from scanning **trending tokens** to scanning **ultra-fresh launches (10 minutes to 24 hours old)**. This catches tokens at birth for maximum alpha.

## Critical Change

**10 MINUTE MINIMUM AGE**: All tokens must be at least 10 minutes old before we scan their buyers. This is CRITICAL to avoid collecting insider/dev wallets who buy immediately at creation.

## What Changed

### 1. Launch Tracker (`collectors/launch_tracker.py`)

#### Added 10-minute minimum parameter
```python
def __init__(self, max_age_hours: int = 24, min_age_minutes: int = 10):
    self.min_age_minutes = min_age_minutes  # CRITICAL: Avoid insider/dev wallets
```

#### Updated Pump.fun endpoint
- **OLD**: `https://frontend-api.pump.fun/coins/king-of-the-hill` (only graduated tokens)
- **NEW**: `https://frontend-api.pump.fun/coins/latest` (ALL fresh launches)

#### Added 10-minute minimum filter
```python
now = datetime.now()
cutoff_old = now - timedelta(hours=self.max_age_hours)
cutoff_recent = now - timedelta(minutes=self.min_age_minutes)

# CRITICAL: 10 min minimum to avoid insider/dev wallets
if cutoff_old < launch_time < cutoff_recent:
    # Token is qualified
```

#### Increased buyer limit from 20 to 100
```python
async def get_first_buyers(self, token_address: str, limit: int = 100,
                           min_minutes: int = 10, max_minutes: int = 30):
```

#### Added time window filter for buyers
Only gets buyers who bought **between 10-30 minutes** after launch:
```python
time_since_launch = (tx_time - token.launch_time).total_seconds() / 60

# Filter: bought between 10-30 min after launch
if min_minutes <= time_since_launch <= max_minutes:
    wallet = self._extract_buyer(tx, token_address)
```

### 2. Pump.fun Collector (`collectors/pumpfun.py`)

#### Added fresh launch method
```python
async def get_fresh_pumpfun_launches(self, min_age_minutes: int = 10,
                                    max_age_hours: int = 24) -> List[Dict]:
    """
    Get ultra-fresh Pump.fun launches (10 min - 24 hours old).

    CRITICAL: 10 minute minimum to avoid insider/dev wallets.
    """
    url = "https://frontend-api.pump.fun/coins/latest?limit=100&offset=0&includeNsfw=true"

    # Cloudflare bypass headers
    headers = {...}

    # Filter by age: 10 min - 24 hours
    if cutoff_old < launch_time < cutoff_recent:
        fresh_tokens.append({...})
```

#### Updated collect_wallets method
```python
async def collect_wallets(self, target_count: int = 500,
                         use_fresh_launches: bool = True):
    if use_fresh_launches:
        # NEW: Get ultra-fresh launches (10 min - 24 hours old)
        fresh_tokens = await self.get_fresh_pumpfun_launches(
            min_age_minutes=10,  # CRITICAL: Avoid insider/dev wallets
            max_age_hours=24
        )
    else:
        # OLD: Get trending tokens
        tokens = await self.get_trending_solana_tokens()
```

### 3. Pipeline Orchestrator (`pipeline/orchestrator.py`)

#### Enabled fresh launch mode
```python
async with PumpFunCollector() as collector:
    # Use ultra-fresh launches (10 min - 24 hours old)
    # CRITICAL: 10 min minimum to avoid insider/dev wallets
    pumpfun_wallets = await collector.collect_wallets(
        target_count=target_per_source,
        use_fresh_launches=True  # Scan 10min-24h launches, not trending
    )
```

## Why This Matters

### Before Fix
- Scanned **trending tokens** (already popular)
- Got wallets who bought **after** the pump
- Late to the party = lower alpha

### After Fix
- Scans **ultra-fresh launches** (10 min - 24 hours old)
- Gets wallets who bought **within 10-30 min** of creation
- Ultra-early = maximum alpha

### The 10-Minute Rule

**Why 10 minutes minimum?**

At token creation (0-10 minutes), buyers are typically:
- **Devs** testing the token
- **Insiders** with advance notice
- **Bots** with privileged access
- **Friends/team** of the creator

These wallets have **unfair advantages** and don't represent genuine market discovery.

**After 10 minutes:**
- Token is publicly visible
- Fair game for all traders
- Represents genuine early discovery
- Shows real market interest

**The 10-30 Minute Window:**
- Ultra-early entries
- Genuine discovery, not insider info
- Best risk/reward ratio
- Maximum alpha potential

## Deployment

### Quick Deploy

```bash
# SSH to VPS
ssh root@your-vps-ip

# Navigate to project
cd /root/Soulwinners

# Run deployment script
bash deployment/deploy_fresh_launch_fix.sh
```

### Manual Deploy

```bash
# Copy files to VPS
scp collectors/launch_tracker.py root@your-vps-ip:/root/Soulwinners/collectors/
scp collectors/pumpfun.py root@your-vps-ip:/root/Soulwinners/collectors/
scp pipeline/orchestrator.py root@your-vps-ip:/root/Soulwinners/pipeline/

# SSH to VPS
ssh root@your-vps-ip

# Restart service
systemctl restart soulwinners

# Monitor logs
tail -f /root/Soulwinners/logs/pipeline.log
```

## Verification

### Check Logs

```bash
tail -f logs/pipeline.log
```

Look for:
```
Found X ultra-fresh launches (10min-24h)
Found X fresh Pump.fun launches (10min-24h)
Collected X pump.fun wallets from fresh launches
Found X buyers (10-30min window)
```

### Test Fresh Launch Scanner

```bash
cd /root/Soulwinners
python3 -c "
import asyncio
from collectors.launch_tracker import LaunchTracker

async def test():
    tracker = LaunchTracker(max_age_hours=24, min_age_minutes=10)
    tokens = await tracker.scan_fresh_launches()
    print(f'Found {len(tokens)} fresh launches (10min-24h old)')

    if tokens:
        token = tokens[0]
        age_min = (datetime.now() - token.launch_time).total_seconds() / 60
        print(f'First token: {token.symbol} ({age_min:.0f} min old)')

        buyers = await tracker.get_first_buyers(
            token.address,
            limit=100,
            min_minutes=10,
            max_minutes=30
        )
        print(f'Buyers in 10-30min window: {len(buyers)}')

asyncio.run(test())
"
```

Expected output:
```
Found 20-50 fresh launches (10min-24h old)
First token: PUMP123 (45 min old)
Buyers in 10-30min window: 30-80
```

## Expected Results

### Token Collection
- **Before**: 20-30 trending tokens
- **After**: 50-100 fresh launches

### Wallet Collection
- **Before**: 100-300 wallets (trending token buyers)
- **After**: 300-800 wallets (ultra-early buyers)

### Quality Improvement
- **Before**: Mixed quality (late + early buyers)
- **After**: High quality (only ultra-early, no insiders)

### Alpha Improvement
- **Before**: Following the crowd
- **After**: Catching tokens at birth

## Strategy Tiers (Future)

Based on buyer timing:

### Ultra-Early (10-30 min)
- Highest alpha
- Genuine discovery
- Best risk/reward
- **This is what we collect now**

### Early (30 min - 2 hours)
- Still very early
- Good alpha
- Less risk than ultra-early

### Medium (2-6 hours)
- Early but not ultra
- Moderate alpha
- More data available

### Late (6-24 hours)
- Historical data
- Lower alpha
- Used for analysis only

## Troubleshooting

### No fresh tokens found

**Check:**
```bash
# Test Pump.fun API directly
curl "https://frontend-api.pump.fun/coins/latest?limit=10"
```

**Verify:**
- API endpoint is accessible
- Cloudflare headers are working
- Tokens have `created_timestamp` field

### Getting insider wallets

**Check:**
```bash
# Verify 10-minute minimum is applied
grep "min_age_minutes: int = 10" collectors/launch_tracker.py
```

**Verify:**
- Time filter is `cutoff_old < launch_time < cutoff_recent`
- NOT `launch_time > cutoff_old` (would include 0-10 min)

### Too few buyers

**Check:**
```bash
# Verify buyer limit is 100
grep "limit: int = 100" collectors/launch_tracker.py
```

**Verify:**
- Time window is 10-30 minutes (not too narrow)
- Helius API key is working
- Token has enough transaction history

## Performance Monitoring

### Key Metrics

```bash
# Fresh tokens per scan
grep "Found.*fresh launches" logs/pipeline.log | tail -5

# Buyers per token
grep "Found.*buyers.*window" logs/pipeline.log | tail -10

# Wallets collected
grep "Collected.*wallets from fresh launches" logs/pipeline.log | tail -5
```

### Database Queries

```bash
sqlite3 data/soulwinners.db "
SELECT COUNT(*), source, tier
FROM qualified_wallets
GROUP BY source, tier
"
```

Expected to see more `pumpfun` source wallets after this fix.

## Success Criteria

✅ **Deployment successful if:**

1. Logs show "ultra-fresh launches (10min-24h)"
2. Using `/coins/latest` endpoint (not `/coins/king-of-the-hill`)
3. Buyer limit is 100 (not 20)
4. Time window is 10-30 minutes
5. 10 minute minimum is enforced
6. More wallets collected per scan
7. No insider/dev wallets in pool

## Rollback

If issues occur, rollback to trending mode:

```python
# In pipeline/orchestrator.py, line 132
pumpfun_wallets = await collector.collect_wallets(
    target_count=target_per_source,
    use_fresh_launches=False  # Use trending tokens
)
```

Then restart service:
```bash
systemctl restart soulwinners
```

---

**🎯 Fresh Launch Pipeline v1.0**

Catching tokens at birth = maximum alpha

**Status: Ready for Production** ✅
