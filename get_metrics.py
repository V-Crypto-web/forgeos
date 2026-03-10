import urllib.request
import json
from collections import Counter

try:
    with urllib.request.urlopen("http://localhost:8081/api/v1/tasks") as response:
        tasks = json.loads(response.read())
except Exception as e:
    print("Error fetching tasks:", e)
    tasks = []

try:
    with urllib.request.urlopen("http://localhost:8081/api/v1/scheduler/status") as response:
        scheduler = json.loads(response.read())
except Exception:
    scheduler = {}

try:
    with urllib.request.urlopen("http://localhost:8081/api/v1/metrics/racing") as response:
        racing = json.loads(response.read())
except Exception:
    racing = {}

print("\n=== Mission Control Summary ===")
active_runs = sum(1 for t in tasks if t.get("status") == "RUNNING")
print(f"Active (RUNNING) Runs: {active_runs}")
completed_runs = sum(1 for t in tasks if t.get("status") == "DONE")
print(f"Completed (DONE): {completed_runs}")
failed_runs = sum(1 for t in tasks if t.get("status") == "FAILED")
print(f"Failed Total: {failed_runs}")

stalled_counts = Counter(t.get("current_state") for t in tasks if t.get("current_state", "").startswith("FAILED_STALLED"))
print("Stalled task breakdown:")
for state, count in stalled_counts.items():
    print(f" - {state}: {count}")

print("\n=== Scheduler Status ===")
print(f"Status: {scheduler.get('status')}")
print(f"Process Running: {scheduler.get('process_running')}")
print(f"Last Tick: {scheduler.get('last_tick')}")

print("\n=== Racing Metrics ===")
print(f"Races Total: {racing.get('races_total')}")
dist = racing.get('winner_strategy_distribution', {})
top_strategy = max(dist.items(), key=lambda x: x[1])[0] if dist else "None"
print(f"Top Strategy: {top_strategy}")

linear = racing.get('linear', {})
racing_stats = racing.get('racing', {})

l_done = linear.get("done", 0)
l_tasks = linear.get("tasks", 0)
l_rate = linear.get("success_rate", 0) * 100
print(f"Linear: {l_done}/{l_tasks} done ({l_rate:.1f}%)")

r_done = racing_stats.get("done", 0)
r_tasks = racing_stats.get("tasks", 0)
r_rate = racing_stats.get("success_rate", 0) * 100
print(f"Racing: {r_done}/{r_tasks} done ({r_rate:.1f}%)")
