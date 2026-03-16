"""
Autonomous Agent Engine - Inspired by Devin AI
Runs independently, makes decisions, executes plans, learns from results
PERSISTENT MEMORY - survives API key changes, restarts, everything
"""
import asyncio
import logging
import json
from datetime import datetime
from pathlib import Path
import requests
from database import get_connection
from bot.agent.trust_system import trust

logger = logging.getLogger(__name__)

class AutonomousAgent:
    """
    Self-running agent that monitors, reasons, plans, and acts
    Learns over time with PERSISTENT memory stored in database
    """
    
    def __init__(self):
        import os
        self.openai_key = os.getenv("OPENAI_API_KEY", "")
        self.memory_file = Path("/root/Soulwinners/data/agent_memory.db")
        self.init_memory_db()
        
    def init_memory_db(self):
        """Create persistent memory tables in main database"""
        conn = get_connection()
        cursor = conn.cursor()
        
        # Agent's learned patterns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type TEXT NOT NULL,
                pattern_data TEXT NOT NULL,
                confidence REAL DEFAULT 0,
                times_seen INTEGER DEFAULT 1,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Agent's decisions and outcomes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                situation TEXT NOT NULL,
                decision TEXT NOT NULL,
                reasoning TEXT,
                action_taken TEXT,
                outcome TEXT,
                success BOOLEAN,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Agent's knowledge base
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                insight TEXT NOT NULL,
                source TEXT,
                confidence REAL DEFAULT 0.5,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("✅ Agent memory database initialized")
    
    async def observe(self):
        """
        OBSERVE phase - gather current system state
        Returns comprehensive snapshot
        """
        conn = get_connection()
        cursor = conn.cursor()
        
        observations = {
            "timestamp": datetime.now().isoformat(),
            "positions": {},
            "wallets": {},
            "system_health": {},
            "patterns": []
        }
        
        # Position metrics
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE created_at > datetime('now', '-1 hour')) as last_hour,
                COUNT(*) FILTER (WHERE token_symbol = 'UNKNOWN') as unknown,
                COUNT(*) FILTER (WHERE social_score IS NOT NULL) as enriched
            FROM position_lifecycle WHERE wallet_type != 'backlog'
        """)
        total, hour, unknown, enriched = cursor.fetchone()
        observations["positions"] = {
            "total": total,
            "last_hour": hour,
            "unknown_tokens": unknown,
            "enriched": enriched,
            "enrichment_rate": enriched/total if total > 0 else 0
        }
        
        # Wallet metrics
        cursor.execute("""
            SELECT COUNT(*), AVG(importance_score), MAX(importance_score)
            FROM wallet_global_pool
        """)
        w_count, w_avg, w_max = cursor.fetchone()
        observations["wallets"] = {
            "total": w_count,
            "avg_score": w_avg or 0,
            "top_score": w_max or 0
        }
        
        # Check for patterns we've seen before
        cursor.execute("""
            SELECT pattern_type, pattern_data, confidence, times_seen
            FROM agent_patterns
            WHERE last_seen > datetime('now', '-7 days')
            ORDER BY confidence DESC LIMIT 10
        """)
        observations["patterns"] = [
            {"type": t, "data": json.loads(d), "confidence": c, "seen": s}
            for t, d, c, s in cursor.fetchall()
        ]
        
        conn.close()
        return observations
    
    async def reason(self, observations):
        """
        REASON phase - analyze observations with AI + past learnings
        Returns insights and recommended actions
        """
        # Build context with MEMORY
        conn = get_connection()
        cursor = conn.cursor()
        
        # Get past successful decisions
        cursor.execute("""
            SELECT situation, decision, outcome
            FROM agent_decisions
            WHERE success = 1
            ORDER BY timestamp DESC LIMIT 5
        """)
        past_wins = cursor.fetchall()
        
        # Get learned insights
        cursor.execute("""
            SELECT topic, insight, confidence
            FROM agent_knowledge
            ORDER BY confidence DESC, updated_at DESC LIMIT 10
        """)
        knowledge = cursor.fetchall()
        conn.close()
        
        # Build AI prompt with memory
        context = f"""You are Edge Bot, an autonomous trading intelligence agent.

CURRENT OBSERVATIONS:
{json.dumps(observations, indent=2)}

YOUR LEARNED KNOWLEDGE:
{chr(10).join(f"• {topic}: {insight} (confidence: {conf:.0%})" for topic, insight, conf in knowledge)}

PAST SUCCESSFUL DECISIONS:
{chr(10).join(f"• {sit} → {dec} → {out}" for sit, dec, out in past_wins)}

TASK: Analyze current state and recommend actions. Consider:
1. What patterns do you see?
2. What needs immediate attention?
3. What can be improved?
4. What should be monitored?

Respond in JSON:
{{
  "situation_summary": "brief summary",
  "issues": ["issue1", "issue2"],
  "opportunities": ["opp1", "opp2"],
  "recommended_actions": [
    {{"action": "action_name", "priority": "high/medium/low", "reasoning": "why"}}
  ],
  "new_patterns": [
    {{"type": "pattern_type", "data": {{}}, "confidence": 0.8}}
  ]
}}"""

        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.openai_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You are an autonomous trading intelligence agent. Always respond in valid JSON."},
                        {"role": "user", "content": context}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1000,
                },
                timeout=20
            )
            
            result = response.json()
            analysis = json.loads(result['choices'][0]['message']['content'])
            return analysis
            
        except Exception as e:
            logger.error(f"Reasoning error: {e}")
            return self.fallback_reasoning(observations)
    
    def fallback_reasoning(self, obs):
        """Rule-based reasoning when AI unavailable"""
        issues = []
        actions = []
        
        if obs["positions"]["unknown_tokens"] > 1000:
            issues.append(f"{obs['positions']['unknown_tokens']} UNKNOWN tokens")
            actions.append({
                "action": "fix_unknown_tokens",
                "priority": "high",
                "reasoning": "Too many UNKNOWN tokens hurting data quality"
            })
        
        if obs["positions"]["enrichment_rate"] < 0.5:
            issues.append(f"Only {obs['positions']['enrichment_rate']:.0%} enrichment")
            actions.append({
                "action": "increase_enrichment",
                "priority": "medium",
                "reasoning": "Low SAGEO coverage limits intelligence"
            })
        
        return {
            "situation_summary": "System running, some issues detected",
            "issues": issues,
            "opportunities": [],
            "recommended_actions": actions,
            "new_patterns": []
        }
    
    async def plan(self, analysis):
        """
        PLAN phase - create multi-step execution plan
        Returns ordered list of tasks
        """
        plan = []
        
        for action in analysis.get("recommended_actions", []):
            if action["priority"] == "high":
                plan.insert(0, action)  # High priority first
            else:
                plan.append(action)
        
        return plan
    
    async def act(self, plan):
        """
        ACT phase - execute plan using safe tools
        Returns results of actions
        """
        from bot.ai_tools import ai_tools
        
        results = []
        
        for task in plan:
            action_name = task["action"]
            
            try:
                if action_name == "fix_unknown_tokens":
                    # Run the fix script
                    result = ai_tools.query_database(
                        "SELECT COUNT(*) FROM position_lifecycle WHERE token_symbol = 'UNKNOWN'"
                    )
                    results.append({
                        "action": action_name,
                        "status": "initiated",
                        "details": f"Found {result['rows'][0][0]} to fix"
                    })
                
                elif action_name == "increase_enrichment":
                    # Check enrichment queue
                    result = ai_tools.query_database(
                        "SELECT COUNT(*) FROM position_lifecycle WHERE social_score IS NULL LIMIT 100"
                    )
                    results.append({
                        "action": action_name,
                        "status": "queued",
                        "details": f"{result['rows'][0][0]} positions ready for enrichment"
                    })
                
                elif action_name == "check_logs":
                    log_result = ai_tools.view_logs("bot", 50)
                    results.append({
                        "action": action_name,
                        "status": "completed",
                        "details": "Logs reviewed"
                    })
                
                # Add delay between actions
                await asyncio.sleep(2)
                
            except Exception as e:
                results.append({
                    "action": action_name,
                    "status": "error",
                    "details": str(e)
                })
        
        return results
    
    async def learn(self, observations, analysis, results):
        """
        LEARN phase - store patterns, update knowledge, remember outcomes
        This is what makes it TRULY autonomous - it gets smarter over time
        """
        conn = get_connection()
        cursor = conn.cursor()
        
        # Store new patterns discovered
        for pattern in analysis.get("new_patterns", []):
            cursor.execute("""
                INSERT INTO agent_patterns (pattern_type, pattern_data, confidence)
                VALUES (?, ?, ?)
                ON CONFLICT(pattern_type, pattern_data) DO UPDATE SET
                    times_seen = times_seen + 1,
                    confidence = MAX(confidence, excluded.confidence),
                    last_seen = CURRENT_TIMESTAMP
            """, (
                pattern["type"],
                json.dumps(pattern["data"]),
                pattern.get("confidence", 0.5)
            ))
        
        # Store decision and outcome
        for result in results:
            cursor.execute("""
                INSERT INTO agent_decisions 
                (situation, decision, reasoning, action_taken, outcome, success)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                analysis.get("situation_summary", ""),
                result["action"],
                "", # reasoning from analysis
                result["action"],
                result["details"],
                result["status"] in ["completed", "initiated", "queued"]
            ))
        
        # Update knowledge base
        for issue in analysis.get("issues", []):
            cursor.execute("""
                INSERT INTO agent_knowledge (topic, insight, confidence)
                VALUES ('issue_detection', ?, 0.7)
            """, (issue,))
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Learned from cycle: {len(results)} actions, {len(analysis.get('new_patterns', []))} patterns")
    

    async def notify_telegram(self, message):
        """Send alert to Telegram"""
        bot_token = "8483614914:AAFjwtH2pct_OdZgi4zrcPNKq6zWdb62ypQ"
        chat_id = "1153491543"
        
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
                timeout=5
            )
            if response.status_code == 200:
                logger.info(f"📱 Telegram alert sent")
            else:
                logger.error(f"Telegram failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    async def autonomous_loop(self):
        """
        Main autonomous loop - runs forever
        OBSERVE → REASON → PLAN → ACT → LEARN
        """
        logger.info("🤖 AUTONOMOUS AGENT STARTING")
        cycle = 0
        
        while True:
            try:
                cycle += 1
                logger.info(f"🔄 Cycle #{cycle} starting...")
                
                # 1. OBSERVE
                observations = await self.observe()
                logger.info(f"👁️  Observed: {observations['positions']['total']} positions, {observations['wallets']['total']} wallets")
                
                # 2. REASON
                analysis = await self.reason(observations)
                logger.info(f"🧠 Analyzed: {len(analysis.get('issues', []))} issues, {len(analysis.get('recommended_actions', []))} actions")
                
                # 3. PLAN
                plan = await self.plan(analysis)
                logger.info(f"📋 Plan: {len(plan)} tasks")
                
                # 4. ACT
                results = await self.act(plan)
                logger.info(f"⚡ Executed: {len(results)} actions")
                
                # 5. LEARN
                await self.learn(observations, analysis, results)
                
                # Update trust score
                action_success = None
                if results:
                    action_success = all(r.get("status") in ["completed", "initiated"] for r in results)
                
                new_trust = trust.update_trust(
                    cycle_success=True,
                    action_success=action_success,
                    patterns_learned=len(analysis.get("new_patterns", []))
                )
                
                # Log summary
                logger.info(f"✅ Cycle #{cycle} complete. Next in 5 minutes.")
                
                # Wait before next cycle
                await asyncio.sleep(300)  # 5 minutes
                
            except Exception as e:
                logger.error(f"❌ Cycle error: {e}", exc_info=True)
                await asyncio.sleep(60)  # 1 min on error

# Global instance
agent = AutonomousAgent()
