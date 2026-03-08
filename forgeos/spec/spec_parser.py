import os
from typing import Dict, Any, List

class SpecParser:
    """
    Ingests technical specifications (Markdown) and Architecture Decision Records (ADR).
    Provides structured context to the Planner, enforcing the rule that LLMs are not
    the source of truth.
    """
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        self.spec_dir = os.path.join(self.workspace_path, "docs", "spec")
        self.adr_dir = os.path.join(self.workspace_path, "docs", "adr")
        
    def _read_file_safe(self, filepath: str) -> str:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def get_core_spec_context(self) -> str:
        """Loads the main architectural spec if it exists."""
        # For MVP we just look for a main spec file
        spec_file = os.path.join(self.workspace_path, "README.md")
        return self._read_file_safe(spec_file)

    def get_adrs(self) -> List[str]:
        """Loads all Architectural Decision Records to prevent the Planner from violating them."""
        adrs = []
        if os.path.exists(self.adr_dir):
            for filename in os.listdir(self.adr_dir):
                if filename.endswith(".md"):
                    content = self._read_file_safe(os.path.join(self.adr_dir, filename))
                    adrs.append(content)
        return adrs
        
    def build_planner_context(self, issue_description: str) -> Dict[str, Any]:
        """
        Builds the unified context payload that Planner receives before execution.
        """
        core_spec = self.get_core_spec_context()
        adrs = self.get_adrs()
        
        # Format ADRs into a single string
        adr_context = "\n\n".join([f"--- ADR ---\n{adr}" for adr in adrs])
        
        system_context = f"""
# Source of Truth Context
You are the Planner. You MUST obey the architectural constraints defined below.

## Core Specification
{core_spec[:2000] if core_spec else "No core specification found."}

## Architecture Decision Records (ADRs)
{adr_context if adr_context else "No active ADRs."}
"""
        return {
            "system_context": system_context,
            "issue_description": issue_description,
            "traceability_id": "task_from_issue" # MVP traceability anchor
        }
