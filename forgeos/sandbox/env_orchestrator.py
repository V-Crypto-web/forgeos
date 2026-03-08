import os
import subprocess
from typing import Tuple

class EnvironmentOrchestrator:
    """
    Module 14: Environment Orchestrator (Execution OS Layer)
    Auto-detects the project's build system (pip, poetry, uv, npm) and sets up the 
    execution environment autonomously before tests are run.
    Ensures that the LLM doesn't have to guess how to install dependencies.
    """
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        
    def setup_environment(self, mode: str = "heuristic_recovery") -> Tuple[bool, str]:
        """
        Detects the environment type and attempts to install dependencies.
        Modes: 'strict' (fails if no explicit configs found) or 'heuristic_recovery' (injects fallbacks).
        Returns (success, logs).
        """
        import json
        import time
        from forgeos.sandbox.env_cache import EnvironmentCacheManager
        from forgeos.observability.telemetry import TelemetryLogger
        cache_manager = EnvironmentCacheManager()
        telemetry = TelemetryLogger()
        
        # Format workspace paths like 1234_requests -> issue_number_reponame
        issue_prefix = os.path.basename(self.workspace_path).split('_')[0]
        issue_number = int(issue_prefix) if issue_prefix.isdigit() else 0
        repo_name = os.path.basename(self.workspace_path).split('_')[1] if '_' in os.path.basename(self.workspace_path) else "unknown"
        python_version = "python3"
        venv_path = os.path.join(self.workspace_path, ".venv")
        
        cache_metrics = cache_manager.get_or_create_env(
            repo_name=repo_name,
            repo_path=self.workspace_path,
            venv_path=venv_path,
            python_version=python_version,
            bootstrap_cmds=[]
        )
        
        
        telemetry.log_event(
            event_type="env_cache_hit" if cache_metrics["hit"] else "env_cache_miss",
            issue_number=issue_number,
            state="INIT",
            message=f"Environment cache {'hit' if cache_metrics['hit'] else 'miss'} for {repo_name} [{cache_metrics['cache_key']}].",
            metadata=cache_metrics
        )
        
        if cache_metrics["hit"]:
            # If cache hit, we instantly jump out and bypass pip installs
            logs = f"Environment cloned instantly from cache ({cache_metrics['clone_time']:.2f}s).\n"
            report = {
                "timestamp": time.time(),
                "repo_declared_requirements": False,
                "repo_declared_pyproject": False,
                "editable_install_attempted": False,
                "fallback_packages_added": [],
                "bootstrap_mode": "cache_hit",
                "success": True,
                "duration_seconds": cache_metrics["clone_time"]
            }
            report_path = os.path.join(self.workspace_path, "bootstrap_report.json")
            try:
                with open(report_path, "w") as f:
                    json.dump(report, f, indent=2)
            except Exception:
                pass
            return True, logs
            
        report = {
            "timestamp": time.time(),
            "repo_declared_requirements": False,
            "repo_declared_pyproject": False,
            "editable_install_attempted": False,
            "fallback_packages_added": [],
            "bootstrap_mode": mode,
            "success": False,
            "duration_seconds": 0.0
        }
        start_time = time.time()
        
        def save_report(success_state: bool, final_logs: str) -> Tuple[bool, str]:
            report["success"] = success_state
            report["duration_seconds"] = time.time() - start_time
            
            if success_state and not cache_metrics.get("hit"):
                cache_manager.cache_env(venv_path, cache_metrics["base_env_path"])
                
            report_path = os.path.join(self.workspace_path, "bootstrap_report.json")
            try:
                with open(report_path, "w") as f:
                    json.dump(report, f, indent=2)
            except Exception as e:
                final_logs += f"\\nFailed to save bootstrap_report.json: {e}"
            return success_state, final_logs

        if os.path.exists(os.path.join(self.workspace_path, "poetry.lock")):
            report["repo_declared_pyproject"] = True
            succ, logs = self._run_cmd("poetry install")
            return save_report(succ, logs)
            
        elif os.path.exists(os.path.join(self.workspace_path, "Pipfile")):
            report["repo_declared_requirements"] = True  # Using this flag generically for explicit envs
            succ, logs = self._run_cmd("pipenv install")
            return save_report(succ, logs)
            
        elif os.path.exists(os.path.join(self.workspace_path, "requirements.txt")):
            report["repo_declared_requirements"] = True
            venv_path = os.path.join(self.workspace_path, ".venv")
            logs = ""
            if not os.path.exists(venv_path):
                success, log = self._run_cmd(f"python3 -m venv {venv_path}")
                logs += log + "\\n"
                if not success:
                    return save_report(False, logs)
                    
            pip_path = os.path.join(venv_path, "bin", "pip")
            success, log = self._run_cmd(f"{pip_path} install -r requirements.txt")
            logs += log
            return save_report(success, logs)
            
        else:
            if mode == "strict":
                return save_report(False, "Strict mode: No recognized dependency logic found. Setup failed.")
                
            # Fallback: Create a venv and install base test dependencies
            venv_path = os.path.join(self.workspace_path, ".venv")
            logs = "No recognized dependency logic found. Using safe fallback (Heuristic Recovery).\\n"
            if not os.path.exists(venv_path):
                success, log = self._run_cmd(f"python3 -m venv {venv_path}")
                logs += log + "\\n"
                if not success:
                    return save_report(False, logs)
                
            pip_path = os.path.join(venv_path, "bin", "pip")
            fallback_pkgs = ["pytest", "pytest-mock", "pytest-httpbin", "pytest-cov", "pytest-json-report", "setuptools", "wheel"]
            report["fallback_packages_added"] = fallback_pkgs
            
            success, log = self._run_cmd(f"{pip_path} install {' '.join(fallback_pkgs)}")
            logs += log + "\\n"
            
            # Install the package itself in editable mode if setup.py exists
            if os.path.exists(os.path.join(self.workspace_path, "setup.py")) or os.path.exists(os.path.join(self.workspace_path, "pyproject.toml")):
                report["editable_install_attempted"] = True
                if os.path.exists(os.path.join(self.workspace_path, "pyproject.toml")):
                    report["repo_declared_pyproject"] = True
                    
                # Try to install with test/dev extras if they exist, fallback to normal editable
                success, log = self._run_cmd(f"{pip_path} install -e '.[dev,tests,test]'")
                if not success:
                    success, clean_log = self._run_cmd(f"{pip_path} install -e .")
                    log += "\\n" + clean_log
                logs += log
                
            return save_report(True, logs)
            
    def _run_cmd(self, cmd: str) -> Tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd, shell=True, cwd=self.workspace_path,
                capture_output=True, text=True
            )
            output = f"$ {cmd}\n" + result.stdout + "\n" + result.stderr
            return result.returncode == 0, output
        except Exception as e:
            return False, f"Failed to execute {cmd}: {str(e)}"
