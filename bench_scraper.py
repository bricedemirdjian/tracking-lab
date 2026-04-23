#!/usr/bin/env python3
"""
bench_scraper.py — measure scraper throughput before/after the async refactor.

Usage:
  # Against the new async engine (default):
  python3 bench_scraper.py

  # Against a list of TikTok handles (positional args):
  python3 bench_scraper.py chiara_tiktok1 chiara_tiktok2 mrbeast

  # Mixed-platform test:
  python3 bench_scraper.py --platform tiktok:mrbeast --platform youtube:mkbhd \\
                           --platform instagram:natgeo

  # DB-backed test (uses actual accounts of user_id=1):
  python3 bench_scraper.py --from-db --user-id 1

The benchmark skips writing to the database (dry-run). It measures raw fetch
latency per account + total wall-clock for the whole batch.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time


# --- Default test fixture: 5 handles across 4 platforms ------------------
DEFAULT_TARGETS = [
    {"platform": "tiktok",    "username": "mrbeast"},
    {"platform": "tiktok",    "username": "khaby.lame"},
    {"platform": "youtube",   "username": "MrBeast"},
    {"platform": "youtube",   "username": "mkbhd"},
    {"platform": "instagram", "username": "natgeo"},
]


def _parse_platform_arg(val: str) -> dict:
    """Parse --platform tiktok:mrbeast into a dict."""
    if ":" not in val:
        raise argparse.ArgumentTypeError(
            f"Expected format 'platform:username', got '{val}'"
        )
    platform, username = val.split(":", 1)
    platform = platform.strip().lower()
    username = username.strip().lstrip("@")
    valid = {"tiktok", "youtube", "instagram", "linkedin"}
    if platform not in valid:
        raise argparse.ArgumentTypeError(
            f"Unknown platform '{platform}'. Valid: {sorted(valid)}"
        )
    return {"platform": platform, "username": username}


async def _bench_once(targets: list[dict]) -> tuple[float, list[dict]]:
    """Run one benchmark pass — returns (wall_seconds, per_target_results)."""
    from scraper_async import (
        fetch_instagram_async,
        fetch_linkedin_async,
        fetch_tiktok_async,
        fetch_youtube_async,
        close_session,
    )

    async def _one(t: dict) -> dict:
        start = time.perf_counter()
        platform = t["platform"]
        username = t["username"]
        try:
            if platform == "tiktok":
                data = await fetch_tiktok_async(username)
            elif platform == "youtube":
                data = await fetch_youtube_async(username)
            elif platform == "instagram":
                data = await fetch_instagram_async(username)
            elif platform == "linkedin":
                data = await fetch_linkedin_async(username)
            else:
                data = None
        except Exception as e:
            return {
                **t,
                "ok": False,
                "error": str(e)[:200],
                "elapsed": time.perf_counter() - start,
                "items": 0,
            }
        elapsed = time.perf_counter() - start
        if platform in ("tiktok", "youtube"):
            items = len(data) if data else 0
        elif platform == "instagram":
            items = len(data.get("videos", [])) if data else 0
        elif platform == "linkedin":
            items = len(data.get("posts", [])) if data else 0
        else:
            items = 0
        return {
            **t,
            "ok": bool(data),
            "elapsed": elapsed,
            "items": items,
        }

    t0 = time.perf_counter()
    try:
        results = await asyncio.gather(*(_one(t) for t in targets))
    finally:
        await close_session()
    wall = time.perf_counter() - t0
    return wall, results


def _print_report(wall: float, results: list[dict]) -> None:
    ok = sum(1 for r in results if r["ok"])
    total = len(results)
    items = sum(r.get("items", 0) for r in results)
    per = [r["elapsed"] for r in results]

    print("\n" + "=" * 68)
    print("BENCHMARK REPORT")
    print("=" * 68)
    print(f"Accounts tested   : {total}")
    print(f"Successful        : {ok}/{total}")
    print(f"Items fetched     : {items}")
    print(f"Wall clock total  : {wall:.2f}s")
    print(
        f"Per-account       : min={min(per):.2f}s  max={max(per):.2f}s  "
        f"avg={sum(per) / len(per):.2f}s"
    )
    # Effective concurrency speedup vs serial
    serial = sum(per)
    if wall > 0:
        speedup = serial / wall
        print(f"Serial would take : {serial:.2f}s  →  effective speedup ×{speedup:.1f}")
    print("-" * 68)
    for r in results:
        status = "OK " if r["ok"] else "FAIL"
        err = f" [{r['error']}]" if r.get("error") else ""
        print(
            f"  {status}  {r['platform']:<10} @{r['username']:<25} "
            f"{r['elapsed']:>6.2f}s  items={r['items']}{err}"
        )
    print("=" * 68)


def _targets_from_db(user_id: int) -> list[dict]:
    """Pull actual account list from the database for an end-to-end test."""
    from database import get_all_accounts
    rows = get_all_accounts(user_id=user_id)
    return [
        {"platform": r.get("platform", "tiktok"), "username": r["username"]}
        for r in rows
    ]


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark the async scraper module",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--platform", "-p",
        action="append",
        type=_parse_platform_arg,
        default=[],
        help="Add a target. Format: platform:username (repeatable)",
    )
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Pull target list from the database (requires --user-id)",
    )
    parser.add_argument(
        "--user-id", type=int, default=None,
        help="Use this user_id when --from-db is set",
    )
    parser.add_argument(
        "positional",
        nargs="*",
        help="TikTok handles (shorthand — same as --platform tiktok:<handle>)",
    )
    args = parser.parse_args()

    # Determine targets
    if args.from_db:
        if args.user_id is None:
            print("ERROR: --from-db requires --user-id", file=sys.stderr)
            sys.exit(2)
        targets = _targets_from_db(args.user_id)
        if not targets:
            print(f"No accounts found for user_id={args.user_id}", file=sys.stderr)
            sys.exit(1)
    elif args.platform or args.positional:
        targets = list(args.platform)
        for p in args.positional:
            targets.append({"platform": "tiktok", "username": p.lstrip("@")})
    else:
        targets = DEFAULT_TARGETS

    print(f"Benchmarking {len(targets)} accounts...")
    print(f"  MAX_CONCURRENCY = {os.environ.get('SCRAPER_MAX_CONCURRENCY', '20')}")
    print(f"  CACHE_TTL       = {os.environ.get('SCRAPER_CACHE_TTL', '300')}s")
    print("")

    wall, results = asyncio.run(_bench_once(targets))
    _print_report(wall, results)


if __name__ == "__main__":
    main()
