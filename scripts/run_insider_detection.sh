#!/bin/bash
# Insider Detection Cron Wrapper
# Runs every 15 minutes via crontab

set -e

# Change to project directory
cd /root/Soulwinners

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Run insider detection
python3 scripts/run_insider_detection.py >> logs/insider_detection.log 2>&1

# Exit with the same code as Python script
exit $?
