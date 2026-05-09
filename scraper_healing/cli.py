"""CLI for ad-hoc healing runs and benchmarks.

  python -m scraper_healing.cli instagram natgeo
  python -m scraper_healing.cli tiktok mrbeast
  python -m scraper_healing.cli batch instagram:natgeo tiktok:mrbeast youtube:mkbhd
"""
from __future__ import annotations

import asyncio
import json
import sys

from . import healing


async def _single(platform: str, username: str) -> int:
    res = await healing.scrape(platform, username)
    print(json.dumps(res, indent=2, default=str))
    return 0 if res.get("validation", {}).get("ok") else 2


async def _batch(args: list[str]) -> int:
    targets = []
    for a in args:
        if ":" not in a:
            print(f"skip malformed: {a}", file=sys.stderr)
            continue
        p, u = a.split(":", 1)
        targets.append((p.strip(), u.strip().lstrip("@")))
    results = await healing.scrape_batch(targets, concurrency=8)
    ok = sum(1 for r in results if r.get("validation", {}).get("ok"))
    print(json.dumps(results, indent=2, default=str))
    print(f"\n{ok}/{len(results)} OK", file=sys.stderr)
    return 0 if ok == len(results) else 2


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 1
    if sys.argv[1] == "batch":
        return asyncio.run(_batch(sys.argv[2:]))
    platform, username = sys.argv[1], sys.argv[2].lstrip("@")
    return asyncio.run(_single(platform, username))


if __name__ == "__main__":
    sys.exit(main())
