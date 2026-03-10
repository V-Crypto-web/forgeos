"""
opportunity_runner.py
=====================
Orchestrates the full Opportunity Engine pipeline:

  1. Detect signals from failure_db, telemetry, backlog
  2. Score and rank signals
  3. Materialize top signals as real GitHub Issues
  4. Append new epics to improvement_backlog.json
  5. Also fixes any existing epics with placeholder github_issue=9999

Called by burn_in.py when backlog is low OR on startup as pre-flight.
"""
from __future__ import annotations
import os
import json
import sys

# Ensure repo root is in path
_ROOT = os.path.abspath(os.path.dirname(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from opportunity_detector import detect_all_opportunities
from forge_cloud.issue_materializer import (
    materialize_epics_without_issues,
    materialize_signals_as_issues,
)


DEFAULT_BACKLOG = os.path.join(_ROOT, "forge_cloud", "data", "improvement_backlog.json")
DEFAULT_REPO    = os.getenv("FORGEOS_GITHUB_REPO", "V-Crypto-web/forgeos")


def run_opportunity_engine(
    forgeos_root:   str = None,
    backlog_path:   str = None,
    min_new_epics:  int = 5,
    dry_run:        bool = False,
) -> int:
    """
    Full Opportunity Engine run.

    Steps:
      1. Fix existing epics with github_issue=9999 → real issues
      2. Detect new opportunity signals
      3. Materialize top signals as GitHub Issues + backlog entries

    Returns: total count of new/updated issues created.
    """
    forgeos_root = forgeos_root or _ROOT
    backlog_path = backlog_path or DEFAULT_BACKLOG

    print("[OPP ENGINE] ═══ Opportunity Engine Starting ═══")
    total_created = 0

    # ── Step 1: Fix placeholder issues ────────────────────────────────────────
    print("[OPP ENGINE] Phase 1: Materializing epics with placeholder issue numbers…")
    fixed = materialize_epics_without_issues(backlog_path, repo=DEFAULT_REPO, dry_run=dry_run)
    total_created += fixed
    print(f"[OPP ENGINE] Phase 1 complete: {fixed} epics materialized")

    # ── Step 2: Detect signals ─────────────────────────────────────────────────
    print("[OPP ENGINE] Phase 2: Detecting opportunity signals…")
    telemetry_path = "/tmp/forgeos_telemetry.log"
    signals = detect_all_opportunities(
        forgeos_root=forgeos_root,
        backlog_path=backlog_path,
        telemetry_path=telemetry_path,
        top_n=min_new_epics + 3,  # detect a few extra for filtering
    )

    if not signals:
        print("[OPP ENGINE] Phase 2: No signals detected")
        print("[OPP ENGINE] ═══ Opportunity Engine Complete ═══")
        return total_created

    print(f"[OPP ENGINE] Phase 2: Detected {len(signals)} signals:")
    for s in signals[:5]:
        print(f"  [{s['score']:.3f}] {s['title'][:70]}")

    # ── Step 3: Materialize as GitHub Issues + backlog entries ────────────────
    print(f"[OPP ENGINE] Phase 3: Materializing top {min_new_epics} signals as GitHub Issues…")
    top_signals = signals[:min_new_epics]

    new_epics = materialize_signals_as_issues(
        signals=top_signals,
        backlog_path=backlog_path,
        repo=DEFAULT_REPO,
        dry_run=dry_run,
    )

    if new_epics:
        _append_to_backlog(new_epics, backlog_path, dry_run)
        total_created += len(new_epics)
        print(f"[OPP ENGINE] Phase 3: Added {len(new_epics)} new epics to backlog")
    else:
        print("[OPP ENGINE] Phase 3: No new epics generated (all duplicates or errors)")

    print(f"[OPP ENGINE] ═══ Complete — {total_created} total issues created ═══")
    return total_created


def _append_to_backlog(new_epics: list[dict], backlog_path: str, dry_run: bool = False):
    """Appends new epic entries to the backlog JSON file."""
    if dry_run:
        print(f"[OPP ENGINE] [DRY RUN] Would append {len(new_epics)} epics to backlog")
        return

    try:
        if os.path.exists(backlog_path):
            with open(backlog_path) as f:
                backlog = json.load(f)
        else:
            backlog = []

        existing_ids = {ep.get("id") for ep in backlog}
        added = 0
        for ep in new_epics:
            if ep.get("id") not in existing_ids:
                backlog.append(ep)
                existing_ids.add(ep["id"])
                added += 1

        with open(backlog_path, "w") as f:
            json.dump(backlog, f, indent=2)

        print(f"[OPP ENGINE] Backlog updated: +{added} epics (total: {len(backlog)})")
    except Exception as e:
        print(f"[OPP ENGINE ERROR] Failed to update backlog: {e}")


# ── CLI entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ForgeOS Opportunity Engine")
    parser.add_argument("--root",      default=_ROOT,          help="ForgeOS root path")
    parser.add_argument("--backlog",   default=DEFAULT_BACKLOG, help="Backlog JSON path")
    parser.add_argument("--min",       type=int, default=5,    help="Min new epics to generate")
    parser.add_argument("--dry-run",   action="store_true",    help="Don't create real issues")
    args = parser.parse_args()

    n = run_opportunity_engine(
        forgeos_root=args.root,
        backlog_path=args.backlog,
        min_new_epics=args.min,
        dry_run=args.dry_run,
    )
    print(f"\nResult: {n} issues created/updated")
