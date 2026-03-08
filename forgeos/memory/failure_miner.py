import os
import json
import uuid
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, ConfigDict
from forgeos.providers.model_router import ProviderRouter, ModelRole

FAILURE_DB_PATH = os.path.join(os.getcwd(), "forgeos", "memory", "failure_db")

class FailureRecord(BaseModel):
    model_config = ConfigDict(extra='ignore')
    
    issue_id: str
    repo_class: str
    issue_class: str
    failure_class: str
    failure_signature: str
    strategy_attempted: str
    retry_count: int
    patch_width: int
    simulator_warning: str
    outcome: str

class FailureIntelligenceEngine:
    def __init__(self):
        self.router = ProviderRouter()
        os.makedirs(FAILURE_DB_PATH, exist_ok=True)
        
    def _build_trace_dump(self, context) -> str:
        # Build a text representation of the failed run
        trace = f"Issue ID: {context.issue_number}\n"
        trace += f"Repo Path: {context.repo_path}\n"
        trace += f"Issue Text:\n{context.issue_text}\n"
        trace += f"\n--- RETRY COUNT: {context.retries} ---\n"
        
        trace += "\n--- EXECUTION LOGS ---\n"
        for log in context.logs:
            trace += f"{log}\n"
            
        trace += "\n--- LAST PATCH ATTEMPT ---\n"
        if context.patch:
            trace += context.patch
            
        return trace

    def mine_failure(self, context) -> Optional[Dict[str, Any]]:
        """
        Extracts structured failure intelligence from the execution context.
        Returns the FailureRecord dict if successful, or None.
        """
        # We only care about mining failures where the environment actually worked.
        # If the environment didn't bootstrap, it's not a cognitive failure.
        if "patch apply failed" in str(context.logs).lower() or not context.patch:
            print("[FailureMiner] Skipping non-cognitive failure (no patch generated).")
            return
            
        print("[FailureMiner] Mining execution trace for Cognitive Failure Intelligence...")
        
        trace = self._build_trace_dump(context)
        
        
        user_prompt = f"""
        A run has FAILED. You must analyze the execution trace and extract structured intelligence about WHY it failed.
        
        # Taxonomy Reminders
        - failure_class: Retrieval Failure, Strategy Failure, Reasoning Failure, or Verification Deficit.
        - failure_signature: A short string classifying the exact error (e.g., 'async_missing_await', 'patch_too_wide', 'wrong_module', 'test_timeout', 'contract_break').
        - outcome: How did it end? (e.g., 'deadlock', 'max_retries', 'architect_intervention', 'simulator_rejection_loop').
        - patch_width: Approximate number of files modified (an integer).
        
        # Execution Trace:
        {trace}
        
        Return ONLY valid JSON matching this exact schema:
        {{
            "issue_id": "string",
            "repo_class": "string",
            "issue_class": "string",
            "failure_class": "string",
            "failure_signature": "string",
            "strategy_attempted": "string",
            "retry_count": int,
            "patch_width": int,
            "simulator_warning": "string",
            "outcome": "string"
        }}
        """
        
        try:
            res = self.router.generate_response(
                ModelRole.PLANNER, 
                system_prompt="You are the ForgeOS Failure Intelligence Engine. Output ONLY valid JSON.",
                user_prompt=user_prompt,
                response_format={"type": "json_object"}
            )
            res_str = res["content"]
            
            # The model_config will ignore extra fields if they are hallucinated
            record = FailureRecord.model_validate_json(res_str)
            
            # Save the record
            record_id = str(uuid.uuid4())[:8]
            fname = f"{record.issue_id}_{record.failure_signature}_{record_id}.json"
            fpath = os.path.join(FAILURE_DB_PATH, fname)
            
            with open(fpath, "w") as f:
                json.dump(record.model_dump(), f, indent=4)
                
            print(f"[FailureMiner] Extracted failure signature: '{record.failure_signature}' -> Saved to {fname}")
            return record.model_dump()
            
        except Exception as e:
            print(f"[FailureMiner] Failed to mine failure trace: {e}")
            return None

