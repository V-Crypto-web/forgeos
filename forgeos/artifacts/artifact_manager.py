import os
import json
from typing import Dict, Any

class ArtifactManager:
    """
    Module 8: Artifact Layer implementation.
    Responsible for persisting execution artifacts (plans, patches, impact reports)
    both locally and optionally pushing them alongside PRs for full audit trails.
    """
    def __init__(self, workspace_path: str, issue_number: int):
        self.workspace_path = workspace_path
        self.issue_number = issue_number
        self.artifacts_dir = os.path.join(self.workspace_path, ".forgeos", "artifacts", f"issue_{issue_number}")
        
        # Ensure directory exists
        os.makedirs(self.artifacts_dir, exist_ok=True)
        
    def save_plan(self, plan_content: str) -> str:
        """Saves the generated execution plan."""
        os.makedirs(self.artifacts_dir, exist_ok=True)
        filepath = os.path.join(self.artifacts_dir, "plan.md")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(plan_content)
        return filepath
        
    def save_patch(self, patch_content: str, attempt: int = 1) -> str:
        """Saves the generated patch. Supports multiple attempts."""
        os.makedirs(self.artifacts_dir, exist_ok=True)
        filepath = os.path.join(self.artifacts_dir, f"patch_attempt_{attempt}.diff")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(patch_content)
        return filepath
        
    def save_impact_report(self, impact_data: Dict[str, Any]) -> str:
        """Saves the Change Impact Engine analysis report."""
        os.makedirs(self.artifacts_dir, exist_ok=True)
        filepath = os.path.join(self.artifacts_dir, "impact_report.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(impact_data, f, indent=2)
        return filepath

    def load_impact_report(self) -> Dict[str, Any]:
        """Loads the saved impact report if it exists."""
        filepath = os.path.join(self.artifacts_dir, "impact_report.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_test_results(self, test_data: Dict[str, Any], attempt: int = 1) -> str:
        """Saves the results from the sandbox execution."""
        os.makedirs(self.artifacts_dir, exist_ok=True)
        filepath = os.path.join(self.artifacts_dir, f"test_results_{attempt}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(test_data, f, indent=2)
        return filepath
