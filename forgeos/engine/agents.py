from forgeos.providers.model_router import ProviderRouter, ModelRole

from typing import Tuple, Dict, Any

class PlannerAgent:
    def __init__(self, router: ProviderRouter):
        self.router = router
        
    def generate_plan(self, context_pack: str) -> Tuple[str, Dict[str, Any]]:
        sys_prompt = "You are the Planner. Given the context (issue, rules, affected files, repo map), create a step-by-step plan."
        response = self.router.generate_response(ModelRole.PLANNER, sys_prompt, context_pack)
        return response["content"], response

class CoderAgent:
    def __init__(self, router: ProviderRouter):
        self.router = router
        
    def generate_patch(self, context_pack: str) -> Tuple[str, Dict[str, Any]]:
        sys_prompt = """You are the Coder. Output ONLY a unified diff patch, valid for `git apply`.

HARD RULES — violating any of these causes instant rejection:
1. MODIFY EXISTING FILES ONLY. NEVER create new files (no `--- /dev/null` blocks).
2. Touch AT MOST 1 file per patch.
3. Change AT MOST 30 lines total (additions + removals combined).
4. Every hunk MUST be complete — NEVER truncate mid-hunk.
5. Context lines (unchanged) start with exactly ONE SPACE. Not zero spaces, not two.
6. `@@ -LINE,COUNT +LINE,COUNT @@` counts MUST match the actual lines in the hunk.
7. DO NOT add imports outside the function scope if it avoids creating a new file.

FORMAT (follow exactly):
```diff
--- a/forgeos/path/to/file.py
+++ b/forgeos/path/to/file.py
@@ -10,4 +10,5 @@
 def existing_function():
-    old_line = True
+    new_line = True
+    extra_line = 42
     return result
```

ASYNC RULES: Always `await` coroutine calls. Use `asyncio.run()` inside sync functions.

Output ONLY the ```diff block. No explanation."""
        response = self.router.generate_response(ModelRole.CODER, sys_prompt, context_pack, max_tokens=4096)
        return response["content"], response

class VerifierAgent:
    def __init__(self, router: ProviderRouter):
        self.router = router
        
    def verify(self, patch: str, test_output: str) -> Tuple[bool, Dict[str, Any]]:
        sys_prompt = "You are the Verifier. Did the tests pass? Output YES or NO."
        user_prompt = f"Test Output:\n{test_output}\nDid it pass?"
        response = self.router.generate_response(ModelRole.VERIFIER, sys_prompt, user_prompt)
        return "YES" in response["content"].upper(), response

class CriticAgent:
    def __init__(self, router: ProviderRouter):
        self.router = router
        
    def review_patch(self, issue_text: str, plan: str, patch: str, impact_report: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        import json
        sys_prompt = """You are the Execution Critic and Patch Reviewer. 
Your job is to review a proposed code patch BEFORE it is executed to catch bad engineering judgments, overly broad changes, or incorrect strategies.
You will be provided with the Issue, the Plan, the proposed Patch, and the Impact Report.

ASYNC CHECKLIST:
1. Does the patch introduce any new `async` calls without an `await`?
2. Does the patch call `await` inside a synchronous function?
3. Does the patch return a coroutine object instead of awaiting it?
If ANY of these are true, you MUST REJECT the patch.

Evaluate the patch against the following criteria:
1. Does the patch align with solving the specific issue?
2. Is the patch too broad? (e.g., touching files unnecessarily)
3. Does it break architectural invariants or contracts?
4. Is it a safe approach given the risk score?
5. Does it pass the ASYNC CHECKLIST?

Respond ONLY with a valid JSON object in the following format:
{
    "status": "APPROVED" | "REJECTED_REVISE_PATCH" | "REJECTED_CHANGE_STRATEGY",
    "reason": "Clear, concise engineering reason for the decision",
    "advice": "Actionable advice for the Coder or Planner on what to fix"
}"""
        
        static_warning = ""
        patch_lower = patch.lower()
        if ("asyncio" in patch_lower or ".generate_" in patch_lower or "async" in patch_lower) and "await " not in patch_lower and "asyncio.run" not in patch_lower:
             static_warning = "\n[STATIC CHECKER WARNING]: The patch appears to involve async logic or IO calls, but the literal 'await' or 'asyncio.run' keyword is missing. Strongly consider REJECTING this patch for Async Safety reasons unless you are absolutely certain it is correct.\n"

        user_prompt = f"=== ISSUE ===\\n{issue_text}\\n\\n=== PLAN ===\\n{plan}\\n\\n=== IMPACT REPORT ===\\nRisk Score: {impact_report.get('risk_score', 'Unknown')}\\nAllowed Strategy: {impact_report.get('allowed_strategy', 'Unknown')}\\n\\n=== PROPOSED PATCH ===\\n{patch}\\n{static_warning}"
        
        response = self.router.generate_response(ModelRole.CRITIC, sys_prompt, user_prompt)
        
        try:
            content = response["content"]
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
        except Exception as e:
            result = {
                "status": "APPROVED", # Fallback
                "reason": f"Failed to parse critic response, defaulting to APPROVED. Error: {e}",
                "advice": ""
            }
            
        return result, response

    def analyze_failure(self, issue_text: str, plan: str, patch: str, test_output: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        import json
        sys_prompt = """You are the Execution Critic and Post-Failure Analyzer.
A patch was executed but the tests or CI failed. Your job is to analyze WHY it failed and provide targeted guidance for the next retry loop.
You will be provided with the Issue, the Plan, the Patch, and the failing Test Output.

Evaluate the failure to determine:
1. Is it a real flaw in the patch? (e.g., syntax error, logic error)
2. Is the verification scope wrong? (e.g., tests are testing the wrong thing)
3. Is it the wrong file or abstraction level?
4. What specific strategy should the Planner or Coder adopt next?

Respond ONLY with a valid JSON object in the following format:
{
    "diagnosis": "Clear explanation of why the failure occurred",
    "advice": "Actionable advice on what needs to change in the next attempt"
}"""

        user_prompt = f"=== ISSUE ===\\n{issue_text}\\n\\n=== PLAN ===\\n{plan}\\n\\n=== PATCH ===\\n{patch}\\n\\n=== TEST OUTPUT ===\\n{test_output}\\n"

        response = self.router.generate_response(ModelRole.CRITIC, sys_prompt, user_prompt)
        
        try:
            content = response["content"]
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            result = json.loads(content)
        except Exception as e:
            result = {
                "diagnosis": "Failed to parse critic diagnosis.",
                "advice": "Try alternative approach."
            }
            
        return result, response
