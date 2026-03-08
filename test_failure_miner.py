import os
import sys

# Ensure run from root
sys.path.insert(0, os.getcwd())

from forgeos.engine.state_machine import ExecutionContext
from forgeos.memory.failure_miner import FailureIntelligenceEngine

ctx = ExecutionContext(issue_number=999, repo_path="/tmp/mock_repo")
ctx.issue_text = "The application crashes on boot because the main loop relies on a synchronous call inside the ASYNC executor."
ctx.retries = 3
ctx.logs = [
    "Entering state: INIT",
    "Entering state: PLAN",
    "Entering state: PATCH",
    "Entering state: VERIFY",
    "Critic rejected patch: coroutine was never awaited inside `main.py`.",
    "Entering state: RETRY",
    "Entering state: PATCH",
    "Entering state: RUN_TESTS",
    "CRITICAL WARNING: Max budget exceeded. Execution forcefully halted.",
    "Execution finished with state: FAILED"
]
ctx.patch = """
@@ -10,3 +10,4 @@
 def init_server():
-    start_sync()
+    # Forgot to add await again
+    start_sync()
"""

miner = FailureIntelligenceEngine()
print("Triggering FailureMiner on Mock Trace...")
miner.mine_failure(ctx)
