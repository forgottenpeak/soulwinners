#!/bin/bash
# Start the SoulWinners Real-Time Monitor

cd /Users/APPLE/Desktop/Soulwinners

# Kill any existing monitors
pkill -f "python3 run_monitor.py" 2>/dev/null

# Create logs directory
mkdir -p logs

# Start the monitor
echo "Starting SoulWinners Real-Time Monitor..."
nohup python3 run_monitor.py >> logs/monitor.log 2>&1 &
PID=$!

echo "Monitor started with PID: $PID"
echo "Logs: logs/monitor.log"
echo ""
echo "To check status: ps aux | grep run_monitor"
echo "To view logs: tail -f logs/monitor.log"
echo "To stop: pkill -f 'python3 run_monitor.py'"
