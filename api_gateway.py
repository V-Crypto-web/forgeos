from fastapi import FastAPI, BackgroundTasks, HTTPException, WebSocket
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import json
import asyncio
import threading

from uuid import uuid4
from datetime import datetime, timedelta
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
PROJECT_REGISTRY_PATH = "/tmp/forgeos_project_registry.json"

class _PersistentRegistry(dict):
    """Dict subclass that auto-saves to disk on every write.
    
    Enforces a retention policy: keeps the latest REGISTRY_HOT_LIMIT terminal
    tasks (DONE/FAILED). Older terminal tasks are archived to JSONL and pruned
    from the hot dict to prevent unbounded memory growth.
    """
    REGISTRY_HOT_LIMIT = 500   # max DONE/FAILED tasks kept in hot memory
    ARCHIVE_PATH = "/tmp/forgeos_task_archive.jsonl"

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

    def trim(self):
        """Archive + remove oldest terminal tasks beyond REGISTRY_HOT_LIMIT."""
        terminal = [(k, v) for k, v in self.items()
                    if v.get("status") in ("DONE", "FAILED")]
        if len(terminal) <= self.REGISTRY_HOT_LIMIT:
            return
        terminal.sort(key=lambda x: x[1].get("started_at", ""))
        to_archive = terminal[:len(terminal) - self.REGISTRY_HOT_LIMIT]
        try:
            with open(self.ARCHIVE_PATH, "a", encoding="utf-8") as af:
                for _, record in to_archive:
                    af.write(json.dumps(record, default=str) + "\n")
        except Exception:
            pass
        for k, _ in to_archive:
            super().__delitem__(k)
        self._save()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._save()
        # Trim periodically: only when a task completes
        if isinstance(value, dict) and value.get("status") in ("DONE", "FAILED"):
            self.trim()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._save()

TASK_REGISTRY: dict = _PersistentRegistry(TASK_REGISTRY_PATH)
PROJECT_REGISTRY: dict = _PersistentRegistry(PROJECT_REGISTRY_PATH)

# Auto-seed the default local ForgeAI repo if registry is empty
if not PROJECT_REGISTRY:
    PROJECT_REGISTRY["forgeos"] = {
        "id": "forgeos",
        "name": "ForgeOS (Self-Hosted)",
        "repo_url": "https://github.com/V-Crypto-web/forgeos.git",
        "local_path": "/opt/ForgeAI",
        "project_type": "core_system",
        "type": "system",
        "description": "Autonomous self-improvement OS",
    }

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
    repo_path: Optional[str] = None
    project_id: Optional[str] = None
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
            racing_enabled=False if os.environ.get("FORGEOS_TRIAGE_MODE", "0").strip() in ("1", "true", "yes") else True,
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
        final_status = "DONE" if final_ctx.current_state == EngineState.DONE else "FAILED"
        TASK_REGISTRY[task_id]["status"]        = final_status
        TASK_REGISTRY[task_id]["current_state"] = final_ctx.current_state.value
        TASK_REGISTRY[task_id]["plan"]          = final_ctx.plan
        TASK_REGISTRY[task_id]["patch"]         = final_ctx.patch
        TASK_REGISTRY[task_id]["pr_url"]        = getattr(final_ctx, "pr_url", None)
        TASK_REGISTRY[task_id]["global_cost"]   = final_ctx.global_cost
        TASK_REGISTRY[task_id]["branch_results"]= final_ctx.branch_results
        TASK_REGISTRY[task_id]["logs"]          = final_ctx.logs[-100:]
        TASK_REGISTRY[task_id]["had_race"]      = bool(final_ctx.branch_results)

        # ── Fix 3: Backlog auto-sync ──────────────────────────────────────────────
        epic_id = TASK_REGISTRY[task_id].get("epic_id")
        if epic_id:
            _sync_backlog_status(epic_id, final_status)
        # ─────────────────────────────────────────────────────────────────

    except Exception as e:
        TASK_REGISTRY[task_id]["status"]        = "FAILED"
        TASK_REGISTRY[task_id]["current_state"] = "FAILED"
        TASK_REGISTRY[task_id]["error"]         = str(e)
        import traceback
        TASK_REGISTRY[task_id]["traceback"]     = traceback.format_exc()
        # Sync failure to backlog too
        epic_id = TASK_REGISTRY[task_id].get("epic_id")
        if epic_id:
            _sync_backlog_status(epic_id, "FAILED")


def _sync_backlog_status(epic_id: str, task_status: str):
    """Updates improvement_backlog.json status when a task completes."""
    BACKLOG_PATH = "/opt/ForgeAI/forge_cloud/data/improvement_backlog.json"
    if not os.path.exists(BACKLOG_PATH):
        BACKLOG_PATH = "/Users/vasiliyprachev/Python_Projects/ForgeAI/forge_cloud/data/improvement_backlog.json"
    if not os.path.exists(BACKLOG_PATH):
        return
    # Map task terminal status to backlog status
    if task_status == "DONE":
        backlog_status = "done"
    elif task_status.startswith("FAILED"):
        backlog_status = "failed"
    else:
        return  # Only sync terminal states
    try:
        with open(BACKLOG_PATH, "r") as f:
            backlog = json.load(f)
        changed = False
        for item in backlog:
            if item.get("id") == epic_id and item.get("status") not in ("done", "failed"):
                item["status"] = backlog_status
                changed = True
                break
        if changed:
            with open(BACKLOG_PATH, "w") as f:
                json.dump(backlog, f, indent=2)
            print(f"[BACKLOG SYNC] {epic_id} → {backlog_status}")
    except Exception as e:
        print(f"[BACKLOG SYNC ERROR] {epic_id}: {e}")



# ── Issue Run ─────────────────────────────────────────────────────────────────
@app.post("/api/v1/issues/run")
async def run_issue(req: RunIssueRequest, background_tasks: BackgroundTasks):
    """Spawns an asynchronous engine process to resolve an issue."""
    # Resolve repo_path from project_id if provided
    repo_path = req.repo_path
    if req.project_id:
        if req.project_id not in PROJECT_REGISTRY:
            raise HTTPException(status_code=404, detail="Project not found")
        repo_path = PROJECT_REGISTRY[req.project_id]["local_path"]
        
    if not repo_path:
        raise HTTPException(status_code=400, detail="Must provide either project_id or repo_path")

    task_id = f"task_{req.issue_number}_{str(uuid4())[:8]}"
    record = _make_task_record(task_id, repo_path, req.issue_number, req.mode)
    TASK_REGISTRY[task_id] = record
    t = threading.Thread(target=_run_engine_background, args=(repo_path, req.issue_number, task_id), daemon=True)
    t.start()
    return record

# ── Project Registry Endpoints ────────────────────────────────────────────────
@app.get("/api/v1/projects")
async def list_projects():
    """Returns all registered projects."""
    return list(PROJECT_REGISTRY.values())

@app.post("/api/v1/projects")
async def create_project(req: ProjectCreateRequest):
    """Registers a new project, cloning the repo to a local workspace."""
    project_id = f"proj_{str(uuid4())[:8]}"
    name = req.name or project_id
    
    # Establish a default workspaces directory
    workspaces_dir = os.path.expanduser("~/ForgeOS_Workspaces")
    os.makedirs(workspaces_dir, exist_ok=True)
    
    # Simple clean up of name for folder creation
    safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).replace(' ', '_')
    local_path = os.path.join(workspaces_dir, safe_name)
    
    # Background or Sync clone (we'll do sync for simplicity in MVP, but this could block)
    if not os.path.exists(local_path):
        try:
            print(f"[API] Cloning {req.repo_url} into {local_path}...")
            subprocess.run(["git", "clone", req.repo_url, local_path], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail=f"Failed to clone repository: {e.stderr}")
            
    PROJECT_REGISTRY[project_id] = {
        "id": project_id,
        "name": name,
        "repo_url": req.repo_url,
        "local_path": local_path,
        "project_type": req.project_type,
        "policies": req.policies or {}
    }
    
    return PROJECT_REGISTRY[project_id]

# ── Task Registry Endpoints ───────────────────────────────────────────────────
@app.get("/api/v1/tasks/summary")
async def tasks_summary():
    """Lightweight KPI endpoint — returns counts only, no full task data."""
    counts = {"RUNNING": 0, "DONE": 0, "FAILED": 0, "total": len(TASK_REGISTRY)}
    for t in TASK_REGISTRY.values():
        s = t.get("status", "UNKNOWN")
        counts[s] = counts.get(s, 0) + 1
    return counts

@app.get("/api/v1/tasks")
async def list_tasks(
    limit: int = 50,
    status: str = None,
    after: str = None,
):
    """Returns tasks newest first. Supports ?limit=N, ?status=DONE|FAILED|RUNNING, ?after=task_id."""
    tasks = sorted(TASK_REGISTRY.values(), key=lambda t: t.get("started_at", ""), reverse=True)
    if status:
        tasks = [t for t in tasks if t.get("status") == status.upper()]
    if after:
        # Return tasks started before the given task_id's started_at (cursor pagination)
        pivot = TASK_REGISTRY.get(after, {})
        pivot_time = pivot.get("started_at", "")
        if pivot_time:
            tasks = [t for t in tasks if t.get("started_at", "") < pivot_time]
    return tasks[:limit]

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
    # ── Guard: reject if another task already RUNNING ─────────────────────────
    running = [t for t in TASK_REGISTRY.values() if t.get("status") == "RUNNING"]
    if running:
        raise HTTPException(
            status_code=409,
            detail=f"Task {running[0].get('id')} already RUNNING — wait for it to finish"
        )

    # ── Locate backlog on server or local dev ──────────────────────────────────
    FORGEOS_ROOT_LOCAL = os.getenv("FORGEOS_ROOT", "/opt/ForgeAI")
    backlog_path = os.path.join(FORGEOS_ROOT_LOCAL, "forge_cloud", "data", "improvement_backlog.json")
    if not os.path.exists(backlog_path):
        # fallback for local dev
        backlog_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "forge_cloud", "data", "improvement_backlog.json"
        )
    if not os.path.exists(backlog_path):
        raise HTTPException(status_code=500, detail=f"Backlog database missing: {backlog_path}")

    with open(backlog_path, "r") as f:
        backlog = json.load(f)
    target = next((item for item in backlog if item["id"] == req.epic_id), None)
    if not target:
        raise HTTPException(status_code=404, detail=f"Epic '{req.epic_id}' not found in backlog")
    if target.get("status") == "failed":
        raise HTTPException(status_code=409, detail=f"Epic '{req.epic_id}' already marked failed — reset its status first")

    # ── Build execution context ────────────────────────────────────────────────
    exec_path    = target.get("repo_path") or FORGEOS_ROOT_LOCAL
    github_url   = target.get("repo_url", "")
    issue_number = target.get("github_issue", 0)

    task_id = f"task_self_{req.epic_id.replace('-', '_')}_{str(uuid4())[:8]}"
    record = _make_task_record(task_id, exec_path, issue_number, "supervised")
    record["epic_id"]    = req.epic_id
    record["epic_title"] = target.get("title", "")
    record["github_url"] = github_url
    TASK_REGISTRY[task_id] = record
    t = threading.Thread(target=_run_engine_background, args=(exec_path, issue_number, task_id), daemon=True)
    t.start()
    return {
        "status": "accepted",
        "task_id": task_id,
        "message": f"Self-Improvement loop started for {req.epic_id}",
        "repo": exec_path,
        "github_url": github_url,
        "issue": issue_number,
    }


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


# ── Backlog & OmniBench ───────────────────────────────────────────────────────
@app.get("/api/v1/backlog")
def get_backlog():
    path = "/opt/ForgeAI/forge_cloud/data/improvement_backlog.json"
    if not os.path.exists(path):
        path = "/Users/vasiliyprachev/Python_Projects/ForgeAI/forge_cloud/data/improvement_backlog.json"
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []

@app.get("/api/v1/queue")
def get_epic_queue():
    """
    Returns the full epic queue: backlog items enriched with live task state.
    Each item includes: id, title, status, risk_zone, priority, description,
    and if running: task_id, current_state, logs (last 10), elapsed_secs.
    """
    backlog_path = "/opt/ForgeAI/forge_cloud/data/improvement_backlog.json"
    if not os.path.exists(backlog_path):
        backlog_path = "/Users/vasiliyprachev/Python_Projects/ForgeAI/forge_cloud/data/improvement_backlog.json"

    backlog = []
    if os.path.exists(backlog_path):
        with open(backlog_path, "r") as f:
            backlog = json.load(f)

    # Build a map of epic_id -> latest running task
    epic_tasks: dict = {}
    for task in TASK_REGISTRY.values():
        eid = task.get("epic_id")
        if not eid:
            continue
        existing = epic_tasks.get(eid)
        if not existing or task.get("started_at", "") > existing.get("started_at", ""):
            epic_tasks[eid] = task

    now_iso = datetime.utcnow().isoformat()
    result = []
    for item in backlog:
        entry = {
            "id":          item.get("id"),
            "title":       item.get("title", ""),
            "description": item.get("description", ""),
            "status":      item.get("status", "todo"),
            "risk_zone":   item.get("risk_zone", "green"),
            "priority":    item.get("priority", "medium"),
            "task":        None,
        }
        task = epic_tasks.get(item.get("id"))
        if task:
            started = task.get("started_at", now_iso)
            try:
                from datetime import timezone
                dt = datetime.fromisoformat(started.replace("Z", "+00:00")).replace(tzinfo=None)
                elapsed = int((datetime.utcnow() - dt).total_seconds())
            except Exception:
                elapsed = 0
            entry["task"] = {
                "id":            task["id"],
                "status":        task.get("status"),
                "current_state": task.get("current_state"),
                "elapsed_secs":  elapsed,
                "logs":          task.get("logs", [])[-10:],
                "global_cost":   task.get("global_cost", 0.0),
            }
            # Mirror task status back into entry status
            if task.get("status") == "RUNNING":
                entry["status"] = "in_progress"
            elif task.get("status") == "DONE":
                entry["status"] = "done"
        result.append(entry)

    # Sort: in_progress first, then todo, then done
    order = {"in_progress": 0, "todo": 1, "done": 2}
    result.sort(key=lambda x: order.get(x["status"], 3))
    return result

@app.get("/api/v1/omnibench")
def get_omnibench_baseline():
    path = "/opt/ForgeAI/forge_cloud/data/omnibench_baseline.yaml"
    if not os.path.exists(path):
        path = "/Users/vasiliyprachev/Python_Projects/ForgeAI/forge_cloud/data/omnibench_baseline.yaml"
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
    # TRIAGE_MODE: scheduler cannot be started while golden path debugging is active
    if os.environ.get("FORGEOS_TRIAGE_MODE", "0").strip() in ("1", "true", "yes"):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"ok": False, "message": "TRIAGE_MODE active. Set FORGEOS_TRIAGE_MODE=0 in .env to enable the scheduler."}
        )
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


# ── Triage Status Endpoint ────────────────────────────────────────────────────────────────
@app.get("/api/v1/triage/status")
def get_triage_status():
    """
    Truth table endpoint for triage mode.
    Returns one row per task with all fields needed to debug the golden path.
    """
    triage_active = os.environ.get("FORGEOS_TRIAGE_MODE", "0").strip() in ("1", "true", "yes")
    rows = []
    tasks = sorted(TASK_REGISTRY.values(), key=lambda t: t.get("started_at", ""), reverse=True)
    for t in tasks[:100]:  # last 100 tasks
        # Determine patch protocol from last log line mentioning a protocol
        patch_protocol = "unknown"
        for log_line in reversed(t.get("logs", [])):
            if "search_replace" in log_line:
                patch_protocol = "search_replace"
                break
            elif "unified_diff" in log_line:
                patch_protocol = "unified_diff"
                break
            elif "full_file_rewrite" in log_line:
                patch_protocol = "full_file_rewrite"
                break
        # Last error = most recent log line starting with a known failure token
        last_error = None
        for log_line in reversed(t.get("logs", [])):
            if any(tok in log_line for tok in ("PATCH_NOT_FOUND", "MALFORMED_PATCH", "FAILED", "Error", "error", "[TRIAGE]")):
                last_error = log_line[:200]
                break
        rows.append({
            "task_id":       t.get("id"),
            "project":       t.get("repo", "").split("/")[-1] if t.get("repo") else t.get("epic_title", ""),
            "issue":         t.get("issue"),
            "current_state": t.get("current_state"),
            "status":        t.get("status"),
            "retry_count":   len([l for l in t.get("logs", []) if "RETRY" in l or "retry" in l.lower()]),
            "patch_protocol": patch_protocol,
            "last_error":    last_error,
            "started_at":    t.get("started_at"),
            "updated_at":    t.get("updated_at"),
            "terminal_reason": t.get("terminal_reason"),
            "global_cost":   t.get("global_cost", 0.0),
        })
    return {
        "triage_mode": triage_active,
        "scheduler_running": _scheduler_is_running(),
        "task_count": len(rows),
        "tasks": rows,
    }


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
                            timeout = 300  # git clone can take 2-3 min on first task after restart
                        elif record.get("current_state") == "PLAN":
                            timeout = 180
                        elif record.get("current_state") == "BRANCH_RACE":
                            timeout = 300
                            
                        if elapsed > timeout:
                            stalled_state = record.get("current_state", "UNKNOWN")
                            record["status"] = "FAILED"
                            record["current_state"] = "FAILED_STALLED_" + stalled_state
                            record["terminal_reason"] = "timeout_exceeded"
                            logs = record.get("logs", [])
                            stalled_msg = f"Task aborted by Reaper. Stalled in {stalled_state} for > {timeout}s."
                            logs.append(stalled_msg)

                            # ── STALLED_INIT Diagnosis ──────────────────────────────────
                            # Capture all thread tracebacks so we know WHERE the engine hung
                            import sys, traceback, threading
                            thread_dump = []
                            for tid, frame in sys._current_frames().items():
                                tname = next((t.name for t in threading.enumerate() if t.ident == tid), f"tid-{tid}")
                                tb_lines = traceback.format_stack(frame)
                                thread_dump.append(f"[Thread {tname}]\n{''.join(tb_lines[-6:])}")
                            diagnosis = "\n---\n".join(thread_dump[:4])  # top 4 threads
                            logs.append(f"[REAPER DIAGNOSIS] Thread dump at kill time:\n{diagnosis[:2000]}")

                            # Write to FailureMemory so Opportunity Engine learns
                            try:
                                import sys as _sys
                                _forgeos_root = os.getenv("FORGEOS_ROOT", "/opt/ForgeAI")
                                if _forgeos_root not in _sys.path:
                                    _sys.path.insert(0, _forgeos_root)
                                from forgeos.memory.failure_memory import FailureMemory
                                _issue_num = record.get("issue", 0) or 0
                                fm = FailureMemory(issue_id=int(_issue_num))
                                fm.record_failure(
                                    error_signature=f"STALLED_INIT::{stalled_state}",
                                    strategy=record.get("mode", "supervised"),
                                )
                                logs.append(f"[REAPER] Failure written to FailureMemory.")
                            except Exception as _fme:
                                logs.append(f"[REAPER] FailureMemory write failed (non-fatal): {_fme}")
                                # Fallback: write directly to failure_db JSONL
                                try:
                                    import json as _json
                                    _db_dir = os.path.join(_forgeos_root, "forgeos", "memory", "failure_db")
                                    os.makedirs(_db_dir, exist_ok=True)
                                    _entry = {
                                        "ts": now.isoformat() + "Z",
                                        "task_id": task_id,
                                        "error_type": "STALLED_INIT",
                                        "state": stalled_state,
                                        "diagnosis": diagnosis[:800],
                                    }
                                    with open(os.path.join(_db_dir, "stalled_init.jsonl"), "a") as _dbf:
                                        _dbf.write(_json.dumps(_entry) + "\n")
                                except Exception:
                                    pass



                            record["logs"] = logs
                            print(f"[REAPER] Killed {task_id}: {stalled_msg}")

                            # Append structured event to telemetry log
                            import json
                            with open("/tmp/forgeos_telemetry.log", "a") as f:
                                event = {
                                    "timestamp": now.isoformat() + "Z",
                                    "event": "task_stalled",
                                    "issue_id": record.get("issue"),
                                    "state": record.get("current_state"),
                                    "message": stalled_msg,
                                    "diagnosis_snippet": diagnosis[:400],
                                }
                                f.write(json.dumps(event) + "\n")


                                
                    except Exception as e:
                        print(f"[REAPER] Error processing {task_id}: {e}")
        except Exception as e:
            print(f"[REAPER] Loop error: {e}")
            
        await asyncio.sleep(15)

@app.on_event("startup")
async def startup_event():
    # Pre-warm heavy imports so first task doesn't exceed INIT timeout
    import threading
    def _prewarm():
        try:
            from forgeos.engine.state_machine import StateMachine  # noqa: triggers litellm import
            print("[STARTUP] Pre-warm import complete.")
        except Exception as _e:
            print(f"[STARTUP] Pre-warm import failed (non-fatal): {_e}")
    threading.Thread(target=_prewarm, daemon=True).start()
    asyncio.create_task(_task_reaper_loop())

# ── Epic 66: Cost Awareness & Optimization Endpoints ────────────────────────
@app.get("/api/v1/opportunities")
def get_opportunities():
    """Returns top opportunities detected by the Opportunity Engine."""
    try:
        from opportunity_detector import detect_all_opportunities
        forgeos_root = os.path.dirname(os.path.dirname(__file__))
        backlog_path = os.path.join(os.path.dirname(__file__), "data", "improvement_backlog.json")
        return detect_all_opportunities(forgeos_root, backlog_path)
    except Exception as e:
        print(f"Error fetching opportunities: {e}")
        return []

@app.post("/api/v1/opportunities/{opp_id}/generate-epic")
def generate_epic_from_opportunity(opp_id: str):
    """Triggers materialization of a specific opportunity into a GitHub issue and Backlog Epic."""
    # Since materializer runs in bulk inside opportunity_runner, we'll just shell out to it
    try:
        env = {**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(__file__))}
        subprocess.Popen(
            ["python3", os.path.join(os.path.dirname(os.path.dirname(__file__)), "opportunity_runner.py")],
            env=env,
            start_new_session=True,
        )
        return {"ok": True, "message": "Dispatched Opportunity Engine to materialize epics."}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/api/v1/learning/champion-history")
def get_champion_history():
    """Returns the history of strategy promotions."""
    # Mock history since self_change_ledger isn't fully implemented yet
    return [
        {"timestamp": datetime.utcnow().isoformat() + "Z", "old_champion": "gpt-4-turbo-baseline", "new_champion": "gpt-4o-haiku-optimized", "reason": "Higher success rate (+12%) at lower cost (-40%)"},
        {"timestamp": (datetime.utcnow() - timedelta(days=2)).isoformat() + "Z", "old_champion": "claude-3-opus", "new_champion": "gpt-4-turbo-baseline", "reason": "Context window saturation in Claude led to high Verification Deficit"}
    ]

@app.get("/api/v1/learning/ledger")
def get_ledger_entries():
    """Returns the self-change ledger of all constitution and strategy updates."""
    # Mock ledger until persistence is fully wired
    now = datetime.utcnow()
    return [
        {"timestamp": now.isoformat() + "Z", "reason": "Epic 64: Added 'No placeholders' guardrail to constitution.", "old_policy": "N/A", "new_policy": "Constitution Amendment", "blocked": False},
        {"timestamp": (now - timedelta(hours=4)).isoformat() + "Z", "reason": "Proposed patch removes type annotations.", "old_policy": "Strict typing", "new_policy": "N/A", "blocked": True},
        {"timestamp": (now - timedelta(hours=24)).isoformat() + "Z", "reason": "Epic 63: Adapted testing strategy for FastAPI endpoints.", "old_policy": "Unit tests only", "new_policy": "Include integration stubs", "blocked": False},
    ]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
