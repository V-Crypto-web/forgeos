import os
import json
import time
import subprocess
from typing import Dict, Any, List

class OmniBenchHarness:
    """
    Epic 35: Omni-Bench Harness
    A mass evaluator to test ForgeOS against 50+ issues and collect core SWE metrics.
    """
    def __init__(self, dataset_path: str):
        self.dataset_path = dataset_path
        self.results_path = os.path.join(os.path.dirname(dataset_path), "omni_bench_results.json")
        self.tasks = self._load_dataset()
        
    def _load_dataset(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.dataset_path):
            print(f"Dataset not found: {self.dataset_path}")
            return []
            
        with open(self.dataset_path, "r", encoding="utf-8") as f:
            return json.load(f)
            
    def run_all(self):
        if not self.tasks:
            return
            
        print(f"Starting Omni-Bench across {len(self.tasks)} tasks...")
        results = []
        total_start = time.time()
        
        for task in self.tasks:
            repo_name = task.get("repo_name", "unknown_repo")
            issue_number = task.get("original_issue_number", task.get("id", "0"))
            repo_url = task.get("repo_url", f"https://github.com/mock/{repo_name}")


            
            print(f"\\n--- Running Task: {repo_name} #{issue_number} ---")
            task_start = time.time()
            
            # Execute forge_cli.py using the 'repair' command to trigger autonomous cloning
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cmd = ["python3", "forge_cli.py", "repair", repo_url, str(issue_number)]
            
            # Ensure the child process runs with real API keys
            child_env = os.environ.copy()
            child_env["FORGEOS_MOCK_LLM"] = "false"
            
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, cwd=root_dir, env=child_env)
                success = "✅ Issue" in res.stdout and "resolved successfully" in res.stdout
                
                # Scrape telemetry for cost
                cost = 0.0
                for line in res.stdout.split("\\n"):
                    if "Total Run Cost:" in line:
                        try:
                            cost = float(line.split("$")[-1][:6])
                        except:
                            pass
                            
                results.append({
                    "issue_number": issue_number,
                    "repo": repo_url,
                    "success": success,
                    "cost": cost,
                    "time_seconds": time.time() - task_start,
                    "status": "PASS" if success else "FAIL"
                })
            except Exception as e:
                print(f"Task Failed due to Exception: {e}")
                results.append({
                    "issue_number": issue_number,
                    "repo": repo_url,
                    "success": False,
                    "error": str(e)
                })
                
        self._generate_report(results, time.time() - total_start)
        
    def _generate_report(self, results: List[Dict[str, Any]], total_time: float):
        successes = sum(1 for r in results if r.get("success"))
        total = len(results)
        success_rate = (successes / total) * 100 if total > 0 else 0
        total_cost = sum(r.get("cost", 0) for r in results)
        avg_cost = total_cost / total if total > 0 else 0
        
        report = {
            "timestamp": time.time(),
            "total_tasks": total,
            "successes": successes,
            "success_rate_percent": success_rate,
            "total_cost_usd": total_cost,
            "average_cost_usd": avg_cost,
            "total_time_seconds": total_time,
            "individual_results": results
        }
        
        with open(self.results_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            
        print(f"\\n=== Omni-Bench Complete ===")
        print(f"Success Rate: {success_rate:.1f}% ({successes}/{total})")
        print(f"Total Cost: ${total_cost:.4f}")
        print(f"Average Cost/Task: ${avg_cost:.4f}")
        print(f"Results saved to {self.results_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ForgeOS Mass Evaluation Runner")
    parser.add_argument("--dataset", required=True, help="Path to JSON dataset of tasks")
    args = parser.parse_args()
    
    harness = OmniBenchHarness(args.dataset)
    harness.run_all()
