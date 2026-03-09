import argparse
import time
import sys
import os
from forgeos.engine.orchestrator import execute_engine_flow, TaskRequest, executions
from forgeos.engine.state_machine import EngineState

def main():
    parser = argparse.ArgumentParser(description="ForgeOS MVP CLI Engine")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    run_parser = subparsers.add_parser("run", help="Run ForgeOS on a known issue")
    run_parser.add_argument("--repo", required=True, help="GitHub repository (e.g., username/repo_name or full URL)")
    run_parser.add_argument("--issue", required=True, type=int, help="Issue number to resolve")
    
    epic_parser = subparsers.add_parser("epic", help="Delegate a large Epic into Sub-Tasks via CTO Agent")
    epic_parser.add_argument("--repo", required=True, help="GitHub repository (e.g., username/repo_name or full URL)")
    epic_parser.add_argument("--issue", required=True, type=int, help="Epic issue number to resolve")
    
    repair_parser = subparsers.add_parser("repair", help="Repair an issue in a real third-party repo")
    repair_parser.add_argument("repo", help="Repository URL to repair")
    repair_parser.add_argument("issue", help="Issue URL or number to repair")
    
    args = parser.parse_args()

    repo_url = args.repo
    
    # Extract issue number from URL if necessary
    issue_number = args.issue
    if isinstance(issue_number, str):
        if "github.com" in issue_number:
            issue_number = int(issue_number.split("/")[-1])
        elif issue_number.isdigit():
            issue_number = int(issue_number)
        else:
            print("Invalid issue format.")
            sys.exit(1)

    print(f"\\n🚀 Starting ForgeOS Engine [{args.command.upper()}] for {repo_url} Issue #{issue_number}")
    print("================================================================")
    
    if args.command == "epic":
        from forgeos.connectors.github_connector import GitHubConnector
        from forgeos.agents.cto_agent import CTOAgent
        from forgeos.providers.model_router import ProviderRouter
        from forgeos.observability.telemetry import TelemetryLogger
        
        epic_logger = TelemetryLogger(workspace_path=f"/tmp/forgeos_workspaces/epic_{issue_number}")
        epic_logger.log_event("epic_received", issue_number, "INIT", f"Received Epic {issue_number} for {repo_url}")
        
        print(f"\\n🧠 CTO Agent starting Epic Decomposition for {repo_url} Issue #{issue_number}")
        github = GitHubConnector()
        
        try:
            # Use local tasks json fallback for mock
            import json
            bench_file = "/Users/vasiliyprachev/Python_Projects/ForgeAI/forge_bench/alpha_tasks.json"
            epic_title = ""
            epic_body = ""
            
            if "ForgeAI" in repo_url or os.environ.get("FORGEOS_MOCK_LLM") == "true":
                with open(bench_file, "r") as f:
                    tasks = json.load(f)
                    task = next((t for t in tasks if t["id"] == issue_number), None)
                    if task:
                        epic_title = task['title']
                        epic_body = task['description']
                    else:
                        epic_title = "Dummy Epic"
                        epic_body = "Mocked body."
            else:
                repo_full_name = repo_url.replace("https://github.com/", "").replace(".git", "")
                issue_data = github.fetch_issue(repo_full_name, issue_number)
                epic_title = issue_data['title']
                epic_body = issue_data['body']
                
            print(f"  Epic Title: {epic_title}")
            print("  Delegating to CTO Agent...")
            
            router = ProviderRouter()
            cto = CTOAgent(router)
            # We won't clone the repo in the CLI just for the map. We can pass a dummy map or 
            # a highly compressed summary for MVP.
            repo_map_mock = "Main directories: api/, models/, core/. Python backend."
            # Local path is usually the pwd for MVP tests
            local_repo_path = "/Users/vasiliyprachev/Python_Projects/ForgeAI" if "ForgeAI" in repo_url else ""
            plan, _ = cto.decompose_epic(epic_title, epic_body, repo_map_mock, repo_path=local_repo_path)
            
            sub_tasks = plan.get("sub_tasks", [])
            print(f"  CTO Agent generated {len(sub_tasks)} Sub-Tasks.")
            
            epic_logger.log_event("epic_decomposed", issue_number, "PLANNING", f"Decomposed into {len(sub_tasks)} tasks", metadata={"sub_tasks_count": len(sub_tasks)})
            
            # Execute them sequentially
            for idx, task in enumerate(sub_tasks):
                epic_logger.log_event("subtask_started", issue_number, "EXECUTION", f"Started Sub-Task {idx+1}: {task.get('title')}", metadata={"sub_task_idx": idx+1, "title": task.get('title')})
                
                print(f"\\n================================================================")
                print(f"🚀 Spawning ForgeOS Instance {idx+1}/{len(sub_tasks)}")
                print(f"   Task: {task.get('title')}")
                print(f"   Desc: {task.get('description')}")
                
                sub_job_id = f"cli_epic_{issue_number}_sub_{idx}"
                
                # We pass issue_number + something, or just reuse issue_number for DB linking
                sub_request = TaskRequest(
                    issue_number=issue_number, 
                    parent_epic_id=issue_number,
                    repo_url=repo_url,
                    issue_title=task.get('title'),
                    issue_description=task.get('description')
                )
                
                import threading
                engine_thread = threading.Thread(target=execute_engine_flow, args=(sub_job_id, sub_request))
                engine_thread.daemon = True
                engine_thread.start()
                
                last_log_index = 0
                current_state = None
                
                while True:
                    if sub_job_id in executions:
                        ctx = executions[sub_job_id]
                        
                        if current_state != ctx.current_state:
                            current_state = ctx.current_state
                            print(f"\\n> [Sub-Task {idx+1}] State Transition: {current_state.value}")
                            
                        while last_log_index < len(ctx.logs):
                            print(f"  [LOG] {ctx.logs[last_log_index]}")
                            last_log_index += 1
                        
                        if current_state in [EngineState.DONE, EngineState.FAILED]:
                            break
                            
                    time.sleep(0.5)
                    
                if current_state == EngineState.DONE:
                    epic_logger.log_event("subtask_completed", issue_number, "DONE", f"Completed Sub-Task {idx+1}", metadata={"sub_task_idx": idx+1, "status": "success"})
                    print(f"✅ Sub-Task {idx+1} resolved successfully!")
                else:
                    epic_logger.log_event("subtask_completed", issue_number, "FAILED", f"Failed Sub-Task {idx+1}", metadata={"sub_task_idx": idx+1, "status": "failed"})
                    print(f"❌ Failed to resolve Sub-Task {idx+1}. Halting Epic pipeline.")
                    break
                    
            epic_logger.log_event("epic_completed", issue_number, "DONE", f"Epic {issue_number} Execution Finished")
            sys.exit(0)
                    
        except Exception as e:
            print(f"CTO Agent failed: {e}")
            sys.exit(1)
            
    # Default 'run' logic
    job_id = f"cli_{args.command}_{issue_number}"
    request = TaskRequest(issue_number=issue_number, repo_url=repo_url)
    
    try:
        import threading
        
        engine_thread = threading.Thread(target=execute_engine_flow, args=(job_id, request))
        engine_thread.daemon = True
        engine_thread.start()
        
        last_log_index = 0
        current_state = None
        
        # Polling loop for live CLI output
        while True:
            if job_id in executions:
                ctx = executions[job_id]
                
                # Print state change
                if current_state != ctx.current_state:
                    current_state = ctx.current_state
                    print(f"\\n> State Transition: {current_state.value}")
                    
                # Print new logs
                while last_log_index < len(ctx.logs):
                    print(f"  [LOG] {ctx.logs[last_log_index]}")
                    last_log_index += 1
                
                if current_state in [EngineState.DONE, EngineState.FAILED]:
                    break
                    
            time.sleep(0.5)
            
        print("\\n================================================================")
        if current_state == EngineState.DONE:
            print(f"✅ Issue #{issue_number} resolved successfully!")
        else:
            print(f"❌ Failed to resolve issue #{issue_number}.")
            
    except KeyboardInterrupt:
        print("\\n\\n🛑 Execution interrupted by user.")
        sys.exit(1)

if __name__ == "__main__":
    main()
