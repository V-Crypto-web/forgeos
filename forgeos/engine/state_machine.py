from enum import Enum
from typing import Dict, Any, Optional
from pydantic import BaseModel
import os

class EngineState(str, Enum):
    INIT = "INIT"
    FETCH_ISSUE = "FETCH_ISSUE"
    PATTERN_RETRIEVAL = "PATTERN_RETRIEVAL"
    PLAN = "PLAN"
    BRANCH_RACE = "BRANCH_RACE"
    IMPACT_ANALYSIS = "IMPACT_ANALYSIS"
    PATCH = "PATCH"
    PATCH_WIDTH_REJECT = "PATCH_WIDTH_REJECT"
    EXECUTION_CRITIC = "EXECUTION_CRITIC"
    PATCH_SIMULATION = "PATCH_SIMULATION"
    RUN_TESTS = "RUN_TESTS"
    VERIFY = "VERIFY"
    RETRY = "RETRY"
    CREATE_PR = "CREATE_PR"
    POLL_CI = "POLL_CI"
    DONE = "DONE"
    FAILED = "FAILED"

class ExecutionContext(BaseModel):
    issue_number: Optional[int] = None
    parent_epic_id: Optional[int] = None
    repo_path: Optional[str] = None
    github_url: Optional[str] = None   # GitHub repo URL for issue fetch + PR creation
    plan: Optional[str] = None
    patch: Optional[str] = None
    test_results: Optional[Dict[str, Any]] = None
    logs: list[str] = []
    current_state: EngineState = EngineState.INIT
    strategy: str = "patch"
    retries: int = 0
    failure_memory: Optional[Any] = None  # To hold a reference to the FailureMemory instance
    run_ledger: Optional[Any] = None # To hold a reference to RunLedger
    artifact_manager: Optional[Any] = None # To hold a reference to ArtifactManager
    telemetry: Optional[Any] = None # To hold a reference to TelemetryLogger
    issue_text: str = ""
    spec_context: str = ""
    traceability_id: str = ""
    pattern_context: Optional[Dict[str, Any]] = None
    patch_scope_context: Optional[Dict[str, Any]] = None
    simulation_context: Optional[Dict[str, Any]] = None
    global_cost: float = 0.0
    failure_record: Optional[Dict[str, Any]] = None
    racing_enabled: bool = False           # Opt-in: enables Branch Racing
    branch_results: Optional[list] = None  # Saved race results for Mission Control

MAX_COST_PER_ISSUE = 1.00 # Max budget per run in dollars

class StateMachine:
    """
    Core Execution State Machine for ForgeOS MVP.
    Moves the execution context linearly through the defined states.
    For MVP, we use a simple linear progression with early escapes for FAILED states.
    """
    def __init__(self):
        # We will dispatch to handlers based on the state.
        self.handlers = {
            EngineState.INIT: self.handle_init,
            EngineState.FETCH_ISSUE: self.handle_fetch_issue,
            EngineState.PATTERN_RETRIEVAL: self.handle_pattern_retrieval,
            EngineState.PLAN: self.handle_plan,
            EngineState.BRANCH_RACE: self.handle_branch_race,
            EngineState.IMPACT_ANALYSIS: self.handle_impact_analysis,
            EngineState.PATCH: self.handle_patch,
            EngineState.PATCH_WIDTH_REJECT: self.handle_patch_width_reject,
            EngineState.EXECUTION_CRITIC: self.handle_execution_critic,
            EngineState.PATCH_SIMULATION: self.handle_patch_simulation,
            EngineState.RUN_TESTS: self.handle_run_tests,
            EngineState.VERIFY: self.handle_verify,
            EngineState.RETRY: self.handle_retry,
            EngineState.CREATE_PR: self.handle_create_pr,
            EngineState.POLL_CI: self.handle_poll_ci,
            EngineState.DONE: self.handle_done,
        }

    def run(self, context: ExecutionContext) -> ExecutionContext:
        """Execute the state machine until DONE or FAILED."""
        try:
            while context.current_state not in [EngineState.DONE, EngineState.FAILED]:
                handler = self.handlers.get(context.current_state)
                if not handler:
                    context.logs.append(f"No handler found for state: {context.current_state}")
                    self.mark_progress(context, context.current_state.value, EngineState.FAILED.value)
                    context.current_state = EngineState.FAILED
                    break
                
                prev_state = context.current_state.value
                context.logs.append(f"Entering state: {prev_state}")
                try:
                    # Transition to the next state
                    context = handler(context)
                    new_state = context.current_state.value
                    
                    if prev_state != new_state:
                        self.mark_progress(context, prev_state, new_state)
                    
                    # Enforce Hard Cap
                    if context.global_cost >= MAX_COST_PER_ISSUE:
                        context.logs.append(f"CRITICAL WARNING: Max budget exceeded (${context.global_cost:.4f} / ${MAX_COST_PER_ISSUE:.4f}). Halting to prevent runaway costs.")
                        self.mark_progress(context, context.current_state.value, EngineState.FAILED.value)
                        context.current_state = EngineState.FAILED
                        # To let upstream know why it failed
                        context.test_results = {"status": "failed", "errors": "Max budget exceeded. Execution forcefully halted.", "command": "Engine Governor"}
                        
                except Exception as e:
                    import traceback
                    context.logs.append(f"Error in state {context.current_state.value}: {str(e)}\n{traceback.format_exc()}")
                    self.mark_progress(context, context.current_state.value, EngineState.FAILED.value)
                    context.current_state = EngineState.FAILED
                    
            context.logs.append(f"Execution finished with state: {context.current_state.value}")
            if context.telemetry:
                context.telemetry.log_event("execution_finished", context.issue_number, context.current_state.value, f"Engine finished with state {context.current_state.value}")
                
            if context.current_state == EngineState.FAILED:
                try:
                    from forgeos.memory.failure_miner import FailureIntelligenceEngine
                    miner = FailureIntelligenceEngine()
                    miner.mine_failure(context)
                except Exception as e:
                    context.logs.append(f"[FailureMiner] Hook crashed: {e}")
                    
        except Exception as outer_e:
            context.logs.append(f"CRITICAL ENGINE FAULT: {outer_e}")
            if context.current_state not in [EngineState.DONE, EngineState.FAILED]:
                self.mark_progress(context, context.current_state.value, EngineState.FAILED.value)
                context.current_state = EngineState.FAILED
        finally:
            # The Ultimate Safeguard — Ensure terminal transitions are broadcasted even on thread death
            if context.current_state not in [EngineState.DONE, EngineState.FAILED]:
                context.logs.append("WARNING: Engine loop exited but state is not DONE or FAILED. Forcing FAILED.")
                self.mark_progress(context, context.current_state.value, "FAILED_ORPHANED")
                context.current_state = EngineState.FAILED
                
        return context

    # --- Handlers (Mocks for now, delegates to actual modules later) ---
    
    def touch_heartbeat(self, context: ExecutionContext, message: str = "Heartbeat"):
        """Emits a task_heartbeat event to update the API gateway's last seen time."""
        if context.telemetry:
            context.telemetry.log_event("task_heartbeat", context.issue_number or "task", context.current_state.value, message)

    def mark_progress(self, context: ExecutionContext, from_state: str, to_state: str):
        """Emits a specialized task_progress event signifying forward motion."""
        if context.telemetry:
            context.telemetry.log_event("task_progress", context.issue_number or "task", to_state, f"Progressed from {from_state} to {to_state}")
    
    def log_and_record(self, context: ExecutionContext, message: str, event_type: str = "state_transition", metadata: Dict[str, Any] = None):
        """Helper to append to local memory array and write to structured telemetry."""
        context.logs.append(message)
        if context.telemetry:
            context.telemetry.log_event(event_type, context.issue_number, context.current_state.value, message, metadata, parent_epic_id=context.parent_epic_id)
        if context.run_ledger:
            payload = {"state": context.current_state.value, "message": message}
            if metadata:
                payload.update(metadata)
            context.run_ledger.append_event(event_type, payload)

    def _trigger_learning_loop(self, context: ExecutionContext, outcome: str):
        """Asynchronously triggers the LLM to extract the pattern from the run execution so it can be used for future instances."""
        if context.telemetry:
            context.telemetry.log_event("pattern_learning_triggered", context.issue_number or "task", context.current_state.value, f"Started pattern extraction for outcome: {outcome}")
            
        import threading
        def _learn():
            try:
                from forgeos.providers.model_router import ProviderRouter
                from forgeos.agents.pattern_extractor import PatternExtractorAgent
                from forgeos.memory.pattern_library import PatternLibrary
                
                router = ProviderRouter()
                extractor = PatternExtractorAgent(router)
                library = PatternLibrary()
                
                # Mock test output if somehow empty
                test_output = "No valid test logs."
                if context.test_results:
                    test_output = str(context.test_results.get("output", "")) + "\n" + str(context.test_results.get("errors", ""))
                    
                record, stats = extractor.extract_pattern(
                    issue_text=context.issue_text,
                    patch=context.patch or "No patch generated.",
                    test_output=test_output,
                    strategy=context.strategy,
                    outcome=outcome
                )
                
                library.save_pattern(record)
                self.log_and_record(context, f"Learning Loop completed. Saved Pattern ID '{record.pattern_id}' with outcome '{outcome}'.")
                
                if context.telemetry:
                    context.telemetry.log_event("pattern_saved", context.issue_number or "task", context.current_state.value, f"Saved Pattern ID: {record.pattern_id}")
                    
            except Exception as e:
                self.log_and_record(context, f"Learning Loop failed: {e}", event_type="warning")
                
        # Fire and forget
        thread = threading.Thread(target=_learn)
        thread.daemon = True
        thread.start()

    def handle_init(self, context: ExecutionContext) -> ExecutionContext:
        self.log_and_record(context, "Initializing execution context.")
        self.touch_heartbeat(context, "Context Initialized")
        
        if context.repo_path and context.repo_path.startswith("http"):
            from forgeos.sandbox.sandbox_runner import SandboxRunner
            runner = SandboxRunner()
            self.log_and_record(context, f"Autonomous Cloning: {context.repo_path}")
            cloned_path = runner.clone_repo(context.repo_path, context.issue_number)
            context.repo_path = cloned_path
            self.log_and_record(context, f"Repo cloned to {cloned_path}")
            
        context.current_state = EngineState.FETCH_ISSUE
        return context

    def handle_fetch_issue(self, context: ExecutionContext) -> ExecutionContext:
        if context.issue_text:
            self.log_and_record(context, "Issue text provided via CTO Agent. Skipping fetch.")
            context.current_state = EngineState.PATTERN_RETRIEVAL
            return context
            
        self.log_and_record(context, f"Fetching issue details for issue: {context.issue_number}")
        
        from forgeos.connectors.github_connector import GitHubConnector
        github = GitHubConnector()
        
        try:
            # Use github_url if set (separate from local repo_path)
            github_source = context.github_url or context.repo_path or ""
            repo_full_name = github_source.replace("https://github.com/", "").replace(".git", "")
            # Reject local paths (they don't start with a valid org/repo format)
            if repo_full_name.startswith("/") or "\\" in repo_full_name:
                raise ValueError(f"Not a GitHub URL: {repo_full_name}")
            issue_data = github.fetch_issue(repo_full_name, context.issue_number)
            context.issue_text = f"Title: {issue_data['title']}\nBody: {issue_data['body']}"
        except Exception as e:
            self.log_and_record(context, f"GitHub fetch failed: {e}. Trying to load from local dataset.", event_type="warning")
            # MVP Fallback: check if we have a local task definition (useful for Gauntlet)
            try:
                import json
                bench_file = "/Users/vasiliyprachev/Python_Projects/ForgeAI/forge_bench/alpha_tasks.json"
                with open(bench_file, "r") as f:
                    tasks = json.load(f)
                    task = next((t for t in tasks if t["id"] == context.issue_number), None)
                    if task:
                        context.issue_text = f"Title: {task['title']}\\nBody: {task['description']}"
                    else:
                        context.issue_text = "Bug: Mocked issue response due to failure."
            except:
                context.issue_text = "Bug: Mocked issue response due to failure."
        
        self.log_and_record(context, "Parsing Core Spec and ADRs for context injection.")
        from forgeos.spec.spec_parser import SpecParser
        parser = SpecParser(context.repo_path if context.repo_path else ".")
        parsed_ctx = parser.build_planner_context(context.issue_text)
        
        context.spec_context = parsed_ctx["system_context"]
        context.traceability_id = parsed_ctx["traceability_id"]

        # ── Source Code Injection ─────────────────────────────────────────────
        # Parse the issue text for explicit file path mentions and inject their
        # content into spec_context so the planner LLM targets the real files.
        import re, glob
        file_refs = re.findall(r'[\w/]+\.py', context.issue_text or "")
        injected_srcs = []
        for fref in file_refs[:5]:   # cap at 5 files
            # Try relative to repo_path first, then project root
            candidates = [
                os.path.join(context.repo_path or ".", fref),
                os.path.join(context.repo_path or ".", *fref.split("/")),
            ]
            for cpath in candidates:
                if os.path.exists(cpath):
                    try:
                        with open(cpath, "r", encoding="utf-8") as f:
                            src = f.read()
                        injected_srcs.append(
                            f"\n\n=== SOURCE FILE: {fref} ===\n{src[:4000]}"
                        )
                    except Exception:
                        pass
                    break
        if injected_srcs:
            context.spec_context = (context.spec_context or "") + "\n".join(injected_srcs)
            context.logs.append(f"Injected {len(injected_srcs)} source file(s) into planner context.")

        # Epic 46: Feature Flag for A/B Benchmarking
        if os.environ.get("FORGEOS_ENABLE_PATTERN_LIB", "true").lower() == "false":
            context.logs.append("OMNIBENCH: Pattern Library disabled via feature flag. Skipping retrieval.")
            context.pattern_context = {"similar_patterns_found": 0, "status": "Disabled via flag."}
            context.current_state = EngineState.PLAN
            return context

        context.current_state = EngineState.PATTERN_RETRIEVAL
        return context

        
    def handle_pattern_retrieval(self, context: ExecutionContext) -> ExecutionContext:
        self.log_and_record(context, "Consulting Experience Memory (Pattern Library) for historical engineering patterns.")
        try:
            from forgeos.memory.pattern_library import PatternLibrary
            from forgeos.sandbox.sandbox_runner import SandboxRunner
            import re
            
            library = PatternLibrary()
            repo_class = "python_backend_library" # Fallback
            
            # Simple heuristic detection for repo class
            if context.repo_path and "requests" in context.repo_path:
                repo_class = "http_client"
            elif context.repo_path and "starlette" in context.repo_path:
                repo_class = "async_web_framework"
                
            # Naive issue class heuristic
            issue_class = "tiny_bugfix"
            if "async" in context.issue_text.lower():
                issue_class = "async_bug"
            elif "timeout" in context.issue_text.lower():
                issue_class = "timeout_regression"
                
            from forgeos.providers.model_router import ProviderRouter
            router = ProviderRouter()
            
            # Hybrid Retrieval: Generate Query Embedding
            # We construct a query string capturing the essence of the current problem
            query_text = f"Issue: {issue_class} {context.issue_text[:500]}"
            
            # If we are in a retry loop and have a failure signature, append it
            if context.test_results and context.test_results.get("errors"):
                # Rough signature 
                failure_sig = context.test_results.get("errors", "")[:100].replace('\n', ' ')
                query_text += f" Failure: {failure_sig}"
                
            query_embedding = router.get_embedding(query_text)
                
            match_res = library.find_similar_patterns(repo_class, issue_class, query_embedding=query_embedding)
            context.pattern_context = match_res
            
            if match_res["similar_patterns_found"] > 0:
                self.log_and_record(context, f"Found {match_res['similar_patterns_found']} successful patterns matching repo_class='{repo_class}' and issue_class='{issue_class}'. Constraints set.")
                if context.telemetry:
                    context.telemetry.log_event("pattern_retrieval_hit", context.issue_number or "task", context.current_state.value, "Found matching patterns", {"count": match_res["similar_patterns_found"]})
            else:
                self.log_and_record(context, "No strict pattern match found. Planner will operate without historical constraints.")
                if context.telemetry:
                    context.telemetry.log_event("pattern_retrieval_miss", context.issue_number or "task", context.current_state.value, "No matching patterns found")
                
        except Exception as e:
            self.log_and_record(context, f"Pattern Library retrieval warning: {e}", event_type="warning")
            context.pattern_context = {"similar_patterns_found": 0, "status": "Failed to retrieve patterns."}
            
        context.current_state = EngineState.PLAN
        return context
        
    def handle_plan(self, context: ExecutionContext) -> ExecutionContext:
        self.log_and_record(context, f"Planning task execution.", metadata={"traceability_id": context.traceability_id})
        self.touch_heartbeat(context, "Started Planning")
        
        # Instantiate ProviderRouter and PlannerAgent
        from forgeos.providers.model_router import ProviderRouter
        from forgeos.engine.agents import PlannerAgent
        from forgeos.repo.repo_analyzer import RepoAnalyzer
        
        # Build Context Pack
        analyzer = RepoAnalyzer(context.repo_path if context.repo_path else ".")
        from forgeos.engine.context_pack import ContextPackBuilder
        pack_builder = ContextPackBuilder(context, analyzer)
        planner_prompt = pack_builder.build_planner_prompt()
        
        router = ProviderRouter()
        planner = PlannerAgent(router)
        
        # Generate Plan using compressed Context Pack
        context.plan, stats = planner.generate_plan(planner_prompt)
        
        cost = stats.get("cost", 0.0)
        context.global_cost += cost
        context.logs.append(f"Plan generated via {stats['model']} [COST: ${cost:.4f}]")
        
        if context.telemetry:
            context.telemetry.log_cost(context.issue_number, context.current_state.value, stats["model"], stats["prompt_tokens"], stats["completion_tokens"])
            
        # Council Deliberation Loop
        from forgeos.agents.council import CouncilAgent
        council = CouncilAgent(router)
        
        max_council_retries = 2
        for i in range(max_council_retries):
            context.logs.append(f"Submitting plan to Multi-Agent Council (Attempt {i+1})...")
            is_approved, critique, c_stats = council.deliberate(context, context.plan)
            
            c_cost = c_stats.get("cost", 0.0)
            context.global_cost += c_cost
            context.logs.append(f"Council deliberation finished [COST: ${c_cost:.4f}]")
            
            if context.telemetry:
                context.telemetry.log_event("council_review", context.issue_number, context.current_state.value, "Council resolved.", {"approved": is_approved, "cost": c_cost})
                
            if is_approved:
                context.logs.append("Council APPROVED the plan.")
                break
            else:
                context.logs.append(f"Council REJECTED the plan:\\n{critique}")
                if i < max_council_retries - 1:
                    context.logs.append("Asking Planner to revise plan based on Council feedback...")
                    revision_prompt = f"{planner_prompt}\\n\\nPREVIOUS DRAFT REJECTED BY COUNCIL.\\nCRITIQUES:\\n{critique}\\nPlease provide a revised plan addressing these issues."
                    context.plan, r_stats = planner.generate_plan(revision_prompt)
                    r_cost = r_stats.get("cost", 0.0)
                    context.global_cost += r_cost
                    context.logs.append(f"Revised plan generated [COST: ${r_cost:.4f}]")
                else:
                    context.logs.append("Council max retries reached. Proceeding with last rejected plan (Fallback).")
        
        if context.artifact_manager:
            context.artifact_manager.save_plan(context.plan)
            context.logs.append("Plan saved to artifact layer.")

        # Route to Branch Racing if eligible, otherwise linear IMPACT_ANALYSIS
        from forgeos.engine.branch_manager import should_race
        if should_race(context):
            context.logs.append("[BranchRacing] Task eligible for speculative parallelism. Routing to BRANCH_RACE.")
            context.current_state = EngineState.BRANCH_RACE
        else:
            context.current_state = EngineState.IMPACT_ANALYSIS
        return context

    def handle_branch_race(self, context: ExecutionContext) -> ExecutionContext:
        """Runs N strategy branches in parallel, selects the winner, and injects it into the pipeline."""
        self.log_and_record(context, "[BRANCH_RACE] Starting speculative parallelism — racing strategies.",
                            metadata={"racing_enabled": True})
        self.touch_heartbeat(context, "Starting Speculative Race")
        try:
            from forgeos.engine.branch_manager import StrategyBranchManager
            n = 3 if getattr(context, "retries", 0) > 0 else 2  # 3 branches on retry, 2 on first pass
            winner = StrategyBranchManager.race(context, n_branches=n)

            if winner and (winner.plan or winner.patch):
                context.logs.append(
                    f"[BRANCH_RACE] Winner: {winner.strategy_type} | score={winner.score} | "
                    f"sim={'APPROVED' if winner.sim_approved else 'REJECTED'} | cost=${winner.cost:.3f}"
                )
                # Inject winner into pipeline
                self.touch_heartbeat(context, f"Selected Winner '{winner.strategy_type}'")
                if winner.plan:
                    context.plan = winner.plan
                if winner.patch:
                    context.patch = winner.patch
                
                # The winner cost is currently logged, but we should add it to global
                context.global_cost += winner.cost
                
                # Store all branch results for Mission Control
                context.branch_results = []
                self.mark_progress(context, EngineState.BRANCH_RACE.value, EngineState.IMPACT_ANALYSIS.value)
            else:
                context.logs.append("[BRANCH_RACE] No viable winner. Falling back to linear execution.")
                self.mark_progress(context, EngineState.BRANCH_RACE.value, EngineState.IMPACT_ANALYSIS.value)
        except Exception as e:
            import traceback
            context.logs.append(f"[BRANCH_RACE] Crashed: {e}\n{traceback.format_exc()}. Continuing linear.")
            self.mark_progress(context, EngineState.BRANCH_RACE.value, EngineState.IMPACT_ANALYSIS.value)

        context.current_state = EngineState.IMPACT_ANALYSIS
        return context

    def handle_impact_analysis(self, context: ExecutionContext) -> ExecutionContext:
        self.log_and_record(context, "Analyzing impact radius and risk score of proposed plan.")
        
        from forgeos.repo.impact_engine import ImpactEngine
        from forgeos.repo.repo_analyzer import RepoAnalyzer
        analyzer = RepoAnalyzer(context.repo_path if context.repo_path else ".")
        impact = ImpactEngine(analyzer)
        
        try:
            plan_str = context.plan if context.plan else ""
            
            # Fetch the actual repo map keys instead of crashing on context.repo_map
            actual_repo_map = analyzer.generate_repo_map()
            touched_files = list(actual_repo_map.keys())[:3] if actual_repo_map else []
            
            report = impact.analyze_impact(touched_files)
            
            if context.artifact_manager:
                context.artifact_manager.save_impact_report(report)
                
            context.logs.append(f"Impact Analysis Complete: Risk={report.get('risk_score')}, AffectedFiles={len(report.get('affected_files', []))}")
            if context.telemetry:
                context.telemetry.log_event("impact_analysis", context.issue_number, context.current_state.value, report.get('risk_score', 'medium'))
                
        except Exception as e:
            context.logs.append(f"Impact Analysis failed: {e}. Defaulting to High Risk.")
            if context.artifact_manager:
                context.artifact_manager.save_impact_report({"risk_score": "high", "error": str(e)})

        context.current_state = EngineState.PATCH
        return context

    def handle_patch(self, context: ExecutionContext) -> ExecutionContext:
        print("[DEBUG] Inside handle_patch: Starting!")
        self.log_and_record(context, "Drafting Code Patch via Coder module.")
        
        if not context.patch:
            # Instantiate ProviderRouter and CoderAgent
            from forgeos.providers.model_router import ProviderRouter
            from forgeos.engine.agents import CoderAgent
            
            from forgeos.repo.repo_analyzer import RepoAnalyzer
            from forgeos.engine.context_pack import ContextPackBuilder
            analyzer = RepoAnalyzer(context.repo_path if context.repo_path else ".")
            pack_builder = ContextPackBuilder(context, analyzer)
            coder_prompt = pack_builder.build_coder_prompt()
            
            router = ProviderRouter()
            coder = CoderAgent(router)
            
            context.patch, stats = coder.generate_patch(coder_prompt)
            
            cost = stats.get("cost", 0.0)
            context.global_cost += cost
            context.logs.append(f"Patch generated via {stats['model']} [COST: ${cost:.4f}]")
            
            if context.telemetry:
                context.telemetry.log_cost(context.issue_number, context.current_state.value, stats["model"], stats["prompt_tokens"], stats["completion_tokens"])
        else:
            print("[DEBUG] Inside handle_patch: using BRANCH_RACE winning patch")
            context.logs.append("Patch already provided (likely from BRANCH_RACE winner). Skipping Coder generation.")
        
        if context.artifact_manager:
            # We determine attempt based on how many times failure memory recorded a failure for this strategy
            attempt = 1
            if context.failure_memory and context.test_results:
                sig = context.test_results.get("errors", "Unknown Test Failure")[:50]
                key = f"{sig}::{context.strategy}"
                if key in context.failure_memory.failures:
                    attempt = context.failure_memory.failures[key]["attempts"] + 1
                    
            context.artifact_manager.save_patch(context.patch, attempt)
            context.logs.append(f"Patch attempt {attempt} saved to artifact layer.")
            
        # Epic 49: Patch Scope Analysis Gate
        from forgeos.verification.patch_scope_analyzer import ScopeAnalyzer
        scope_analyzer = ScopeAnalyzer(context.repo_path if context.repo_path else ".")
        
        risk = "low" # Default to low risk budget
        analysis = scope_analyzer.evaluate_patch(context.patch, risk_profile=risk)
        
        if context.telemetry:
            context.telemetry.log_event(
                "patch_scope_analysis", 
                context.issue_number, 
                context.current_state.value, 
                analysis.scope_class.value, 
                {"net_delta": analysis.net_loc_delta, "files": analysis.total_files_changed, "rejected": analysis.is_rejected}
            )
            
        if analysis.is_rejected:
            context.logs.append(f"PATCH WIDTH REJECTED: {analysis.rejection_reason}")
            context.test_results = {
                "status": "failed",
                "errors": f"PATCH_WIDTH_REJECTED: {analysis.rejection_reason}",
                "command": "Patch Width Limiter"
            }
            context.current_state = EngineState.PATCH_WIDTH_REJECT
            return context
            
        context.logs.append(f"Patch Scope Approved: {analysis.scope_class.value} (Files: {analysis.total_files_changed}, Delta: {analysis.net_loc_delta})")
        
        if context.patch_scope_context is None:
            context.patch_scope_context = {}
        context.patch_scope_context["scope_class"] = analysis.scope_class.value
        
        print("[DEBUG] Inside handle_patch: Entering EXECUTION_CRITIC!")
        context.current_state = EngineState.EXECUTION_CRITIC
        return context

    def handle_patch_width_reject(self, context: ExecutionContext) -> ExecutionContext:
        context.logs.append("Routing rejected wide patch back to Planner for Hard Replan (Option A).")
        
        # Route back to PLAN so the Planner can rethink the architectural strategy
        context.current_state = EngineState.PLAN
        return context

    def handle_execution_critic(self, context: ExecutionContext) -> ExecutionContext:
        context.logs.append("Executing pre-flight patch review (Architecture & Security Critics).")
        
        from forgeos.providers.model_router import ProviderRouter
        from forgeos.agents.critics.architecture_critic import ArchitectureCritic
        from forgeos.agents.critics.security_critic import SecurityCritic
        
        router = ProviderRouter()
        arch_critic = ArchitectureCritic(router)
        sec_critic = SecurityCritic(router)
        
        repo_map_str = context.spec_context if hasattr(context, 'spec_context') else "Unknown architecture"
        print("[DEBUG] Inside handle_execution_critic: Calling ArchitectureCritic!")
        arch_res, arch_stats = arch_critic.evaluate(repo_map=repo_map_str, patch=context.patch or "")
        print("[DEBUG] Inside handle_execution_critic: Calling SecurityCritic!")
        sec_res, sec_stats = sec_critic.evaluate(patch=context.patch or "")
        print("[DEBUG] Inside handle_execution_critic: Both critics returned!")
        
        total_cost = arch_stats.get("cost", 0.0) + sec_stats.get("cost", 0.0)
        context.global_cost += total_cost
        context.logs.append(f"Patch reviewed via Multi-Critic [COST: ${total_cost:.4f}]")
        if context.telemetry:
            context.telemetry.log_cost(context.issue_number, context.current_state.value, "Multi-Critic", 0, 0)
        
        arch_status = arch_res.get("status", "APPROVED")
        sec_status = sec_res.get("status", "APPROVED")

        # Only hard-reject on explicitly structural/security-critical decisions
        # WARN / CAUTION / APPROVED all proceed — only REJECTED or BLOCKED halt execution
        BLOCK_STATUSES = {"REJECTED", "BLOCKED"}

        if arch_status not in BLOCK_STATUSES and sec_status not in BLOCK_STATUSES:
            if arch_status != "APPROVED" or sec_status != "APPROVED":
                notes = []
                if arch_status != "APPROVED":
                    notes.append(f"[Architecture Note] {arch_res.get('reason','')}")
                if sec_status != "APPROVED":
                    notes.append(f"[Security Note] {sec_res.get('reason','')}")
                context.logs.append(f"Multi-Critic WARNING (proceeding): {' | '.join(notes)}")
            else:
                context.logs.append("Multi-Critic APPROVED the patch.")

            # Epic 46: Feature Flag for A/B Benchmarking
            if os.environ.get("FORGEOS_ENABLE_PATCH_SIM", "true").lower() == "false":
                context.logs.append("OMNIBENCH: Patch Simulation disabled via feature flag. Proceeding directly to tests.")
                context.current_state = EngineState.RUN_TESTS
            else:
                context.current_state = EngineState.PATCH_SIMULATION
        else:
            reasons = []
            if arch_status in BLOCK_STATUSES:
                reasons.append(f"[Architecture] {arch_res.get('reason')} - Advice: {arch_res.get('advice')}")
            if sec_status in BLOCK_STATUSES:
                reasons.append(f"[Security] {sec_res.get('reason')} - Advice: {sec_res.get('advice')}")
                
            rejection_text = "\\n".join(reasons)
            context.logs.append(f"Critic REJECTED the patch.\\n{rejection_text}")
            
            # Epic 59 Async Hazard Tracking
            if context.telemetry and "await" not in (context.patch or "").lower() and "async" in (context.patch or "").lower():
                context.telemetry.log_async_hazard(context.issue_number, context.current_state.value, context.patch)
            
            context.test_results = {
                "status": "failed",
                "errors": f"MULTI_CRITIC_REJECTION:\\n{rejection_text}",
                "command": "Pre-flight Validation"
            }
            context.current_state = EngineState.RETRY
            
        return context

    def handle_patch_simulation(self, context: ExecutionContext) -> ExecutionContext:
        print("[DEBUG] Inside handle_patch_simulation: Starting!")
        self.log_and_record(context, "[PATCH_SIMULATION] Executing Static Patch Simulation (Risk & Semantic Gate).")
        self.touch_heartbeat(context, "Starting Patch Simulation via Ast/LLM")
        
        print("[DEBUG] Inside handle_patch_simulation: Importing PatchSimulatorAgent!")
        from forgeos.providers.model_router import ProviderRouter
        from forgeos.agents.critics.impact_simulator import PatchSimulatorAgent
        from forgeos.repo.repo_analyzer import RepoAnalyzer
        
        router = ProviderRouter()
        simulator = PatchSimulatorAgent(router)
        
        # We need the symbol index to look at callers
        analyzer = RepoAnalyzer(context.repo_path if context.repo_path else ".")
        try:
            symbol_index_str = str(analyzer.generate_symbol_index())
        except Exception:
            symbol_index_str = "Symbol index unavailable."
            
        print("[DEBUG] Inside handle_patch_simulation: Calling simulate_impact()!")
        sim_res, sim_stats = simulator.simulate_impact(
            issue_text=context.spec_context,
            patch=context.patch or "",
            symbol_index_str=symbol_index_str
        )
        print("[DEBUG] Inside handle_patch_simulation: simulate_impact() returned!")
        
        cost = sim_stats.get("cost", 0.0)
        context.global_cost += cost
        context.logs.append(f"Patch simulation completed via {sim_stats.get('model', 'none')} [COST: ${cost:.4f}]")
        
        if context.telemetry:
            context.telemetry.log_event("patch_simulation", context.issue_number, context.current_state.value, "Simulation finished.", {"cost": cost, "risk": sim_res.get("risk_score")})
            
        decision = sim_res.get("strategy_decision", "proceed")
        reasoning = sim_res.get("reasoning", "No structural risks found.")
        
        # Store the verification scope recommendation dynamically so sandbox_runner can read it later
        if not context.simulation_context:
            context.simulation_context = {}
        context.simulation_context["verification_scope_recommendation"] = sim_res.get("verification_scope_recommendation", "unit_only")
        
        context.logs.append(f"Simulation Decision: {decision}. Reason: {reasoning}")
        
        if decision == "reject_patch_and_replan":
            context.logs.append("WARNING: Simulation intercepted a severe structural flaw. HALTING execution.")
            
            # Formulate the fake test failure to feed FailureMemory and Planner
            context.test_results = {
                "status": "failed",
                "errors": f"SIMULATION_REJECT: Contract Break Detected.\nREASONING: {reasoning}",
                "command": "Static Impact Simulation"
            }
            context.current_state = EngineState.RETRY
        else:
            context.current_state = EngineState.RUN_TESTS
            
        return context

    def handle_run_tests(self, context: ExecutionContext) -> ExecutionContext:
        context.logs.append("Running tests in sandbox.")
        self.touch_heartbeat(context, "Bootstrapping environment and running tests")

        # ── Apply patch to disk before running tests ──────────────────────────
        # context.patch is a unified diff string. Write it to a temp file and
        # apply it with `git apply` so pytest evaluates the patched code.
        patch_applied = False
        repo_path = context.repo_path if context.repo_path else "."
        patch_tmp = None
        if context.patch:
            import tempfile, subprocess as sp
            try:
                # Strip markdown fences if present (LLM sometimes wraps in ```diff)
                raw_patch = context.patch
                lines = raw_patch.split("\n")
                
                # First, unpack from markdown fences if needed
                if "```" in raw_patch:
                    inside = False
                    fenced_lines = []
                    for line in lines:
                        if line.startswith("```"):
                            inside = not inside
                            continue
                        if inside:
                            fenced_lines.append(line)
                    lines = fenced_lines

                # Now aggressively sanitize to valid git-apply lines
                patch_lines = []
                for line in lines:
                    # Valid patch lines start with these prefixes.
                    # Relaxed a bit to avoid stripping normal diff context
                    valid_starts = ("---", "+++", "@@", "+", "-", " ", "\\", "diff ", "index ")
                    if any(line.startswith(prefix) for prefix in valid_starts) or line.strip() == "":
                        patch_lines.append(line)
                        
                raw_patch = "\n".join(patch_lines)


                with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
                    f.write(raw_patch)
                    patch_tmp = f.name

                result = sp.run(
                    ["git", "apply", "--whitespace=fix", patch_tmp],
                    cwd=repo_path, capture_output=True, text=True
                )
                if result.returncode == 0:
                    patch_applied = True
                    context.logs.append(f"Patch applied successfully via git apply.")
                else:
                    context.logs.append(f"git apply failed (rc={result.returncode}): {result.stderr[:200]}")
                    context.logs.append(f"Attempting fallback to GNU patch...")
                    # Fallback to patch with a generous fuzz factor
                    result2 = sp.run(
                        ["patch", "-p1", "-F3", "-i", patch_tmp],
                        cwd=repo_path, capture_output=True, text=True
                    )
                    if result2.returncode == 0:
                        patch_applied = True
                        context.logs.append(f"Patch applied successfully via patch fallback.")
                    else:
                        context.logs.append(f"GNU patch fallback failed (rc={result2.returncode}): {result2.stderr[:200]}\nStdout: {result2.stdout[:200]}")

            except Exception as e:
                context.logs.append(f"Patch application error: {e}")

        # Load Sandbox
        from forgeos.sandbox.sandbox_runner import SandboxRunner
        runner = SandboxRunner()


        # Determine Verification Scope
        test_targets = []
        if context.artifact_manager:
            import os, json
            from forgeos.engine.context_pack import ContextPackBuilder
            from forgeos.repo.repo_analyzer import RepoAnalyzer
            
            # Parse impacted risk to decide scope
            impact_report = context.artifact_manager.load_impact_report()
            risk = impact_report.get("risk_score", "high")
            
            if risk in ["low", "medium"]:
                # Retrieve test map
                analyzer = RepoAnalyzer(context.repo_path if context.repo_path else ".")
                cache_dir = ContextPackBuilder(context, analyzer).cache_dir
                test_map_path = os.path.join(cache_dir, "test_map.json")
                test_map = {}
                if os.path.exists(test_map_path):
                    with open(test_map_path, "r") as f:
                        test_map = json.load(f)
                        
                # Simple heuristic target resolution based on diff parsing
                if context.patch:
                    for target_file in test_map.keys():
                        if target_file in context.patch:
                            test_targets.extend(test_map.get(target_file, []))
                            
            # Ensure unique targets
            test_targets = list(set(test_targets))
            
            # Read Simulator's verification scope recommendation
            rec_scope = "unit_only"
            if hasattr(context, "simulation_context"):
                rec_scope = context.simulation_context.get("verification_scope_recommendation", "unit_only")
                
            # Epic 49: Verification Coupling based on explicit patch scope
            scope_class = "narrow_local_patch"
            if hasattr(context, "patch_scope_context"):
                scope_class = context.patch_scope_context.get("scope_class", "narrow_local_patch")
            
            if scope_class in ["wide_patch", "cross_boundary_patch"]:
                rec_scope = "full_suite"
                context.logs.append("Verification escalation triggering full test suite due to wide patch scope.")
            elif scope_class == "medium_patch" and rec_scope == "unit_only":
                rec_scope = "integration_plus_package"
                context.logs.append("Verification escalation to package level due to medium patch scope.")
                
            if risk in ["critical", "high"] or rec_scope in ["integration_plus_package", "full_suite"] or not test_targets:
                test_targets = None # Fallback to full suite
                if rec_scope in ["integration_plus_package", "full_suite"]:
                    context.logs.append(f"Verification Engine escalated scope to: {rec_scope}")
                
            if test_targets:
                context.logs.append(f"Verification Scope Targeted: {len(test_targets)} files based on {risk} risk and {rec_scope} recommendation.")
            else:
                context.logs.append(f"Verification Scope Escalated: Full test suite based on {risk} risk or no targeted files found.")
                
            if context.telemetry:
                context.telemetry.log_event(
                    "verification_scope_selected", 
                    context.issue_number, 
                    context.current_state.value, 
                    f"Scope: {'Targeted' if test_targets else 'Full'}", 
                    {"risk": risk, "targets": len(test_targets) if test_targets else "all"}
                )

        # In MVP, this relies on sandbox doing real things or mock if test_command fails
        context.test_results = runner.run_tests(context.repo_path if context.repo_path else ".", test_targets=test_targets)

        # ── Revert patch after tests ──────────────────────────────────────────
        # Always restore the repo to clean state after testing regardless of result
        if patch_applied:
            try:
                import subprocess as sp
                sp.run(["git", "checkout", "--", "."], cwd=repo_path, capture_output=True)
                if patch_tmp and os.path.exists(patch_tmp):
                    os.unlink(patch_tmp)
                context.logs.append("Repo restored to clean state after test run.")
            except Exception as e:
                context.logs.append(f"Warning: could not revert patch: {e}")

        if context.artifact_manager:
            context.artifact_manager.save_test_results(context.test_results)

        context.logs.append(
            f"Test run complete: status={context.test_results.get('status')} "
            f"returncode={context.test_results.get('returncode')} "
            f"patch_applied={patch_applied}"
        )

        context.current_state = EngineState.VERIFY
        return context


    def handle_verify(self, context: ExecutionContext) -> ExecutionContext:
        context.logs.append("Verifying test results and applying critique if necessary.")
        test_output = context.test_results.get("output", "") + "\\n" + context.test_results.get("errors", "")
        
        if context.test_results and context.test_results.get("status") == "success":
            context.logs.append("Tests passed. Engaging Test Adequacy Agent to verify execution validity.")
            from forgeos.providers.model_router import ProviderRouter
            from forgeos.agents.critics.test_adequacy_agent import TestAdequacyAgent
            
            router = ProviderRouter()
            adequacy_agent = TestAdequacyAgent(router)
            
            result, stats = adequacy_agent.evaluate(patch=context.patch or "", repo_path=context.repo_path or ".", test_output=test_output)
            
            cost = stats.get("cost", 0.0)
            context.global_cost += cost
            context.logs.append(f"Adequacy verified via {stats['model']} [COST: ${cost:.4f}]")
            
            if result.get("status", "REJECTED") == "APPROVED":
                context.logs.append("Test Adequacy APPROVED. The patch is verified.")
                context.current_state = EngineState.CREATE_PR
                return context
            else:
                reason = result.get("reason", "Verification Deficit.")
                advice = result.get("advice", "Run explicit tests targeting the changed files.")
                context.logs.append(f"Test Adequacy REJECTED the success: {reason}")
                
                # Mock a failure so the Execution Critic diagnoses the Verification Deficit
                context.test_results["status"] = "failed"
                context.test_results["errors"] = f"VERIFICATION DEFICIT:\\n{reason}\\nADVICE: {advice}"
                # Fall through to the failure handler below
                
        context.logs.append("Tests failed. Engaging Post-Failure Critic for diagnosis.")
        
        from forgeos.os.failure_taxonomy import FailureTaxonomyEngine
        cmd = context.test_results.get("command", "")
        
        failure_category = FailureTaxonomyEngine.classify_error(test_output, cmd)
        self.log_and_record(context, f"Failure Taxonomy Engine classified failure as: {failure_category.value}")

        from forgeos.providers.model_router import ProviderRouter
        from forgeos.agents.critics.execution_critic import ExecutionCritic
        
        router = ProviderRouter()
        critic = ExecutionCritic(router)
        
        test_output = context.test_results.get("output", "") + "\\n" + context.test_results.get("errors", "")
        if len(test_output) > 10000:
            test_output = "...[TRUNCATED]\\n" + test_output[-10000:]
            
        result, stats = critic.analyze_failure(
            issue_text=context.issue_text,
            plan=context.plan or "",
            patch=context.patch or "",
            repo_path=context.repo_path or ".",
            test_output=test_output,
            failure_category=failure_category.value
        )
        
        cost = stats.get("cost", 0.0)
        context.global_cost += cost
        context.logs.append(f"Failure analyzed via {stats['model']} [COST: ${cost:.4f}]")
        
        if context.telemetry:
            context.telemetry.log_cost(context.issue_number, context.current_state.value, stats["model"], stats["prompt_tokens"], stats["completion_tokens"])
            
        diagnosis = result.get("diagnosis", "Unknown Diagnosis")
        advice = result.get("advice", "Try alternative approach.")
        
        context.logs.append(f"Critic Diagnosis: {diagnosis}")
        
        # Prefix critic feedback to errors so FailureMemory catches it
        orig_err = context.test_results.get("errors", "Unknown Test Failure")
        context.test_results["errors"] = f"CRITIC DIAGNOSIS: {diagnosis}\\nADVICE: {advice}\\n\\nRAW ERRORS:\\n{orig_err}"
        
        # Extract structured cognitive failure record using FailureMiner
        try:
            from forgeos.memory.failure_miner import FailureIntelligenceEngine
            miner = FailureIntelligenceEngine()
            context.failure_record = miner.mine_failure(context)
        except Exception as e:
            context.logs.append(f"[FailureMiner] Hook crashed during VERIFY: {e}")
        
        context.current_state = EngineState.RETRY
        return context

    def handle_retry(self, context: ExecutionContext) -> ExecutionContext:
        context.logs.append("Handling retry logic and consulting Adaptive Policy Engine.")
        context.retries += 1
        
        from forgeos.engine.policies import PolicyEngine, StrategyDirective
        directive = PolicyEngine.evaluate(context.failure_record, context.retries, max_retries=5)
        
        context.logs.append(f"PolicyEngine returned directive: {directive.value}")
        
        if directive == StrategyDirective.ABORT:
            context.logs.append("CRITICAL: PolicyEngine decided to ABORT execution due to loop traps or max retries.")
            self._trigger_learning_loop(context, "failed")
            context.current_state = EngineState.FAILED
            return context
            
        elif directive == StrategyDirective.FAST_RETRY:
            context.logs.append("FAST_RETRY directive: Bypassing Planner and going directly to CODE.")
            context.current_state = EngineState.PATCH
            return context
            
        elif directive == StrategyDirective.HARD_REPLAN:
            context.logs.append("HARD_REPLAN directive: Resetting Plan and routing to PLAN.")
            context.plan = None
            context.current_state = EngineState.PLAN
            return context
            
        elif directive == StrategyDirective.KNOWLEDGE_EXPANSION:
            context.logs.append("KNOWLEDGE_EXPANSION directive: Re-running Impact Analysis/Retrieval.")
            context.current_state = EngineState.IMPACT_ANALYSIS
            return context
            
        # Fallback to STANDARD_RETRY and consulting Failure Memory (Deadlock Breaker)
        if context.failure_memory and context.test_results:
            error_signature = context.test_results.get("errors", "Unknown Test Failure")[:50] # Short MVP signature
            context.failure_memory.record_failure(error_signature, context.strategy)
            
            if context.failure_memory.is_strategy_blocked(error_signature, context.strategy):
                from forgeos.providers.model_router import ProviderRouter
                from forgeos.agents.architect import ArchitectAgent
                
                context.logs.append(f"CRITICAL: Strategy '{context.strategy}' is blocked (3+ failures). Summoning Deadlock Breaker Architect.")
                
                router = ProviderRouter()
                architect = ArchitectAgent(router)
                adr_text, stats = architect.generate_adr(context)
                
                cost = stats.get("cost", 0.0)
                context.global_cost += cost
                context.logs.append(f"Architect produced ADR via {stats.get('model', 'none')} [COST: ${cost:.4f}]")
                
                if context.telemetry:
                    context.telemetry.log_event("architect_summoned", context.issue_number, context.current_state.value, "Generated ADR to break deadlock.", {"cost": cost})
                    
                context.spec_context += f"\\n\\n{adr_text}"
                context.plan = None
                context.patch = None
                
                # Naive strategy switch for MVP
                if context.strategy == "patch":
                    context.strategy = "rewrite"
                elif context.strategy == "rewrite":
                    context.strategy = "test-driven"
                else:
                    context.logs.append("No more strategies left. Escalate to Failed.")
                    self._trigger_learning_loop(context, "failed")
                    context.current_state = EngineState.FAILED
                    return context
            
            context.logs.append(f"Retrying with strategy: {context.strategy}")
            context.current_state = EngineState.PLAN
        else:
            # Without memory, just transition
            context.current_state = EngineState.PLAN
            
        return context

    def handle_create_pr(self, context: ExecutionContext) -> ExecutionContext:
        context.logs.append("Creating Pull Request via GitHub Connector.")
        
        # Determine repo_full_name
        repo_full_name = context.repo_path.replace("https://github.com/", "").replace(".git", "") if context.repo_path else "mock/repo"
        
        # We assume Sandbox has pushed the branch
        branch_name = f"forgeos/issue-{context.issue_number}"
        
        # Instantiate sandbox to commit and push
        from forgeos.sandbox.sandbox_runner import SandboxRunner
        runner = SandboxRunner()
        commit_msg = f"Fix: Resolve issue #{context.issue_number}"
        push_success = runner.commit_and_push(context.repo_path if context.repo_path else ".", branch_name, commit_msg)
        
        if not push_success:
            context.logs.append("Warning: Could not push branch to remote. PR creation might fail if branch does not exist.")
            
        from forgeos.connectors.github_connector import GitHubConnector
        github = GitHubConnector()
        
        pr_title = f"Fix: Resolve issue #{context.issue_number}"
        
        # Build Supervised Flow PR Body
        impact_score = "Unknown"
        if context.artifact_manager:
            report = context.artifact_manager.load_impact_report()
            impact_score = report.get("risk_score", "Unknown")
            
        test_out = "No tests were run."
        if context.test_results:
            test_out = f"**Status**: {context.test_results.get('status', 'Unknown')}\\n**Command**: `{context.test_results.get('command', '')}`"
        
        pr_body = f"""## 🤖 ForgeOS Autonomous Resolution

This PR was generated automatically by ForgeOS in **Supervised Mode**.

### 📋 Overview
Fixes #{context.issue_number}

### 🧠 Execution Plan
<details><summary>Click to view</summary>
{context.plan if context.plan else 'No plan generated.'}
</details>

### 🔬 Impact & Risk Analysis
- **Risk Score**: {impact_score}

### 🧪 Verification
{test_out}
"""
        
        try:
            pr_url = github.create_pull_request(repo_full_name, pr_title, pr_body, branch_name)
            context.logs.append(f"PR Created successfully: {pr_url}")
            
            # Fire learning loop for successful patch
            self._trigger_learning_loop(context, "success")
            
            context.current_state = EngineState.POLL_CI
        except Exception as e:
            context.logs.append(f"Failed to create PR: {e}")
            context.current_state = EngineState.FAILED
            
        return context

    def handle_poll_ci(self, context: ExecutionContext) -> ExecutionContext:
        context.logs.append("Polling CI status on GitHub.")
        
        repo_full_name = context.repo_path.replace("https://github.com/", "").replace(".git", "") if context.repo_path else "mock/repo"
        branch_name = f"forgeos/issue-{context.issue_number}"
        
        from forgeos.connectors.github_connector import GitHubConnector
        github = GitHubConnector()
        import os
        import time
        max_attempts = 15
        attempt = 0
        
        while attempt < max_attempts:
            attempt += 1
            try:
                checks = github.get_commit_check_runs(repo_full_name, branch_name)
                
                if "check_runs" not in checks or len(checks["check_runs"]) == 0:
                    context.logs.append("No CI checks found. Assuming success or CI not configured.")
                    context.current_state = EngineState.DONE
                    return context
                    
                all_completed = all(run.get("status") == "completed" for run in checks["check_runs"])
                
                if all_completed:
                    any_failed = any(run.get("conclusion") in ["failure", "cancelled", "timed_out", "action_required"] for run in checks["check_runs"])
                    if any_failed:
                        context.logs.append("CI checks failed. Transitioning to RETRY.")
                        failures = [run for run in checks["check_runs"] if run.get("conclusion") in ["failure", "cancelled", "timed_out", "action_required"]]
                        
                        summary_msg = failures[0].get('output', {}).get('summary', 'No summary provided by CI')
                        context.test_results = {
                            "status": "failed",
                            "errors": f"CI Check Failed: {failures[0].get('name')} - {summary_msg}",
                            "command": "GitHub Actions"
                        }
                        context.current_state = EngineState.RETRY
                    else:
                        context.logs.append("All CI checks passed successfully.")
                        context.current_state = EngineState.DONE
                    return context
                    
                context.logs.append(f"CI checks still running. Waiting... (Attempt {attempt}/{max_attempts})")
                
            except Exception as e:
                context.logs.append(f"Error polling CI: {e}")
                
            if not os.environ.get("GITHUB_TOKEN"):
                # Always exit instantly if in mock mode and all_completed wasn't mocked properly
                context.logs.append("No GITHUB_TOKEN set. Mocking CI success.")
                context.current_state = EngineState.DONE
                return context
                
            time.sleep(30)
            
        context.logs.append("Timed out waiting for CI checks. Ending execution.")
        context.current_state = EngineState.DONE
        return context

    def handle_done(self, context: ExecutionContext) -> ExecutionContext:
        context.logs.append("Finalizing execution and drafting PR summary.")
        from forgeos.providers.model_router import ProviderRouter
        from forgeos.agents.pr_generator import PRGeneratorAgent
        
        router = ProviderRouter()
        pr_agent = PRGeneratorAgent(router)
        
        pr_desc, stats = pr_agent.generate_pr_description(context)
        
        cost = stats.get("cost", 0.0)
        context.global_cost += cost
        context.logs.append(f"PR Description generated via {stats.get('model', 'none')} [COST: ${cost:.4f}]")
        
        if context.telemetry:
            context.telemetry.log_event("pr_description_drafted", context.issue_number, context.current_state.value, "Drafted PR markdown.", {"cost": cost})
            
        # We save this description so the external CLI can print it
        if context.artifact_manager:
            import os
            cache_dir = context.artifact_manager.cache_dir
            with open(os.path.join(cache_dir, "PR_DESCRIPTION.md"), "w") as f:
                f.write(pr_desc)
                
        # This is a terminal state, break loop
        return context
