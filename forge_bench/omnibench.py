import os
import time
import json
from dataclasses import dataclass, field
from typing import List, Dict
from forgeos.sandbox.sandbox_runner import SandboxRunner
from forgeos.engine.state_machine import StateMachine, EngineState, ExecutionContext

@dataclass
class IssueContext:
    issue_number: int
    repo_url: str
    issue_text: str
    expected_strategy: str = ""

@dataclass
class BenchmarkConfig:
    name: str
    enable_pattern_lib: str
    enable_patch_sim: str

@dataclass
class BenchmarkResult:
    config_name: str
    issue_number: int
    success: bool
    retries: int
    cost: float
    time_taken: float
    sim_rejects: int

class OmniBench:
    def __init__(self, dataset: List[IssueContext], configs: List[BenchmarkConfig]):
        self.dataset = dataset
        self.configs = configs
        self.results: List[BenchmarkResult] = []

    def run(self):
        print(f"=== Starting OmniBench against {len(self.dataset)} issues & {len(self.configs)} configs ===")
        for config in self.configs:
            print(f"\n--- Loading Configuration: {config.name} ---")
            os.environ["FORGEOS_ENABLE_PATTERN_LIB"] = config.enable_pattern_lib
            os.environ["FORGEOS_ENABLE_PATCH_SIM"] = config.enable_patch_sim

            for issue in self.dataset:
                res = self._run_single_issue(config.name, issue)
                self.results.append(res)
                
        self._generate_report()

    def _run_single_issue(self, config_name: str, issue: IssueContext) -> BenchmarkResult:
        print(f"Running Issue #{issue.issue_number}...")
        start_time = time.time()
        
        # We need mock components for the sandbox and artifact layers in a pure benchmark, 
        # but for this MVP, we will run the actual ForgeOS state machine up to DONE/FAILED
        
        # Ensure we have a clean context for each run
        runner = SandboxRunner()
        sanitized_name = config_name.replace(' ', '_').replace('(', '').replace(')', '')
        repo_path = runner.clone_repo(issue.repo_url, f"{issue.issue_number}_{sanitized_name}")
        
        context = ExecutionContext(
            issue_number=issue.issue_number,
            repo_path=repo_path,
            issue_text=issue.issue_text
        )
        engine = StateMachine()
        
        retries = 0
        sim_rejects = 0
        
        # Hard cap to prevent infinite retry loops during benchmarking
        # Run the full engine
        try:
            context = engine.run(context)
        except Exception as e:
            print(f"Engine crash: {e}")
            
        success = context.current_state == EngineState.DONE

        # Parse logs to construct benchmark metrics
        for log in context.logs:
            if "Entering state: RETRY" in log:
                retries += 1
            if "WARNING: Simulation intercepted a severe structural flaw" in log:
                sim_rejects += 1

        cost = context.global_cost
        time_taken = time.time() - start_time
        
        print(f"Result: {'SUCCESS' if success else 'FAILED'} | Retries: {retries} | SimRejects: {sim_rejects} | Cost: ${cost:.3f}")
        
        if not success and cost == 0.0:
            print("--- CRITICAL FAILURE LOGS ---")
            for log in context.logs:
                print(f"  {log}")
            print("-----------------------------")
        
        return BenchmarkResult(
            config_name=config_name,
            issue_number=issue.issue_number,
            success=success,
            retries=retries,
            cost=cost,
            time_taken=time_taken,
            sim_rejects=sim_rejects
        )

    def _generate_report(self):
        report_path = "benchmark_results.md"
        print(f"\n=== Generating Markdown Report -> {report_path} ===")
        
        # Aggregate stats
        stats = {}
        for config in self.configs:
            stats[config.name] = {
                "total": 0, "success": 0, "first_pass": 0, "cost": 0.0, "time": 0.0, "sim_rejects": 0
            }
            
        for r in self.results:
            c = stats[r.config_name]
            c["total"] += 1
            if r.success:
                c["success"] += 1
                if r.retries == 0:
                    c["first_pass"] += 1
            c["cost"] += r.cost
            c["time"] += r.time_taken
            c["sim_rejects"] += r.sim_rejects

        lines = [
            "# OmniBench A/B Analysis Report",
            "Measuring the engineering impact of Cognitive Stack v2 vs Baseline.",
            "",
            "| Configuration | Success Rate | First-Pass Yield | Avg Cost | Prevented Bad Tests |",
            "|---|---|---|---|---|"
        ]
        
        for name, data in stats.items():
            total = data["total"]
            if total == 0: continue
            
            sr = (data["success"] / total) * 100
            fp = (data["first_pass"] / total) * 100
            avg_cost = data["cost"] / total
            
            lines.append(f"| **{name}** | {sr:.1f}% ({data['success']}/{total}) | {fp:.1f}% | ${avg_cost:.3f} | {data['sim_rejects']} |")
            
        with open(report_path, "w") as f:
            f.write("\n".join(lines))
            
        print("Done.")

if __name__ == "__main__":
    dataset_path = "forge_bench/taxonomy_tasks.json"
    dataset = []
    
    if os.path.exists(dataset_path):
        with open(dataset_path, "r") as f:
            raw_tasks = json.load(f)
            # Run all tasks for the overnight benchmark farm
            for t in raw_tasks:
                dataset.append(IssueContext(
                    issue_number=t["id"],
                    repo_url=t["repo_url"],
                    issue_text=t["title"] + "\\n" + t["description"]
                ))
    else:
        print(f"Dataset {dataset_path} not found. Please generate it first.")
        exit(1)
        
    configs = [
        BenchmarkConfig("Stack A (Baseline)", "false", "false"),
        BenchmarkConfig("Stack B (Retrieval Only)", "true", "false"),
        BenchmarkConfig("Stack C (Full Cognitive v2)", "true", "true")
    ]
    
    bench = OmniBench(dataset, configs)
    bench.run()
