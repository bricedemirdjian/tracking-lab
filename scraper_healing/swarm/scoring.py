"""Multi-metric scoring for the swarm. Reads:

* ``scraper_healing/data/endpoint-stats.json`` (existing) — per-platform
  per-endpoint success/fail counters.
* ``scraper_healing/swarm/data/cycle-history.jsonl`` (this module) —
  cycle-level outcomes appended by the orchestrator.

Computes the 5 L7 scores plus exposes the raw history for the dashboard.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .. import core


_DATA = Path(__file__).parent / "data"
_DATA.mkdir(parents=True, exist_ok=True)
_HISTORY = _DATA / "cycle-history.jsonl"
_HISTORY_CAP_LINES = 5000  # rolling cap; old lines get pruned during read


def record_cycle(record: dict) -> None:
    """Append one cycle outcome. Compatible with `jq`/Loki/Datadog ingestion."""
    record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **record}
    try:
        with _HISTORY.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as e:
        core.warn("swarm_history_write_failed", err=str(e))


def load_history(limit: int | None = None) -> list[dict]:
    if not _HISTORY.exists():
        return []
    rows: list[dict] = []
    try:
        with _HISTORY.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception as e:
        core.warn("swarm_history_read_failed", err=str(e))
        return []
    if len(rows) > _HISTORY_CAP_LINES:
        rows = rows[-_HISTORY_CAP_LINES:]
    if limit:
        rows = rows[-limit:]
    return rows


def _avg(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 1) if xs else 0.0


def compute_swarm_metrics(history: list[dict] | None = None) -> dict:
    """Returns the 5 L7 scores plus a few introspection helpers."""
    history = history if history is not None else load_history()
    cycles = [h for h in history if h.get("kind") == "cycle"]

    n = len(cycles)
    success = [h for h in cycles if h.get("ok")]
    failure = [h for h in cycles if not h.get("ok")]

    success_rate = round(100 * len(success) / n, 1) if n else 0.0
    failure_rate = round(100 - success_rate, 1) if n else 0.0

    completeness_scores = [h.get("review_score", 0) for h in cycles if h.get("review_score") is not None]
    data_completeness = _avg(completeness_scores)

    # Selector stability: average reliability of all known endpoints
    stats = json.loads((Path(__file__).parent.parent / "data" / "endpoint-stats.json").read_text()) \
        if (Path(__file__).parent.parent / "data" / "endpoint-stats.json").exists() \
        else {"endpoints": {}}
    endpoint_scores = []
    for platform, endpoints in stats.get("endpoints", {}).items():
        for endpoint, s in endpoints.items():
            total = s.get("success", 0) + s.get("fail", 0)
            if total >= 3:
                endpoint_scores.append(100 * (s.get("success", 0) + 1) / (total + 2))
    selector_stability = _avg(endpoint_scores)

    # Adversarial resilience: cycles where adversary was active AND succeeded
    adversarial = [h for h in cycles if h.get("adversary_mode") and h["adversary_mode"] != "none"]
    adversarial_success = [h for h in adversarial if h.get("ok") and h.get("review_score", 0) >= 70]
    adversarial_resilience = round(100 * len(adversarial_success) / len(adversarial), 1) if adversarial else 100.0

    # Evolution effectiveness: % of cycles where applied proposals existed AND
    # the next cycle on the same target succeeded.
    effective_evolutions = 0
    seen_evolutions = 0
    by_target: dict[tuple[str, str], list[dict]] = {}
    for h in cycles:
        key = (h.get("platform"), h.get("username"))
        by_target.setdefault(key, []).append(h)
    for runs in by_target.values():
        for prev, cur in zip(runs, runs[1:]):
            if (prev.get("evolution_applied") or 0) > 0:
                seen_evolutions += 1
                if cur.get("ok") and cur.get("review_score", 0) > prev.get("review_score", 0):
                    effective_evolutions += 1
    evolution_effectiveness = round(100 * effective_evolutions / seen_evolutions, 1) if seen_evolutions else 0.0

    return {
        "success_rate": success_rate,
        "failure_rate": failure_rate,
        "data_completeness_score": data_completeness,
        "selector_stability_score": round(selector_stability, 1),
        "adversarial_resilience_score": adversarial_resilience,
        "evolution_effectiveness_score": evolution_effectiveness,
        "n_cycles": n,
        "n_success": len(success),
        "n_failure": len(failure),
        "n_adversarial_cycles": len(adversarial),
    }


def metric_summary_for_dashboard(history_limit: int = 200) -> dict[str, Any]:
    """Convenience for the Flask dashboard panel."""
    history = load_history(limit=history_limit)
    metrics = compute_swarm_metrics(history)
    return {
        "metrics": metrics,
        "recent_cycles": history[-30:],
    }
