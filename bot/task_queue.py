"""
Task Queue System - Prevents database locks and blocking
Tasks run in background, AI gets notified when complete
"""
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

class TaskQueue:
    """Simple file-based task queue"""
    
    def __init__(self):
        self.queue_dir = Path("/root/Soulwinners/data/task_queue")
        self.queue_dir.mkdir(exist_ok=True)
        
    async def add_task(self, task_type, params=None):
        """Add a task to the queue"""
        task_id = f"{int(datetime.now().timestamp())}_{task_type}"
        task = {
            "id": task_id,
            "type": task_type,
            "params": params or {},
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        
        task_file = self.queue_dir / f"{task_id}.json"
        with open(task_file, 'w') as f:
            json.dump(task, f)
        
        logger.info(f"✅ Queued task: {task_type}")
        return task_id
    
    def get_pending_tasks(self):
        """Get all pending tasks"""
        tasks = []
        for task_file in self.queue_dir.glob("*.json"):
            with open(task_file, 'r') as f:
                task = json.load(f)
                if task.get("status") == "pending":
                    tasks.append(task)
        return sorted(tasks, key=lambda x: x['created_at'])
    
    def mark_complete(self, task_id, result=None):
        """Mark task as complete"""
        task_file = self.queue_dir / f"{task_id}.json"
        if task_file.exists():
            with open(task_file, 'r') as f:
                task = json.load(f)
            
            task["status"] = "complete"
            task["completed_at"] = datetime.now().isoformat()
            task["result"] = result
            
            with open(task_file, 'w') as f:
                json.dump(task, f)
    
    def mark_failed(self, task_id, error):
        """Mark task as failed"""
        task_file = self.queue_dir / f"{task_id}.json"
        if task_file.exists():
            with open(task_file, 'r') as f:
                task = json.load(f)
            
            task["status"] = "failed"
            task["completed_at"] = datetime.now().isoformat()
            task["error"] = str(error)
            
            with open(task_file, 'w') as f:
                json.dump(task, f)

# Global instance
task_queue = TaskQueue()
