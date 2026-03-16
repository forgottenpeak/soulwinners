"""
Edge Bot Autonomous AI Supervisor
Powered by OpenAI GPT-4o-mini

Features:
- Deep system checks every 12 hours
- On-demand debugging
- Monitors health, finds bugs
- Reports to you proactively
"""
import asyncio
import logging
from datetime import datetime, timedelta
from database import get_connection
import requests
import subprocess
import os
import json

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = "8483614914:AAFjwtH2pct_OdZgi4zrcPNKq6zWdb62ypQ"
TELEGRAM_REPORT_CHAT = "-1003534177506"

class EdgeBotAI:
    """Autonomous AI that monitors and controls the system"""
    
    def __init__(self):
        self.last_deep_check = None
        self.scheduled_tasks = {}  # {task_id: {time, action, data}}
        
    async def supervisor_loop(self):
        """Main loop - runs forever, checks every hour"""
        logger.info("🤖 Edge Bot AI Supervisor starting...")
        await self.notify("🤖 **Edge Bot AI Online**\n\nAutonomous supervisor activated. Running deep checks every 12 hours.")
        
        while True:
            try:
                current_hour = datetime.now().hour
                
                # Deep check every 12 hours (at 9 AM and 9 PM)
                if current_hour in [9, 21]:
                    if not self.last_deep_check or \
                       (datetime.now() - self.last_deep_check) > timedelta(hours=11):
                        
                        logger.info("🔍 Running scheduled deep system check...")
                        report = await self.deep_system_check()
                        await self.notify(f"📋 **12-Hour System Audit**\n\n{report}")
                        
                        self.last_deep_check = datetime.now()
                
                # Check scheduled tasks
                await self.check_scheduled_tasks()
                
                # Sleep for 1 hour
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error(f"Supervisor loop error: {e}")
                await asyncio.sleep(3600)
    
    async def deep_system_check(self):
        """Comprehensive system analysis using AI"""
        
        # Collect all system data
        data = await self.collect_system_data()
        
        # Use OpenAI to analyze
        analysis = await self.ai_analyze(data, "deep_check")
        
        return analysis
    
    async def collect_system_data(self):
        """Gather comprehensive metrics"""
        conn = get_connection()
        cursor = conn.cursor()
        
        # Positions
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE created_at > datetime('now', '-24 hours')) as last_24h,
                COUNT(*) FILTER (WHERE created_at > datetime('now', '-1 hour')) as last_1h
            FROM position_lifecycle 
            WHERE wallet_type != 'backlog'
        """)
        pos_total, pos_24h, pos_1h = cursor.fetchone()
        
        # SAGEO enrichment
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN social_score IS NOT NULL THEN 1 ELSE 0 END) as enriched
            FROM position_lifecycle 
            WHERE wallet_type != 'backlog'
        """)
        total_pos, enriched = cursor.fetchone()
        enrichment_pct = (enriched / total_pos * 100) if total_pos > 0 else 0
        
        # Top wallets
        cursor.execute("""
            SELECT COUNT(*) FROM wallet_global_pool 
            WHERE importance_score > 5
        """)
        performing_wallets = cursor.fetchone()[0]
        
        conn.close()
        
        # System processes
        webhook_running = subprocess.run(
            ['pgrep', '-f', 'webhook_server'], 
            capture_output=True
        ).returncode == 0
        
        bot_running = subprocess.run(
            ['pgrep', '-f', 'run_bot'],
            capture_output=True
        ).returncode == 0
        
        # Recent logs
        try:
            recent_logs = subprocess.run(
                ['tail', '-50', '/root/Soulwinners/logs/bot.log'],
                capture_output=True,
                text=True
            ).stdout
            error_count = len([l for l in recent_logs.split('\n') if 'ERROR' in l])
        except:
            error_count = 0
        
        return {
            'positions': {
                'total': pos_total,
                'last_24h': pos_24h,
                'last_1h': pos_1h,
                'rate_per_hour': pos_1h,
            },
            'sageo_enrichment': enrichment_pct,
            'performing_wallets': performing_wallets,
            'webhook_running': webhook_running,
            'bot_running': bot_running,
            'recent_errors': error_count,
            'timestamp': datetime.now().isoformat(),
        }
    
    async def ai_analyze(self, data, mode="deep_check"):
        """Call OpenAI GPT-4o-mini for analysis"""
        
        if mode == "deep_check":
            prompt = f"""You are Edge Bot AI, monitoring a Solana trading intelligence system.

SYSTEM STATUS:
• Positions: {data['positions']['total']} total, {data['positions']['last_24h']} in 24h, {data['positions']['rate_per_hour']}/hour
• SAGEO enrichment: {data['sageo_enrichment']:.1f}%
• Performing wallets (score >5): {data['performing_wallets']}
• Webhook: {'✅ Running' if data['webhook_running'] else '❌ DOWN'}
• Bot: {'✅ Running' if data['bot_running'] else '❌ DOWN'}
• Recent errors: {data['recent_errors']}

Analyze system health and report:
✅ Status: (Healthy/Warning/Critical)
🔍 Issues: (any bugs or problems detected)
📊 Metrics: (key performance indicators)
💡 Recommendations: (what to improve)

Keep it CONCISE - 4-5 lines max."""
        
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You are Edge Bot AI, a concise system monitoring assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 300,
                },
                timeout=15
            )
            
            result = response.json()
            
            if 'choices' in result:
                return result['choices'][0]['message']['content']
            else:
                logger.error(f"OpenAI API error: {result}")
                return self.fallback_analysis(data)
                
        except Exception as e:
            logger.error(f"AI analysis error: {e}")
            return self.fallback_analysis(data)
    
    def fallback_analysis(self, data):
        """Simple analysis without AI"""
        issues = []
        
        if not data['webhook_running']:
            issues.append("❌ Webhook DOWN")
        if not data['bot_running']:
            issues.append("❌ Bot DOWN")
        if data['positions']['rate_per_hour'] < 20:
            issues.append(f"⚠️ Low volume: {data['positions']['rate_per_hour']}/hour")
        if data['recent_errors'] > 5:
            issues.append(f"⚠️ {data['recent_errors']} recent errors")
        
        status = "✅ Healthy" if not issues else "⚠️ Issues Found"
        
        return f"""{status}

🔍 Issues: {', '.join(issues) if issues else 'None'}
📊 Metrics: {data['positions']['last_24h']} positions (24h), {data['performing_wallets']} top wallets
💡 Recommendations: {'Review and fix issues' if issues else 'System operating normally'}"""
    
    async def on_demand_check(self, user_query):
        """When you ask AI to investigate"""
        
        logger.info(f"On-demand investigation: {user_query}")
        
        # Collect data
        data = await self.collect_system_data()
        
        # Get detailed logs if query mentions errors/bugs
        if any(word in user_query.lower() for word in ['error', 'bug', 'wrong', 'problem', 'issue']):
            try:
                data['detailed_logs'] = subprocess.run(
                    ['tail', '-100', '/root/Soulwinners/logs/bot.log'],
                    capture_output=True,
                    text=True
                ).stdout
            except:
                pass
        
        # Ask AI to investigate
        prompt = f"""User asked: "{user_query}"

SYSTEM DATA:
{json.dumps(data, indent=2, default=str)}

Investigate this issue. Find the root cause and suggest a fix.
Be specific and actionable. Keep response under 200 words."""
        
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You are Edge Bot AI debugging assistant. Be concise and helpful."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 400,
                },
                timeout=20
            )
            
            result = response.json()
            return result['choices'][0]['message']['content']
            
        except Exception as e:
            logger.error(f"On-demand check error: {e}")
            return f"Error investigating: {e}"
    
    async def schedule_task(self, task_description, hours_from_now, task_data):
        """Schedule a task for later"""
        task_id = f"task_{len(self.scheduled_tasks)}"
        execute_time = datetime.now() + timedelta(hours=hours_from_now)
        
        self.scheduled_tasks[task_id] = {
            'description': task_description,
            'execute_time': execute_time,
            'data': task_data
        }
        
        logger.info(f"Task scheduled: {task_description} at {execute_time}")
        return task_id
    
    async def check_scheduled_tasks(self):
        """Check if any tasks are due"""
        now = datetime.now()
        
        for task_id, task in list(self.scheduled_tasks.items()):
            if now >= task['execute_time']:
                # Execute task
                await self.execute_scheduled_task(task)
                # Remove from schedule
                del self.scheduled_tasks[task_id]
    
    async def execute_scheduled_task(self, task):
        """Execute a scheduled task"""
        logger.info(f"Executing scheduled task: {task['description']}")
        
        # Example: Count buys over 2 SOL
        if 'count_buys' in task['data']:
            min_sol = task['data'].get('min_sol', 2.0)
            
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    AVG(buy_sol_amount) as avg_sol,
                    MAX(buy_sol_amount) as max_sol
                FROM position_lifecycle
                WHERE buy_sol_amount >= ?
                AND created_at > datetime('now', '-24 hours')
            """, (min_sol,))
            
            total, avg_sol, max_sol = cursor.fetchone()
            conn.close()
            
            report = f"""📊 **Scheduled Report: {task['description']}**

Total buys ≥{min_sol} SOL: {total}
Average size: {avg_sol:.2f} SOL
Largest buy: {max_sol:.2f} SOL

Report generated at {datetime.now().strftime('%I:%M %p')}"""
            
            await self.notify(report)
    
    async def notify(self, message):
        """Send notification to Telegram"""
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_REPORT_CHAT,
                    "text": message,
                    "parse_mode": "Markdown"
                },
                timeout=5
            )
        except Exception as e:
            logger.error(f"Notify error: {e}")

# Global instance
edge_ai = EdgeBotAI()

async def start_ai_supervisor():
    """Start the autonomous supervisor"""
    await edge_ai.supervisor_loop()

# Export for external use
async def ask_ai(query):
    """On-demand AI investigation"""
    return await edge_ai.on_demand_check(query)

async def schedule_ai_task(description, hours, data):
    """Schedule AI task"""
    return await edge_ai.schedule_task(description, hours, data)
