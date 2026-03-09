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
        
    def log_event(self, event_type: str, issue_number: int, state: str, message: str, metadata: Dict[str, Any] = None, parent_epic_id: int = None):
        """
        Records a structured telemetry event.
        """
        payload = {
            "timestamp": time.time(),
            "event_type": event_type,
            "issue_number": issue_number,
            "parent_epic_id": parent_epic_id,
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
                "cost": cost
            }
        )
        
    def log_async_hazard(self, issue_number: int, state: str, patch_snippet: str):
        """
        Special event for tracking Async Safety hazards detected by the Critic's static checker.
        """
        self.log_event(
            event_type="async_safety_hazard",
            issue_number=issue_number,
            state=state,
            message="Static Checker flagged missing await/asyncio.run in patch.",
            metadata={
                "patch_snippet": patch_snippet[:200]
            }
        )
        
    def log_symbol_graph_hit(self, issue_number: int, state: str, symbol_count: int):
        """
        Special event for tracking successful injections of Symbol Graph context (Epic 48).
        """
        self.log_event(
            event_type="symbol_graph_hit",
            issue_number=issue_number,
            state=state,
            message=f"Injected Symbol Graph context for {symbol_count} relevant symbols.",
            metadata={
                "symbol_count": symbol_count
            }
        )
