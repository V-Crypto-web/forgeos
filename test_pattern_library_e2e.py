import os
import sys

# Ensure run from root
sys.path.insert(0, os.getcwd())

from forgeos.engine.state_machine import StateMachine, ExecutionContext, EngineState
from forgeos.observability.telemetry import TelemetryLogger

import shutil
if os.path.exists("/tmp/forgeos_patterns"):
    shutil.rmtree("/tmp/forgeos_patterns")

class MockTelemetry:
    def __init__(self):
        self.events = []
    
    def log_event(self, event_type, issue_number, state, message, metadata=None):
        self.events.append((event_type, state, metadata))
        print(f"[Telemetry] {event_type} | {state} | {metadata}")
        
    def log_cost(self, *args, **kwargs):
        pass

import forgeos.providers.model_router
original_generate = forgeos.providers.model_router.ProviderRouter.generate_response
original_embedding = forgeos.providers.model_router.ProviderRouter.get_embedding

def mock_generate_response(self, role, sys_prompt, user_prompt, **kwargs):
    print(f"[MockRouter] Generating mock pattern response...")
    return {
        "content": '{"repo_class": "mock_repo", "issue_class": "divide_zero", "failure_signature": "divide_zero_error", "test_scope": "unit_tests", "patch_width": "narrow_local", "description": "A divide by zero mock."}',
        "prompt_tokens": 10,
        "completion_tokens": 10
    }

def mock_get_embedding(self, text, model="mock"):
    return [0.1] * 1536

forgeos.providers.model_router.ProviderRouter.generate_response = mock_generate_response
forgeos.providers.model_router.ProviderRouter.get_embedding = mock_get_embedding

def run_e2e_mock():
    # Attempt 1: Mock a Failure in State Machine directly invoking triggering learning loop
    print("--- SIMULATING FAILED RUN ---")
    ctx = ExecutionContext(issue_number=101, repo_path="/tmp/mock_repo")
    ctx.issue_text = "Fix the divide by zero in calculate_metrics"
    ctx.strategy = "naive_patch"
    ctx.test_results = {"status": "failed", "errors": "ZeroDivisionError in line 44", "output": ""}
    ctx.current_state = EngineState.FAILED
    ctx.telemetry = MockTelemetry()
    
    sm = StateMachine()
    # Trigger manually since we skip engine loop
    sm._trigger_learning_loop(ctx, "failed")
    
    # Wait for async thread
    import time
    time.sleep(3)
    
    print("\n--- SIMULATING RETRIEVAL FOR NEW RUN ---")
    ctx2 = ExecutionContext(issue_number=102, repo_path="/tmp/mock_repo")
    ctx2.issue_text = "divide by zero error when calculating user metrics"
    ctx2.current_state = EngineState.PATTERN_RETRIEVAL
    ctx2.telemetry = MockTelemetry()
    
    sm.handle_pattern_retrieval(ctx2)
    
    print("\n--- INJECTED CONTEXT ---")
    from forgeos.repo.repo_analyzer import RepoAnalyzer
    from forgeos.engine.context_pack import ContextPackBuilder
    analyzer = RepoAnalyzer("/tmp/mock_repo")
    
    class MockAnalyzer:
        def __init__(self): self.repo_path = "/tmp"
        def get_git_info(self): return "main", "123"
        def get_repo_map_summary(self, *args, **kwargs): return "mock repo map"
        
    pack_builder = ContextPackBuilder(ctx2, MockAnalyzer())
    prompt = pack_builder.build_planner_prompt()
    
    assert "ADVISORY GUIDANCE FROM PRIOR RUNS" in prompt
    print("Retrieval Hit Verified!")
    
if __name__ == "__main__":
    run_e2e_mock()
