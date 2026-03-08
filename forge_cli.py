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
    
    job_id = f"cli_{args.command}_{issue_number}"
    request = TaskRequest(issue_number=issue_number, repo_url=repo_url)
    
    try:
        # For simplicity in the CLI MVP, we run synchronously instead of as a background task.
        # This allows us to print the logs in real-time or poll them.
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
                    print(f"\n> State Transition: {current_state.value}")
                    
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
        print("\n\n🛑 Execution interrupted by user.")
        sys.exit(1)

if __name__ == "__main__":
    main()
