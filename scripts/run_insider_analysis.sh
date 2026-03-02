#!/bin/bash
# Run insider wallet analysis
# Add to cron: 0 3 * * 0 /root/Soulwinners/scripts/run_insider_analysis.sh
# (Runs every Sunday at 3 AM)

cd /root/Soulwinners
source venv/bin/activate 2>/dev/null || true

echo "$(date): Starting insider analysis..."
python3 scripts/analyze_insiders.py >> logs/insider_analysis.log 2>&1
echo "$(date): Insider analysis complete"
