#!/bin/bash
# Setup 24-hour auto-discovery cron job for SoulWinners
# Run this script once to install the cron job

PROJECT_DIR="/Users/APPLE/Desktop/Soulwinners"
PYTHON="/usr/bin/python3"
LOG_DIR="$PROJECT_DIR/logs"

# Create logs directory if not exists
mkdir -p "$LOG_DIR"

# Create the pipeline script wrapper
cat > "$PROJECT_DIR/cron_pipeline.sh" << 'EOF'
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
EOF

chmod +x "$PROJECT_DIR/cron_pipeline.sh"

echo "Created cron wrapper script: cron_pipeline.sh"
echo ""

# Show current crontab
echo "Current crontab:"
crontab -l 2>/dev/null || echo "(empty)"
echo ""

# Add cron job (runs at midnight UTC = 4pm PST / 7pm EST)
CRON_LINE="0 0 * * * $PROJECT_DIR/cron_pipeline.sh"

# Check if already exists
if crontab -l 2>/dev/null | grep -q "cron_pipeline.sh"; then
    echo "Cron job already exists!"
else
    # Add to crontab
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "✅ Cron job added!"
fi

echo ""
echo "Cron schedule: 0 0 * * * (midnight UTC daily)"
echo ""
echo "To view cron jobs: crontab -l"
echo "To remove: crontab -e (and delete the line)"
echo "To test now: ./cron_pipeline.sh"
