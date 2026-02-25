#!/bin/bash
cd /Users/APPLE/Desktop/Soulwinners
/usr/bin/python3 run_pipeline.py \
    --threshold-sol 10 \
    --threshold-trades 15 \
    --threshold-win 60 \
    --threshold-roi 50 \
    >> logs/cron_pipeline.log 2>&1

# Timestamp the run
echo "=== Pipeline completed at $(date) ===" >> logs/cron_pipeline.log
