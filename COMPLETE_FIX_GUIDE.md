# Complete SoulWinners Fix - Deployment Guide

## Overview

This guide deploys all remaining fixes for the SoulWinners system:

1. ✅ **Cloudflare Blocking Fix** (Already deployed)
2. ⬜ **Insider Detection Cron** (Fresh launch snipers)
3. ⬜ **Cluster Analysis Cron** (Connected wallet groups)
4. ⬜ **Telegram Bot Commands** (New /insiders, /clusters, /early_birds)
5. ⬜ **Database Settings** (Fix discovery frequency)

## Quick Deploy (VPS)

### One-Command Deploy

```bash
# SSH to VPS
ssh root@your-vps-ip

# Navigate to project
cd /root/Soulwinners

# Run complete fix script
sudo bash deployment/complete_soulwinners_fix.sh

# Verify deployment
bash deployment/verify_soulwinners.sh
```

## What Gets Fixed

### 1. Cloudflare Blocking ✅

**Status:** Already deployed

**Files:**
- `collectors/pumpfun.py` - Added browser headers
- `collectors/dexscreener.py` - Added browser headers

**Verification:**
```bash
grep "CLOUDFLARE_BYPASS_HEADERS" collectors/pumpfun.py
grep "CLOUDFLARE_BYPASS_HEADERS" collectors/dexscreener.py
```

**Test:**
```bash
python3 -c "
from collectors.pumpfun import PumpFunCollector
import asyncio

async def test():
    async with PumpFunCollector() as c:
        tokens = await c.get_trending_solana_tokens()
        print(f'✓ Got {len(tokens)} tokens')

asyncio.run(test())
"
```

Should output: `✓ Got 28 tokens` (not 0)

### 2. Insider Detection Cron

**Purpose:** Find wallets that buy newly created/migrated tokens early

**Schedule:** Every 15 minutes

**What it does:**
1. Scans for fresh token launches
2. Identifies wallets buying within minutes of creation
3. Tracks early entry patterns
4. Adds high-performers to insider pool

**Files created:**
- `scripts/run_insider_detection.py` - Main script
- `scripts/run_insider_detection.sh` - Cron wrapper

**Cron entry:**
```cron
*/15 * * * * /root/Soulwinners/scripts/run_insider_detection.sh >> /root/Soulwinners/logs/insider_cron.log 2>&1
```

**Monitor:**
```bash
tail -f logs/insider_cron.log
```

**Expected output:**
```
INSIDER DETECTION - Starting
Step 1: Scanning for fresh launches...
✓ Fresh launch scan complete
Step 2: Detecting insider wallets...
✓ Insider detection complete
INSIDER DETECTION - Complete
```

### 3. Cluster Analysis Cron

**Purpose:** Find connected wallets (dev teams, insider groups)

**Schedule:** Every 20 minutes

**What it does:**
1. Analyzes wallet transaction patterns
2. Finds shared tokens between wallets
3. Identifies coordinated buying
4. Detects dev wallet groups

**Files created:**
- `scripts/run_cluster_analysis.py` - Main script
- `scripts/run_cluster_analysis.sh` - Cron wrapper

**Cron entry:**
```cron
*/20 * * * * /root/Soulwinners/scripts/run_cluster_analysis.sh >> /root/Soulwinners/logs/cluster_cron.log 2>&1
```

**Monitor:**
```bash
tail -f logs/cluster_cron.log
```

**Expected output:**
```
CLUSTER ANALYSIS - Starting
Analyzing wallet clusters...
✓ Cluster analysis complete
CLUSTER ANALYSIS - Complete
```

### 4. Telegram Bot Commands

**New commands to add manually:**

#### /insiders
Shows insider pool statistics:
- Total insiders detected
- Average early entries per wallet
- Average win rate
- Recent additions
- Tier breakdown

#### /clusters
Shows detected wallet clusters:
- Total clusters found
- Average cluster size
- Top clusters by size and connection strength
- Cluster types (dev team, insider group, etc.)

#### /early_birds
Shows fresh launch snipers:
- Wallets with most early entries
- Win rates for early entries
- Top performers ranked by entries

#### /cron (fix)
Updates discovery frequency display from 10 to 30 minutes

**To add these commands:**

1. Open `bot/commands.py`

2. Add command handlers in `start()` method:
```python
self.application.add_handler(CommandHandler("insiders", self.cmd_insiders))
self.application.add_handler(CommandHandler("clusters", self.cmd_clusters))
self.application.add_handler(CommandHandler("early_birds", self.cmd_early_birds))
```

3. Add methods from `deployment/add_new_commands.py`

4. Update `/help` command with new commands

5. Restart bot:
```bash
systemctl restart soulwinners
```

### 5. Database Settings

**Fix:** Update discovery frequency to 30 minutes

**Command:**
```bash
sqlite3 /root/Soulwinners/data/soulwinners.db \
  "UPDATE settings SET value='30' WHERE key='discovery_frequency_min'"
```

**Verify:**
```bash
sqlite3 /root/Soulwinners/data/soulwinners.db \
  "SELECT key, value FROM settings WHERE key='discovery_frequency_min'"
```

Should output: `discovery_frequency_min|30`

## Step-by-Step Deployment

### Step 1: Prepare Files on Mac

```bash
cd /Users/APPLE/Desktop/Soulwinners

# Ensure Cloudflare fix is in place (already done)
grep "CLOUDFLARE_BYPASS_HEADERS" collectors/pumpfun.py
grep "CLOUDFLARE_BYPASS_HEADERS" collectors/dexscreener.py

# Ensure scripts exist
ls -la scripts/run_insider_detection.py
ls -la scripts/run_cluster_analysis.py

# Check deployment scripts
ls -la deployment/complete_soulwinners_fix.sh
ls -la deployment/verify_soulwinners.sh
```

### Step 2: Deploy to VPS

```bash
# Copy files to VPS
scp -r collectors scripts deployment \
  root@your-vps-ip:/root/Soulwinners/

# SSH to VPS
ssh root@your-vps-ip

# Navigate to project
cd /root/Soulwinners

# Make scripts executable
chmod +x scripts/*.sh
chmod +x scripts/*.py
chmod +x deployment/*.sh

# Run deployment
sudo bash deployment/complete_soulwinners_fix.sh
```

### Step 3: Add Telegram Commands (Manual)

This step requires manual code editing:

```bash
# On VPS or locally
nano bot/commands.py

# Add three new command methods:
# - cmd_insiders()
# - cmd_clusters()
# - cmd_early_birds()

# See deployment/add_new_commands.py for the code
python3 deployment/add_new_commands.py

# Copy the output and add to bot/commands.py

# Restart bot
systemctl restart soulwinners
```

### Step 4: Verify Deployment

```bash
# Run verification script
bash deployment/verify_soulwinners.sh

# Check all services
systemctl status soulwinners

# Check cron jobs
crontab -l | grep -E "insider|cluster"

# Monitor logs in real-time
tail -f logs/pipeline.log
tail -f logs/insider_cron.log
tail -f logs/cluster_cron.log
```

## Expected Results

### Before Fix

```
✗ DexScreener API: Error 1016 (Cloudflare)
✗ Tokens collected: 0
✗ Wallets collected: 0
✗ Insider pool: Empty
✗ Clusters: Not detected
✗ Pipeline: Failed
```

### After Fix

```
✓ DexScreener API: Working (28 tokens)
✓ Tokens collected: 50-100
✓ Wallets collected: 100-500
✓ Insider pool: Growing (15min updates)
✓ Clusters: Detected (20min updates)
✓ Pipeline: Running successfully
```

## Monitoring

### Real-time Logs

```bash
# Main pipeline (wallet collection)
tail -f logs/pipeline.log | grep -E "Found|Collected|trending"

# Insider detection
tail -f logs/insider_cron.log

# Cluster analysis
tail -f logs/cluster_cron.log

# All combined
multitail logs/pipeline.log logs/insider_cron.log logs/cluster_cron.log
```

### Check Pipeline Status

```bash
# Recent pipeline runs
sqlite3 data/soulwinners.db \
  "SELECT started_at, wallets_collected, wallets_added, status
   FROM pipeline_runs
   ORDER BY id DESC LIMIT 5"

# Current pool size
sqlite3 data/soulwinners.db \
  "SELECT tier, COUNT(*) FROM qualified_wallets GROUP BY tier"

# Insider pool
sqlite3 data/soulwinners.db \
  "SELECT COUNT(*) FROM insider_pool WHERE is_active=1"

# Clusters
sqlite3 data/soulwinners.db \
  "SELECT COUNT(DISTINCT cluster_id) FROM wallet_clusters WHERE is_active=1"
```

### Telegram Bot Monitoring

```
/status    - Overall system status
/pool      - Wallet pool statistics
/insiders  - Insider pool stats
/clusters  - Cluster detection stats
/early_birds - Fresh launch snipers
/cron      - Cron job status
/logs      - Recent log entries
```

## Troubleshooting

### Issue: No tokens collected (still 0)

**Check:**
```bash
# Verify Cloudflare fix
grep "CLOUDFLARE_BYPASS_HEADERS" collectors/pumpfun.py
grep "headers=CLOUDFLARE_BYPASS_HEADERS" collectors/pumpfun.py

# Test collector manually
python3 -c "
from collectors.pumpfun import PumpFunCollector
import asyncio
async def test():
    async with PumpFunCollector() as c:
        tokens = await c.get_trending_solana_tokens()
        print(f'Tokens: {len(tokens)}')
asyncio.run(test())
"
```

**Fix:**
- Ensure Cloudflare fix is deployed
- Restart service: `systemctl restart soulwinners`

### Issue: Insider cron not running

**Check:**
```bash
# Verify cron job
crontab -l | grep insider

# Check script permissions
ls -la scripts/run_insider_detection.sh

# Test manually
/root/Soulwinners/scripts/run_insider_detection.sh

# Check logs
tail -n 50 logs/insider_cron.log
```

**Fix:**
- Ensure scripts are executable: `chmod +x scripts/*.sh`
- Verify cron is installed: `*/15 * * * *` schedule
- Check Python path in script

### Issue: Cluster cron not running

**Check:**
```bash
# Verify cron job
crontab -l | grep cluster

# Test manually
/root/Soulwinners/scripts/run_cluster_analysis.sh

# Check logs
tail -n 50 logs/cluster_cron.log
```

**Fix:**
- Same as insider cron troubleshooting

### Issue: Telegram commands not working

**Check:**
```bash
# Verify bot is running
systemctl status soulwinners

# Check bot logs
tail -f logs/bot.log

# Test bot connection
curl https://api.telegram.org/bot<YOUR_TOKEN>/getMe
```

**Fix:**
- Ensure new commands are added to `bot/commands.py`
- Restart bot: `systemctl restart soulwinners`
- Verify admin user ID is set

## Performance Expectations

### Regular Pool (Every 30 minutes)

- Scans: 50-100 tokens
- Collects: 100-500 wallets
- Qualifies: 50-200 wallets
- Adds to pool: 10-50 new wallets

### Insider Pool (Every 15 minutes)

- Scans: 20-50 fresh launches
- Detects: 5-20 insider wallets
- Adds: 1-10 qualified insiders

### Cluster Detection (Every 20 minutes)

- Analyzes: All pool wallets
- Finds: 5-15 clusters
- Identifies: 20-50 connected wallets

## Success Criteria

✅ **Deployment successful if:**

1. Cloudflare fix applied
   - `grep "CLOUDFLARE_BYPASS_HEADERS" collectors/*.py` returns results

2. Cron jobs installed
   - `crontab -l` shows both insider and cluster jobs

3. Tokens being collected
   - `logs/pipeline.log` shows "Found X trending tokens"

4. Wallets being added
   - `logs/pipeline.log` shows "Collected X wallets"

5. Insider detection running
   - `logs/insider_cron.log` has entries
   - Database has `insider_pool` table with rows

6. Cluster analysis running
   - `logs/cluster_cron.log` has entries
   - Database has `wallet_clusters` table with rows

7. Services running
   - `systemctl status soulwinners` shows "active (running)"

8. No errors in logs
   - No "Error 1016" in pipeline.log
   - No Python tracebacks in cron logs

## Complete Deployment Checklist

### Pre-Deployment

- [ ] Backup current database
- [ ] Note current pool size
- [ ] Save current crontab
- [ ] Verify VPS access

### Deployment

- [ ] Copy files to VPS
- [ ] Run deployment script
- [ ] Verify Cloudflare fix
- [ ] Check cron jobs installed
- [ ] Update database settings
- [ ] Add Telegram commands (manual)
- [ ] Restart services

### Post-Deployment

- [ ] Run verification script
- [ ] Check service status
- [ ] Monitor logs for 30 minutes
- [ ] Verify token collection working
- [ ] Verify wallet collection working
- [ ] Wait 15 minutes, check insider cron
- [ ] Wait 20 minutes, check cluster cron
- [ ] Test Telegram bot commands

### Verification

- [ ] Pipeline log shows tokens
- [ ] Pipeline log shows wallets
- [ ] Insider log shows activity
- [ ] Cluster log shows activity
- [ ] Pool size increasing
- [ ] No error 1016 in logs
- [ ] Telegram bot responds
- [ ] New commands work

## Support

If issues persist:

1. Check all logs:
   ```bash
   tail -n 100 logs/pipeline.log
   tail -n 100 logs/insider_cron.log
   tail -n 100 logs/cluster_cron.log
   ```

2. Verify database:
   ```bash
   sqlite3 data/soulwinners.db ".tables"
   sqlite3 data/soulwinners.db "SELECT COUNT(*) FROM qualified_wallets"
   ```

3. Test collectors manually:
   ```bash
   python3 -c "from collectors.pumpfun import PumpFunCollector; ..."
   ```

4. Re-run deployment:
   ```bash
   bash deployment/complete_soulwinners_fix.sh
   ```

---

**🎉 SoulWinners Complete Fix Deployment v1.0**

All components working together:
- Regular pool discovery (30min)
- Insider detection (15min)
- Cluster analysis (20min)
- Real-time Telegram monitoring
- Cloudflare bypass working

**Status: Ready for Production** ✅
