"""Multi-agent swarm — chaos engineering + LLM-style evolution layer.

Wraps the existing ``scraper_healing`` self-healing scraper with three
additional agents:

* ``adversary`` — injects failures (latency, 4xx/5xx, malformed payloads,
  shape drift) so we can prove the healer recovers without bypassing any
  real anti-bot mechanism.
* ``evolution`` — when the healer fails or the reviewer flags issues,
  proposes new field paths / aliases and persists winners via
  ``core.remember_path``. Optional LLM mode if ``EVOLUTION_USE_LLM=1`` and
  ``ANTHROPIC_API_KEY`` is present; falls back to deterministic heuristics.
* ``orchestrator`` — runs N cycles in a loop:
  ``scrape → review → maybe adversary → maybe evolve → score``.

State lives under ``scraper_healing/swarm/data/`` (gitignored where
appropriate). The reliability stats reused are the existing
``scraper_healing/data/endpoint-stats.json`` — no duplication.

CLI:

    python -m scraper_healing.swarm.cli --cycles 10 --intensity 0.5
"""
from __future__ import annotations

from .adversary import AdversaryAgent, ChaosMode
from .evolution import EvolutionAgent
from .orchestrator import SwarmOrchestrator
from .scoring import compute_swarm_metrics, record_cycle

__all__ = [
    "AdversaryAgent",
    "ChaosMode",
    "EvolutionAgent",
    "SwarmOrchestrator",
    "compute_swarm_metrics",
    "record_cycle",
]
