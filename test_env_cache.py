import os
import shutil
import time
from forgeos.sandbox.env_orchestrator import EnvironmentOrchestrator

# Setup mock repo
os.makedirs("/tmp/1_mockrepo", exist_ok=True)
os.makedirs("/tmp/2_mockrepo", exist_ok=True)

for i, ws in enumerate(["/tmp/1_mockrepo", "/tmp/2_mockrepo"]):
    with open(os.path.join(ws, "requirements.txt"), "w") as f:
        f.write("requests==2.31.0\n")

print("=== MOCK WORKSPACE 1: EXPECTING CACHE MISS ===")
orch1 = EnvironmentOrchestrator("/tmp/1_mockrepo")
start1 = time.time()
success1, log1 = orch1.setup_environment()
duration1 = time.time() - start1
print(f"Result: {success1} | Duration: {duration1:.2f}s")
if not success1:
    print(log1)

print("\n=== MOCK WORKSPACE 2: EXPECTING CACHE HIT ===")
orch2 = EnvironmentOrchestrator("/tmp/2_mockrepo")
start2 = time.time()
success2, log2 = orch2.setup_environment()
duration2 = time.time() - start2
print(f"Result: {success2} | Duration: {duration2:.2f}s")
print("Logs:", log2)

# Cleanup
shutil.rmtree("/tmp/1_mockrepo")
shutil.rmtree("/tmp/2_mockrepo")
