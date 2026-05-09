"""CLI for the swarm orchestrator.

Examples:

    # 1 cycle on a small fixed list, 30% chaos intensity (default)
    python -m scraper_healing.swarm.cli \\
        --targets instagram:natgeo tiktok:khaby.lame

    # 5 cycles, full chaos, fixed seed for reproducibility
    python -m scraper_healing.swarm.cli \\
        --cycles 5 --intensity 1.0 --seed 42 \\
        --targets instagram:natgeo

    # Read targets from the live DB (top N accounts being tracked)
    python -m scraper_healing.swarm.cli --from-db --limit 20

    # Dump current metrics as JSON (no scraping)
    python -m scraper_healing.swarm.cli --metrics-only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Iterable

from .. import core
from .orchestrator import SwarmOrchestrator
from .scoring import compute_swarm_metrics, load_history


def _parse_targets(items: Iterable[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw in items:
        if ":" not in raw:
            print(f"skip {raw!r} — expected platform:username", file=sys.stderr)
            continue
        platform, username = raw.split(":", 1)
        out.append((platform.strip().lower(), username.strip()))
    return out


def _targets_from_db(limit: int) -> list[tuple[str, str]]:
    """Pull top-N accounts from the live Postgres v1 DB.

    Uses the same DATABASE_URL Vercel/Flask app uses. Falls back to an
    empty list if the env var is missing or the connection fails — no
    hard dependency on Postgres at import time.
    """
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set — cannot pull targets from DB", file=sys.stderr)
        return []
    try:
        import psycopg2  # type: ignore
    except ImportError:
        print("psycopg2 not installed — pip install psycopg2-binary", file=sys.stderr)
        return []
    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT platform, username FROM accounts
                    WHERE username IS NOT NULL AND username != ''
                    ORDER BY last_updated DESC NULLS LAST
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [(p, u) for p, u in cur.fetchall()]
    except Exception as e:
        print(f"db query failed: {e}", file=sys.stderr)
        return []


async def _run(args: argparse.Namespace) -> int:
    if args.from_db:
        targets = _targets_from_db(args.limit)
        if not targets:
            print("no targets from DB — aborting", file=sys.stderr)
            return 2
    else:
        targets = _parse_targets(args.targets or [])
        if not targets:
            print("no targets — pass --targets platform:username or --from-db", file=sys.stderr)
            return 2

    orch = SwarmOrchestrator(intensity=args.intensity, seed=args.seed)
    results = await orch.run(targets, cycles=args.cycles, concurrency=args.concurrency)

    metrics = compute_swarm_metrics()
    print(json.dumps({"results": [
        {"platform": r.platform, "username": r.username, "ok": r.ok,
         "score": r.review_score, "mode": r.adversary_mode,
         "evolved": r.evolution_applied, "ms": r.duration_ms,
         "err": r.err}
        for r in results
    ], "swarm_metrics": metrics}, indent=2, default=str))
    return 0 if all(r.ok or r.err is None for r in results) else 1


def main() -> int:
    p = argparse.ArgumentParser(prog="scraper_healing.swarm")
    p.add_argument("--targets", nargs="+", help="platform:username pairs")
    p.add_argument("--from-db", action="store_true", help="pull targets from accounts table")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--cycles", type=int, default=1)
    p.add_argument("--intensity", type=float, default=0.3, help="chaos intensity 0..1")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--metrics-only", action="store_true", help="print current metrics and exit")
    args = p.parse_args()

    if args.metrics_only:
        m = compute_swarm_metrics()
        print(json.dumps({"metrics": m, "history_n": len(load_history())}, indent=2))
        return 0

    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
