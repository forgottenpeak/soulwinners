"""
Task Executor - Runs queued tasks in background
Prevents database locks by running tasks sequentially
"""
import asyncio
import logging
import subprocess
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, '/root/Soulwinners')

from bot.task_queue import task_queue
from database import get_connection

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/root/Soulwinners/logs/executor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class TaskExecutor:
    """Executes tasks from the queue"""
    
    async def execute_task(self, task):
        """Execute a single task"""
        task_type = task['type']
        task_id = task['id']
        
        logger.info(f"🔧 Executing: {task_type}")
        
        try:
            if task_type == "fix_unknown_tokens":
                result = await self.fix_unknown_tokens()
            elif task_type == "toggle_buy_alerts":
                result = await self.toggle_buy_alerts(task['params'])
            elif task_type == "restart_webhook":
                result = await self.restart_webhook()
            else:
                result = f"Unknown task type: {task_type}"
                task_queue.mark_failed(task_id, result)
                return
            
            task_queue.mark_complete(task_id, result)
            logger.info(f"✅ Completed: {task_type}")
            
        except Exception as e:
            logger.error(f"❌ Failed {task_type}: {e}", exc_info=True)
            task_queue.mark_failed(task_id, str(e))
    
    async def fix_unknown_tokens(self):
        """Run the UNKNOWN token fixer"""
        result = subprocess.run(
            ['python3', '/root/Soulwinners/scripts/fix_unknown_tokens.py'],
            cwd='/root/Soulwinners',
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            fixed_count = result.stdout.count('✅ Fixed')
            return f"Fixed {fixed_count} tokens"
        else:
            raise Exception(result.stderr[:500])
    
    async def toggle_buy_alerts(self, params):
        """Toggle buy alerts on/off"""
        enable = params.get('enable', True)
        
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO settings (key, value)
            VALUES ('buy_alerts', ?)
        """, ('enabled' if enable else 'disabled',))
        
        conn.commit()
        conn.close()
        
        return f"Buy alerts {'enabled' if enable else 'disabled'}"
    
    async def restart_webhook(self):
        """Restart the webhook server"""
        # Kill old webhook
        subprocess.run(['pkill', '-f', 'webhook_server'], timeout=5)
        await asyncio.sleep(2)
        
        # Start new webhook
        subprocess.Popen(
            ['python3', '/root/Soulwinners/webhook_server.py', '--port', '5000'],
            stdout=open('/root/Soulwinners/logs/webhook_server.log', 'a'),
            stderr=subprocess.STDOUT,
            cwd='/root/Soulwinners'
        )
        
        await asyncio.sleep(3)
        
        # Verify running
        check = subprocess.run(['pgrep', '-f', 'webhook_server'], capture_output=True)
        if check.returncode == 0:
            return "Webhook restarted successfully"
        else:
            raise Exception("Webhook failed to start")


async def main():
    """Main executor loop"""
    executor = TaskExecutor()
    logger.info("🚀 Executor started - processing tasks every 10 seconds")
    
    while True:
        try:
            # Get pending tasks
            tasks = task_queue.get_pending_tasks()
            
            # Execute each task
            for task in tasks:
                await executor.execute_task(task)
            
            # Wait before checking again
            await asyncio.sleep(10)
            
        except Exception as e:
            logger.error(f"Executor error: {e}", exc_info=True)
            await asyncio.sleep(10)


if __name__ == "__main__":
    asyncio.run(main())
