import os
import shutil
import subprocess
from forgeos.sandbox.sandbox_runner import SandboxRunner

def run_test():
    print("=== Testing Matryoshka Sandbox Integration ===")
    test_repo = "/tmp/Fake_ForgeAI_repo"
    if os.path.exists(test_repo):
        shutil.rmtree(test_repo)
        
    os.makedirs(test_repo)
    
    # Create fake tests that pass (Phase 1)
    with open(os.path.join(test_repo, "test_dummy.py"), "w") as f:
        f.write("def test_ok(): pass\n")
        
    # Create a poisonous Phase 2 integration boot payload
    with open(os.path.join(test_repo, "test_pattern_library_e2e.py"), "w") as f:
        f.write("import sys\nprint('Simulated Engine Crash during Matryoshka boot!')\nsys.exit(1)\n")
        
    runner = SandboxRunner()
    
    print("\n--- Running Tests on Poisoned Repo ---")
    res = runner.run_tests(test_repo, test_targets=["test_dummy.py"])
    
    # We expect Phase 1 (pytest) to pass, but Phase 2 (Matryoshka) to fail
    assert res["status"] == "failed", f"Expected 'failed' status due to suicide catch, got {res['status']}"
    assert "FATAL: INTEGRATION SUICIDE DETECTED" in res["errors"], "Missing suicide flag in stderr"
    
    print("\n✅ Matryoshka Suicide Catch Verified Successfully!")

if __name__ == "__main__":
    run_test()
