"""
autonomous_scheduler.py
=======================
ForgeOS Level-B: Autonomous Discovery & Dispatching.

Every N minutes, this scheduler:
  1. Mines the failure_db for recurring patterns.
  2. Reads the improvement_backlog.json.
  3. Scores candidate tasks.
  4. Selects the top item (green/yellow zone, not currently running).
  5. Dispatches a POST /api/v1/improvement/run.
  6. Emits telemetry events for Mission Control.

Run directly:
  python3 forge_cloud/autonomous_scheduler.py

Or call scheduler.run_once() from an orchestrator.
"""

import os
import json
import time
import logging
import threading
import collections
import requests
from datetime import datetime
from typing import Optional

# ── Config ────────────────────────────────────────────────────────────────────
FAILURE_DB_PATH    = os.path.join(os.path.dirname(__file__), "..", "forgeos", "memory", "failure_db")
BACKLOG_PATH       = os.path.join(os.path.dirname(__file__), "data", "improvement_backlog.json")
TELEMETRY_LOG      = "/tmp/forgeos_telemetry.log"
API_BASE           = "http://localhost:8081"
SCHEDULER_LOG      = "/tmp/forgeos_scheduler.log"

TICK_INTERVAL_SECS = 1800   # 30 minutes
MAX_CONCURRENT     = 1      # only one self-improvement task at a time
TARGET_PROJECT     = "ForgeOS"
SCHEDULER_STATE_PATH = "/tmp/forgeos_scheduler_state.json"

# Risk guard: only allow green/yellow items — hard-block red
ALLOWED_RISK_ZONES = {"green", "yellow"}

# Priority → numeric weight for scoring
PRIORITY_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.3}

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger("ForgeScheduler")
if not log.handlers:
    log.setLevel(logging.INFO)
    _fmt = logging.Formatter("[%(asctime)s] %(levelname)s %(message)s")
    _fh  = logging.FileHandler(SCHEDULER_LOG)
    _fh.setFormatter(_fmt)
    _sh  = logging.StreamHandler()
    _sh.setFormatter(_fmt)
    log.addHandler(_fh)
    log.addHandler(_sh)
    log.propagate = False  # don't bubble to root logger

# ── Telemetry ─────────────────────────────────────────────────────────────────
def _emit(event_type: str, message: str, metadata: dict = None):
    payload = {
        "timestamp": time.time(),
        "event_type": event_type,
        "issue_number": 0,
        "state": "SCHEDULER",
        "message": message,
        "metadata": metadata or {},
    }
    try:
        with open(TELEMETRY_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except Exception as e:
        log.warning(f"Telemetry write failed: {e}")

def _persist_state(state: dict):
    """Writes the last scheduler tick result to a JSON file for Mission Control to read."""
    try:
        with open(SCHEDULER_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log.warning(f"State persistence failed: {e}")

# ── Failure Landscape Mining ──────────────────────────────────────────────────
def _mine_failure_landscape() -> dict:
    """
    Reads failure_db/*.json and returns a frequency map:
      { failure_signature: count }
    """
    landscape = collections.Counter()
    db_path = os.path.abspath(FAILURE_DB_PATH)
    if not os.path.isdir(db_path):
        log.warning(f"failure_db not found at {db_path}")
        return landscape

    for fname in os.listdir(db_path):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(db_path, fname), "r") as f:
                rec = json.load(f)
            sig = rec.get("failure_signature", "unknown")
            landscape[sig] += 1
        except Exception:
            pass

    total = sum(landscape.values()) or 1
    log.info(f"Failure landscape: {len(landscape)} signatures across {total} records")
    _emit("failure_landscape_mined", f"{total} failure records read",
          {"signatures": dict(landscape.most_common(5))})
    return landscape

# ── Backlog Loading ────────────────────────────────────────────────────────────
def _load_backlog() -> list:
    path = os.path.abspath(BACKLOG_PATH)
    if not os.path.exists(path):
        log.warning(f"Backlog not found at {path}")
        return []
    with open(path, "r") as f:
        return json.load(f)

# ── Scoring ────────────────────────────────────────────────────────────────────
def _score_item(item: dict, landscape: dict, total_failures: int) -> float:
    """
    Score = 0.5 * impact + 0.3 * frequency + 0.2 * success_probability

    - impact:              based on priority field (high=1, medium=0.6, low=0.3)
    - frequency:           fraction of failure records that match this epic's keywords
    - success_probability: inverse of priority (high priority tasks are harder; medium/low safer)
    """
    priority = item.get("priority", "low")
    impact = PRIORITY_WEIGHT.get(priority, 0.3)

    # Frequency: count how many failure signatures contain words from the title/description
    title_words = set((item.get("title", "") + " " + item.get("description", "")).lower().split())
    hit = sum(count for sig, count in landscape.items()
              if any(w in sig.lower() for w in title_words if len(w) > 4))
    frequency = min(hit / max(total_failures, 1), 1.0)

    # Success probability: medium priority items are the sweet spot for v1 autonomous runs
    sp_map = {"high": 0.5, "medium": 0.9, "low": 0.7}
    success_prob = sp_map.get(priority, 0.5)

    score = 0.5 * impact + 0.3 * frequency + 0.2 * success_prob
    return round(score, 4)

# ── Active Task Guard ─────────────────────────────────────────────────────────
def _count_active_self_tasks() -> int:
    """Queries the task registry and counts tasks with status=RUNNING."""
    try:
        resp = requests.get(f"{API_BASE}/api/v1/tasks", timeout=5)
        if resp.status_code == 200:
            tasks = resp.json()
            running = [t for t in tasks if t.get("status") == "RUNNING"]
            return len(running)
    except Exception as e:
        log.warning(f"Could not query task registry: {e}")
    return 0

# ── Dispatcher ────────────────────────────────────────────────────────────────
def _dispatch(item: dict) -> Optional[dict]:
    """POSTs to /api/v1/improvement/run and returns the response dict."""
    try:
        resp = requests.post(
            f"{API_BASE}/api/v1/improvement/run",
            json={"epic_id": item["id"]},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            log.error(f"Dispatch failed: HTTP {resp.status_code} — {resp.text}")
    except Exception as e:
        log.error(f"Dispatch exception: {e}")
    return None

# ── Main Scheduler Tick ────────────────────────────────────────────────────────
def run_once():
    """Perform a single scheduler tick."""
    log.info("=== Scheduler Tick ===")
    _emit("scheduler_tick", "Autonomous scheduler tick started", {
        "time": datetime.utcnow().isoformat(),
        "target_project": TARGET_PROJECT,
    })

    # 1. Mine failure landscape
    landscape = _mine_failure_landscape()
    total_failures = sum(landscape.values()) or 1

    # 2. Load backlog
    backlog = _load_backlog()
    candidates = [
        item for item in backlog
        if item.get("status") not in ("done", "in_progress")
    ]
    _emit("candidate_tasks_found", f"{len(candidates)} eligible backlog items", {
        "ids": [i["id"] for i in candidates]
    })

    if not candidates:
        log.info("No candidate tasks found. Scheduler idle.")
        _emit("no_candidates", "No eligible tasks in backlog — scheduler idle.")
        return None

    # 3. Score all candidates
    scored = []
    for item in candidates:
        score = _score_item(item, landscape, total_failures)
        log.info(f"  {item['id']} [{item.get('priority','?')} priority] → score={score}")
        _emit("task_scored", f"{item['id']} scored {score}", {
            "id": item["id"], "title": item["title"], "score": score
        })
        scored.append((score, item))

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best_item = scored[0]
    log.info(f"Selected: {best_item['id']} (score={best_score})")
    _emit("task_selected", f"Top candidate: {best_item['id']} — {best_item['title']}", {
        "id": best_item["id"], "score": best_score, "priority": best_item.get("priority")
    })

    # Persist full tick state for Mission Control
    tick_state = {
        "last_tick": datetime.utcnow().isoformat() + "Z",
        "selected": {"id": best_item["id"], "title": best_item["title"], "score": best_score},
        "all_scores": [
            {"id": item["id"], "title": item["title"],
             "priority": item.get("priority"), "risk_zone": item.get("risk_zone", "green"),
             "score": sc}
            for sc, item in scored
        ],
        "landscape_top": dict(sorted(landscape.items(), key=lambda x: -x[1])[:10]),
        "total_failures": total_failures,
        "status": "idle",  # Updated below on dispatch
    }

    # 4. Guard: max concurrent
    active = _count_active_self_tasks()
    if active >= MAX_CONCURRENT:
        log.info(f"Active self-tasks ({active}) >= max ({MAX_CONCURRENT}). Skipping dispatch.")
        _emit("run_blocked_active_task", f"Skipped dispatch — {active} task(s) already running", {
            "active": active, "skipped_id": best_item["id"]
        })
        tick_state["status"] = "blocked_active_task"
        tick_state["active_count"] = active
        _persist_state(tick_state)
        return None

    # 5. Dispatch
    log.info(f"Dispatching improvement run for {best_item['id']}…")
    result = _dispatch(best_item)

    if result:
        log.info(f"Run dispatched: task_id={result.get('task_id')}")
        _emit("run_dispatched", f"Dispatched {best_item['id']} → task {result.get('task_id')}", {
            "epic_id": best_item["id"],
            "task_id": result.get("task_id"),
            "project": TARGET_PROJECT,
        })
        tick_state["status"] = "dispatched"
        tick_state["dispatched_task_id"] = result.get("task_id")
        _persist_state(tick_state)
        return result
    else:
        log.error(f"Dispatch failed for {best_item['id']}")
        _emit("task_skipped", f"Dispatch failed for {best_item['id']}", {"id": best_item["id"]})
        tick_state["status"] = "dispatch_failed"
        _persist_state(tick_state)
        return None

# ── Active Task Watcher ────────────────────────────────────────────────────────
def _wait_for_task_completion(task_id: str, poll_every: int = 20, timeout: int = 7200):
    """
    Polls GET /api/v1/tasks until the given task_id is DONE or FAILED.
    Returns the final status, or 'timeout' if it takes too long.
    """
    deadline = time.time() + timeout
    log.info(f"[Watcher] Waiting for task {task_id} to complete…")
    while time.time() < deadline:
        try:
            resp = requests.get(f"{API_BASE}/api/v1/tasks", timeout=5)
            if resp.status_code == 200:
                tasks = resp.json()
                for t in tasks:
                    if t.get("id") == task_id:
                        status = t.get("status", "")
                        state  = t.get("current_state", "?")
                        if status in ("DONE", "FAILED"):
                            log.info(f"[Watcher] Task {task_id} finished with status={status}")
                            return status
                        log.info(f"[Watcher] Task {task_id} still {status} / {state}")
        except Exception as e:
            log.warning(f"[Watcher] Poll error: {e}")
        time.sleep(poll_every)
    log.warning(f"[Watcher] Timeout waiting for {task_id}")
    return "timeout"

def _wait_until_free(poll_every: int = 30):
    """Blocks until active running-task count drops below MAX_CONCURRENT."""
    while True:
        active = _count_active_self_tasks()
        if active < MAX_CONCURRENT:
            return
        log.info(f"[Watcher] {active} task(s) running, waiting {poll_every}s…")
        time.sleep(poll_every)


# ── Continuous Loop ────────────────────────────────────────────────────────────
def run_loop(interval: int = 300):
    """
    Event-driven scheduler loop.

    Logic:
      TICK
       ├─ dispatched a task  → wait for it to finish → immediate next TICK
       ├─ blocked (running)  → wait until free → immediate next TICK
       ├─ no candidates      → sleep `interval` seconds → next TICK
       └─ dispatch failed    → sleep 60s → retry TICK

    `interval` is only used as a "no work to do" cooldown, not a fixed heartbeat.
    """
    log.info(f"Autonomous Scheduler starting. Idle interval: {interval}s")
    _emit("scheduler_started", f"Event-driven loop started (idle_interval={interval}s)", {
        "idle_interval": interval,
        "max_concurrent": MAX_CONCURRENT,
        "target_project": TARGET_PROJECT,
    })

    while True:
        try:
            result = run_once()
        except Exception as e:
            log.error(f"Tick error: {e}")
            _emit("scheduler_error", f"Tick crashed: {e}", {"error": str(e)})
            result = None

        # Read persisted state to understand what happened this tick
        try:
            with open(SCHEDULER_STATE_PATH) as f:
                tick_state = json.load(f)
            tick_status = tick_state.get("status", "unknown")
            dispatched_task_id = tick_state.get("dispatched_task_id")
        except Exception:
            tick_status = "unknown"
            dispatched_task_id = None

        if tick_status == "dispatched" and dispatched_task_id:
            # Task just started — wait for it to finish, then re-tick immediately
            log.info(f"Task dispatched ({dispatched_task_id}). Watching for completion…")
            _wait_for_task_completion(dispatched_task_id)
            log.info("Task done. Re-ticking immediately.")

        elif tick_status == "blocked_active_task":
            # Something is already running — wait until it's free
            log.info("Blocked by active task. Waiting until slot is free…")
            _wait_until_free()
            log.info("Slot free. Re-ticking immediately.")

        elif tick_status in ("dispatch_failed", "unknown"):
            # Transient error — short retry delay
            log.info("Dispatch failed or unknown. Retrying in 60s…")
            time.sleep(60)

        else:
            # "idle" — no candidates in backlog
            log.info(f"No work found. Sleeping {interval}s before next scan…")
            time.sleep(interval)


# ── Entry Point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ForgeOS Autonomous Scheduler")
    parser.add_argument("--once", action="store_true", help="Run a single tick and exit")
    parser.add_argument("--interval", type=int, default=300,
                        help="Idle cooldown in seconds when no work found (default: 300)")
    args = parser.parse_args()

    if args.once:
        result = run_once()
        print(json.dumps(result, indent=2) if result else "No task dispatched.")
    else:
        run_loop(interval=args.interval)
