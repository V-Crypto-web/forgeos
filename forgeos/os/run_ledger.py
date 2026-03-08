import os
import json
import time
from typing import Dict, Any, List

class RunLedger:
    """
    Module 12: Run Ledger (Execution OS Layer)
    An immutable append-only ledger that records every state transition, tool call, 
    patch attempt, and test execution for a given Task ID.
    This enables deterministic replay and debugging of the autonomous loop.
    """
    def __init__(self, workspace_path: str, issue_number: int):
        self.issue_number = issue_number
        # Store ledgers in the global .forgeos directory of the workspace
        self.ledger_dir = os.path.join(workspace_path, ".forgeos", "ledger", f"issue_{issue_number}")
        os.makedirs(self.ledger_dir, exist_ok=True)
        
        timestamp = int(time.time())
        self.ledger_file = os.path.join(self.ledger_dir, f"run_ledger_{timestamp}.jsonl")
        
    def append_event(self, event_type: str, payload: Dict[str, Any]):
        """Append a deterministic event to the ledger."""
        event = {
            "timestamp": time.time(),
            "event_type": event_type,
            "payload": payload
        }
        with open(self.ledger_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
            
    def get_events(self) -> List[Dict[str, Any]]:
        """Read all events from the current ledger."""
        events = []
        if os.path.exists(self.ledger_file):
            with open(self.ledger_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))
        return events
