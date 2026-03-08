import os
import json
import shutil

workspace_dir = "/tmp/forgeos_workspaces/"
failures = []

for d in os.listdir(workspace_dir):
    path = os.path.join(workspace_dir, d)
    if not os.path.isdir(path): continue
        
    boot_path = os.path.join(path, "bootstrap_report.json")
    if not os.path.exists(boot_path): continue
        
    try:
        with open(boot_path) as f:
            boot = json.load(f)
            if not boot.get("success"):
                continue # Env failure, skip
    except:
        continue
        
    issue_id = d.split("_")[-1]
    artifacts_dir = os.path.join(path, ".forgeos", "artifacts", f"issue_{issue_id}")
    if not os.path.exists(artifacts_dir): continue
    
    test_files = [f for f in os.listdir(artifacts_dir) if f.startswith("test_results_")]
    if not test_files: continue
    
    test_files.sort()
    last_test_file = test_files[-1]
    try:
        with open(os.path.join(artifacts_dir, last_test_file)) as f:
            tdata = json.load(f)
            # Find if there are failures
            out = tdata.get("output", "")
            if "failed" in out.lower() or "error" in out.lower() or tdata.get("passed") == 0:
                failures.append(d)
    except:
        continue

print(f"Found {len(failures)} cognitive failures.")

# Let's aggregate the traces into a dump directory so we can read them easily
dump_dir = "forge_bench/failure_traces"
os.makedirs(dump_dir, exist_ok=True)

for fail_dir in failures:
    source_artifacts = os.path.join(workspace_dir, fail_dir, ".forgeos", "artifacts")
    target_dir = os.path.join(dump_dir, fail_dir)
    os.makedirs(target_dir, exist_ok=True)
    
    # Copy diffs, plans, test results
    for f in os.listdir(source_artifacts):
        if f.endswith(".diff") or f.endswith(".md") or f.endswith(".json"):
            shutil.copy2(os.path.join(source_artifacts, f), os.path.join(target_dir, f))

print(f"Traces dumped to {dump_dir}")
