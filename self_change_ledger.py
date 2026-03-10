"""
self_change_ledger.py
=====================
Immutable append-only ledger for all self-modifications ForgeOS makes to its
own codebase (Ouroboros loop). Every entry is a JSON line in
/tmp/forgeos_self_change_ledger.jsonl

Each entry:
  {
    "ts":          "ISO-8601",
    "task_id":     "task_self_epic_opp_...",
    "epic_id":     "epic-opp-...",
    "decision":    "COMMITTED" | "REJECTED",
    "branch":      "ouroboros/patch-...",
    "files":       ["path/a.py", ...],
    "reason":      "tests passed" | "git apply --check failed: ...",
    "cost_usd":    0.042
  }
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone

LEDGER_PATH = os.environ.get("FORGEOS_LEDGER_PATH", "/tmp/forgeos_self_change_ledger.jsonl")


def record(
    task_id: str,
    epic_id: str,
    decision: str,          # "COMMITTED" | "REJECTED"
    branch: str,
    files: list[str],
    reason: str,
    cost_usd: float = 0.0,
) -> dict:
    """Append one entry to the ledger and return it."""
    entry = {
        "ts":       datetime.now(timezone.utc).isoformat(),
        "task_id":  task_id,
        "epic_id":  epic_id,
        "decision": decision,
        "branch":   branch,
        "files":    files,
        "reason":   reason,
        "cost_usd": round(cost_usd, 6),
    }
    try:
        with open(LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[LEDGER ERROR] Could not write entry: {e}")
    return entry


def load(n: int = 100) -> list[dict]:
    """Return the last N entries from the ledger (newest last)."""
    if not os.path.exists(LEDGER_PATH):
        return []
    entries = []
    try:
        with open(LEDGER_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        pass
    return entries[-n:]
