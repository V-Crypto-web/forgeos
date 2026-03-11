import json
from typing import Dict, Any, Tuple
from forgeos.providers.model_router import ProviderRouter, ModelRole

class PatchSimulatorAgent:
    """
    A strictly constrained Critic Agent functioning as a 'Static Patch Impact Simulator'.
    It intercepts proposed patches before they are run through to test suites.
    Its goal is to prevent the wasting of test cycles on structurally flawed patches 
    (e.g., ones that break basic function contracts or massively over-expand the scope).
    """
    def __init__(self, router: ProviderRouter):
        self.router = router

    def simulate_impact(self, issue_text: str, patch: str, symbol_index_str: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        sys_prompt = """You are the Static Patch Impact Simulator.
Your role is to evaluate a newly generated diff (patch) BEFORE it is executed to predict its structural impact.
You do NOT check if the logic solves the bug perfectly, but whether the structural changes carry high execution risk.

Evaluate the following:
1. Contract Break: Does it alter a function signature, remove a return keyword, or break typing expectations that existing callers (see Symbol Index) might rely on?
2. Scope Expansion: Does it touch significantly more files than necessary, or alter generic infrastructure for a highly localized bug?
3. Async Hazards: Is an `await` missing? Are unawaited coroutines being returned?

Respond ONLY with this JSON schema:
{
    "risk_score": "low" | "medium" | "high" | "critical",
    "contract_break_risk": true | false,
    "affected_callers": ["file.py", "module.py"], // Based on your best guess from Symbol Index
    "verification_scope_recommendation": "unit_only" | "integration_plus_package" | "full_suite",
    "strategy_decision": "proceed" | "warn" | "soft_block" | "hard_block",
    "reasoning": "1-sentence explanation of the structural risk."
}

CRITICAL RULES:
- `hard_block`: Catastrophic API breaks outside the scope of the issue, severe syntax breakage.
- `soft_block`: Patch is too wide, or touches unrelated files.
- `warn`: Behavioral change required by the issue (adding bounds checks, raising expected errors, adding guard clauses). This allows execution to proceed while noting the change.
- If `risk_score` is high/critical, set `verification_scope_recommendation` to "full_suite" or "integration_plus_package".
- Only use `hard_block` or `soft_block` if structurally reckless or harmful. If behavioral changes are requested by the issue (like catching an error, checking bounds, modifying state to fix a bug), DO NOT reject. Use `warn` or `proceed`. Do not block valid bugfixes just because they change behavior—changing behavior is the point!"""

        user_prompt = f"=== ISSUE TEXT ===\n{issue_text}\n\n=== SYMBOL INDEX EXCERPT ===\n{symbol_index_str[:2000]}\n\n=== PROPOSED PATCH ===\n{patch[:4000]}"
        
        response = self.router.generate_response(ModelRole.CRITIC, sys_prompt, user_prompt)
        
        try:
            content = response["content"]
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            data = json.loads(content)
        except Exception:
            # Safe Fallback to Proceed if parser fails
            data = {
                "risk_score": "low",
                "contract_break_risk": False,
                "affected_callers": [],
                "verification_scope_recommendation": "unit_only",
                "strategy_decision": "proceed",
                "reasoning": "Fallback to proceed due to parse failure."
            }
            
        return data, response
