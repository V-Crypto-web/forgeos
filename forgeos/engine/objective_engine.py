import json
import os
import yaml
from typing import Dict, Any, Tuple
from forgeos.providers.model_router import ProviderRouter, ModelRole

class ObjectiveEngine:
    """
    Project Constitution & Objective Layer (Epic 62).
    Reads `project_constitution.yaml` from the target repository and ensures all 
    generated plans strictly adhere to the project's North Star, Primary Metrics, 
    and Guardrails. Prevents "local optimizations" that hurt overarching goals.
    """
    def __init__(self, router: ProviderRouter):
        self.router = router
        self.constitution = None
        self.constitution_text = ""

    def load_constitution(self, repo_path: str) -> bool:
        """Attempts to load project_constitution.yaml from the repo root."""
        yaml_path = os.path.join(repo_path, "project_constitution.yaml")
        if not os.path.exists(yaml_path) and "forgeos_workspaces/ForgeAI" in repo_path:
            # Fallback for local testing where repo_path is a tmp dir but we want the real config
            yaml_path = "/Users/vasiliyprachev/Python_Projects/ForgeAI/project_constitution.yaml"
            
        if os.path.exists(yaml_path):
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    self.constitution = yaml.safe_load(f)
                    self.constitution_text = yaml.dump(self.constitution)
                return True
            except Exception as e:
                print(f"[ObjectiveEngine] Failed to parse constitution YAML: {e}")
                return False
        return False

    def get_context_injection(self) -> str:
        """Returns the constitution as a system prompt addition for CTO/Planner."""
        if not self.constitution_text:
            return ""
        
        return f"""
====== PROJECT CONSTITUTION (CRITICAL CONSTRAINTS) ======
Your proposed solutions MUST strictly adhere to these goals:
{self.constitution_text}
=========================================================
"""

    def evaluate_plan(self, plan_text: str, issue_text: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Evaluates a proposed plan against the project constitution.
        Returns: (is_approved, critique_reason, stats)
        """
        if not self.constitution:
            return True, "No constitution found. Proceeding.", {"cost": 0.0}

        sys_prompt = f"""You are the Objective Engine for this repository.
Your task is to review proposed architectural/development plans against the Project Constitution.
If the plan violates 'guardrails', focus heavily on 'deprioritize' areas without strong justification, 
or strays completely from the 'north_star', you MUST REJECT IT.

==== PROJECT CONSTITUTION ====
{self.constitution_text}
==============================

Output ONLY valid JSON:
{{
  "approved": true/false,
  "reason": "Clear explanation of why it aligns with the North Star, or which guardrail it violates."
}}"""
        
        user_prompt = f"Issue: {issue_text}\n\nProposed Plan:\n{plan_text}"
        
        response = self.router.generate_response(ModelRole.CRITIC, sys_prompt, user_prompt)
        content = response["content"]
        
        # Safe JSON parse
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
            
        try:
            result = json.loads(content)
            return result.get("approved", True), result.get("reason", "Parsed, returning default approval."), response
        except Exception as e:
            return True, f"Failed to parse Objective Engine response. Falling back to True. Error: {e}", response
