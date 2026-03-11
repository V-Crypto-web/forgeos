import json
import os
from typing import Dict, Any, List
# Using a rough character-to-token heuristic for MVP to avoid tiktoken dependency everywhere
CHARS_PER_TOKEN = 4

class TokenBudget:
    PLANNER_MAX = 8000
    CODER_MAX = 16000   # increased: large files need full context for accurate hunks
    RETRY_MAX = 12000

class ContextPackBuilder:
    """
    Builds context packs (L1/L2/L3) to compress prompt size, adhering to token budget policies.
    """
    def __init__(self, execution_context: Any, repo_analyzer: Any):
        self.ctx = execution_context
        self.analyzer = repo_analyzer
        self.cache_dir = self._get_cache_dir()

    def _get_cache_dir(self) -> str:
        branch, commit = self.analyzer.get_git_info()
        return os.path.join(self.analyzer.repo_path, ".forgeos", "cache", branch, commit)

    def _estimate_tokens(self, text: str) -> int:
        return len(text) // CHARS_PER_TOKEN

    def _load_json_artifact(self, filename: str) -> Dict[str, Any]:
        path = os.path.join(self.cache_dir, filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def get_compressed_failure_memory(self, max_failures: int = 3) -> str:
        """Compresses failure memory by taking only the most recent N deduplicated errors."""
        if not self.ctx.failure_memory or not self.ctx.failure_memory.failures:
            return "No previous failures."
            
        # Get last N failures based on attempt counts (simple heuristic for MVP)
        # In a real app we'd track a chronological log of failures in FailureMemory
        failures = []
        for sig, data in self.ctx.failure_memory.failures.items():
            failures.append(f"- Strategy '{data['strategy']}' failed {data['attempts']} times with signature: {sig}")
            
        # Sort by attempts descending and take top N
        failures.sort(key=lambda x: int(x.split(' failed ')[1].split(' times')[0]), reverse=True)
        compressed = failures[:max_failures]
        return "\\n".join(compressed)

    def get_compressed_plan_history(self) -> str:
        """Returns the current plan delta or summary, rather than the entire massive history."""
        if not self.ctx.plan:
            return "No previous plan."
        
        # In a full system we'd summarize the plan here. For MVP we truncate.
        plan_str = self.ctx.plan
        estimated_tokens = self._estimate_tokens(plan_str)
        if estimated_tokens > 500:
            return plan_str[:500 * CHARS_PER_TOKEN] + "\\n... (Plan truncated to fit budget)"
        return plan_str

    def _prune_repo_map(self, max_files: int = 50) -> str:
        """
        AI Context Pruning (Epic 28).
        Reads the full AST repo_map.json and heuristically filters it down 
        to the top `max_files` based on keyword matches with the issue text.
        """
        repo_map = self._load_json_artifact("repo_map.json")
        if not repo_map:
            return self.analyzer.get_repo_map_summary(max_length=15000)
            
        # Extract keywords (simple heuristic)
        issue_text = self.ctx.issue_text.lower()
        keywords = [w for w in issue_text.replace("_", " ").split() if len(w) > 3]
        
        file_scores = []
        for filepath, data in repo_map.items():
            score = 0
            # 1. Match on filename
            if any(kw in filepath.lower() for kw in keywords):
                score += 10
            # 2. Match on classes
            for c in data.get("classes", []):
                c_name = c.get("name").lower() if isinstance(c, dict) else c.lower()
                if any(kw in c_name for kw in keywords):
                    score += 5
            # 3. Match on functions
            for f in data.get("functions", []):
                f_name = f.get("name").lower() if isinstance(f, dict) else f.lower()
                if any(kw in f_name for kw in keywords):
                    score += 3
                    
            # Bonus for core files
            if filepath.endswith("main.py") or filepath.endswith("app.py") or filepath.endswith("models.py") or filepath.endswith("__init__.py"):
                score += 5
                
            file_scores.append((score, filepath, data))
            
        # Sort by score descending and take top N
        file_scores.sort(key=lambda x: x[0], reverse=True)
        top_files = file_scores[:max_files]
        
        # Reconstruct pruned map text
        lines = []
        lines.append(f"--- PRUNED REPO MAP (Showing top {len(top_files)} of {len(repo_map)} files) ---")
        for score, filepath, data in top_files:
            lines.append(f"\\nFile: {filepath} (Relevance Score: {score})")
            if data.get("classes"):
                c_names = [c.get("name") if isinstance(c, dict) else c for c in data["classes"]]
                lines.append("  Classes: " + ", ".join(c_names))
            if data.get("functions"):
                f_names = [f.get("name") if isinstance(f, dict) else f for f in data["functions"]]
                lines.append("  Functions: " + ", ".join(f_names))
                
        return "\\n".join(lines)

    def build_planner_prompt(self) -> str:
        """
        Builds a hierarchical prompt, dropping L3 or L2 if it exceeds PLANNER_MAX.
        """
        # L1: Critical Context
        # Issue, ACs, touched files (if any), last failure, risk score (if any), dynamic docs
        touched = self.ctx.patch if self.ctx.patch else "None yet"
        
        from forgeos.engine.retriever import DocRetriever
        doc_retriever = DocRetriever()
        external_docs = doc_retriever.retrieve_context(self.ctx.issue_text)
        
        pattern_str = "No historical patterns found."
        if hasattr(self.ctx, 'pattern_context') and self.ctx.pattern_context:
            if self.ctx.pattern_context.get("similar_patterns_found", 0) > 0:
                p_ctx = self.ctx.pattern_context
                rec = ", ".join(p_ctx.get("recommended_strategies", []))
                avoid = ", ".join(p_ctx.get("avoid_strategies", []))
                test_scope = ", ".join(p_ctx.get("recommended_test_scopes", []))
                notes = "\n  - ".join(p_ctx.get("historical_notes", []))
                
                pattern_str = f"ADVISORY GUIDANCE FROM PRIOR RUNS:\n"
                pattern_str += f"- RECOMMENDED STRATEGIES: {rec if rec else 'None'}\n"
                pattern_str += f"- STRATEGIES TO AVOID: {avoid if avoid else 'None'}\n"
                pattern_str += f"- RECOMMENDED TEST SCOPE: {test_scope if test_scope else 'Unknown'}\n"
                if notes:
                    pattern_str += f"- RISK NOTES / OBSERVATIONS:\n  - {notes}"
            else:
                pattern_str = "No historical patterns matched. Proceed with standard planning."

        l1_context = f"""=== [L0] SCOPE CONSTRAINTS (PATCH BUDGET) ===
You are bounded by strict Execution Limits to prevent Scope Explosion.
Your Plan MUST fit within the following Patch Budget:
- MAX FILES TOUCHED: 2 (for low risk), 4 (for medium risk)
- MAX LOC ADDED/REMOVED: 50 (for low risk), 120 (for medium risk)
- DO NOT introduce unprotected structural breaks (e.g., converting sync functions to async, breaking public signatures) unless absolutely required.

=== [L1] CRITICAL CONTEXT ===
ISSUE:
{self.ctx.issue_text}

{external_docs}
SPEC/ADR RULES:
{self.ctx.spec_context}

ENGINEERING HISTORY (PATTERN LIBRARY):
{pattern_str}

RECENT FAILURES:
{self.get_compressed_failure_memory()}
"""
        # L2: Supporting Context
        # Relevant symbols, touched file dependencies, previous plan
        symbol_index = self._load_json_artifact("symbol_index.json")
        symbol_definitions = self._load_json_artifact("symbol_definitions.json")
        repo_map = self._load_json_artifact("repo_map.json")
        symbol_graph = self._load_json_artifact("symbol_graph.json")
        
        l2_text_components = []
        l2_text_components.append(f"PREVIOUS PLAN:\n{self.get_compressed_plan_history()}")
        
        # Simple extraction of keywords from issue text to find relevant symbols
        issue_keywords = set([w.lower() for w in self.ctx.issue_text.split() if len(w) > 4])
        relevant_symbols = []
        
        if symbol_index:
            hit_symbol_graph = False
            for file_path, symbols in symbol_index.get("files", {}).items():
                for sym_name, sym_type in symbols.items():
                    if any(kw in sym_name.lower() or kw in file_path.lower() for kw in issue_keywords):
                        snippet = ""
                        if symbol_definitions:
                            sym_def = symbol_definitions.get("files", {}).get(file_path, {}).get(sym_name, {})
                            snippet = sym_def.get("snippet", "")
                        
                        graph_info = ""
                        if symbol_graph and sym_type == "function" and sym_name in symbol_graph:
                            node = symbol_graph[sym_name]
                            callers = node.get("callers", [])
                            callees = node.get("callees", [])
                            imports = node.get("imports", [])
                            graph_info = f"\n  - Callers: {', '.join(callers) if callers else 'None'}\n  - Callees: {', '.join(callees) if callees else 'None'}\n  - File Imports: {', '.join(imports) if imports else 'None'}"
                            hit_symbol_graph = True

                        if snippet:
                            # Truncate massive classes/functions to ~40 lines to preserve token budget
                            # Allows the planner to see the __init__ and signatures, but not the whole body
                            lines = snippet.split('\n')
                            if len(lines) > 40:
                                snippet = '\n'.join(lines[:40]) + '\n    # ... (body truncated to save context window)'
                            relevant_symbols.append(f"### {sym_type.upper()}: {sym_name} (in {file_path}){graph_info}\n```python\n{snippet}\n```")
                        else:
                            relevant_symbols.append(f"- {sym_type} {sym_name} in {file_path}{graph_info}")
                            
            if hit_symbol_graph and self.ctx.telemetry:
                # Assuming TelemetryLogger has log_symbol_graph_hit
                if hasattr(self.ctx.telemetry, 'log_symbol_graph_hit'):
                    self.ctx.telemetry.log_symbol_graph_hit(self.ctx.issue_number, self.ctx.current_state.value, len(relevant_symbols))
                        
        if relevant_symbols:
            # Take top 15 relevant symbols to avoid blowing budget (was 20, but now they are much larger blocks)
            sym_text = "\n\n".join(relevant_symbols[:15])
            l2_text_components.append(f"RELEVANT SYMBOL DEFINITIONS:\n{sym_text}")
        elif repo_map:
            # Fallback to general repo map summary if no symbols matched
            l2_text_components.append(f"REPO MAP SUMMARY:\n{str(repo_map)[:1000]}")
            
        l2_content = "\n\n".join(l2_text_components)
        
        l2_context = f"""

=== [L2] SUPPORTING CONTEXT ===
{l2_content}
"""
        # L3: Deep Context
        # Full Repo Map Excerpt (Pruned to Top 50)
        pruned_map = self._prune_repo_map(max_files=50)
        l3_context = f"""

=== [L3] REPOSITORY MAP (PRUNED) ===
{pruned_map}
"""
        
        # Assemble with budget
        total_prompt = l1_context
        
        # Try to fit everything (L1 + L2 + L3)
        if self._estimate_tokens(total_prompt + l2_context + l3_context) < TokenBudget.PLANNER_MAX:
            total_prompt += l2_context + l3_context
            return total_prompt
            
        # Try to fit L1 + L2
        if self._estimate_tokens(total_prompt + l2_context) < TokenBudget.PLANNER_MAX:
            total_prompt += l2_context
            total_prompt += "\n[L3 Deep Context dropped due to token budget limits.]"
            return total_prompt
            
        # Try to fit L1 + Trimmed L2
        trimmed_l2 = l2_context[:(TokenBudget.PLANNER_MAX - self._estimate_tokens(total_prompt)) * CHARS_PER_TOKEN]
        if self._estimate_tokens(total_prompt + trimmed_l2) <= TokenBudget.PLANNER_MAX:
            total_prompt += trimmed_l2
            total_prompt += "\n[L2 Context truncated and L3 dropped due to severe token budget limits.]"
            return total_prompt
            
        # Fallback to L1 only
        total_prompt += "\n[L2 and L3 Context completely dropped due to extreme token budget limits.]"
        return total_prompt

    def build_coder_prompt(self) -> str:
        """
        Builds a hierarchical prompt for the coder.
        Injects actual file content for relevant files so the LLM can generate
        line-accurate diffs instead of hallucinating line numbers.
        """
        # Extract relevant file paths from plan + issue text
        import re, glob
        plan_text = self.ctx.plan or ""
        issue_text = self.ctx.issue_text or ""
        combined_text = plan_text + "\n" + issue_text
        repo_root = self.ctx.repo_path if self.ctx.repo_path else "."

        relevant_files = []

        # Strategy 1: find full relative paths like `forgeos/engine/state_machine.py`
        for path in re.findall(r'[\w/]+\.py', combined_text):
            full_path = os.path.join(repo_root, path)
            if os.path.exists(full_path):
                relevant_files.append((path, full_path))

        # Strategy 2: find bare module names like `state_machine`, `policies`, etc.
        # and resolve them by searching the repo with glob
        bare_names = re.findall(r'\b([a-z][a-z_]+)\b', combined_text)
        seen_names = set()
        for name in bare_names:
            if name in seen_names or len(name) < 5:
                continue
            seen_names.add(name)
            matches = glob.glob(os.path.join(repo_root, "**", f"{name}.py"), recursive=True)
            for m in matches[:1]:  # take first match only
                rel = os.path.relpath(m, repo_root)
                if (rel, m) not in relevant_files:
                    relevant_files.append((rel, m))

        # Deduplicate and limit
        seen_paths = set()
        deduped = []
        for item in relevant_files:
            if item[1] not in seen_paths:
                seen_paths.add(item[1])
                deduped.append(item)
        relevant_files = deduped[:4]  # Max 4 files to stay within token budget

        # Build file content block with FULL content (up to 400 lines) for accurate diffs
        file_content_block = ""
        for rel_path, full_path in relevant_files:
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
                    # Up to 400 lines — enough for any realistic target file
                    lines_list = content.split("\n")
                    lines = lines_list[:400]
                    # Add line numbers so the LLM can write precise @@ hunk headers
                    numbered = [f"{i+1:4d}: {l}" for i, l in enumerate(lines)]
                    content_preview = "\n".join(numbered)
                    if len(lines_list) > 400:
                        content_preview += f"\n# ... ({len(lines_list) - 400} more lines not shown)"
                file_content_block += f"\n### FILE: {rel_path}\n```python\n{content_preview}\n```\n"
            except Exception:
                pass

        l1_context = f"""=== [L0] SCOPE CONSTRAINTS (PATCH BUDGET) ===
You are bounded by strict Execution Limits to prevent Scope Explosion.
Write a `narrow_local_patch` that strictly targets the issue without breaking architectural boundaries.
- MAX FILES TOUCHED: 2 (for low risk), 4 (for medium risk)
- MAX LOC DELTA: 50 (for low risk), 120 (for medium risk)
IF you exceed these execution limits or touch irrelevant files, your patch will be FORCEFULLY REJECTED by the internal AST Gate before tests even run.

=== [L1] CRITICAL CONTEXT ===
PLAN:
{self.ctx.plan}

RECENT FAILURES:
{self.get_compressed_failure_memory()}
"""
        l2_context = f"""
=== [L2] ACTUAL FILE CONTENT (Use these EXACT line numbers in your diff) ===
CRITICAL: The line numbers shown below (e.g. `  12: `) are for your reference ONLY to build `@@ -X,Y +A,B @@` hunks. NEVER INCLUDE THEM IN YOUR ACTUAL OUTPUT PATCH!

ISSUE REF:
{self.ctx.issue_text[:200]}...

{file_content_block if file_content_block else "No file content available — use repo map for guidance."}
"""
        
        pruned_map = self._prune_repo_map(max_files=50)
        l3_context = f"""
=== [L3] REPOSITORY MAP (PRUNED) ===
{pruned_map}
"""

        total_prompt = l1_context
        
        # Try to fit everything (L1 + L2 + L3)
        if self._estimate_tokens(total_prompt + l2_context + l3_context) < TokenBudget.CODER_MAX:
            total_prompt += l2_context + l3_context
            return total_prompt
            
        # Try to fit L1 + L2
        if self._estimate_tokens(total_prompt + l2_context) < TokenBudget.CODER_MAX:
            total_prompt += l2_context
            total_prompt += "\n[L3 Deep Context dropped due to token budget limits.]"
            return total_prompt
            
        # Try to fit L1 + Trimmed L2
        trimmed_l2 = l2_context[:(TokenBudget.CODER_MAX - self._estimate_tokens(total_prompt)) * CHARS_PER_TOKEN]
        if self._estimate_tokens(total_prompt + trimmed_l2) <= TokenBudget.CODER_MAX:
            total_prompt += trimmed_l2
            total_prompt += "\n[L2 Context truncated and L3 dropped due to severe token budget limits.]"
            return total_prompt
            
        # Fallback to L1 only
        total_prompt += "\n[L2 and L3 Context completely dropped due to extreme token budget limits.]"
        return total_prompt
