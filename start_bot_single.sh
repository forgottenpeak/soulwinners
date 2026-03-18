#!/bin/bash
cd /root/Soulwinners
source venv/bin/activate
exec python3 run_bot.py > logs/bot.log 2>&1
