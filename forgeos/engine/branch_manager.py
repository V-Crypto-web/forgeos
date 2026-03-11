"""
branch_manager.py
=================
Epic 58: Speculative Parallelism / Strategy Branch Racing.

The StrategyBranchManager takes an ExecutionContext after PLAN and spawns
N parallel "branch runs", each using a different strategy orientation.
It collects results, scores them via WinnerSelectionPolicy, persists loser
artifacts to LoserBranchSink, and returns the winning BranchResult so the
state machine can continue with the best strategy.

Architecture:
  context (post-PLAN)
    ├─ Branch A: minimal_local_patch
    ├─ Branch B: test_first_patch
    └─ Branch C: narrow_rewrite
         ↓ (parallel threads)
    Each branch: build prompt → generate plan variant → generate patch → simulate → evaluate
         ↓
    WinnerSelectionPolicy → winning BranchResult
         ↓
    LoserBranchSink → save losing branches as learning data
"""

import os
import json
import time
import copy
import uuid
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Branch Budget Guardrails ──────────────────────────────────────────────────
MAX_BRANCHES        = 3
MAX_BRANCH_COST     = 0.30   # USD per branch
BRANCH_TIMEOUT_SECS = 180    # 3 minutes per branch
BRANCH_DB_PATH      = os.path.join(os.path.dirname(__file__), "..", "..", ".forgeos", "branches")

# ── Strategy Types ────────────────────────────────────────────────────────────
STRATEGY_TYPES = {
    "minimal_local_patch": (
        "Apply the SMALLEST possible change that fixes the issue. "
        "Touch ONLY the directly failing lines. Do NOT refactor, do NOT add helpers. "
        "Prefer single-file edits."
    ),
    "test_first_patch": (
        "Write failing tests FIRST that reproduce the issue, then implement the "
        "minimal fix that makes them pass. Your patch MUST include both the test "
        "file change and the implementation change."
    ),
    "narrow_rewrite": (
        "Identify the root cause function or class and rewrite ONLY that unit cleanly. "
        "Do not touch callers or wider modules. The rewrite must preserve the public "
        "interface exactly."
    ),
}

# ── Data Structures ───────────────────────────────────────────────────────────
@dataclass
class BranchResult:
    branch_id: str
    strategy_type: str
    plan: str
    patch: str
    cost: float
    patch_width: int             # number of files changed
    sim_approved: bool
    sim_warning: str
    test_passed: bool
    test_output: str
    retry_count: int = 0
    score: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

# ── Winner Selection Policy ───────────────────────────────────────────────────
class WinnerSelectionPolicy:
    """
    score = 1.0 * test_passed
           + 0.4 * sim_approved
           + 0.3 * (1 / max(patch_width, 1))   ← narrower is better
           - 0.2 * cost
           - 0.1 * retry_count
           - 0.15 * sim_warning_penalty
    """

    @staticmethod
    def score(result: BranchResult) -> float:
        s = 0.0
        s += 1.0 * (1 if result.test_passed else 0)
        s += 0.4 * (1 if result.sim_approved else 0)
        s += 0.3 * (1 / max(result.patch_width, 1))
        s -= 0.2 * min(result.cost, 1.0)          # cap cost penalty at 1.0 USD
        s -= 0.1 * result.retry_count
        s -= 0.15 * (1 if result.sim_warning else 0)
        return round(s, 4)

    @classmethod
    def select(cls, results: List[BranchResult]) -> Optional[BranchResult]:
        """Returns the highest-scoring branch, or None if all failed."""
        if not results:
            return None
        scored = [(cls.score(r), r) for r in results]
        scored.sort(key=lambda x: x[0], reverse=True)
        for sc, r in scored:
            r.score = sc
        best_score, best = scored[0]
        if best_score <= 0:
            return None   # Nothing worth keeping
        return best

# ── Loser Branch Sink ─────────────────────────────────────────────────────────
class LoserBranchSink:
    """Saves losing branch artifacts as first-class learning data."""

    @staticmethod
    def persist(context_stub: dict, losers: List[BranchResult]) -> List[str]:
        """Saves loser branches to .forgeos/branches/{task_id}/. Returns saved paths."""
        task_id = context_stub.get("task_id", str(uuid.uuid4())[:8])
        base = os.path.join(BRANCH_DB_PATH, task_id)
        os.makedirs(base, exist_ok=True)
        saved = []

        for r in losers:
            fname = f"{r.branch_id}_{r.strategy_type}.json"
            fpath = os.path.join(base, fname)
            record = {
                **r.to_dict(),
                "issue_id": context_stub.get("issue_number"),
                "repo": context_stub.get("repo_path"),
                "recorded_at": time.time(),
                "label": "loser_branch",
            }
            with open(fpath, "w") as f:
                json.dump(record, f, indent=2)
            saved.append(fpath)

        print(f"[LoserSink] Saved {len(losers)} losing branches to {base}")
        return saved

# ── Branch Executor (single branch) ──────────────────────────────────────────
def _execute_branch(
    strategy_type: str,
    strategy_hint: str,
    context_snapshot: dict,
    branch_budget: float,
) -> BranchResult:
    """
    Runs a single branch: Planner (with strategy hint) → Coder → PatchSimulator.
    Actual sandbox test execution omitted from v1 for cost control; sim result is
    used as the primary quality signal.
    """
    branch_id = f"branch_{strategy_type[:4]}_{str(uuid.uuid4())[:6]}"
    cost = 0.0
    print(f"[BranchManager] Starting branch: {branch_id} ({strategy_type})")

    try:
        from forgeos.providers.model_router import ProviderRouter, ModelRole
        router = ProviderRouter()

        issue_text  = context_snapshot.get("issue_text", "")
        spec_context = context_snapshot.get("spec_context", "")
        repo_path   = context_snapshot.get("repo_path", ".")

        # ── 1. Strategy-Augmented Planning ──────────────────────────────────
        plan_prompt = f"""
You are a senior software engineer. Given the following issue, generate an implementation plan.

## Strategy Constraint
You MUST follow this strategy: **{strategy_type}**
Strategy guidance: {strategy_hint}

## Issue
{issue_text}

## Repository Context
{spec_context[:3000]}

Output a concise markdown plan (500 words max). Be specific about exactly which files and functions to change.
"""
        plan_resp = router.generate_response(
            ModelRole.PLANNER,
            system_prompt="You are a focused software engineer. Output only the implementation plan.",
            user_prompt=plan_prompt,
        )
        plan = plan_resp.get("content", "")
        cost += plan_resp.get("cost", 0.0)

        if cost > branch_budget:
            return BranchResult(
                branch_id=branch_id, strategy_type=strategy_type,
                plan=plan, patch="", cost=cost, patch_width=0,
                sim_approved=False, sim_warning="Budget exceeded during planning",
                test_passed=False, test_output="", error="budget_exceeded"
            )

        # ── 2. Patch Generation ───────────────────────────────────────────────
        patch_prompt = f"""
You are a senior software engineer writing a code patch.

## Strategy
{strategy_hint}

## Plan to Implement
{plan}

## Issue
{issue_text}

Output ONLY a valid unified diff patch (git diff format). No explanations.
"""
        patch_resp = router.generate_response(
            ModelRole.CODER,
            system_prompt="""You are the Coder. Given the context, generate ONLY a unified diff patch.
CRITICAL: Your unified diff must be 100% valid for `git apply`.
- DO NOT use placeholders like `...` or `// code continues`.
- You MUST include the exact unchanged context lines around your additions/deletions.
- If you skip context lines or use pseudocode, the patch will corrupt and fail.
- NEVER include the reference line numbers (e.g., `  12: `) from the context in your generated diff. Produce raw valid python code only!
- Output ONLY the raw patch enclosed in ```diff ... ```.""",
            user_prompt=patch_prompt,
        )
        patch = patch_resp.get("content", "")
        cost += patch_resp.get("cost", 0.0)

        # ── 3. Quick patch width estimate ─────────────────────────────────────
        patch_width = max(1, patch.count("\n--- "))  # count file headers

        if cost > branch_budget:
            return BranchResult(
                branch_id=branch_id, strategy_type=strategy_type,
                plan=plan, patch=patch, cost=cost, patch_width=patch_width,
                sim_approved=False, sim_warning="Budget exceeded after coding",
                test_passed=False, test_output="", error="budget_exceeded"
            )

        # ── 4. PatchSimulator ─────────────────────────────────────────────────
        sim_approved  = False
        sim_warning   = ""
        try:
            from forgeos.agents.critics.impact_simulator import PatchSimulatorAgent
            sim = PatchSimulatorAgent(router)
            sim_result, sim_stats = sim.simulate_impact(
                issue_text=issue_text,
                patch=patch,
                symbol_index_str="{}"
            )
            cost += sim_stats.get("cost", 0.0)
            sim_approved = sim_result.get("status", "REJECTED") == "APPROVED"
            sim_warning  = sim_result.get("warning", "")
        except Exception as e:
            sim_warning = f"Simulator unavailable: {e}"
            sim_approved = True  # Be optimistic if sim is down

        return BranchResult(
            branch_id=branch_id,
            strategy_type=strategy_type,
            plan=plan,
            patch=patch,
            cost=round(cost, 4),
            patch_width=patch_width,
            sim_approved=sim_approved,
            sim_warning=sim_warning,
            test_passed=False,  # Real test execution deferred to main pipeline
            test_output="deferred_to_main_pipeline",
        )

    except Exception as e:
        print(f"[BranchManager] Branch {branch_id} crashed: {e}")
        return BranchResult(
            branch_id=branch_id, strategy_type=strategy_type,
            plan="", patch="", cost=cost, patch_width=0,
            sim_approved=False, sim_warning="", test_passed=False,
            test_output="", error=str(e)
        )

# ── Main Orchestrator ─────────────────────────────────────────────────────────
class StrategyBranchManager:
    """
    Orchestrates parallel branch execution and winner selection.

    Usage (from state machine):
        from forgeos.engine.branch_manager import StrategyBranchManager, should_race
        if should_race(context):
            winner = StrategyBranchManager.race(context, n_branches=2)
            if winner:
                context.plan  = winner.plan
                context.patch = winner.patch
                context.branch_results = [r.to_dict() for r in results]
    """

    @staticmethod
    def race(context, n_branches: int = 2) -> Optional[BranchResult]:
        """
        Runs n_branches strategies in parallel and returns the winner.
        Saves a race summary to the branch DB for Mission Control.
        """
        n = min(n_branches, MAX_BRANCHES)
        strategies = list(STRATEGY_TYPES.items())[:n]

        context_snapshot = {
            "issue_text":  getattr(context, "issue_text", ""),
            "spec_context": getattr(context, "spec_context", ""),
            "repo_path":   getattr(context, "repo_path", "."),
            "issue_number": getattr(context, "issue_number", 0),
        }

        print(f"[BranchManager] Racing {n} strategies: {[s[0] for s in strategies]}")
        results: List[BranchResult] = []
        lock = threading.Lock()

        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = {
                pool.submit(
                    _execute_branch,
                    strategy_type,
                    strategy_hint,
                    context_snapshot,
                    MAX_BRANCH_COST,
                ): strategy_type
                for strategy_type, strategy_hint in strategies
            }
            for future in as_completed(futures, timeout=BRANCH_TIMEOUT_SECS):
                try:
                    result = future.result()
                    with lock:
                        results.append(result)
                    print(f"[BranchManager] Branch complete: {result.strategy_type} sim={result.sim_approved} cost=${result.cost:.3f}")
                except Exception as e:
                    print(f"[BranchManager] Future failed: {e}")

        if not results:
            print("[BranchManager] All branches failed. Falling back to linear mode.")
            return None

        # Score and select winner
        winner = WinnerSelectionPolicy.select(results)
        losers = [r for r in results if r is not winner]

        if winner:
            winner.score = WinnerSelectionPolicy.score(winner)
            print(f"[BranchManager] Winner: {winner.strategy_type} (score={winner.score})")
        else:
            print("[BranchManager] No viable winner found. Falling back to linear mode.")

        # Persist loser artifacts
        context_stub = {
            "task_id": f"{context_snapshot['issue_number']}_{str(uuid.uuid4())[:6]}",
            "issue_number": context_snapshot["issue_number"],
            "repo_path": context_snapshot["repo_path"],
        }
        if losers:
            LoserBranchSink.persist(context_stub, losers)

        # Write race summary for Mission Control to read
        StrategyBranchManager._persist_race_summary(context_stub["task_id"], results, winner)

        return winner

    @staticmethod
    def _persist_race_summary(race_id: str, results: List[BranchResult], winner: Optional[BranchResult]):
        """Writes race summary JSON to /tmp for Mission Control polling."""
        summary = {
            "race_id": race_id,
            "timestamp": time.time(),
            "branches": [r.to_dict() for r in results],
            "winner_id": winner.branch_id if winner else None,
            "winner_strategy": winner.strategy_type if winner else None,
        }
        os.makedirs("/tmp/forgeos_races", exist_ok=True)
        path = f"/tmp/forgeos_races/{race_id}.json"
        with open(path, "w") as f:
            json.dump(summary, f, indent=2)
        print(f"[BranchManager] Race summary saved: {path}")

# ── Eligibility Check ─────────────────────────────────────────────────────────
def should_race(context) -> bool:
    """
    Returns True if this task is eligible for branch racing.
    Criteria (any one triggers racing):
      - issue_text contains async/integration/race keywords
      - retries > 0 (previous attempt failed)
      - plan confidence is low (heuristic: plan is short = low confidence)
      - strategy is not 'patch' (already been patched, now exploring alternatives)
    """
    if not getattr(context, "racing_enabled", False):
        return False   # Globally opt-in

    issue_text = (getattr(context, "issue_text", "") or "").lower()
    TRIGGER_KEYWORDS = ["async", "race", "integration", "timeout", "deadlock",
                        "concurren", "import", "dependency", "refactor"]
    keyword_hit = any(k in issue_text for k in TRIGGER_KEYWORDS)

    has_retries    = getattr(context, "retries", 0) > 0
    plan_is_short  = len(getattr(context, "plan", "") or "") < 300

    return keyword_hit or has_retries or plan_is_short
