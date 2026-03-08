import os
import hashlib
import time
import subprocess
import shutil

CACHE_DIR = "/tmp/forgeos_deps_cache"

class EnvironmentCacheManager:
    """
    Epic 53: Fast-Clone Venv Caching Layer.
    Fingerprints repository dependencies and clones Base Environments via `rsync -a` 
    to bypass the 40+ second `pip install` loop per sandbox.
    """
    def __init__(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        
    def _compute_deps_hash(self, repo_path: str, python_version: str) -> str:
        """
        Creates a strict deterministic hash of the environment requirements.
        Monitors setups.py, requirements.txt, pyproject.toml, and tox.ini if present.
        """
        hasher = hashlib.sha256()
        hasher.update(python_version.encode("utf-8"))
        
        dep_files = ["setup.py", "requirements.txt", "pyproject.toml", "poetry.lock", "Pipfile.lock", "tox.ini"]
        for fname in dep_files:
            fpath = os.path.join(repo_path, fname)
            if os.path.exists(fpath):
                hasher.update(fname.encode("utf-8"))
                with open(fpath, "rb") as f:
                    hasher.update(f.read())
                    
        return hasher.hexdigest()[:16]

    def get_or_create_env(self, repo_name: str, repo_path: str, venv_path: str, python_version: str, bootstrap_cmds: list[str]) -> dict:
        """
        Checks if a Base Environment exists.
        If HIT: Clones it into the target venv_path.
        If MISS: Instructs caller to run the full bootstrap.
        Returns metrics for Telemetry.
        """
        deps_hash = self._compute_deps_hash(repo_path, python_version)
        cache_key = f"{repo_name}_{deps_hash}"
        base_env_path = os.path.join(CACHE_DIR, cache_key)
        
        metrics = {"hit": False, "clone_time": 0.0, "base_env_path": base_env_path, "cache_key": cache_key}
        
        if os.path.exists(base_env_path) and os.path.exists(os.path.join(base_env_path, "bin", "python")):
            print(f"[EnvCache] ⚡ HIT: Base environment found for {cache_key}. Fast cloning...")
            start_time = time.time()
            
            # Use rsync for deterministic fast symlink-aware copies
            # We copy the CACHED env into the Target working VENV path
            cmd = ["rsync", "-a", f"{base_env_path}/", f"{venv_path}/"]
            res = subprocess.run(cmd, capture_output=True, text=True)
            
            if res.returncode == 0:
                metrics["clone_time"] = time.time() - start_time
                metrics["hit"] = True
                print(f"[EnvCache] successfully cloned in {metrics['clone_time']:.2f}s")
            else:
                print(f"[EnvCache] ERROR: Fast clone failed: {res.stderr}. Forcing miss.")
                
        else:
            print(f"[EnvCache] 🐌 MISS: No base environment found for {cache_key}.")
            
        return metrics

    def cache_env(self, source_venv_path: str, base_env_path: str):
        """
        After a MISS, once the EnvironmentOrchestrator successfully builds the sandbox,
        we dump it into the cache for future runs.
        """
        print(f"[EnvCache] Snapshotting built environment to cache: {base_env_path}...")
        try:
            cmd = ["rsync", "-a", f"{source_venv_path}/", f"{base_env_path}/"]
            subprocess.run(cmd, capture_output=True, text=True, check=True)
            print("[EnvCache] Snapshot complete.")
        except subprocess.CalledProcessError as e:
            print(f"[EnvCache] Warning: Failed to snapshot environment: {e.stderr}")
