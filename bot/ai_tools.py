"""
Safe AI execution tools - READ-ONLY + settings control
AI can query data and change settings, but CANNOT modify code or delete data
"""
import logging
from database import get_connection
import subprocess

logger = logging.getLogger(__name__)

class SafeAITools:
    """Safe tools AI can use - no destructive operations"""
    
    def query_database(self, query: str, params: tuple = ()):
        """
        Execute READ-ONLY database queries
        Blocks: UPDATE, DELETE, DROP, ALTER, INSERT
        """
        query_upper = query.upper().strip()
        
        # Block dangerous operations
        forbidden = ['UPDATE', 'DELETE', 'DROP', 'ALTER', 'INSERT', 'CREATE', 'TRUNCATE']
        if any(cmd in query_upper for cmd in forbidden):
            return {"error": "Only SELECT queries allowed for safety"}
        
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            
            # Limit results to 100 rows for safety
            results = cursor.fetchmany(100)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            
            conn.close()
            
            return {
                "success": True,
                "columns": columns,
                "rows": results,
                "count": len(results)
            }
        except Exception as e:
            logger.error(f"Query error: {e}")
            return {"error": str(e)}
    
    def update_setting(self, key: str, value: str):
        """
        Update bot settings (alerts, limits, etc)
        Safe - only modifies settings table
        """
        allowed_settings = [
            'buy_alerts',
            'alert_limit_per_hour', 
            'daily_alert_limit',
            'min_probability'
        ]
        
        if key not in allowed_settings:
            return {"error": f"Can only modify: {', '.join(allowed_settings)}"}
        
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO settings (key, value)
                VALUES (?, ?)
            """, (key, value))
            conn.commit()
            conn.close()
            
            return {"success": True, "setting": key, "value": value}
        except Exception as e:
            return {"error": str(e)}
    
    def get_setting(self, key: str):
        """Get current setting value"""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            result = cursor.fetchone()
            conn.close()
            
            return {"success": True, "key": key, "value": result[0] if result else None}
        except Exception as e:
            return {"error": str(e)}
    
    def view_logs(self, log_file: str = "bot", lines: int = 50):
        """
        View log files (READ-ONLY)
        Allowed: bot, webhook_server, lifecycle
        """
        allowed_logs = {
            'bot': '/root/Soulwinners/logs/bot.log',
            'webhook': '/root/Soulwinners/logs/webhook_server.log',
            'lifecycle': '/root/Soulwinners/logs/lifecycle.log'
        }
        
        if log_file not in allowed_logs:
            return {"error": f"Can only view: {', '.join(allowed_logs.keys())}"}
        
        try:
            result = subprocess.run(
                ['tail', f'-{lines}', allowed_logs[log_file]],
                capture_output=True,
                text=True,
                timeout=5
            )
            return {"success": True, "log": log_file, "content": result.stdout}
        except Exception as e:
            return {"error": str(e)}
    
    def get_process_status(self):
        """Check if services are running (READ-ONLY)"""
        try:
            webhook = subprocess.run(['pgrep', '-f', 'webhook_server'], capture_output=True)
            bot = subprocess.run(['pgrep', '-f', 'run_bot'], capture_output=True)
            
            return {
                "success": True,
                "webhook": "running" if webhook.returncode == 0 else "stopped",
                "bot": "running" if bot.returncode == 0 else "stopped"
            }
        except Exception as e:
            return {"error": str(e)}

# Global instance
ai_tools = SafeAITools()
