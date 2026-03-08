from typing import Tuple, Dict, Any
import json
from forgeos.providers.model_router import ProviderRouter, ModelRole

class ExecutionCritic:
    """
    Analyzes test failures, lint errors, and environment crashes to figure out why the code didn't run.
    """
    def __init__(self, router: ProviderRouter):
        self.router = router
        
    def analyze_failure(self, issue_text: str, plan: str, patch: str, repo_path: str, test_output: str, failure_category: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        from forgeos.verification.pytest_parser import PytestAnalyzer
        
        analyzer = PytestAnalyzer(workspace_path=repo_path)
        structured_payload = analyzer.analyze(test_output)
        test_payload_md = structured_payload.to_markdown()
        
        sys_prompt = f"""You are the Execution Critic.
A patch was executed but the tests or CI failed with category: {failure_category}.
Analyze WHY it failed and provide targeted guidance. Focus on runtime syntax, test failures, or missing dependencies.

CRITICAL UPGRADE (Epic 41 Phase 14):
If the error output contains "coroutine 'X' was never awaited", "RuntimeWarning: coroutine", or "object 'coroutine' has no attribute", you must EXPLICITLY flag this as an Async/Await Semantic Break. Your advice MUST instruct the Coder to either add the `await` keyword, or if inside a synchronous function, to use `asyncio.run()` or refactor the caller to be `async def`. Do not provide generic syntax advice if a coroutine mismatch is detected.

Respond ONLY with a valid JSON object:
{{
    "diagnosis": "Root cause of the execution failure (mention Async/Coroutine explicitly if detected)",
    "advice": "Actionable advice on what needs to change computationally"
}}"""

        user_prompt = f"=== ISSUE ===\\n{issue_text}\\n\\n=== PLAN ===\\n{plan}\\n\\n=== PATCH ===\\n{patch}\\n\\n=== STRUCTURED TEST PAYLOAD ===\\n{test_payload_md}\\n"
        response = self.router.generate_response(ModelRole.CRITIC, sys_prompt, user_prompt)
        
        try:
            content = response["content"]
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            result = json.loads(content)
        except Exception as e:
            result = {"diagnosis": "Failed to parse critic diagnosis.", "advice": "Try alternative approach."}
            
        return result, response
