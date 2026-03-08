import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import Dict, Any
from forgeos.engine.state_machine import StateMachine, ExecutionContext
from forgeos.memory.failure_memory import FailureMemory
from forgeos.artifacts.artifact_manager import ArtifactManager
from forgeos.observability.telemetry import TelemetryLogger
from forgeos.os.run_ledger import RunLedger

app = FastAPI(title="ForgeOS Development Engine", version="1.2.0")

class TaskRequest(BaseModel):
    issue_number: int
    repo_url: str
    
class TaskResponse(BaseModel):
    status: str
    message: str
    job_id: str

# In-memory execution tracker for MVP
executions: Dict[str, ExecutionContext] = {}

def execute_engine_flow(job_id: str, request: TaskRequest):
    """Background task to run the State Machine orchestrator."""
    # Extract project name from URL to form the strict workspace path
    repo_name = request.repo_url.split('/')[-1].replace('.git', '')
    workspace_path = f"/tmp/forgeos_workspaces/{repo_name}_issue_{request.issue_number}"
    
    memory_manager = FailureMemory(issue_id=request.issue_number)
    artifact_manager = ArtifactManager(workspace_path=workspace_path, issue_number=request.issue_number)
    telemetry_logger = TelemetryLogger(workspace_path=workspace_path)
    run_ledger = RunLedger(workspace_path=workspace_path, issue_number=request.issue_number)
    
    context = ExecutionContext(
        issue_number=request.issue_number,
        repo_path=workspace_path, 
        failure_memory=memory_manager,
        artifact_manager=artifact_manager,
        telemetry=telemetry_logger,
        run_ledger=run_ledger
    )
    executions[job_id] = context
    
    machine = StateMachine()
    # Execute the machine completely
    final_context = machine.run(context)
    
    executions[job_id] = final_context

@app.post("/api/v1/tasks/run", response_model=TaskResponse)
async def run_task(request: TaskRequest, background_tasks: BackgroundTasks):
    job_id = f"job_{request.issue_number}"
    
    if job_id in executions and executions[job_id].current_state not in ["DONE", "FAILED"]:
        raise HTTPException(status_code=400, detail="Task already running for this issue.")
        
    background_tasks.add_task(execute_engine_flow, job_id, request)
    
    return TaskResponse(
        status="accepted",
        message="Task added to ForgeOS Engine queue.",
        job_id=job_id
    )

@app.get("/api/v1/tasks/{job_id}/status")
async def get_task_status(job_id: str):
    if job_id not in executions:
        raise HTTPException(status_code=404, detail="Job not found.")
        
    ctx = executions[job_id]
    return {
        "job_id": job_id,
        "state": ctx.current_state.value,
        "logs": ctx.logs[-10:] # last 10 logs
    }
