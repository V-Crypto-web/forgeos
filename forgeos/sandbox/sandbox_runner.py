import subprocess
import os
import shutil

class SandboxRunner:
    """
    Executes operations in an isolated environment.
    For MVP, we use local subprocesses in a temporary workspace directory,
    relying on Docker/Containers in future iterations.
    """
    def __init__(self, workspace_dir: str = "/tmp/forgeos_workspaces"):
        self.workspace_dir = workspace_dir
        os.makedirs(self.workspace_dir, exist_ok=True)
        
    def clone_repo(self, repo_url: str, issue_number: int) -> str:
        """Clones a repository into a fresh workspace directory."""
        repo_name = repo_url.split('/')[-1].replace('.git', '')
        target_dir = os.path.join(self.workspace_dir, f"{repo_name}_issue_{issue_number}")
        
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
            
        print(f"Cloning {repo_url} into {target_dir}...")
        subprocess.run(["git", "clone", repo_url, target_dir], check=True, capture_output=True)
        return target_dir

    def bootstrap_environment(self, repo_path: str) -> str:
        """
        Reads repo_profile.yaml or delegates to EnvironmentOrchestrator to autonomously
        create a virtual environment and install dependencies.
        Returns the path to the python executable within the venv.
        """
        import yaml
        profile_path = os.path.join(repo_path, "repo_profile.yaml")
        venv_path = os.path.join(repo_path, ".venv")
        python_exec = os.path.join(venv_path, "bin", "python")
        pytest_exec = os.path.join(venv_path, "bin", "pytest")

        # Fast path: existing .venv with pytest already installed — just use it
        if os.path.exists(python_exec) and os.path.exists(pytest_exec):
            print(f"Reusing existing .venv at {venv_path} (pytest already installed).")
            return python_exec

        if not os.path.exists(profile_path):
            print(f"No repo_profile.yaml found in {repo_path}. Using EnvironmentOrchestrator.")

            from forgeos.sandbox.env_orchestrator import EnvironmentOrchestrator
            orch = EnvironmentOrchestrator(repo_path)
            success, logs = orch.setup_environment()
            print(logs)
            if not success:
                print("Environment setup failed. Falling back to system python.")
                return "python3"
            return python_exec if os.path.exists(python_exec) else "python3"
            
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
            
        if not os.path.exists(venv_path):
            print(f"Creating virtual environment at {venv_path}...")
            # We use the system python3.11 or whatever is available to create the venv
            subprocess.run(["python3", "-m", "venv", ".venv"], cwd=repo_path, check=True)
            
            # Install dependencies based on repo_profile
            install_cmd = profile.get("install_command", "")
            if install_cmd:
                # Replace generic 'python' with our venv python
                install_cmd = install_cmd.replace("python ", f"{python_exec} ")
                print(f"Bootstrapping environment with: {install_cmd}")
                # We use shell=True here because install commands might contain '&&'
                subprocess.run(install_cmd, cwd=repo_path, shell=True, check=True)
        else:
            print(f"Virtual environment already exists at {venv_path}.")
            
        return python_exec

    def apply_patch(self, repo_path: str, patch_content: str) -> bool:
        """Applies a code patch to the repository."""
        patch_file = os.path.join(repo_path, "changes.patch")
        with open(patch_file, "w") as f:
            f.write(patch_content)
        
        print(f"Applying patch in {repo_path}")
        result = subprocess.run(["git", "apply", "changes.patch"], cwd=repo_path, capture_output=True, text=True)
        
        # Clean up patch file
        if os.path.exists(patch_file):
            os.remove(patch_file)
        
        if result.returncode != 0:
            print(f"Patch apply failed: {result.stderr}")
            return False
            
        return True

    def run_tests(self, repo_path: str, test_targets: list[str] = None, escalate_on_fail: bool = True) -> dict:
        """Runs the test suite. Auto-installs pytest-json-report if missing. Falls back to plain pytest."""
        python_exec = self.bootstrap_environment(repo_path)

        # Ensure pytest and pytest-json-report are available in the venv
        subprocess.run(
            [python_exec, "-m", "pip", "install", "-q", "pytest", "pytest-json-report"],
            cwd=repo_path, capture_output=True
        )

        report_file = os.path.join(repo_path, ".report.json")

        def _run(cmd):
            return subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)

        # Try with json-report first
        base_cmd = [python_exec, "-m", "pytest", "--json-report", f"--json-report-file={report_file}", "-v"]
        command = base_cmd + (test_targets or [])
        result = _run(command)

        # If json-report plugin errors out use plain pytest
        if result.returncode not in [0, 1, 2, 5] and ("no module named" in result.stderr.lower() or "unrecognized" in result.stderr.lower()):
            print("pytest-json-report unavailable, falling back to plain pytest...")
            base_cmd = [python_exec, "-m", "pytest", "-v"]
            command = base_cmd + (test_targets or [])
            result = _run(command)

        # Escalation: if targeted test files not found, try full suite
        if result.returncode not in [0, 5] and test_targets and escalate_on_fail:
            print("Targeted tests not found. Escalating to full suite...")
            command = [python_exec, "-m", "pytest", "-v"]
            result = _run(command)

        # returncode 5 = no tests collected — treat as pass (repo has no tests yet)
        status = "success" if result.returncode in [0, 5] else "failed"
        if result.returncode == 5:
            print("No tests found in repo — treating as pass (no test failures).")

        # --- PHASE 2: MATRYOSHKA INTEGRATION TEST (For Self-Hosting Safety) ---
        # If we are testing a patch on ForgeAI itself, unit tests passing is NOT ENOUGH.
        # We must prove the core engine can still boot and run a dummy payload without crashing.
        # This prevents "Suicide Loops" where a patch passes tests but breaks the orchestrator.
        if status == "success" and ("ForgeAI" in repo_path or repo_path.endswith("ForgeAI")):
            print("--- INITIATING PHASE 2: MATRYOSHKA INTEGRATION TEST ---")
            # We run the E2E test script inside the guest sandbox as our integration proof
            # using the guest's own python executable
            matryoshka_cmd = [python_exec, "test_pattern_library_e2e.py"]
            matryoshka_result = _run(matryoshka_cmd)
            
            if matryoshka_result.returncode != 0:
                print("--- MATRYOSHKA PHASE 2 FAILED ---")
                print("The patch passed unit tests but the engine crashed during integration boot!")
                print(matryoshka_result.stderr)
                status = "failed"
                # Rewrite the output to forcefully flag this as a suicide patch
                result.stderr = "FATAL: INTEGRATION SUICIDE DETECTED.\n" + matryoshka_result.stderr
                result.stdout = result.stdout + "\n[MATRYOSHKA] Integration failed.\n" + matryoshka_result.stdout
                result.returncode = matryoshka_result.returncode
            else:
                print("--- MATRYOSHKA PHASE 2 PASSED ---")
                result.stdout = result.stdout + "\n[MATRYOSHKA] Engine booted successfully in guest sandbox."

        return {
            "status": status,
            "output": result.stdout,
            "errors": result.stderr,
            "returncode": result.returncode,
            "command": " ".join(command)
        }


        
    def commit_and_push(self, repo_path: str, branch_name: str, commit_message: str) -> bool:
        """Commits the current changes and pushes them to the given branch."""
        print(f"Committing and pushing changes to {branch_name} in {repo_path}")
        
        # Checkout new branch
        subprocess.run(["git", "checkout", "-b", branch_name], cwd=repo_path, capture_output=True)
        
        # Add and commit
        subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)
        res = subprocess.run(["git", "commit", "-m", commit_message], cwd=repo_path, capture_output=True, text=True)
        
        if "nothing to commit" in res.stdout:
            print("Nothing to commit, skipping push.")
            return False
            
        # Push (Mocked for safety if no token or mock mode)
        if os.environ.get("FORGEOS_MOCK_LLM") == "true" or not os.environ.get("GITHUB_TOKEN"):
            print("Mock mode or missing GITHUB_TOKEN: skipping actual git push.")
            return True
            
        # Actual push
        push_res = subprocess.run(["git", "push", "-u", "origin", branch_name], cwd=repo_path, capture_output=True, text=True)
        if push_res.returncode != 0:
            print(f"Git push failed: {push_res.stderr}")
            return False
            
        return True

    def reset_repo(self, repo_path: str) -> None:
        """Resets the repository to clean state, dropping all uncommitted changes."""
        print(f"Resetting repo state in {repo_path}")
        subprocess.run(["git", "reset", "--hard"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "clean", "-fd"], cwd=repo_path, capture_output=True)
