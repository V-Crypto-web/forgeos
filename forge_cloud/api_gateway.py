from fastapi import FastAPI, BackgroundTasks, HTTPException, WebSocket
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess
import os
import json
import asyncio
from uuid import uuid4
from datetime import datetime
from typing import Optional

# Load .env (GITHUB_TOKEN, model keys, etc.) before anything else
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"), override=True)
except ImportError:
    pass  # dotenv not installed — env vars must be set manually

app = FastAPI(title="ForgeOS Cloud Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the dashboard static files
dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard")
app.mount("/dashboard", StaticFiles(directory=dashboard_path, html=True), name="dashboard")

@app.get("/dashboard/")
async def serve_dashboard():
    return FileResponse(os.path.join(dashboard_path, "index.html"))

# ── Task Registry (persistent) ────────────────────────────────────────────────
TASK_REGISTRY_PATH = "/tmp/forgeos_task_registry.json"

class _PersistentRegistry(dict):
    """Dict subclass that auto-saves to disk on every write."""
    def __init__(self, path: str):
        super().__init__()
        self._path = path
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    self.update(json.load(f))
            except Exception:
                pass

    def _save(self):
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(dict(self), f, default=str)
        except Exception:
            pass

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._save()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._save()

TASK_REGISTRY: dict = _PersistentRegistry(TASK_REGISTRY_PATH)

def _make_task_record(task_id: str, repo: str, issue: int, mode: str) -> dict:
    now_iso = datetime.utcnow().isoformat() + "Z"
    return {
        "id": task_id,
        "repo": repo,
        "issue": issue,
        "mode": mode,
        "status": "RUNNING",
        "started_at": now_iso,
        "updated_at": now_iso,
        "last_progress_at": now_iso,
        "heartbeat_at": now_iso,
        "current_state": "INIT",
        "terminal_reason": None,
        "pr_url": None,
    }


# ── Request Models ─────────────────────────────────────────────────────────────
class ProjectCreateRequest(BaseModel):
    repo_url: str
    name: Optional[str] = None
    project_type: Optional[str] = "library"
    policies: Optional[dict] = None

class RunIssueRequest(BaseModel):
    repo_path: str
    issue_number: int
    mode: str = "supervised"

class ImprovementRunRequest(BaseModel):
    epic_id: str

class TaskActionRequest(BaseModel):
    action: str  # approve | reject | retry | halt | force_replan

# ── Engine Runner ──────────────────────────────────────────────────────────────
def _run_engine_background(repo_path: str, issue_number: int, task_id: str):
    """
    Runs the ForgeOS state machine in-process (background thread).
    Updates TASK_REGISTRY[task_id] in real time on every state transition
    so Mission Control can show live progress without waiting for completion.
    """
    TASK_REGISTRY[task_id]["status"] = "RUNNING"
    TASK_REGISTRY[task_id]["current_state"] = "INIT"

    try:
        from forgeos.engine.state_machine import StateMachine, ExecutionContext, EngineState

        context = ExecutionContext(
            repo_path=repo_path,
            github_url=TASK_REGISTRY[task_id].get("github_url", ""),
            issue_number=issue_number,
            strategy=TASK_REGISTRY[task_id].get("mode", "supervised"),
            racing_enabled=True,
        )


        sm = StateMachine()

        # ── Live state bridge ─────────────────────────────────────────────────
        # Monkey-patch log_and_record so EVERY transition is reflected in the UI
        _orig_log = sm.log_and_record
        def _live_log(ctx, message, event_type="state_transition", metadata=None):
            now = datetime.utcnow().isoformat() + "Z"
            TASK_REGISTRY[task_id]["updated_at"] = now
            
            if event_type == "task_heartbeat":
                TASK_REGISTRY[task_id]["heartbeat_at"] = now
            elif event_type == "task_progress" or event_type == "state_transition":
                TASK_REGISTRY[task_id]["last_progress_at"] = now
                TASK_REGISTRY[task_id]["heartbeat_at"] = now
                
            # Update registry with current state immediately
            TASK_REGISTRY[task_id]["current_state"] = ctx.current_state.value if hasattr(ctx.current_state, "value") else str(ctx.current_state)
            TASK_REGISTRY[task_id]["logs"] = ctx.logs[-50:]  # last 50 log lines
            return _orig_log(ctx, message, event_type=event_type, metadata=metadata)
        sm.log_and_record = _live_log

        # ── Run ───────────────────────────────────────────────────────────────
        final_ctx = sm.run(context)

        # Capture results into registry
        TASK_REGISTRY[task_id]["status"]        = "DONE" if final_ctx.current_state == EngineState.DONE else "FAILED"
        TASK_REGISTRY[task_id]["current_state"] = final_ctx.current_state.value
        TASK_REGISTRY[task_id]["plan"]          = final_ctx.plan
        TASK_REGISTRY[task_id]["patch"]         = final_ctx.patch
        TASK_REGISTRY[task_id]["pr_url"]        = getattr(final_ctx, "pr_url", None)
        TASK_REGISTRY[task_id]["global_cost"]   = final_ctx.global_cost
        TASK_REGISTRY[task_id]["branch_results"]= final_ctx.branch_results
        TASK_REGISTRY[task_id]["logs"]          = final_ctx.logs[-100:]
        TASK_REGISTRY[task_id]["had_race"]      = bool(final_ctx.branch_results)

    except Exception as e:
        TASK_REGISTRY[task_id]["status"]        = "FAILED"
        TASK_REGISTRY[task_id]["current_state"] = "FAILED"
        TASK_REGISTRY[task_id]["error"]         = str(e)
        import traceback
        TASK_REGISTRY[task_id]["traceback"]     = traceback.format_exc()


# ── Issue Run ─────────────────────────────────────────────────────────────────
@app.post("/api/v1/issues/run")
async def run_issue(req: RunIssueRequest, background_tasks: BackgroundTasks):
    """Spawns an asynchronous engine process to resolve an issue."""
    task_id = f"task_{req.issue_number}_{str(uuid4())[:8]}"
    record = _make_task_record(task_id, req.repo_path, req.issue_number, req.mode)
    TASK_REGISTRY[task_id] = record
    background_tasks.add_task(_run_engine_background, req.repo_path, req.issue_number, task_id)
    return record

# ── Task Registry Endpoints ───────────────────────────────────────────────────
@app.get("/api/v1/tasks")
async def list_tasks():
    """Returns all tasks, newest first."""
    tasks = sorted(TASK_REGISTRY.values(), key=lambda t: t["started_at"], reverse=True)
    return tasks

@app.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str):
    """Returns a single task record."""
    if task_id not in TASK_REGISTRY:
        raise HTTPException(status_code=404, detail="Task not found")
    return TASK_REGISTRY[task_id]

@app.get("/api/v1/tasks/{task_id}/artifacts")
async def get_task_artifacts(task_id: str):
    """Returns any persisted artifacts for this task (plan, patch, test results)."""
    if task_id not in TASK_REGISTRY:
        raise HTTPException(status_code=404, detail="Task not found")
    record = TASK_REGISTRY[task_id]
    issue = record.get("issue", 0)
    repo = record.get("repo", "")

    artifacts_dir = os.path.join(repo, ".forgeos", "artifacts", str(issue))
    if not os.path.isdir(artifacts_dir):
        return {"plan": None, "patch": None, "test_results": None, "impact_report": None}

    def _read(fname):
        p = os.path.join(artifacts_dir, fname)
        if os.path.exists(p):
            return open(p, "r", encoding="utf-8").read()
        return None

    return {
        "plan": _read("plan.md"),
        "patch": _read("patch.diff"),
        "test_results": _read("test_results.json"),
        "impact_report": _read("impact_report.json"),
    }

@app.post("/api/v1/tasks/{task_id}/action")
async def task_action(task_id: str, req: TaskActionRequest):
    """Applies a manual control action to a running task."""
    if task_id not in TASK_REGISTRY:
        raise HTTPException(status_code=404, detail="Task not found")
    # In MVP, we update the registry and let the engine poll it on next state transition.
    TASK_REGISTRY[task_id]["pending_action"] = req.action
    return {"task_id": task_id, "action": req.action, "status": "accepted"}

# ── Self-Improvement Run ──────────────────────────────────────────────────────
@app.post("/api/v1/improvement/run")
async def run_improvement(req: ImprovementRunRequest, background_tasks: BackgroundTasks):
    """
    Dispatches a self-improvement engine run for the given epic.
    Uses `repo_path` (local) for engine execution (tests run with existing .venv).
    Uses `repo_url` (GitHub) for issue fetching + PR creation metadata.
    Falls back to local ForgeAI path if neither is specified.
    """
    path = "/Users/vasiliyprachev/Python_Projects/ForgeAI/forge_cloud/data/improvement_backlog.json"
    if os.path.exists(path):
        with open(path, "r") as f:
            backlog = json.load(f)
        target = next((item for item in backlog if item["id"] == req.epic_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="Epic not found")

        # Local path for execution (has working .venv + dependencies)
        # GitHub URL stored separately for issue fetch + PR creation
        LOCAL_FORGEOS = "/Users/vasiliyprachev/Python_Projects/ForgeAI"
        exec_path    = target.get("repo_path") or LOCAL_FORGEOS
        github_url   = target.get("repo_url", "")
        issue_number = target.get("github_issue", 0)

        task_id = f"task_self_{req.epic_id.replace('-', '_')}_{str(uuid4())[:8]}"
        record = _make_task_record(task_id, exec_path, issue_number, "supervised")
        record["epic_id"]    = req.epic_id
        record["epic_title"] = target.get("title", "")
        record["github_url"] = github_url   # stored for PR creation
        TASK_REGISTRY[task_id] = record
        background_tasks.add_task(_run_engine_background, exec_path, issue_number, task_id)
        return {
            "status": "accepted",
            "task_id": task_id,
            "message": f"Self-Improvement loop started for {req.epic_id}",
            "repo": exec_path,
            "github_url": github_url,
            "issue": issue_number,
        }
    raise HTTPException(status_code=500, detail="Backlog database missing")



# ── SSE & WebSocket Streams ───────────────────────────────────────────────────
async def _sse_generator():
    log_file = "/tmp/forgeos_telemetry.log"
    if not os.path.exists(log_file):
        open(log_file, 'a').close()
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.5)
                    continue
                yield f"data: {line.strip()}\n\n"
    except asyncio.CancelledError:
        pass

@app.get("/api/v1/engine/stream")
async def sse_logs():
    """SSE endpoint for live state transitions."""
    return StreamingResponse(_sse_generator(), media_type="text/event-stream")

@app.websocket("/api/v1/logs/stream")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    log_file = "/tmp/forgeos_telemetry.log"
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            for line in f:
                if line.strip():
                    await websocket.send_text(line.strip())
    try:
        with open(log_file, "r") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.5)
                    continue
                await websocket.send_text(line.strip())
    except Exception as e:
        print(f"WebSocket Error: {e}")
        await websocket.close()

# ── Project Registry ──────────────────────────────────────────────────────────
REGISTRY_PATH = "/Users/vasiliyprachev/Python_Projects/ForgeAI/forge_cloud/data/project_registry.json"

@app.get("/api/v1/projects")
def get_projects():
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH, "r") as f:
            return json.load(f)
    return []

@app.post("/api/v1/projects/create")
async def create_project(req: ProjectCreateRequest):
    """Registers a new project in project_registry.json."""
    projects = []
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH, "r") as f:
            projects = json.load(f)
    new_project = {
        "id": str(uuid4())[:8],
        "name": req.name or req.repo_url.split("/")[-1],
        "repo_url": req.repo_url,
        "repo_name": req.repo_url.split("/")[-1],
        "type": req.project_type,
        "description": f"Added {datetime.utcnow().strftime('%Y-%m-%d')}",
        "policies": req.policies or {}
    }
    projects.append(new_project)
    with open(REGISTRY_PATH, "w") as f:
        json.dump(projects, f, indent=2)
    return new_project

# ── Backlog & OmniBench ───────────────────────────────────────────────────────
@app.get("/api/v1/backlog")
def get_backlog():
    path = "/Users/vasiliyprachev/Python_Projects/ForgeAI/forge_cloud/data/improvement_backlog.json"
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []

@app.get("/api/v1/omnibench")
def get_omnibench_baseline():
    path = "/Users/vasiliyprachev/.gemini/antigravity/brain/7770d7d4-fee2-4acc-b7f8-248abb7e8762/omnibench_baseline.yaml"
    if os.path.exists(path):
        return {"baseline_yaml": open(path, "r", encoding="utf-8").read()}
    return {"baseline_yaml": "Baseline data not found."}

# ── Repo Architecture ─────────────────────────────────────────────────────────
@app.get("/api/v1/repo/architecture")
def get_repo_architecture():
    import glob
    search_paths = [
        "/Users/vasiliyprachev/Python_Projects/ForgeAI/.forgeos/cache/*/*/repo_map.json",
        "/Users/vasiliyprachev/Python_Projects/ForgeAI/forge_bench/data/django/.forgeos/cache/*/*/repo_map.json",
        "/Users/vasiliyprachev/Python_Projects/ForgeAI/forge_bench/data/starlette/.forgeos/cache/*/*/repo_map.json"
    ]
    for pattern in search_paths:
        matches = glob.glob(pattern)
        if matches:
            latest_map = sorted(matches, key=os.path.getmtime, reverse=True)[0]
            try:
                with open(latest_map, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return {
        "src/main.py": {"classes": ["App"], "functions": ["run"]},
        "src/utils.py": {"classes": [], "functions": ["helper1", "helper2"]}
    }

SCHEDULER_PID_FILE = "/tmp/forgeos_scheduler.pid"
SCHEDULER_SCRIPT   = os.path.join(os.path.dirname(__file__), "autonomous_scheduler.py")

def _scheduler_is_running() -> bool:
    """Returns True if the scheduler process is alive."""
    if not os.path.exists(SCHEDULER_PID_FILE):
        return False
    try:
        pid = int(open(SCHEDULER_PID_FILE).read().strip())
        os.kill(pid, 0)   # signal 0 = just check existence
        return True
    except (ProcessLookupError, ValueError, OSError):
        return False

@app.get("/api/v1/telemetry/history")
def get_telemetry_history(n: int = 200):
    """Returns the last N telemetry log lines as a JSON array for UI pre-loading."""
    log_path = "/tmp/forgeos_telemetry.log"
    if not os.path.exists(log_path):
        return []
    lines = []
    with open(log_path, "r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                lines.append(raw)
    return lines[-n:]

@app.get("/api/v1/scheduler/status")
def get_scheduler_status():
    """Returns the last scheduler tick state plus process_running flag."""
    state = {"status": "never_run", "last_tick": None, "all_scores": [], "landscape_top": {}}
    path = "/tmp/forgeos_scheduler_state.json"
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
                
            # Detect Stale Scheduler
            if state.get("last_tick") and state.get("status") == "active":
                from datetime import datetime
                # Parse the ISO format string 
                tick_time = datetime.fromisoformat(state["last_tick"].replace("Z", "+00:00")).replace(tzinfo=None)
                now = datetime.utcnow()
                
                # Assume default interval is 1800 if not injected into state, buffer x2
                interval = state.get("interval", 1800) 
                if (now - tick_time).total_seconds() > interval * 2.5:
                    state["status"] = "stale"
                    
        except Exception:
            pass
            
    state["process_running"] = _scheduler_is_running()
    return state


@app.post("/api/v1/scheduler/start")
def start_scheduler(interval: int = 1800):
    """Starts the autonomous_scheduler.py in the background."""
    if _scheduler_is_running():
        return {"ok": False, "message": "Scheduler already running"}
    env = {**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(__file__))}
    proc = subprocess.Popen(
        ["python3", SCHEDULER_SCRIPT, "--interval", str(interval)],
        env=env,
        stdout=open("/tmp/forgeos_scheduler.log", "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,   # detach from parent
    )
    with open(SCHEDULER_PID_FILE, "w") as f:
        f.write(str(proc.pid))
    return {"ok": True, "pid": proc.pid, "message": f"Scheduler started (PID {proc.pid}, interval {interval}s)"}

@app.post("/api/v1/scheduler/stop")
def stop_scheduler():
    """Stops the running scheduler process."""
    if not _scheduler_is_running():
        return {"ok": False, "message": "Scheduler is not running"}
    try:
        pid = int(open(SCHEDULER_PID_FILE).read().strip())
        os.kill(pid, 15)   # SIGTERM
        os.remove(SCHEDULER_PID_FILE)
        return {"ok": True, "message": f"Scheduler stopped (PID {pid})"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/api/v1/races")
def list_races():
    """Returns all branch race summaries (newest first)."""
    races_dir = "/tmp/forgeos_races"
    if not os.path.isdir(races_dir):
        return []
    results = []
    for fname in sorted(os.listdir(races_dir), reverse=True):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(races_dir, fname)) as f:
                results.append(json.load(f))
        except Exception:
            pass
    return results


@app.get("/api/v1/metrics/racing")
def get_racing_metrics():
    """
    Computes aggregate Branch Racing analytics from all race summary files.
    Returns:
      - races_total, win_rate, winner_strategy_distribution
      - avg_branches_per_race, avg_race_cost
      - linear vs racing comparison (derived from task registry)
    """
    races_dir = "/tmp/forgeos_races"
    races = []
    if os.path.isdir(races_dir):
        for fname in os.listdir(races_dir):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(races_dir, fname)) as f:
                    races.append(json.load(f))
            except Exception:
                pass

    races_total = len(races)
    if races_total == 0:
        return {
            "races_total": 0,
            "win_rate": 0.0,
            "winner_strategy_distribution": {},
            "avg_branches_per_race": 0.0,
            "avg_race_cost": 0.0,
            "races_with_winner": 0,
            "races_no_winner": 0,
            "linear": {"tasks": 0, "done": 0, "failed": 0, "success_rate": 0.0, "avg_cost": 0.0},
            "racing": {"tasks": races_total, "done": 0, "failed": 0, "success_rate": 0.0, "avg_cost": 0.0},
        }

    # Per-race aggregations
    races_with_winner = sum(1 for r in races if r.get("winner_id"))
    win_rate = round(races_with_winner / races_total, 3) if races_total else 0.0

    strategy_wins: dict = {}
    total_branches = 0
    total_race_cost = 0.0
    for race in races:
        ws = race.get("winner_strategy")
        if ws:
            strategy_wins[ws] = strategy_wins.get(ws, 0) + 1
        branches = race.get("branches", [])
        total_branches += len(branches)
        total_race_cost += sum(b.get("cost", 0.0) for b in branches)

    avg_branches = round(total_branches / races_total, 2) if races_total else 0.0
    avg_race_cost = round(total_race_cost / races_total, 4) if races_total else 0.0

    # Linear vs Racing — use TASK_REGISTRY to separate racing tasks from linear ones
    # Racing tasks are those that went through BRANCH_RACE state (log contains BRANCH_RACE)
    linear_tasks = [t for t in TASK_REGISTRY.values() if not t.get("had_race")]
    racing_tasks = [t for t in TASK_REGISTRY.values() if t.get("had_race")]

    def _mode_stats(tasks):
        n = len(tasks)
        done = sum(1 for t in tasks if t.get("status") == "DONE")
        fail = sum(1 for t in tasks if t.get("status") == "FAILED")
        return {
            "tasks": n,
            "done": done,
            "failed": fail,
            "success_rate": round(done / n, 3) if n else 0.0,
            "avg_cost": 0.0,  # cost stored in context, not yet persisted to registry
        }

    return {
        "races_total": races_total,
        "win_rate": win_rate,
        "winner_strategy_distribution": strategy_wins,
        "avg_branches_per_race": avg_branches,
        "avg_race_cost": avg_race_cost,
        "races_with_winner": races_with_winner,
        "races_no_winner": races_total - races_with_winner,
        "linear": _mode_stats(linear_tasks),
        "racing": _mode_stats(racing_tasks),
    }


@app.get("/api/v1/tasks/{task_id}/branches")
def get_task_branches(task_id: str):
    """Returns branch racing results for a task if available."""
    races_dir = "/tmp/forgeos_races"
    if not os.path.isdir(races_dir):
        return {"branches": [], "winner_id": None}
    # Match by task_id prefix in race files
    for fname in os.listdir(races_dir):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(races_dir, fname)) as f:
                data = json.load(f)
            if task_id in fname or task_id in data.get("race_id", ""):
                return data
        except Exception:
            pass
    return {"branches": [], "winner_id": None}


# ── Background Task Reaper ────────────────────────────────────────────────────
async def _task_reaper_loop():
    """Periodically scans TASK_REGISTRY for tasks that have stalled without terminal states."""
    from datetime import timezone
    while True:
        try:
            now = datetime.utcnow()
            for task_id, record in list(TASK_REGISTRY.items()):
                if record.get("status") == "RUNNING":
                    hb_str = record.get("heartbeat_at") or record.get("started_at")
                    if not hb_str:
                        continue
                    try:
                        # parse ISO datetime (replace Z for fromisoformat compatibility in 3.10)
                        hb_time = datetime.fromisoformat(hb_str.replace("Z", "+00:00")).replace(tzinfo=None)
                        elapsed = (now - hb_time).total_seconds()
                        
                        # Timers based on Epic G Requirements
                        timeout = 1800 # default 30 mins
                        if record.get("current_state") == "INIT":
                            timeout = 60
                        elif record.get("current_state") == "PLAN":
                            timeout = 180
                        elif record.get("current_state") == "BRANCH_RACE":
                            timeout = 300
                            
                        if elapsed > timeout:
                            record["status"] = "FAILED"
                            record["current_state"] = "FAILED_STALLED_" + record.get("current_state", "UNKNOWN")
                            record["terminal_reason"] = "timeout_exceeded"
                            logs = record.get("logs", [])
                            stalled_msg = f"Task aborted by Reaper. Stalled in {record.get('current_state')} for > {timeout}s."
                            logs.append(stalled_msg)
                            record["logs"] = logs
                            print(f"[REAPER] Killed {task_id}: {stalled_msg}")
                            
                            # Append to physical telemetry log so UI picks it up 
                            import json
                            with open("/tmp/forgeos_telemetry.log", "a") as f:
                                event = {
                                    "timestamp": now.isoformat() + "Z",
                                    "event": "task_stalled",
                                    "issue_id": record.get("issue"),
                                    "state": record.get("current_state"),
                                    "message": stalled_msg
                                }
                                f.write(json.dumps(event) + "\n")
                                
                    except Exception as e:
                        print(f"[REAPER] Error processing {task_id}: {e}")
        except Exception as e:
            print(f"[REAPER] Loop error: {e}")
            
        await asyncio.sleep(15)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(_task_reaper_loop())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
