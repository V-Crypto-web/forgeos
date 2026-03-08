import os
import sys

# Add forgeos to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from forgeos.sandbox.sandbox_runner import SandboxRunner
from forgeos.repo.repo_analyzer import RepoAnalyzer

def main():
    print("--- Testing Repo Analyzer ---")
    analyzer = RepoAnalyzer(os.path.abspath(os.path.join(os.path.dirname(__file__), "sample_repo")))
    summary = analyzer.get_repo_map_summary()
    print(summary)
    
    print("\n--- Testing Sandbox Runner ---")
    runner = SandboxRunner()
    repo_url = os.path.abspath(os.path.join(os.path.dirname(__file__), "sample_repo"))
    
    # 1. Clone
    target_dir = runner.clone_repo(repo_url, 1)
    print(f"Cloned to: {target_dir}")
    
    # 2. Run Tests (should have 1 failure due to empty string bug if using pytest)
    # Note: installing pytest if not present might be needed, but we'll try running it
    os.environ["PYTHONPATH"] = target_dir
    res = runner.run_tests(target_dir, "python3 -m pytest")
    print("Test status:", res['status'])
    print("Test output sample:", res['output'][:200])
    
    # 3. Apply Patch
    patch = """diff --git a/api/auth.py b/api/auth.py
index e69de29..b84d471 100644
--- a/api/auth.py
+++ b/api/auth.py
@@ -3,6 +3,9 @@ def validate_token(token: str) -> bool:
     if token is None:
         return False
         
+    if token == "":
+        return False
+        
     # Dummy logic
     if len(token) > 0 and token.startswith("Bearer "):
         return True
"""
    success = runner.apply_patch(target_dir, patch)
    print(f"Patch applied: {success}")
    
    # 4. Run tests again
    res2 = runner.run_tests(target_dir, "python3 -m pytest")
    print("Post-patch test status:", res2['status'])
    
    # 5. Reset
    runner.reset_repo(target_dir)
    print("Repo reset completed.")

if __name__ == "__main__":
    main()
