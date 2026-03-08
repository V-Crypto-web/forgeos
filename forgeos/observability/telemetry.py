import json
import os
import time
from typing import Dict, Any

class TelemetryLogger:
    """
    Module 8: Observability and Telemetry Layer.
    Provides structured JSON logging for all Engine events.
    In the real platform, this streams to OpenCloud / Datadog.
    For MVP, it writes structured logs to a local file.
    """
    def __init__(self, workspace_path: str = "/tmp/forgeos_logs"):
        self.log_dir = workspace_path
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(self.log_dir, "forgeos_telemetry.log")
        
    def log_event(self, event_type: str, issue_number: int, state: str, message: str, metadata: Dict[str, Any] = None):
        """
        Records a structured telemetry event.
        """
        payload = {
            "timestamp": time.time(),
            "event_type": event_type,
            "issue_number": issue_number,
            "state": state,
            "message": message,
            "metadata": metadata or {}
        }
        
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
            
    def log_cost(self, issue_number: int, state: str, model: str, prompt_tokens: int, completion_tokens: int):
        """
        Special event for tracking Token Scheduler/Economist costs.
        """
        try:
            from forgeos.observability.cost_tracker import CostTracker
            cost = CostTracker.calculate_cost(model, prompt_tokens, completion_tokens)
        except Exception:
            cost = 0.0
            
        self.log_event(
            event_type="api_cost",
            issue_number=issue_number,
            state=state,
            message=f"LLM Call to {model} [${cost:.4f}]",
            metadata={
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cost": cost
            }
        )
