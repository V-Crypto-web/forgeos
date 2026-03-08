import os
import json
import time
import subprocess
from typing import List, Dict, Any

class BenchmarkRunner:
    """
    ForgeOS Phase 2: The Gauntlet.
    Reads tasks from a dataset, executes them via forge_cli.py, 
    and aggregates telemetry into forge_bench_results.json.
    """
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        self.bench_dir = os.path.join(workspace_path, "forge_bench")
        self.data_dir = os.path.join(self.bench_dir, "data")
        self.results_file = os.path.join(self.bench_dir, "forge_bench_results.json")
        self.telemetry_file = "/tmp/forgeos_telemetry.log" # From observability module
        
    def load_tasks(self, filepath: str) -> List[Dict[str, Any]]:
        if not os.path.exists(filepath):
            print(f"Dataset not found: {filepath}")
            return []
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
            
    def parse_telemetry(self, issue_number: int) -> Dict[str, Any]:
        """Reads the telemetry log to extract metrics for a specific run."""
        metrics = {
            "success": False,
            "retry_count": 0,
            "total_cost_usd": 0.0,
            "execution_time_seconds": 0.0,
            "impact_risk_score": "unknown",
            "verification_scope": "unknown",
            "planner_prompt_tokens": 0,
            "planner_completion_tokens": 0,
            "coder_prompt_tokens": 0,
            "coder_completion_tokens": 0,
            "verification_time_seconds": 0.0,
            "repo_analysis_time_seconds": 0.0
        }
        
        if not os.path.exists(self.telemetry_file):
            return metrics
            
        start_time = None
        end_time = None
        state_timestamps = {}
        
        with open(self.telemetry_file, "r", encoding="utf-8") as f:
            for line_raw in f:
                line = line_raw.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    if event.get("issue_number") != issue_number:
                        continue
                        
                    if event["event_type"] == "state_transition":
                        state = event["state"]
                        state_timestamps[state] = event["timestamp"]
                        
                        if state == "INIT" and not start_time:
                            start_time = event["timestamp"]
                        if state == "RETRY":
                            metrics["retry_count"] += 1
                        if state == "IMPACT_ANALYSIS" and "Impact:" in event["message"]:
                            # Hacky MVP parsing of the message: "Impact: high Risk. Strategy: no_rewrite."
                            parts = event["message"].split("Impact: ")
                            if len(parts) > 1:
                                metrics["impact_risk_score"] = parts[1].split(" ")[0].lower()
                                
                    elif event["event_type"] == "verification_scope_selected":
                        metrics["verification_scope"] = event["metadata"].get("targets", "unknown")
                                
                    elif event["event_type"] == "execution_finished":
                        end_time = event["timestamp"]
                        metrics["success"] = (event["state"] == "DONE")
                        
                    elif event["event_type"] == "api_cost":
                        # MVP Cost Calculation (Mocked rates)
                        model = event["metadata"].get("model", "unknown")
                        p_t = event["metadata"].get("prompt_tokens", 0)
                        c_t = event["metadata"].get("completion_tokens", 0)
                        
                        # Rough OpenAI pricing as of early 2024
                        if "gpt-4" in model:
                            cost = (p_t * 5.0 / 1e6) + (c_t * 15.0 / 1e6)
                        else: # gpt-3.5 or claude haiku
                            cost = (p_t * 0.5 / 1e6) + (c_t * 1.5 / 1e6) 
                            
                        metrics["total_cost_usd"] += cost
                        
                        # Categorize tokens by logic
                        if event.get("state") == "PLAN":
                            metrics["planner_prompt_tokens"] += p_t
                            metrics["planner_completion_tokens"] += c_t
                        elif event.get("state") == "PATCH":
                            metrics["coder_prompt_tokens"] += p_t
                            metrics["coder_completion_tokens"] += c_t
                        
                except Exception as e:
                    print(f"Error parsing telemetry line: {e}")
                    
        if start_time and end_time:
            metrics["execution_time_seconds"] = round(end_time - start_time, 2)
            
        if "PLAN" in state_timestamps and "IMPACT_ANALYSIS" in state_timestamps:
            # Planner generates the repo map inside PLAN state before moving forward
            metrics["repo_analysis_time_seconds"] = round(state_timestamps["IMPACT_ANALYSIS"] - state_timestamps["PLAN"], 2)
            
        if "RUN_TESTS" in state_timestamps and "VERIFY" in state_timestamps:
            metrics["verification_time_seconds"] = round(state_timestamps["VERIFY"] - state_timestamps["RUN_TESTS"], 2)
            
        return metrics

    def run_benchmark(self, dataset_file: str):
        tasks = self.load_tasks(dataset_file)
        print(f"\\n🎯 Starting Forge Gauntlet with {len(tasks)} tasks dataset...")
        
        results = []
        if os.path.exists(self.results_file):
            with open(self.results_file, "r", encoding="utf-8") as f:
                try:
                    results = json.load(f)
                except json.JSONDecodeError:
                    results = []
        
        for index, task in enumerate(tasks):
            issue_id = task.get("id")
            repo_path = os.path.join(self.data_dir, task.get("repo_name", "unknown"))
            category = task.get("category", "unknown")
            
            print(f"\\n[{index+1}/{len(tasks)}] Running Task {issue_id}: {category} on {task.get('repo_name')}")
            
            # 1. Clean previous telemetry to avoid overlap (optional, but cleaner per-run)
            if os.path.exists(self.telemetry_file):
                os.remove(self.telemetry_file)
                
            # 2. Execute CLI
            env = os.environ.copy()
            env["PYTHONPATH"] = self.workspace_path
            # For MVP Benchmarking, we use the real LLM or a mock depending on env
            if "FORGEOS_MOCK_LLM" not in env:
                env["FORGEOS_MOCK_LLM"] = "true" 
                
            cli_cmd = ["python3", "forge_cli.py", "--repo", repo_path, "--issue", str(issue_id)]
            
            start_t = time.time()
            try:
                # We use subprocess.call to stream stdout to the console directly so we can watch it
                subprocess.call(cli_cmd, env=env, cwd=self.workspace_path)
            except Exception as e:
                print(f"CLI execution failed for task {issue_id}: {e}")
                
            # 3. Parse Telemetry
            metrics = self.parse_telemetry(issue_id)
            metrics["issue_id"] = issue_id
            metrics["repo_name"] = task.get("repo_name")
            metrics["category"] = category
            
            results.append(metrics)
            
            # 4. Save results iteratively
            with open(self.results_file, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2)
                
            print(f"✅ Task {issue_id} finished in {metrics['execution_time_seconds']}s. Success: {metrics['success']}")

        # Print Benchmark Summary
        success_count = sum(1 for r in results if r.get("success", False))
        avg_cost = sum(r.get("total_cost_usd", 0) for r in results) / len(results) if results else 0
        avg_time = sum(r.get("execution_time_seconds", 0) for r in results) / len(results) if results else 0
        avg_planner = sum(r.get("planner_prompt_tokens", 0) for r in results) / len(results) if results else 0
        avg_coder = sum(r.get("coder_prompt_tokens", 0) for r in results) / len(results) if results else 0
        avg_repo_time = sum(r.get("repo_analysis_time_seconds", 0) for r in results) / len(results) if results else 0
        avg_verify_time = sum(r.get("verification_time_seconds", 0) for r in results) / len(results) if results else 0
        
        report_lines = [
            "\\n================================================================",
            "          FORGE GAUNTLET BENCHMARK SUMMARY",
            "================================================================",
            f"Total Tasks Run: {len(results)}",
            f"Success Rate:    {(success_count / len(results) * 100) if results else 0:.1f}%",
            f"Average Time:    {avg_time:.2f} s",
            f"Average Cost:    ${avg_cost:.4f}",
            f"Avg Repo Time:   {avg_repo_time:.2f} s",
            f"Avg Verify Time: {avg_verify_time:.2f} s",
            f"Avg Planner Tks: {int(avg_planner)}",
            f"Avg Coder Tks:   {int(avg_coder)}",
            "================================================================"
        ]
        
        report_text = "\\n".join(report_lines)
        print(report_text)
        
        with open(os.path.join(self.bench_dir, "benchmark_report.txt"), "w", encoding="utf-8") as f:
            f.write(report_text)

if __name__ == "__main__":
    import sys
    runner = BenchmarkRunner(workspace_path="/Users/vasiliyprachev/Python_Projects/ForgeAI")
    
    dataset_name = "alpha_tasks.json"
    if len(sys.argv) > 1:
        dataset_name = sys.argv[1]
        
    dataset = os.path.join(runner.bench_dir, dataset_name)
    
    # Create an empty dummy dataset if it doesn't exist so it doesn't crash on first run
    if not os.path.exists(dataset):
        with open(dataset, "w", encoding="utf-8") as f:
            json.dump([], f)
            print(f"Created empty dataset at {dataset}. Please populate it.")
            
    try:
        runner.run_benchmark(dataset)
    except KeyboardInterrupt:
        print("\\n🛑 Execution interrupted by user.")

