import json
from typing import Dict, Any, List
from forgeos.providers.model_router import ProviderRouter, ModelRole

class CTOAgent:
    """
    Sub-Task Delegator (Phase 8): 
    Takes a large, cross-module 'Epic' issue and breaks it down into a highly constrained 
    list of Sub-Tasks that standard ForgeOS instances can solve independently.
    """
    def __init__(self, router: ProviderRouter):
        self.router = router

    def decompose_epic(self, epic_title: str, epic_body: str, repo_map_summary: str, repo_path: str = "") -> Dict[str, Any]:
        """
        Analyzes the epic and returns a JSON structure of sub-tasks.
        Consults the Project Constitution to align sub-tasks with North Star metrics.
        """
        from forgeos.engine.objective_engine import ObjectiveEngine
        objective_engine = ObjectiveEngine(self.router)
        if repo_path:
            objective_engine.load_constitution(repo_path)
            
        constitution_rules = objective_engine.get_context_injection()
        
        sys_prompt = f"""You are the CTO Agent for ForgeOS.
Your job is to read a large 'Epic' feature request and break it down into a sequence of smaller, actionable Sub-Tasks.
Each Sub-Task must be small enough for a single junior developer (Coder Agent) to implement perfectly via an AST-safe, narrow-scoped patch.

{constitution_rules}

RULES:
1. Tasks must be technically explicit. No vague product requirements.
2. Specify the exact files expected to be touched for each task if possible based on the repo map.
3. Order matters. Foundation/Models must be built before API usage.

Respond ONLY with this valid JSON schema:
{
  "epic_summary": "Brief 1-sentence technical sum-up",
  "sub_tasks": [
    {
      "order": 1,
      "title": "Short title",
      "description": "Very specific technical instructions. e.g., 'Add a calculate_discount method to models.py'",
      "expected_files_to_touch": ["path/to/models.py"]
    }
  ]
}"""

        user_prompt = f"=== EPIC REQUEST ===\nTITLE: {epic_title}\n\nBODY:\n{epic_body}\n\n=== REPO ARCHITECTURE ===\n{repo_map_summary}"
        
        response = self.router.generate_response(ModelRole.PLANNER, sys_prompt, user_prompt)
        
        # Parse output safely
        content = response["content"]
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        try:
            plan = json.loads(content)
            return plan, response
        except json.JSONDecodeError as e:
            # Fallback
            return {
                "epic_summary": "Failed to parse JSON",
                "sub_tasks": [
                    {
                        "order": 1, 
                        "title": "Fallback Task", 
                        "description": f"Original Request: {epic_title} - {epic_body}", 
                        "expected_files_to_touch": []
                    }
                ]
            }, response
