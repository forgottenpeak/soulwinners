# V'ger VPS Deployment Checklist

Use this checklist when deploying V'ger to your VPS.

## Pre-Deployment

### Local Verification

- [ ] Run `python3 test_vger.py` - all tests pass
- [ ] `.env` file contains `VGER_BOT_TOKEN`
- [ ] `.env` file contains `VGER_ADMIN_ID=1153491543`
- [ ] Bot username verified: `@vgerr_bot`
- [ ] Git changes committed (optional)

### VPS Prerequisites

- [ ] OpenClaw trader already deployed
- [ ] OpenClaw service running: `systemctl status openclaw`
- [ ] Database exists: `/root/Soulwinners/data/openclaw.db`
- [ ] Python 3.8+ installed: `python3 --version`
- [ ] Virtualenv exists: `/root/Soulwinners/venv/`

## Deployment Steps

### 1. Connect to VPS

```bash
ssh root@your-vps-ip
```

- [ ] SSH connection successful
- [ ] You are in `/root/` or have root access

### 2. Navigate to Project

```bash
cd /root/Soulwinners
pwd
```

- [ ] Current directory is `/root/Soulwinners`
- [ ] Git repo is up to date: `git status`

### 3. Verify Environment

```bash
cat .env | grep VGER
```

Expected output:
```
VGER_BOT_TOKEN=8402301699:AAFUXJ2kNtQGupo4Qe4JBSY2gGMxs0OZMNQ
VGER_ADMIN_ID=1153491543
```

- [ ] `VGER_BOT_TOKEN` is set
- [ ] `VGER_ADMIN_ID` is set correctly

### 4. Check Deployment Script

```bash
ls -l deployment/deploy_vger.sh
```

- [ ] File exists and is executable
- [ ] If not executable: `chmod +x deployment/deploy_vger.sh`

### 5. Run Deployment

```bash
sudo bash deployment/deploy_vger.sh
```

Watch for:
- [ ] "✓ Prerequisites OK"
- [ ] "✓ Log directory ready"
- [ ] "✓ Dependencies installed"
- [ ] "✓ Service file installed"
- [ ] "✓ V'ger service started successfully"
- [ ] "🟢 V'GER DEPLOYMENT COMPLETE"

### 6. Verify Service

```bash
sudo systemctl status vger
```

Expected:
- [ ] Active: `active (running)`
- [ ] No errors in output
- [ ] Process ID shown

### 7. Check Logs

```bash
tail -f /root/Soulwinners/logs/vger.log
```

Expected to see:
- [ ] "V'GER CONTROL BOT STARTING"
- [ ] "Admin ID: 1153491543"
- [ ] "V'ger bot started. Awaiting commands..."
- [ ] No error messages

Press `Ctrl+C` to exit log view.

## Post-Deployment Testing

### Test 1: Bot Availability

Open Telegram on your phone/desktop.

- [ ] Search for `@vgerr_bot` (note: double 'r')
- [ ] Bot appears in search results
- [ ] Bot has name "V'ger"

### Test 2: /start Command

Send message: `/start`

Expected response:
```
🖖 V'GER ONLINE

I am V'ger. I control the OpenClaw auto-trader.

Use /help to see available commands.
```

- [ ] Bot responds within 2 seconds
- [ ] Response matches above format

### Test 3: /status Command

Send message: `/status`

Expected response shows:
- [ ] Current SOL balance
- [ ] Open positions count
- [ ] Total P&L
- [ ] Goal progress
- [ ] Win/loss statistics
- [ ] Position details (if any positions open)

### Test 4: /settings Command

Send message: `/settings`

Expected response shows:
- [ ] Position sizing settings
- [ ] Exit rules (stop loss, TP1, TP2)
- [ ] Entry filters
- [ ] Advanced settings

### Test 5: /help Command

Send message: `/help`

Expected response shows:
- [ ] List of all commands
- [ ] Command descriptions
- [ ] Example usage

### Test 6: Authorization

If you have a second Telegram account:
- [ ] Send `/start` from unauthorized account
- [ ] Receives: "⛔️ Unauthorized. V'ger responds only to Commander."
- [ ] No access granted

## Verification Checklist

### Service Health

```bash
# Service is enabled (starts on boot)
sudo systemctl is-enabled vger
# Expected: enabled
```
- [ ] Service is enabled

```bash
# Service is active
sudo systemctl is-active vger
# Expected: active
```
- [ ] Service is active

```bash
# No recent failures
sudo systemctl status vger --no-pager | grep -i failed
# Expected: no output
```
- [ ] No failures shown

### Database Access

```bash
# V'ger can read positions
sqlite3 /root/Soulwinners/data/openclaw.db "SELECT COUNT(*) FROM positions;"
# Expected: number (e.g., 0, 1, 2, etc.)
```
- [ ] Database query successful
- [ ] No "locked" errors

### Log Health

```bash
# Check for errors in last 50 lines
tail -n 50 /root/Soulwinners/logs/vger.log | grep -i error
# Expected: no critical errors
```
- [ ] No critical errors
- [ ] Warning about missing trader modules is OK if OpenClaw not running

### Integration Test

If OpenClaw has positions:
- [ ] `/portfolio` shows same positions
- [ ] `/status` P&L matches OpenClaw
- [ ] Token symbols display correctly

## Common Issues

### Issue: Service fails to start

**Check:**
```bash
sudo journalctl -u vger -n 50
```

**Common causes:**
- Missing dependencies → Run `pip install python-telegram-bot python-dotenv`
- Wrong path in service file → Verify `WorkingDirectory` in service file
- Port already in use → Check for duplicate processes

### Issue: Bot doesn't respond

**Check:**
1. Service running?
   ```bash
   sudo systemctl status vger
   ```

2. Bot token correct?
   ```bash
   curl "https://api.telegram.org/bot8402301699:AAFUXJ2kNtQGupo4Qe4JBSY2gGMxs0OZMNQ/getMe"
   ```

3. Network connectivity?
   ```bash
   ping -c 3 api.telegram.org
   ```

### Issue: "Position not found"

**Solution:**
- Use `/portfolio` to see exact token symbols
- Symbols are case-sensitive (use uppercase)
- Example: Use `BONK` not `bonk` or `Bonk`

### Issue: "Database locked"

**Solution:**
```bash
# Restart both services
sudo systemctl restart openclaw
sudo systemctl restart vger
```

## Maintenance

### Daily

- [ ] Check bot is responsive (send `/status`)
- [ ] Verify trades are being logged

### Weekly

- [ ] Review logs for errors
  ```bash
  tail -n 200 /root/Soulwinners/logs/vger.log | grep -i error
  ```

- [ ] Check disk space
  ```bash
  df -h /root/Soulwinners
  ```

### Monthly

- [ ] Rotate logs if needed
  ```bash
  mv logs/vger.log logs/vger.log.old
  sudo systemctl restart vger
  ```

- [ ] Update dependencies
  ```bash
  source venv/bin/activate
  pip install --upgrade python-telegram-bot python-dotenv
  sudo systemctl restart vger
  ```

## Rollback Plan

If V'ger causes issues:

1. **Stop service:**
   ```bash
   sudo systemctl stop vger
   sudo systemctl disable vger
   ```

2. **OpenClaw continues running:**
   - V'ger is read-only
   - Stopping V'ger doesn't affect trading

3. **Debug later:**
   ```bash
   # Test manually
   cd /root/Soulwinners
   source venv/bin/activate
   python3 v_ger_bot.py
   ```

## Success Criteria

V'ger deployment is successful when:

- [x] Service running: `sudo systemctl status vger` shows `active (running)`
- [x] Bot responds: Send `/start` → get response within 2 seconds
- [x] Data accurate: `/status` matches OpenClaw database
- [x] Commands work: `/settings`, `/portfolio`, `/help` all respond correctly
- [x] Authorization works: Only your Telegram user can access
- [x] Logs clean: No critical errors in `logs/vger.log`
- [x] Auto-restart: Service survives VPS reboot

## Final Verification

Run all these commands and verify output:

```bash
# 1. Service status
sudo systemctl status vger

# 2. Recent logs
tail -n 20 /root/Soulwinners/logs/vger.log

# 3. Process running
ps aux | grep v_ger_bot

# 4. Database accessible
sqlite3 /root/Soulwinners/data/openclaw.db "SELECT COUNT(*) FROM stats;"

# 5. Listening for commands
sudo journalctl -u vger -n 10
```

All commands should execute without errors.

## Completion

Date deployed: _______________

Deployed by: _______________

VPS IP: _______________

Bot username: @vgerr_bot

Admin Telegram ID: 1153491543

Service status: ☐ Running ☐ Stopped

Test status: ☐ All tests passed ☐ Some failed

Notes:
_____________________________________________________
_____________________________________________________
_____________________________________________________

---

**Deployment Complete** ✅

Next steps:
1. Use V'ger to monitor your trades: `/status`
2. Check today's performance: `/report`
3. Adjust settings as needed: `/settings`

🖖 **Live long and profit.**
