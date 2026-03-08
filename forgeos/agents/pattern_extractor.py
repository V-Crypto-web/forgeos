import json
from typing import Dict, Any, Tuple
from forgeos.providers.model_router import ProviderRouter, ModelRole
from forgeos.memory.pattern_library import PatternRecord

class PatternExtractorAgent:
    """
    Analyzes the complete execution cycle of an issue and distills the engineering process 
    (success or failure) into a normalized Experience Pattern for future retrieval.
    """
    def __init__(self, router: ProviderRouter):
        self.router = router

    def extract_pattern(self, issue_text: str, patch: str, test_output: str, strategy: str, outcome: str) -> Tuple[PatternRecord, Dict[str, Any]]:
        sys_prompt = """You are the Experience Memory Extractor.
A software engineering agent has just completed an execution cycle.
Analyze the issue, the attempted patch strategy, and the test/compilation results.
Distill this into a normalized Engineering Pattern.

Categorize heuristically:
- repo_class (e.g., "python_backend", "http_client", "cli_tool", "data_pipeline")
- issue_class (e.g., "tiny_bugfix", "async_coroutine_bug", "timeout_regression", "type_error")
- failure_signature (the core error that either caused the bug OR caused the patch to fail, e.g., "missing_await", "none_type_attribute". If success, put "resolved")
- test_scope (e.g., "unit_tests", "async_integration", "full_suite")
- patch_width (e.g., "narrow_local", "broad_refactor")

Respond ONLY with this JSON schema:
{
    "repo_class": "string",
    "issue_class": "string",
    "failure_signature": "string",
    "test_scope": "string",
    "patch_width": "string",
    "description": "A 1-sentence summary of the pattern learned."
}"""

        user_prompt = f"=== ISSUE ===\n{issue_text[:2000]}\n\n=== RECENT PATCH ===\n{patch[:3000]}\n\n=== TEST / VERIFICATION OUTPUT ===\n{test_output[:2000]}\n\nSTRATEGY USED: {strategy}\nOUTCOME: {outcome}"
        
        response = self.router.generate_response(ModelRole.CRITIC, sys_prompt, user_prompt)
        
        try:
            content = response["content"]
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            data = json.loads(content)
            
            # Construct a safe ID
            sig_safe = str(data.get("failure_signature", "unknown")).replace(" ", "_").lower()
            pattern_id = f"{data.get('issue_class', 'gen')}_{sig_safe}"
            
            record = PatternRecord(
                pattern_id=pattern_id[:30],
                repo_class=data.get("repo_class", "unknown"),
                issue_class=data.get("issue_class", "unknown"),
                failure_signature=str(data.get("failure_signature", "unknown"))[:50],
                strategy=strategy,
                test_scope=data.get("test_scope", "unknown"),
                patch_width=data.get("patch_width", "unknown"),
                outcome=outcome,
                description=data.get("description", "")
            )
            
            # Generate embedding for Canonicalization and Semantic Retrieval
            # We embed a combination of the core issue and the failure signature (the essence of the pattern)
            embedding_text = f"Issue: {data.get('issue_class', '')} {issue_text[:500]} Failure: {data.get('failure_signature', '')}"
            record.embedding = self.router.get_embedding(embedding_text)
            
        except Exception as e:
            # Fallback naive record
            record = PatternRecord(
                pattern_id="fallback_pattern",
                repo_class="unknown",
                issue_class="unknown",
                failure_signature="unknown",
                strategy=strategy,
                test_scope="unknown",
                patch_width="unknown",
                outcome=outcome,
                description="Failed to parse LLM extraction."
            )
            
        return record, response
