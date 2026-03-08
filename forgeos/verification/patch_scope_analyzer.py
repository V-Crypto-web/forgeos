import re
from typing import List, Dict
from pydantic import BaseModel
from enum import Enum

class PatchScopeClass(Enum):
    NARROW_LOCAL = "narrow_local_patch"
    MEDIUM = "medium_patch"
    WIDE = "wide_patch"
    CROSS_BOUNDARY = "cross_boundary_patch"

class PatchBudget(BaseModel):
    max_files: int
    max_loc_delta: int
    allowed_scope: List[PatchScopeClass]

class ScopeAnalysisResult(BaseModel):
    total_files_changed: int
    total_loc_added: int
    total_loc_removed: int
    net_loc_delta: int
    files_touched: List[str]
    scope_class: PatchScopeClass
    structural_warnings: List[str]
    is_rejected: bool = False
    rejection_reason: str = ""

class ScopeAnalyzer:
    """
    Deterministically analyzes a unified diff patch to calculate its physical 
    width and structural impact surface without relying on LLMs.
    """
    def __init__(self, workspace_path: str = ""):
        self.workspace_path = workspace_path
        
    def _parse_diff_stats(self, patch: str) -> Dict:
        files_touched = set()
        loc_added = 0
        loc_removed = 0
        
        for line in patch.split('\n'):
            if line.startswith('--- a/') or line.startswith('+++ b/'):
                filename = line[6:].strip()
                if filename:
                    files_touched.add(filename)
            elif line.startswith('+') and not line.startswith('+++'):
                loc_added += 1
            elif line.startswith('-') and not line.startswith('---'):
                loc_removed += 1
                
        return {
            "files": list(files_touched),
            "added": loc_added,
            "removed": loc_removed,
            "delta": loc_added + loc_removed
        }
        
    def _detect_structural_shifts(self, patch: str) -> List[str]:
        warnings = []
        # Fast regex heuristics for structural surface shifts
        if re.search(r'^\+import ', patch, re.MULTILINE) or re.search(r'^\+from .* import ', patch, re.MULTILINE):
            warnings.append("Import Surface Check: Patch introduces new dependencies.")
            
        if re.search(r'^\+ *def [a-zA-Z0-9_]+\(', patch, re.MULTILINE):
            warnings.append("Signature Check: Patch introduces new functions/methods.")
            
        if re.search(r'^\+ *async def', patch, re.MULTILINE):
            warnings.append("Async Boundary Check: Patch introduces new async coroutines.")
            
        if re.search(r'^\+ *class [a-zA-Z0-9_]+', patch, re.MULTILINE):
            warnings.append("Signature Check: Patch introduces new classes.")
            
        return warnings

    def _classify_scope(self, stats: Dict, warnings: List[str]) -> PatchScopeClass:
        num_files = len(stats["files"])
        delta = stats["delta"]
        
        # High risk structural changes elevate the scope
        structural_penalty = len(warnings) > 0
        
        if num_files >= 4 or delta >= 150:
            return PatchScopeClass.CROSS_BOUNDARY
        elif num_files > 2 or delta >= 60 or (num_files > 1 and structural_penalty):
            return PatchScopeClass.WIDE
        elif num_files == 2 or delta > 20 or structural_penalty:
            return PatchScopeClass.MEDIUM
        else:
            return PatchScopeClass.NARROW_LOCAL

    def evaluate_patch(self, patch: str, risk_profile: str = "low") -> ScopeAnalysisResult:
        if not patch:
            return ScopeAnalysisResult(
                total_files_changed=0, total_loc_added=0, total_loc_removed=0, net_loc_delta=0,
                files_touched=[], scope_class=PatchScopeClass.NARROW_LOCAL, structural_warnings=[]
            )
            
        stats = self._parse_diff_stats(patch)
        warnings = self._detect_structural_shifts(patch)
        scope_class = self._classify_scope(stats, warnings)
        
        # Define budgets based on dynamic risk profiling
        if risk_profile == "low":
            budget = PatchBudget(max_files=2, max_loc_delta=50, allowed_scope=[PatchScopeClass.NARROW_LOCAL, PatchScopeClass.MEDIUM])
        elif risk_profile == "medium":
            budget = PatchBudget(max_files=4, max_loc_delta=120, allowed_scope=[PatchScopeClass.NARROW_LOCAL, PatchScopeClass.MEDIUM, PatchScopeClass.WIDE])
        else:
            budget = PatchBudget(max_files=10, max_loc_delta=500, allowed_scope=[s for s in PatchScopeClass])
            
        is_rejected = False
        rejection_reason = ""
        
        if scope_class not in budget.allowed_scope:
            is_rejected = True
            rejection_reason = f"Patch scope ({scope_class.value}) exceeds allowed budget for {risk_profile} risk. Allowed: {[s.value for s in budget.allowed_scope]}."
        elif len(stats["files"]) > budget.max_files:
            is_rejected = True
            rejection_reason = f"Patch touches {len(stats['files'])} files, exceeding the {risk_profile} risk budget of {budget.max_files}."
        elif stats["delta"] > budget.max_loc_delta:
            is_rejected = True
            rejection_reason = f"Patch total LOC delta ({stats['delta']}) exceeds the {risk_profile} risk budget of {budget.max_loc_delta}."
            
        return ScopeAnalysisResult(
            total_files_changed=len(stats["files"]),
            total_loc_added=stats["added"],
            total_loc_removed=stats["removed"],
            net_loc_delta=stats["delta"],
            files_touched=stats["files"],
            scope_class=scope_class,
            structural_warnings=warnings,
            is_rejected=is_rejected,
            rejection_reason=rejection_reason
        )
