import os
from forgeos.engine.state_machine import StateMachine, ExecutionContext, EngineState

class MockCoderAgent:
    def generate_patch(self, prompt: str):
        # Malicious/hallucinating Coder: Returns a massive 500-line diff touching 5 files
        patch = ""
        for i in range(5):
            patch += f"--- a/file{i}.py\n+++ b/file{i}.py\n@@ -1,3 +1,4 @@\n"
            patch += "+    pass\n" * 100
        return patch, {"model": "mock", "cost": 0.0, "prompt_tokens": 0, "completion_tokens": 0}

def test_patch_width_rejection():
    # Monkeypatch the CoderAgent in engine.agents so the local import picks it up
    import forgeos.engine.agents
    forgeos.engine.agents.CoderAgent = lambda router: MockCoderAgent()

    ctx = ExecutionContext()
    ctx.current_state = EngineState.PATCH
    ctx.repo_path = "."
    ctx.issue_number = 999
    
    # Needs a mock telemetry object so it doesn't crash
    class MockTelemetry:
        def log_cost(self, *args, **kwargs): pass
        def log_event(self, *args, **kwargs): print(f"TELEMETRY: {args}")
        
    ctx.telemetry = MockTelemetry()
    
    # Needs a mock analyzer mapping
    import forgeos.repo.repo_analyzer
    class MockAnalyzer:
        def __init__(self, *args, **kwargs):
            self.repo_path = "."
        def get_git_info(self): return ("main", "abc")
        
    forgeos.repo.repo_analyzer.RepoAnalyzer = MockAnalyzer
    
    # Needs mock context builder
    import forgeos.engine.context_pack
    class MockBuilder:
        def __init__(self, *args, **kwargs): pass
        def build_coder_prompt(self): return "MOCK PROMPT"
        
    forgeos.engine.context_pack.ContextPackBuilder = MockBuilder
    
    sm = StateMachine()
    
    # Run PATCH State
    ctx = sm.handle_patch(ctx)
    
    print(f"Post-PATCH State: {ctx.current_state}")
    assert ctx.current_state == EngineState.PATCH_WIDTH_REJECT, "State machine failed to transition to REJECT state for wide patch."
    
    # Run REJECT State
    ctx = sm.handle_patch_width_reject(ctx)
    print(f"Post-REJECT State: {ctx.current_state}")
    assert ctx.current_state == EngineState.PLAN, "State machine failed to route rejected patch to Planner."
    
    print("SUCCESS: State machine cleanly rejected the massive patch and forced a Hard Replan.")

if __name__ == "__main__":
    test_patch_width_rejection()
