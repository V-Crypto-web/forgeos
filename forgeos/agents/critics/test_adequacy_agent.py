from typing import Tuple, Dict, Any
import json
from forgeos.providers.model_router import ProviderRouter, ModelRole

class TestAdequacyAgent:
    """
    Resolves the 'Verification Deficit' Cognitive Failure.
    Analyzes the sandbox test output to guarantee the executed test command
    actually compiled the new patch and covered the modified logic, rather
    than silently returning Exit 0 for 0 items collected.
    """
    def __init__(self, router: ProviderRouter):
        self.router = router

    def evaluate(self, patch: str, repo_path: str, test_output: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        from forgeos.verification.pytest_parser import PytestAnalyzer
        
        analyzer = PytestAnalyzer(workspace_path=repo_path)
        structured_payload = analyzer.analyze(test_output)
        test_payload_md = structured_payload.to_markdown()
        
        sys_prompt = """You are the Test Adequacy Agent.
A Coder agent has proposed a patch and executed tests in a sandbox environment.
Your job is to prevent false positives. Specifically, you must ensure that the tests ACTUALLY ran.

Look for Verification Deficit traits:
1. "collected 0 items" - The test command was wrong.
2. "ImportError / ModuleNotFoundError" - The environment corrupted before running the test logic.
3. Tests passed, but none of them targeted the files modified in the patch (Silent miss).

Respond ONLY with a valid JSON object:
{
    "status": "APPROVED" | "REJECTED",
    "reason": "Why the test execution is valid or invalid",
    "advice": "What test command the Coder should run instead to accurately verify the patch"
}"""
        user_prompt = f"=== PATCH APPLIED ===\n{patch}\n\n=== STRUCTURED TEST PAYLOAD ===\n{test_payload_md}\n"
        response = self.router.generate_response(ModelRole.VERIFIER, sys_prompt, user_prompt)
        
        try:
            content = response["content"]
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            result = json.loads(content)
        except Exception:
            result = {"status": "REJECTED", "reason": "Failed to parse Test Adequacy LLM output", "advice": "Rerun tests with pytest -v."}
            
        return result, response
