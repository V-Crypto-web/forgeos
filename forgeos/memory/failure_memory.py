import json
import os
from typing import Dict, Any, List

class FailureMemory:
    """
    Tracks failed attempts and error signatures to prevent the orchestrator
    from getting stuck in infinite loops trying the same failing strategy.
    
    MVP version stores state in memory and can optionally persist to a simple JSON file.
    """
    def __init__(self, issue_id: int, storage_dir: str = "/tmp/forgeos_memory"):
        self.issue_id = issue_id
        self.storage_dir = storage_dir
        self.memory_file = os.path.join(self.storage_dir, f"failure_memory_issue_{issue_id}.json")
        self.failures: Dict[str, Dict[str, Any]] = {}
        
        os.makedirs(self.storage_dir, exist_ok=True)
        self.load()

    def load(self):
        """Loads failure memory from disk if it exists."""
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, "r") as f:
                    self.failures = json.load(f)
            except Exception as e:
                print(f"Failed to load memory file {self.memory_file}: {e}")
                self.failures = {}

    def save(self):
        """Persists failure memory to disk."""
        with open(self.memory_file, "w") as f:
            json.dump(self.failures, f, indent=2)

    def record_failure(self, error_signature: str, strategy: str):
        """
        Records a failure for a specific error and strategy combination.
        """
        key = f"{error_signature}::{strategy}"
        if key not in self.failures:
            self.failures[key] = {
                "error_signature": error_signature,
                "strategy": strategy,
                "attempts": 0,
                "status": "active"
            }
            
        self.failures[key]["attempts"] += 1
        
        # If we failed 3 times with the same strategy on the same error signature,
        # we mark this strategy as blocked for this error pattern.
        if self.failures[key]["attempts"] >= 3:
            self.failures[key]["status"] = "blocked"
            
        self.save()

    def is_strategy_blocked(self, error_signature: str, strategy: str) -> bool:
        """
        Checks if the orchestrator should avoid this strategy for the given error.
        """
        key = f"{error_signature}::{strategy}"
        if key in self.failures and self.failures[key]["status"] == "blocked":
            return True
        return False
        
    def get_context(self) -> str:
        """
        Returns a context string for the Planner to understand what NOT to do.
        """
        blocked = [f"Do NOT use '{f['strategy']}' for error '{f['error_signature']}' (failed {f['attempts']} times)." 
                   for f in self.failures.values() if f["status"] == "blocked"]
                   
        warnings = [f"Warning: '{f['strategy']}' failed {f['attempts']} times for '{f['error_signature']}'." 
                    for f in self.failures.values() if f["status"] == "active" and f["attempts"] > 1]
                    
        context_lines = []
        if blocked:
            context_lines.append("BLOCKED STRATEGIES:")
            context_lines.extend(blocked)
        if warnings:
            if context_lines:
                context_lines.append("")
            context_lines.append("WARNINGS:")
            context_lines.extend(warnings)
            
        return "\n".join(context_lines) if context_lines else "No current failure memory constraints."
