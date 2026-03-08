import os
import json

base_dir = "/tmp/forgeos_workspaces/"
for p in os.listdir(base_dir):
    art_dir = os.path.join(base_dir, p, ".forgeos", "artifacts")
    if not os.path.exists(art_dir): continue
    for issue_dir in os.listdir(art_dir):
        issue_path = os.path.join(art_dir, issue_dir)
        if not os.path.isdir(issue_path): continue
        plan_f = os.path.join(issue_path, "plan.md")
        test_f = os.path.join(issue_path, "test_results_1.json")
        patch_f = os.path.join(issue_path, "patch_attempt_1.diff")
        
        if os.path.exists(plan_f) and os.path.exists(test_f):
            print(f"\\n================ {p} ================")
            try:
                with open(plan_f) as f:
                    plan = f.read()
                    print(f"--- PLAN SNIPPET ---\\n{plan[:300]}...\\n")
            except: pass
            
            try:
                if os.path.exists(patch_f):
                    with open(patch_f) as f:
                        patch = f.read()
                        print(f"--- PATCH SNIPPET ---\\n{patch[:300]}...\\n")
            except: pass
            
            try:
                with open(test_f) as f:
                    td = json.load(f)
                    print(f"--- TESTS (Passed: {td.get('passed')}, Failed: {td.get('failures')}, Errors: {td.get('errors')}) ---")
                    out = td.get("output", "")
                    # print last 10 lines of test output
                    print("\\n".join(out.split("\\n")[-10:]))
            except: pass
