from enum import Enum
from typing import Optional, Dict, Any

class StrategyDirective(Enum):
    FAST_RETRY = "FAST_RETRY"             # Bypass Planner/Council -> Direct to Coder
    HARD_REPLAN = "HARD_REPLAN"           # Reset Planner -> New approach
    KNOWLEDGE_EXPANSION = "KNOWLEDGE_EXPANSION" # Fetch new info before retry
    STANDARD_RETRY = "STANDARD_RETRY"     # Linearly proceed to NEXT_RETRY
    GOVERNANCE_RELAXATION = "GOVERNANCE_RELAXATION" # Suppress bureaucratic critics and force test execution
    ABORT = "ABORT"                       # Halt execution to protect budget

class PolicyEngine:
    """
    Evaluates failure signatures to determine the optimal execution strategy path.
    """
    
    @classmethod
    def evaluate(cls, failure_record: Optional[Dict[str, Any]], current_retry: int, max_retries: int) -> StrategyDirective:
        if not failure_record:
            return StrategyDirective.STANDARD_RETRY
            
        failure_class = failure_record.get("failure_class", "").upper()
        signature = failure_record.get("failure_signature", "").lower()

        # 0. Malformed patch — always fast-retry immediately (before checking retry budget)
        #    The MALFORMED_PATCH error message tells the Coder exactly how to fix the diff.
        if (signature in ["malformed_patch", "corrupt_patch"]
                or "malformed_patch" in failure_class.lower()
                or "malformed_patch" in signature):
            if current_retry < max_retries + 1:   # allow one extra attempt for patch quality
                return StrategyDirective.FAST_RETRY

        # 1. Abort Traps
        if current_retry >= max_retries:
            if failure_class == "GOVERNANCE_REJECT" or signature in ["simulation_reject_soft", "simulation_reject_hard", "council_reject"]:
                return StrategyDirective.GOVERNANCE_RELAXATION
            return StrategyDirective.ABORT

        if signature in ["patch_too_wide", "test_timeout"]:
            # If we hit a physical scope constraint, don't waste 5 retries on it.
            if current_retry >= 2:
                return StrategyDirective.ABORT

        # 2. Syntax / Fast Retries (No architecture logic broken)
        if signature in ["async_missing_await", "indentation_error", "syntax_error", "variable_not_found", "malformed_patch", "corrupt_patch"]:
            return StrategyDirective.FAST_RETRY
            
        # 3. Knowledge / Information Gaps
        if failure_class == "RETRIEVAL FAILURE" or signature in ["wrong_module", "missing_import"]:
            return StrategyDirective.KNOWLEDGE_EXPANSION
            
        # 4. Logic / Strategy Breaks
        if failure_class in ["STRATEGY FAILURE", "REASONING FAILURE"] or signature in ["contract_break", "regression"]:
            return StrategyDirective.HARD_REPLAN
            
        # Default
        return StrategyDirective.STANDARD_RETRY
