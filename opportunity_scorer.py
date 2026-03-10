"""
opportunity_scorer.py
=====================
Scores OpportunitySignals using a composite formula:
  score = frequency_norm * 0.40 + severity * 0.40 + source_weight * 0.20
"""
from __future__ import annotations
import math


# Max frequency for normalization (anything above this gets 1.0)
MAX_FREQUENCY = 20


def score_signal(signal: dict) -> float:
    """
    Returns composite score [0.0 - 1.0] for an opportunity signal.
    Higher = more important to fix.
    """
    frequency   = signal.get("frequency", 1)
    severity    = signal.get("severity", 0.5)
    source      = signal.get("source", "unknown")

    # Normalize frequency logarithmically — frequent failures matter more but with diminishing returns
    freq_norm = min(math.log1p(frequency) / math.log1p(MAX_FREQUENCY), 1.0)

    # Source weight — failure_db signals are most actionable
    source_weights = {
        "failure_db": 1.0,
        "telemetry":  0.75,
        "backlog":    0.85,
    }
    source_w = source_weights.get(source, 0.5)

    score = freq_norm * 0.40 + severity * 0.40 + source_w * 0.20
    return round(min(score, 1.0), 4)


def rank_signals(signals: list[dict]) -> list[dict]:
    """Sort signals by score descending, mutating each with its score."""
    for s in signals:
        if "score" not in s:
            s["score"] = score_signal(s)
    return sorted(signals, key=lambda x: -x["score"])
