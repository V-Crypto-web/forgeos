import time
import os
import json
import logging
from typing import List, Dict

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ForgeOS_Daemon")

# Mock Queue File
QUEUE_FILE = "/tmp/forgeos_pending_repos.json"

class PreComputeDaemon:
    """
    Module 9 (God Mode): Background AST Pre-Compute Daemon.
    Watches a queue of pending repositories (simulating a webhook consumer).
    When a new repo arrives, it proactively clones it and runs RepoAnalyzer 
    to build the AST (repo_map.json), ensuring zero Cold Start latency for the engine.
    """
    
    def __init__(self):
        self.processed = set()
        
    def init_queue(self):
        if not os.path.exists(QUEUE_FILE):
            with open(QUEUE_FILE, "w") as f:
                json.dump([], f)
                
    def read_queue(self) -> List[Dict]:
        try:
            with open(QUEUE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
            
    def process_repo(self, repo_url: str):
        logger.info(f"Pre-computing AST Cache for: {repo_url}")
        
        # 1. Clone Repo via Sandbox
        from forgeos.sandbox.sandbox_runner import SandboxRunner
        runner = SandboxRunner()
        # Mocking issue ID to 0 for pre-compute
        local_path = runner.setup_environment(repo_url, 0)
        
        if not local_path:
            logger.error(f"Failed to clone repository: {repo_url}")
            return
            
        # 2. Run AST Analyzer
        from forgeos.repo.repo_analyzer import RepoAnalyzer
        analyzer = RepoAnalyzer(local_path)
        
        # This computes the tree and saves it to `.forgeos/cache/.../repo_map.json`
        repo_map = analyzer.generate_repo_map()
        
        logger.info(f"Successfully generated AST for {repo_url}. Found {len(repo_map)} files.")
        
    def run(self):
        logger.info("ForgeOS Pre-Compute Daemon started. Watching for new repositories...")
        self.init_queue()
        
        while True:
            queue = self.read_queue()
            for item in queue:
                repo_url = item.get("url")
                if repo_url and repo_url not in self.processed:
                    self.process_repo(repo_url)
                    self.processed.add(repo_url)
                    
            time.sleep(5)

if __name__ == "__main__":
    daemon = PreComputeDaemon()
    daemon.run()
