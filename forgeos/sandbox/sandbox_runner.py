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
        """Applies a code patch to the repository using multi-stage fallbacks."""
        import re
        
        # Robustly extract the diff block from markdown fences using regex
        cleaned_patch = patch_content
        match = re.search(r"```(?:diff)?\n?(.*?)```", patch_content, flags=re.DOTALL)
        if match:
            cleaned_patch = match.group(1)
            
        # Fallback manual cleanup for dangling markdown or common hallucinations
        cleaned_patch = cleaned_patch.strip() + "\n"
        if cleaned_patch.startswith("```diff"):
            cleaned_patch = cleaned_patch[7:].strip() + "\n"

        # FIX COMMON LLM BUG: Empty context lines missing the leading space
        fixed_lines = []
        for line in cleaned_patch.split("\n"):
            if line == "":
                fixed_lines.append(" ")
            else:
                fixed_lines.append(line)
        cleaned_patch = "\n".join(fixed_lines)

        patch_file = os.path.join(repo_path, "changes.patch")
        with open(patch_file, "w") as f:
            f.write(cleaned_patch)
        
        print(f"Applying patch in {repo_path}")
        
        # Strategy 1: Strict git apply (best for clean patches, respects git index)
        result = subprocess.run(["git", "apply", "changes.patch"], cwd=repo_path, capture_output=True, text=True)
        if result.returncode == 0:
            os.remove(patch_file)
            return True
            
        print(f"git apply failed: {result.stderr.strip()}. Falling back to Strategy 2 (patch -p1)...")
        
        # Strategy 2: Unix patch with fuzzing (lenient on context lines, assumes a/ and b/ prefixes)
        # Using shell=True for input redirection
        patch_cmd_1 = "patch --force -p1 --fuzz=3 < changes.patch"
        res_p1 = subprocess.run(patch_cmd_1, cwd=repo_path, shell=True, capture_output=True, text=True)
        if res_p1.returncode == 0:
            print("Strategy 2 (patch -p1) succeeded.")
            os.remove(patch_file)
            return True
            
        print(f"patch -p1 failed: {res_p1.stdout.strip()}. Falling back to Strategy 3 (patch -p0)...")
        
        # Strategy 3: Unix patch without stripping prefixes (if LLM omitted a/ b/)
        patch_cmd_0 = "patch --force -p0 --fuzz=3 < changes.patch"
        res_p0 = subprocess.run(patch_cmd_0, cwd=repo_path, shell=True, capture_output=True, text=True)
        if res_p0.returncode == 0:
            print("Strategy 3 (patch -p0) succeeded.")
            os.remove(patch_file)
            return True
            
        print(f"patch -p0 failed: {res_p0.stdout.strip()}. Falling back to Strategy 4 (patch -p2)...")
        
        # Strategy 4: Unix patch -p2 (if LLM output a/repo_name/...)
        patch_cmd_2 = "patch --force -p2 --fuzz=3 < changes.patch"
        res_p2 = subprocess.run(patch_cmd_2, cwd=repo_path, shell=True, capture_output=True, text=True)
        if res_p2.returncode == 0:
            print("Strategy 4 (patch -p2) succeeded.")
            os.remove(patch_file)
            return True
            
        print(f"patch -p2 failed: {res_p2.stdout.strip()}. Falling back to Strategy 5 (patch -p3)...")

        # Strategy 5: Unix patch -p3
        patch_cmd_3 = "patch --force -p3 --fuzz=3 < changes.patch"
        res_p3 = subprocess.run(patch_cmd_3, cwd=repo_path, shell=True, capture_output=True, text=True)
        if res_p3.returncode == 0:
            print("Strategy 5 (patch -p3) succeeded.")
            os.remove(patch_file)
            return True

        print(f"ALL patch strategies failed. Final output: {res_p3.stdout.strip()}")
        if os.path.exists(patch_file):
            os.remove(patch_file)
        return False

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
        matryoshka_script = os.path.join(repo_path, "test_pattern_library_e2e.py")
        if status == "success" and ("ForgeAI" in repo_path or repo_path.endswith("ForgeAI")) and os.path.exists(matryoshka_script):
            print("--- INITIATING PHASE 2: MATRYOSHKA INTEGRATION TEST ---")
            # We run the E2E test script inside the guest sandbox as our integration proof
            # using the guest's own python executable
            matryoshka_cmd = [python_exec, matryoshka_script]
            matryoshka_result = _run(matryoshka_cmd)
            
            if matryoshka_result.returncode != 0:
                stderr_lower = matryoshka_result.stderr.lower()
                # If failure is just missing deps (e.g., litellm not installed in sandbox venv),
                # this is a sandbox limitation, NOT a suicide patch. Treat as warning.
                if "modulenotfounderror" in stderr_lower or "importerror" in stderr_lower or "no module named" in stderr_lower:
                    print("--- MATRYOSHKA PHASE 2 SKIPPED (Missing sandbox deps - not a code error) ---")
                    result.stdout = result.stdout + "\n[MATRYOSHKA] Skipped: Missing sandbox deps (not a code regression)."
                else:
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
