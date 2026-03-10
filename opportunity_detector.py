"""
opportunity_detector.py
========================
Detects improvement opportunities for ForgeOS from three signal sources:
  1. failure_db   — recurring patch/execution failures
  2. telemetry    — expensive or high-retry states
  3. backlog      — epics that repeatedly fail to execute

Each detector returns a list of OpportunitySignal dicts.
"""
from __future__ import annotations
import json
import os
import glob
from collections import Counter, defaultdict
from typing import Any


# ── Signal schema ─────────────────────────────────────────────────────────────
def _signal(source: str, signature: str, title: str, description: str,
            frequency: int, severity: float, metadata: dict) -> dict:
    return {
        "source":      source,
        "signature":   signature,
        "title":       title,
        "description": description,
        "frequency":   frequency,
        "severity":    severity,   # 0.0 – 1.0
        "metadata":    metadata,
    }


# ── 1. Failure DB ─────────────────────────────────────────────────────────────
def detect_from_failure_db(failure_db_path: str, top_n: int = 8) -> list[dict]:
    """
    Reads every *.json in failure_db and groups by failure_signature.
    Returns the top_n most frequent failure types as OpportunitySignals.
    """
    signals: list[dict] = []
    freq: Counter = Counter()
    examples: dict[str, list[dict]] = defaultdict(list)

    pattern = os.path.join(failure_db_path, "*.json")
    for path in glob.glob(pattern):
        try:
            with open(path) as f:
                rec = json.load(f)
        except Exception:
            continue

        sig = rec.get("failure_signature", "unknown")
        freq[sig] += 1
        if len(examples[sig]) < 2:
            examples[sig].append(rec)

    SEVERITY_MAP = {
        "malformed_patch":      0.9,
        "corrupt_patch":        0.9,
        "patch_too_wide":       0.7,
        "async_missing_await":  0.85,
        "git_apply":            0.8,
        "patch_corruption":     0.85,
        "dependency_conflict":  0.6,
        "environment_error":    0.75,
        "test_timeout":         0.6,
        "unknown":              0.5,
    }

    DESCRIPTION_MAP = {
        "malformed_patch": (
            "Coder generates unified diffs with missing count fields in hunk headers "
            "(e.g. '@@ -132,6 +137' instead of '@@ -132,6 +137,8 @@'). "
            "Fix: add patch sanitizer in state_machine.handle_patch that normalizes hunk headers "
            "before writing to disk."
        ),
        "corrupt_patch": (
            "Patch file is syntactically corrupt — git apply and GNU patch both reject it. "
            "Root cause: LLM produces partial hunks or missing context lines. "
            "Fix: validate patch structure before apply; auto-repair or retry with tighter prompt."
        ),
        "patch_too_wide": (
            "Patch modifies more files/lines than the impact estimator allows. "
            "Fix: tighten Coder prompt to produce minimal, surgical changes."
        ),
        "async_missing_await": (
            "Coder generates sync calls to async functions, leaving coroutines unawaited. "
            "Fix: add static await-checker in ExecutionCritic before applying patch."
        ),
        "git_apply": (
            "git apply fails because patch context lines don't match current file content. "
            "Fix: fetch current file content and include it in Coder context window."
        ),
    }

    for sig, count in freq.most_common(top_n):
        base_sig = next((k for k in DESCRIPTION_MAP if k in sig), sig)
        title_map = {
            "malformed_patch":      "Fix Malformed Patch Hunk Headers in Coder Output",
            "corrupt_patch":        "Add Patch Corruption Guard Before git apply",
            "patch_too_wide":       "Enforce Surgical Patch Width in Coder Prompt",
            "async_missing_await":  "Add Static Await-Checker in ExecutionCritic",
            "git_apply":            "Include Current File Content in Coder Context",
        }
        title = title_map.get(base_sig, f"Fix recurring failure: {sig}")
        desc  = DESCRIPTION_MAP.get(base_sig, f"Recurring failure signature: {sig}. Count: {count}.")

        signals.append(_signal(
            source="failure_db",
            signature=sig,
            title=title,
            description=desc,
            frequency=count,
            severity=SEVERITY_MAP.get(base_sig, 0.5),
            metadata={"examples": examples[sig], "failure_db_path": failure_db_path},
        ))

    return signals


# ── 2. Telemetry ──────────────────────────────────────────────────────────────
def detect_from_telemetry(telemetry_path: str, top_n: int = 5) -> list[dict]:
    """
    Reads telemetry log and detects states with high cost or high retry rates.
    """
    signals: list[dict] = []
    if not os.path.exists(telemetry_path):
        return signals

    cost_by_state:   defaultdict[str, float] = defaultdict(float)
    count_by_state:  defaultdict[str, int]   = defaultdict(int)
    retry_events:    Counter = Counter()

    try:
        with open(telemetry_path) as f:
            for line in f:
                try:
                    ev = json.loads(line.strip())
                except Exception:
                    continue

                state = ev.get("state", "UNKNOWN")
                etype = ev.get("event_type", "")

                if etype == "api_cost":
                    cost  = ev.get("metadata", {}).get("cost", 0.0)
                    cost_by_state[state]  += cost
                    count_by_state[state] += 1

                elif etype in ("retry_budget_exceeded", "state_retry"):
                    retry_events[state] += 1
    except Exception:
        return signals

    # High-cost states
    for state, total_cost in sorted(cost_by_state.items(), key=lambda x: -x[1])[:top_n]:
        if total_cost < 0.05:
            continue
        count = count_by_state[state] or 1
        avg   = total_cost / count
        signals.append(_signal(
            source="telemetry",
            signature=f"high_cost_{state.lower()}",
            title=f"Reduce LLM Cost in {state} State",
            description=(
                f"State {state} has accumulated ${total_cost:.3f} across {count} calls "
                f"(avg ${avg:.4f}/call). "
                f"Fix: add prompt compression, reduce repo_map size, or cache repeated calls."
            ),
            frequency=count,
            severity=min(total_cost * 5, 1.0),
            metadata={"state": state, "total_cost_usd": total_cost, "avg_cost_usd": avg},
        ))

    # High-retry states
    for state, retries in retry_events.most_common(3):
        if retries < 3:
            continue
        signals.append(_signal(
            source="telemetry",
            signature=f"high_retry_{state.lower()}",
            title=f"Reduce Retry Rate From {state} State",
            description=(
                f"State {state} has triggered {retries} retry events. "
                f"Suggests systematic failure in this state. Investigate root cause and add guard."
            ),
            frequency=retries,
            severity=0.7,
            metadata={"state": state, "retry_count": retries},
        ))

    return signals


# ── 3. Backlog failures ────────────────────────────────────────────────────────
def detect_from_backlog(backlog_path: str) -> list[dict]:
    """
    Finds epics that have status='failed' — systemic inability to execute certain epic types.
    """
    signals: list[dict] = []
    if not os.path.exists(backlog_path):
        return signals

    try:
        with open(backlog_path) as f:
            backlog = json.load(f)
    except Exception:
        return signals

    failed = [ep for ep in backlog if ep.get("status") == "failed"]
    if not failed:
        return signals

    # Group by risk_zone
    high_risk_failed = [e for e in failed if e.get("risk_zone") == "red"]
    repeated_titles  = [e["title"] for e in failed]

    if len(failed) >= 3:
        signals.append(_signal(
            source="backlog",
            signature="systemic_execution_failure",
            title="Investigate Systemic Execution Failure Patterns",
            description=(
                f"{len(failed)} epics have status=failed: {', '.join(ep['id'] for ep in failed[:5])}. "
                f"This suggests a systemic issue in the execution pipeline. "
                f"Investigate common failure modes and add pre-execution validation."
            ),
            frequency=len(failed),
            severity=0.8,
            metadata={"failed_epics": [e["id"] for e in failed], "titles": repeated_titles},
        ))

    return signals


# ── Combined detector ─────────────────────────────────────────────────────────
def detect_all_opportunities(
    forgeos_root: str,
    backlog_path: str,
    telemetry_path: str = "/tmp/forgeos_telemetry.log",
    top_n: int = 10,
) -> list[dict]:
    """
    Runs all three detectors and returns combined, deduplicated signals sorted by score.
    """
    from opportunity_scorer import score_signal

    failure_db = os.path.join(forgeos_root, "forgeos", "memory", "failure_db")
    all_signals: list[dict] = []

    all_signals += detect_from_failure_db(failure_db, top_n=top_n)
    all_signals += detect_from_telemetry(telemetry_path, top_n=5)
    all_signals += detect_from_backlog(backlog_path)

    # Deduplicate by signature
    seen: set[str] = set()
    deduped: list[dict] = []
    for s in all_signals:
        if s["signature"] not in seen:
            seen.add(s["signature"])
            deduped.append(s)

    # Score and sort
    for s in deduped:
        s["score"] = score_signal(s)

    deduped.sort(key=lambda x: -x["score"])
    return deduped[:top_n]
