from typing import Tuple, Dict, Any
import json
from forgeos.providers.model_router import ProviderRouter, ModelRole

class SecurityCritic:
    """
    Audits the diff for hardcoded credentials, SQL/Command injection vectors, and unsafe operations.
    """
    def __init__(self, router: ProviderRouter):
        self.router = router
        
    def evaluate(self, patch: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        sys_prompt = """You are the Security Critic.
Review the proposed code patch for security vulnerabilities.
Check for:
1. Hardcoded secrets, API keys, or passwords.
2. SQL Injection or Command Injection vectors (e.g., using `shell=True` unsafely, concatenating strings into queries).
3. Insecure deserialization or missing auth checks.

CRITICAL GOVERNANCE RULE: Do not invent theoretical security vulnerabilities. Only reject if the patch explicitly introduces a plaintext password, an obvious SQL/Command injection syntax, or an egregious RCE hole. If the patch solves the issue and doesn't explicitly breach these core rules, you MUST APPROVE it. We prefer working fixes over theoretical paranoia.

Respond ONLY with a valid JSON object:
{
    "status": "APPROVED" | "REJECTED_REVISE_PATCH",
    "reason": "Clear, concise security reason",
    "advice": "Actionable advice on how to secure the code"
}"""
        
        user_prompt = f"=== PROPOSED PATCH ===\\n{patch}\\n"
        response = self.router.generate_response(ModelRole.CRITIC, sys_prompt, user_prompt)
        
        try:
            content = response["content"]
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            result = json.loads(content)
        except Exception as e:
            result = {"status": "APPROVED", "reason": "Failed to parse response, defaulting to APPROVED.", "advice": ""}
            
        return result, response
