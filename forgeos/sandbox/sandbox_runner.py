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
        """Runs the test suite within the sandbox, with support for targeted execution and escalation."""
        # Bootstrap dependencies before running tests
        python_exec = self.bootstrap_environment(repo_path)
            
        report_file = os.path.join(repo_path, ".report.json")
        base_cmd = [python_exec, "-m", "pytest", "--json-report", f"--json-report-file={report_file}"]
        
        if test_targets:
            command = base_cmd + test_targets
            print(f"Running targeted tests: {' '.join(command)} in {repo_path}")
        else:
            command = base_cmd
            print(f"Running full test suite in {repo_path} with JSON reporting")
            
        result = subprocess.run(command, cwd=repo_path, capture_output=True, text=True)
        
        # Escalation logic: if targeted tests fail to execute (e.g. not found) or we want to be safe on failure
        if result.returncode not in [0, 5] and test_targets and escalate_on_fail:
            print("Targeted tests failed or not found. Escalating to full test suite...")
            command = base_cmd
            result = subprocess.run(command, cwd=repo_path, capture_output=True, text=True)
            
        return {
            "status": "success" if result.returncode in [0, 5] else "failed",
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
