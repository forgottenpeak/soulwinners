#!/bin/bash
cp config/settings.py config/settings_backup.tmp
git fetch origin
git reset --hard origin/main
if ! grep -q "DATABASE_PATH" config/settings.py; then
    cp config/settings.py.backup config/settings.py
    sed -i 's/"59648c8b-a691-451b-b1ee-3542ad7afd36"/"896e7489-2609-4746-a57e-558dabfa3273"/' config/settings.py
    sed -i '/"2c353fb3-653a-47d2-8247-2286ac7098a8"/d' config/settings.py
    sed -i '/"ee2a7d3e-2935-4736-8c3f-113c268f5510"/d' config/settings.py
    sed -i '/"b371c9f4-2ff4-4426-8949-7125b814a421"/d' config/settings.py
    sed -i 's/POLL_INTERVAL_SECONDS = 30/POLL_INTERVAL_SECONDS = 60/' config/settings.py
fi
echo "✅ Update complete"
