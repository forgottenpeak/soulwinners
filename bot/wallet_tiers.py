"""
Wallet tier system based on importance scores
"""

def get_wallet_tier(score):
    """Get tier name and emoji based on importance score"""
    if score >= 41:
        return "👑 Whale Whisperer"
    elif score >= 26:
        return "⚡ Alpha Hunter"
    elif score >= 16:
        return "🔥 Degen God"
    elif score >= 11:
        return "🎯 Sniper"
    elif score >= 6:
        return "💎 Diamond Hands"
    elif score >= 3:
        return "📈 Scout"
    else:
        return "🔰 Rookie"

def get_tier_color(score):
    """Get color code for tier (for UI)"""
    if score >= 41:
        return "🟣"  # Purple - Legendary
    elif score >= 26:
        return "🔴"  # Red - Epic
    elif score >= 16:
        return "🟠"  # Orange - Rare
    elif score >= 11:
        return "🟡"  # Yellow - Uncommon
    elif score >= 6:
        return "🔵"  # Blue - Common
    elif score >= 3:
        return "🟢"  # Green - Starter
    else:
        return "⚪"  # White - Rookie

TIER_THRESHOLDS = {
    "👑 Whale Whisperer": 41,
    "⚡ Alpha Hunter": 26,
    "🔥 Degen God": 16,
    "🎯 Sniper": 11,
    "💎 Diamond Hands": 6,
    "📈 Scout": 3,
    "🔰 Rookie": 0,
}
