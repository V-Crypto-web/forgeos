import json
import os
import sys

# Import canonicalize function from the miner
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from forgeos.memory.failure_miner import canonicalize_signature

DB_PATH = "/Users/vasiliyprachev/Python_Projects/ForgeAI/forgeos/memory/failure_db"

for fname in os.listdir(DB_PATH):
    if not fname.endswith(".json"): continue
    path = os.path.join(DB_PATH, fname)
    with open(path, "r") as f:
        data = json.load(f)
    
    orig_sig = data.get("failure_signature")
    if not orig_sig: continue
    
    new_sig = canonicalize_signature(orig_sig)
    if orig_sig != new_sig:
        data["failure_signature"] = new_sig
        with open(path, "w") as f:
            json.dump(data, f, indent=4)
        print(f"Updated {fname}: {orig_sig} -> {new_sig}")
print("Migration completed.")
