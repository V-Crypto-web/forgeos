from typing import List, Dict, Any

class ImpactEngine:
    """
    Analyzes the proposed code changes (plan/patch) against the Repo Map to calculate
    the Impact Radius and Risk Score before execution.
    """
    def __init__(self, repo_map: Dict[str, Dict[str, Any]]):
        self.repo_map = repo_map
        
    def analyze_impact(self, touched_files: List[str]) -> Dict[str, Any]:
        """
        Calculates a simple MVP risk score based on the number and nature of touched files.
        """
        risk_score = "low"
        critical_keywords = ["migration", "secret", "billing"]
        high_keywords = ["auth", "config", "core"]
        
        # 1. Check file count
        if len(touched_files) >= 5:
            risk_score = "high"
        elif len(touched_files) >= 2:
            risk_score = "medium"
            
        # 2. Check path keywords for domain risk
        for file in touched_files:
            file_lower = file.lower()
            if any(k in file_lower for k in critical_keywords):
                risk_score = "critical"
                break
            elif any(k in file_lower for k in high_keywords):
                if risk_score not in ["critical"]:
                    risk_score = "high"
                    
        # 3. Determine Verification Scope and Allowed Strategy
        verification_scope = "unit_tests"
        allowed_strategy = "local_patch"
        
        if risk_score == "medium":
            verification_scope = "integration_tests"
        elif risk_score == "high":
            verification_scope = "full_regression"
            allowed_strategy = "no_rewrite"
        elif risk_score == "critical":
            verification_scope = "full_regression + manual_e2e"
            allowed_strategy = "human_approval_required"
            
        return {
            "touched_files": touched_files,
            "impact_radius": len(touched_files),
            "risk_score": risk_score,
            "verification_scope": verification_scope,
            "allowed_strategy": allowed_strategy
        }
