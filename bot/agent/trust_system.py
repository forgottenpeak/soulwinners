"""
Agent Trust & Progression System
Builds confidence over time before allowing autonomous fixes
"""
import sqlite3
from database import get_connection
from datetime import datetime, timedelta

class TrustSystem:
    """Manages agent's trust level and permissions"""
    
    def __init__(self):
        self.init_trust_db()
    
    def init_trust_db(self):
        """Create trust tracking tables"""
        conn = get_connection()
        cursor = conn.cursor()
        
        # Trust metrics
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_trust (
                id INTEGER PRIMARY KEY,
                trust_score REAL DEFAULT 0,
                cycles_completed INTEGER DEFAULT 0,
                successful_actions INTEGER DEFAULT 0,
                failed_actions INTEGER DEFAULT 0,
                patterns_learned INTEGER DEFAULT 0,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Initialize if empty
        cursor.execute("SELECT COUNT(*) FROM agent_trust")
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO agent_trust (id, trust_score) VALUES (1, 0)
            """)
        
        # Permission levels
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                permission_name TEXT UNIQUE,
                required_trust REAL,
                enabled BOOLEAN DEFAULT 0,
                description TEXT
            )
        """)
        
        # Define permission tiers
        permissions = [
            ("view_only", 0, 1, "Read database and logs (ACTIVE)"),
            ("fix_unknown_tokens", 20, 0, "Auto-fix UNKNOWN token symbols"),
            ("update_enrichment", 40, 0, "Run SAGEO enrichment"),
            ("adjust_settings", 60, 0, "Change alert thresholds"),
            ("restart_services", 80, 0, "Restart webhook/bot on errors"),
            ("optimize_database", 90, 0, "Run DB cleanup/optimization"),
            ("full_autonomy", 100, 0, "Complete system control")
        ]
        
        for name, trust, enabled, desc in permissions:
            cursor.execute("""
                INSERT OR IGNORE INTO agent_permissions 
                (permission_name, required_trust, enabled, description)
                VALUES (?, ?, ?, ?)
            """, (name, trust, enabled, desc))
        
        conn.commit()
        conn.close()
    
    def get_trust_score(self):
        """Get current trust score (0-100)"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT trust_score FROM agent_trust WHERE id = 1")
        score = cursor.fetchone()[0]
        conn.close()
        return score
    
    def update_trust(self, cycle_success=True, action_success=None, patterns_learned=0):
        """Update trust score based on performance"""
        conn = get_connection()
        cursor = conn.cursor()
        
        # Get current state
        cursor.execute("""
            SELECT trust_score, cycles_completed, successful_actions, failed_actions, patterns_learned
            FROM agent_trust WHERE id = 1
        """)
        current = cursor.fetchone()
        score, cycles, success, failed, learned = current
        
        # Calculate new score
        new_score = score
        
        # Cycle completion: +0.5 per cycle (200 cycles = 100%)
        if cycle_success:
            new_score += 0.5
            cycles += 1
        
        # Action success/failure
        if action_success is True:
            new_score += 2
            success += 1
        elif action_success is False:
            new_score -= 5  # Penalty for failures
            failed += 1
        
        # Pattern learning bonus
        if patterns_learned > 0:
            new_score += patterns_learned * 0.2
            learned += patterns_learned
        
        # Cap at 100
        new_score = min(100, max(0, new_score))
        
        # Update database
        cursor.execute("""
            UPDATE agent_trust SET
                trust_score = ?,
                cycles_completed = ?,
                successful_actions = ?,
                failed_actions = ?,
                patterns_learned = ?,
                last_updated = CURRENT_TIMESTAMP
            WHERE id = 1
        """, (new_score, cycles, success, failed, learned))
        
        # Auto-enable permissions when trust reached
        cursor.execute("""
            UPDATE agent_permissions 
            SET enabled = 1 
            WHERE required_trust <= ? AND enabled = 0
        """, (new_score,))
        
        conn.commit()
        conn.close()
        
        return new_score
    
    def can_perform(self, action_name):
        """Check if agent has permission for action"""
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT enabled FROM agent_permissions 
            WHERE permission_name = ?
        """, (action_name,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else False
    
    def get_next_unlock(self):
        """Get next permission to unlock"""
        trust = self.get_trust_score()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT permission_name, required_trust, description
            FROM agent_permissions
            WHERE enabled = 0 AND required_trust > ?
            ORDER BY required_trust ASC LIMIT 1
        """, (trust,))
        result = cursor.fetchone()
        conn.close()
        return result
    
    def get_progress_report(self):
        """Generate progress report"""
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM agent_trust WHERE id = 1")
        row = cursor.fetchone()
        trust_id, score, cycles, success, failed, learned, updated = row
        
        cursor.execute("""
            SELECT COUNT(*) FROM agent_permissions WHERE enabled = 1
        """)
        enabled_perms = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "trust_score": score,
            "cycles_completed": cycles,
            "successful_actions": success,
            "failed_actions": failed,
            "patterns_learned": learned,
            "permissions_unlocked": enabled_perms,
            "total_permissions": 7
        }

trust = TrustSystem()
