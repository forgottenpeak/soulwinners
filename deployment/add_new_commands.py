"""
Script to add new commands to bot/commands.py
Adds: /insiders, /clusters, /early_birds
"""

new_commands_code = '''
    async def cmd_insiders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show insider pool statistics."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Insiders command received from user {update.effective_user.id}")

        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Get insider pool stats
            cursor.execute("""
                SELECT COUNT(*),
                       AVG(early_entry_count),
                       AVG(win_rate),
                       AVG(avg_hold_minutes)
                FROM insider_pool
                WHERE is_active = 1
            """)
            total, avg_entries, avg_wr, avg_hold = cursor.fetchone()
            total = total or 0

            # Get tier breakdown
            cursor.execute("""
                SELECT tier, COUNT(*)
                FROM insider_pool
                WHERE is_active = 1
                GROUP BY tier
                ORDER BY
                    CASE tier
                        WHEN 'Elite' THEN 1
                        WHEN 'Pro' THEN 2
                        WHEN 'Emerging' THEN 3
                        ELSE 4
                    END
            """)
            tiers = cursor.fetchall()

            # Get recent additions
            cursor.execute("""
                SELECT wallet_address, tier, early_entry_count, discovered_at
                FROM insider_pool
                WHERE is_active = 1
                ORDER BY discovered_at DESC
                LIMIT 5
            """)
            recent = cursor.fetchall()

            conn.close()

            # Build tier breakdown
            tier_text = ""
            for tier, count in tiers:
                pct = int(count / total * 100) if total > 0 else 0
                tier_text += f"├─ {tier}: {count} ({pct}%)\n"
            if tier_text:
                tier_text = tier_text[:-1]

            # Build recent list
            recent_text = ""
            if recent:
                for wallet, tier, entries, discovered in recent[:3]:
                    short_addr = f"{wallet[:6]}...{wallet[-4:]}"
                    recent_text += f"├─ {short_addr} ({tier})\n"
                    recent_text += f"│  Entries: {entries}, Added: {discovered[:10]}\n"
                recent_text = recent_text[:-1]
            else:
                recent_text = "└─ No recent additions"

            message = f"""🎯 **INSIDER POOL STATISTICS**

📊 **OVERVIEW**
├─ Total Insiders: {total}
├─ Avg Early Entries: {avg_entries:.1f}
├─ Avg Win Rate: {avg_wr:.1%}
└─ Avg Hold Time: {int(avg_hold or 0)}m

🏆 **TIER BREAKDOWN**
{tier_text}

🆕 **RECENT ADDITIONS** (Last 3)
{recent_text}

_Fresh launch snipers detected every 15 minutes_
_Use /early_birds to see latest catches_"""

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Insiders command failed: {e}", exc_info=True)
            await update.message.reply_text(f"Error: {str(e)}")

    async def cmd_clusters(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detected wallet clusters."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Clusters command received from user {update.effective_user.id}")

        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Get cluster stats
            cursor.execute("""
                SELECT COUNT(DISTINCT cluster_id),
                       AVG(cluster_size),
                       COUNT(*)
                FROM wallet_clusters
                WHERE is_active = 1
            """)
            total_clusters, avg_size, total_memberships = cursor.fetchone()
            total_clusters = total_clusters or 0
            avg_size = avg_size or 0

            # Get largest clusters
            cursor.execute("""
                SELECT cluster_id, cluster_type, cluster_size,
                       shared_tokens, connection_strength, detected_at
                FROM wallet_clusters
                WHERE is_active = 1
                GROUP BY cluster_id
                ORDER BY cluster_size DESC, connection_strength DESC
                LIMIT 5
            """)
            top_clusters = cursor.fetchall()

            conn.close()

            # Build top clusters list
            cluster_text = ""
            if top_clusters:
                for i, (cid, ctype, size, tokens, strength, detected) in enumerate(top_clusters[:3], 1):
                    cluster_text += f"**{i}. Cluster #{cid}**\n"
                    cluster_text += f"├─ Type: {ctype}\n"
                    cluster_text += f"├─ Size: {size} wallets\n"
                    cluster_text += f"├─ Shared Tokens: {tokens}\n"
                    cluster_text += f"├─ Strength: {strength:.0%}\n"
                    cluster_text += f"└─ Detected: {detected[:10]}\n\n"
            else:
                cluster_text = "No clusters detected yet.\n"

            message = f"""🔗 **WALLET CLUSTER ANALYSIS**

📊 **OVERVIEW**
├─ Total Clusters: {total_clusters}
├─ Avg Cluster Size: {avg_size:.1f} wallets
└─ Total Memberships: {total_memberships}

🏆 **TOP CLUSTERS** (By Size)

{cluster_text}
_Clusters analyzed every 20 minutes_
_Look for: Dev teams, insider groups, coordinated buyers_"""

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Clusters command failed: {e}", exc_info=True)
            await update.message.reply_text(f"Error: {str(e)}")

    async def cmd_early_birds(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show fresh launch snipers (early bird wallets)."""
        if not self._is_private(update) or not self._is_admin(update.effective_user.id):
            return

        logger.info(f"Early birds command received from user {update.effective_user.id}")

        try:
            conn = get_connection()
            cursor = conn.cursor()

            # Get early bird stats from insider pool
            cursor.execute("""
                SELECT COUNT(*),
                       AVG(early_entry_count),
                       AVG(win_rate),
                       MAX(early_entry_count)
                FROM insider_pool
                WHERE is_active = 1
                AND early_entry_count >= 3
            """)
            total, avg_entries, avg_wr, max_entries = cursor.fetchone()
            total = total or 0

            # Get top performers
            cursor.execute("""
                SELECT wallet_address, tier, early_entry_count,
                       win_rate, avg_roi_percent, discovered_at
                FROM insider_pool
                WHERE is_active = 1
                AND early_entry_count >= 3
                ORDER BY early_entry_count DESC, win_rate DESC
                LIMIT 10
            """)
            top_snipers = cursor.fetchall()

            conn.close()

            # Build top snipers list
            sniper_text = ""
            if top_snipers:
                for i, (wallet, tier, entries, wr, roi, discovered) in enumerate(top_snipers[:5], 1):
                    short_addr = f"{wallet[:6]}...{wallet[-4:]}"
                    sniper_text += f"**{i}. {short_addr}** ({tier})\n"
                    sniper_text += f"├─ Early Entries: {entries}\n"
                    sniper_text += f"├─ Win Rate: {wr:.1%}\n"
                    sniper_text += f"├─ Avg ROI: {roi:+.1f}%\n"
                    sniper_text += f"└─ Found: {discovered[:10]}\n\n"
            else:
                sniper_text = "No early birds detected yet.\n"

            message = f"""🐦 **FRESH LAUNCH SNIPERS**

📊 **STATISTICS**
├─ Total Early Birds: {total}
├─ Avg Early Entries: {avg_entries:.1f}
├─ Avg Win Rate: {avg_wr:.1%}
└─ Max Entries: {max_entries}

🏆 **TOP SNIPERS** (Most Early Entries)

{sniper_text}
_These wallets consistently buy within minutes of token creation_
_Updated every 15 minutes via insider detection_"""

            await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

        except Exception as e:
            logger.error(f"Early birds command failed: {e}", exc_info=True)
            await update.message.reply_text(f"Error: {str(e)}")
'''

# Instructions for adding to commands.py
print("""
╔══════════════════════════════════════════════════════════════╗
║          NEW TELEGRAM COMMANDS CODE                          ║
╚══════════════════════════════════════════════════════════════╝

Add these three new command methods to bot/commands.py:

1. Add after cmd_trader() method (around line 850)
2. Register handlers in __init__ start() method:

   self.application.add_handler(CommandHandler("insiders", self.cmd_insiders))
   self.application.add_handler(CommandHandler("clusters", self.cmd_clusters))
   self.application.add_handler(CommandHandler("early_birds", self.cmd_early_birds))

3. Add to help text in cmd_help():

   • /insiders - Insider pool statistics
   • /clusters - Detected wallet clusters
   • /early_birds - Fresh launch snipers

════════════════════════════════════════════════════════════════

CODE TO ADD:
""")

print(new_commands_code)
