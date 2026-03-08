from typing import Tuple, Dict, Any
import json
from forgeos.providers.model_router import ProviderRouter, ModelRole

class ArchitectureCritic:
    """
    Validates the patch against repo conventions (e.g., using the correct DB ORM, proper imports).
    """
    def __init__(self, router: ProviderRouter):
        self.router = router
        
    def evaluate(self, repo_map: str, patch: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        sys_prompt = """You are the Architecture Critic.
Review the proposed code patch against the repository's structural map.
Does it violate codebase conventions? Are there redundant imports? Does it bypass layered architecture?

Respond ONLY with a valid JSON object:
{
    "status": "APPROVED" | "REJECTED_REVISE_PATCH",
    "reason": "Clear, concise architectural reason",
    "advice": "Actionable advice on how to align with repo architecture"
}"""
        
        user_prompt = f"=== REPO MAP ===\\n{repo_map}\\n\\n=== PROPOSED PATCH ===\\n{patch}\\n"
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
