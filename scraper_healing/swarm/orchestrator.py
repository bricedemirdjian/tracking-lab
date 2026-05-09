"""Swarm orchestrator — runs the multi-agent loop for N cycles.

Each cycle:

    1. Adversary rolls a chaos mode (or NONE).
    2. Build an aiohttp session and (optionally) wrap it with adversarial
       network behavior.
    3. Run ``healing.scrape(platform, username, session=...)`` — the
       existing self-healing scraper does the heavy lifting (multi-strategy
       fetch, recovery walk, validation, snapshotting, score updates).
    4. Reviewer = the validation report already produced by the healer.
       We compute a 0–100 quality score.
    5. If review.ok is False, ask Evolution to propose mutations and
       sandbox-validate them. Successful mutations are persisted via
       ``core.remember_path``.
    6. Record the cycle outcome (kind: 'cycle') in the swarm history.

The orchestrator is intentionally thin — it does NOT duplicate any
scraping logic. It glues the existing healer to two new agents.

Usage:

    from scraper_healing.swarm import SwarmOrchestrator
    asyncio.run(SwarmOrchestrator(intensity=0.3).run([
        ("instagram", "natgeo"),
        ("tiktok", "khaby.lame"),
    ], cycles=3))
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Iterable

import aiohttp

from .. import core, healing, registry
from .adversary import AdversaryAgent, ChaosMode
from .evolution import EvolutionAgent
from .scoring import record_cycle


@dataclass
class CycleResult:
    cycle_id: str
    platform: str
    username: str
    ok: bool
    review_score: int  # 0–100
    adversary_mode: str
    issues: list[dict] = field(default_factory=list)
    evolution_proposed: int = 0
    evolution_applied: int = 0
    duration_ms: int = 0
    err: str | None = None

    def as_history_record(self) -> dict:
        return {
            "kind": "cycle",
            "cycle_id": self.cycle_id,
            "platform": self.platform,
            "username": self.username,
            "ok": self.ok,
            "review_score": self.review_score,
            "adversary_mode": self.adversary_mode,
            "issues": self.issues,
            "evolution_proposed": self.evolution_proposed,
            "evolution_applied": self.evolution_applied,
            "duration_ms": self.duration_ms,
            "err": self.err,
        }


def _quality_score(validation: dict, schema: dict) -> int:
    """Convert the healer's validation report into a 0–100 score weighted
    by which fields are required.
    """
    n_required = sum(1 for s in schema.values() if s.required)
    if n_required == 0:
        return 100 if validation.get("ok") else 0
    errors = validation.get("errors", [])
    required_errors = sum(1 for e in errors if e.get("field") in schema and schema[e["field"]].required)
    optional_errors = len(errors) - required_errors
    # Required errors weigh 2x optional
    deduction = (required_errors * 2 + optional_errors) / (n_required * 2)
    return max(0, round(100 * (1 - min(1.0, deduction))))


class SwarmOrchestrator:
    def __init__(self, *, intensity: float = 0.3, seed: int | None = None):
        self.adversary = AdversaryAgent(intensity=intensity, seed=seed)
        self.evolution = EvolutionAgent()

    async def run_one(self, platform: str, username: str) -> CycleResult:
        cycle_id = f"c-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        t0 = time.monotonic()
        mode = self.adversary.roll()
        core.info("swarm_cycle_start", cycle_id=cycle_id, platform=platform,
                  username=username, adversary_mode=mode.value)

        result = CycleResult(
            cycle_id=cycle_id, platform=platform, username=username,
            ok=False, review_score=0, adversary_mode=mode.value,
        )

        schema = registry.SCHEMAS.get(platform, {})
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                headers={"User-Agent": "TrackingLab-Swarm/1.0"},
            ) as raw:
                # Wrap session with adversarial behavior (or pass-through)
                wrapped = self.adversary.wrap_session(raw)
                payload = await healing.scrape(platform, username, session=wrapped)  # type: ignore[arg-type]

            # Apply payload-level chaos AFTER healing — used to test the
            # reviewer + evolution loop on degraded inputs.
            data = payload.get("data") or {}
            data = self.adversary.mutate(data)
            validation = core.validate_payload(data, schema) if schema else {"ok": True, "errors": []}

            result.review_score = _quality_score(validation, schema)
            result.issues = validation.get("errors", [])
            result.ok = bool(validation.get("ok"))

            # Step into Evolution if review wasn't clean
            if not result.ok and schema:
                proposals = self.evolution.analyze(
                    cycle_id=cycle_id, platform=platform,
                    response=payload.get("raw_response") or data,
                    schema=schema, validation=validation,
                    failed_endpoints=payload.get("failed_endpoints", []),
                )
                result.evolution_proposed = len(proposals)
                if proposals:
                    applied = self.evolution.apply(
                        proposals,
                        response=payload.get("raw_response") or data,
                        schema=schema,
                    )
                    result.evolution_applied = applied

        except Exception as e:
            result.err = f"{type(e).__name__}: {str(e)[:160]}"
            core.error("swarm_cycle_error", cycle_id=cycle_id, err=result.err)
        finally:
            result.duration_ms = int((time.monotonic() - t0) * 1000)
            record_cycle(result.as_history_record())
            core.info("swarm_cycle_end", cycle_id=cycle_id, ok=result.ok,
                      review_score=result.review_score,
                      duration_ms=result.duration_ms,
                      evolution_applied=result.evolution_applied)
        return result

    async def run(
        self,
        targets: Iterable[tuple[str, str]],
        *,
        cycles: int = 1,
        concurrency: int = 4,
        cooldown_ms: int = 250,
    ) -> list[CycleResult]:
        """Run ``cycles`` passes over ``targets`` with bounded concurrency.

        Each (platform, username) pair gets ``cycles`` independent runs.
        Slight cooldown between targets keeps us polite — the per-platform
        rate-limiting in ``healing.py`` is the primary throttle.
        """
        targets = list(targets)
        all_results: list[CycleResult] = []
        sem = asyncio.Semaphore(concurrency)

        async def _bounded_one(p: str, u: str) -> CycleResult:
            async with sem:
                r = await self.run_one(p, u)
                if cooldown_ms:
                    await asyncio.sleep(cooldown_ms / 1000)
                return r

        for cycle_idx in range(cycles):
            core.info("swarm_pass_start", pass_idx=cycle_idx + 1, total=cycles, n_targets=len(targets))
            results = await asyncio.gather(*[_bounded_one(p, u) for p, u in targets], return_exceptions=False)
            all_results.extend(results)
        return all_results
