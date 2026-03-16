#!/usr/bin/env python3
"""
Auto-rotate Helius API keys when exhausted.
Run this as a cron job every hour.
"""
import sys
import os
sys.path.insert(0, '/root/Soulwinners')

from config.settings import WEBHOOK_HELIUS_KEYS
import requests
import sqlite3
from datetime import datetime

# All reserve keys
RESERVE_KEYS = [
    "c56cb8a8-9a05-415b-b6bf-ea6ae83e6f30",
    "900e4055-d54c-424e-a78c-0cec8f98516d",
    "1735609c-f764-46ec-b035-06c3f6d7b25b",
    "9cbcec22-d630-4f9f-9169-f43aceb8a48d",
    "4876637f-e913-4ac2-a0ca-c3a101ab4054",
]

def test_key(key):
    """Test if key is valid."""
    try:
        resp = requests.get(
            f"https://api.helius.xyz/v0/addresses/EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v/balances?api-key={key}",
            timeout=5
        )
        return "tokens" in resp.text
    except:
        return False

def get_active_keys():
    """Get currently active webhook keys from config."""
    return WEBHOOK_HELIUS_KEYS

def rotate_keys():
    """Check active keys and rotate if exhausted."""
    active_keys = get_active_keys()
    
    print(f"[{datetime.now()}] Checking {len(active_keys)} active keys...")
    
    # Test active keys
    exhausted = []
    for key in active_keys:
        if not test_key(key):
            print(f"❌ Key exhausted: {key[:8]}...")
            exhausted.append(key)
        else:
            print(f"✅ Key valid: {key[:8]}...")
    
    if not exhausted:
        print("✅ All keys working")
        return
    
    # Find replacement keys
    replacements = []
    for reserve_key in RESERVE_KEYS:
        if reserve_key not in active_keys and test_key(reserve_key):
            replacements.append(reserve_key)
            if len(replacements) >= len(exhausted):
                break
    
    if len(replacements) < len(exhausted):
        print(f"⚠️  Only {len(replacements)} valid reserve keys found, need {len(exhausted)}")
        return
    
    # Update config
    new_keys = [k for k in active_keys if k not in exhausted] + replacements[:len(exhausted)]
    
    with open('config/settings.py', 'r') as f:
        content = f.read()
    
    old_keys_str = str(active_keys).replace("'", '"')
    new_keys_str = str(new_keys).replace("'", '"')
    
    content = content.replace(old_keys_str, new_keys_str)
    
    with open('config/settings.py', 'w') as f:
        f.write(content)
    
    print(f"✅ Rotated keys: {[k[:8] for k in replacements]}")
    print("🔄 Restart webhook for changes to take effect")
    
    # Log rotation
    with open('logs/key_rotation.log', 'a') as f:
        f.write(f"[{datetime.now()}] Rotated {len(exhausted)} keys\n")

if __name__ == "__main__":
    rotate_keys()
