"""Self-healing orchestrator. The single entry point: `scrape(platform, username)`.

Lifecycle of one scrape:

    1. Pick fetch strategies (registry.STRATEGIES) ranked by reliability score.
    2. Try each in order with timeout + retry. First non-empty response wins.
    3. Snapshot the raw response (rotated, last 10 per (platform, username)).
    4. Diff vs previous snapshot — log alerts on shape change.
    5. Extract every field per registry.SCHEMAS using FieldSpec paths.
    6. For each missing/invalid field, run AI-like recovery (alias walk).
    7. Validate the output payload — partial success is recorded, returns
       both data and validation report.
    8. Update endpoint scores (success/failure) — auto-training over time.

This module deliberately doesn't replace your existing scraper_async.py — it
wraps it. Migration plan: change call sites one at a time.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

import aiohttp

from . import core, recovery, registry
from . import instagram as ig
from . import tiktok as tt
from . import youtube as yt
from . import linkedin as li

# Strategy implementations (must match names in registry.STRATEGIES).
STRATEGIES: dict[str, dict[str, Callable[..., Awaitable[Any]]]] = {
    "instagram": {
        "ig_web_profile_info": ig.ig_web_profile_info,
        "ig_users_pk_info": ig.ig_users_pk_info,
        "ig_search_then_info": ig.ig_search_then_info,
    },
    "tiktok": {
        "tt_ytdlp_default": tt.tt_ytdlp_default,
        "tt_ytdlp_alt_host": tt.tt_ytdlp_alt_host,
    },
    "youtube": {
        "yt_ytdlp_flat": yt.yt_ytdlp_flat,
        "yt_ytdlp_video_detail": yt.yt_ytdlp_video_detail,
    },
    "linkedin": {
        "li_proxy_default": li.li_proxy_default,
    },
}


async def _try_strategies(platform: str, username: str, session: aiohttp.ClientSession) -> dict | None:
    """Walk strategies ranked by score. Return first response or None if all fail."""
    available = registry.STRATEGIES.get(platform, [])
    ranked = core.rank_endpoints(platform, available)
    for endpoint in ranked:
        fn = STRATEGIES.get(platform, {}).get(endpoint)
        if not fn:
            continue
        t0 = time.monotonic()
        try:
            response = await fn(username, session)
            latency_ms = int((time.monotonic() - t0) * 1000)
            core.record_success(platform, endpoint, latency_ms)
            core.info("strategy_ok", platform=platform, endpoint=endpoint, username=username, ms=latency_ms)
            return {"_endpoint": endpoint, "_latency_ms": latency_ms, "response": response}
        except Exception as e:
            reason = str(e)[:200]
            core.record_failure(platform, endpoint, reason)
            core.warn("strategy_fail", platform=platform, endpoint=endpoint, username=username, err=reason)
    return None


def _extract_with_recovery(platform: str, response: Any, schema: dict[str, core.FieldSpec]) -> tuple[dict, dict]:
    """Resolve every field in schema from response. Returns (payload, meta)."""
    payload: dict[str, Any] = {}
    meta: dict[str, Any] = {}

    for name, spec in schema.items():
        if name.startswith("__"):
            continue  # computed fields handled by caller
        # 1. Try learned path first (auto-training memory)
        chosen_path = None
        value = None
        learned = core.learned_path(platform, name)
        candidate_paths = ([learned] if learned else []) + [spec.path] + spec.fallbacks
        for path in candidate_paths:
            if not path:
                continue
            v = core.get_path(response, path)
            if v is not None and core.is_valid(spec.type, v):
                value = v
                chosen_path = path
                break

        # 2. Recovery: walk response looking for aliased keys
        if value is None and spec.aliases:
            recovered = recovery.recover(platform, name, response, spec)
            if recovered is not None and core.is_valid(spec.type, recovered):
                value = recovered
                chosen_path = "recovered"

        payload[name] = value
        meta[name] = {"path": chosen_path, "type": spec.type, "required": spec.required}

    return payload, meta


def _augment_computed(platform: str, payload: dict, response: Any) -> dict:
    """Compute aggregate fields the schema marks with __name__ (videos_count, posts_count)."""
    if platform in ("tiktok", "youtube"):
        entries = response.get("entries") if isinstance(response, dict) else None
        payload["videos_count"] = len(entries) if isinstance(entries, list) else 0
    elif platform == "linkedin":
        posts = response.get("posts") if isinstance(response, dict) else None
        payload["posts_count"] = len(posts) if isinstance(posts, list) else 0
    return payload


async def scrape(platform: str, username: str, *, session: aiohttp.ClientSession | None = None) -> dict:
    """Public entry point. Always returns a dict — `validation.ok` tells you whether it's safe."""
    if platform not in registry.STRATEGIES:
        raise ValueError(f"unknown platform: {platform}")
    schema = registry.SCHEMAS[platform]

    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()

    started_at = time.monotonic()
    try:
        attempt = await _try_strategies(platform, username, session)
        if not attempt:
            return {
                "platform": platform,
                "username": username,
                "data": None,
                "validation": {"ok": False, "errors": [{"error": "all_strategies_failed"}]},
                "duration_ms": int((time.monotonic() - started_at) * 1000),
            }

        response = attempt["response"]
        endpoint = attempt["_endpoint"]

        # Snapshot + drift detection
        prev = core.latest_snapshot(platform, username)
        core.snapshot(platform, username, response)
        diff = core.shape_diff(prev, response)
        if diff.get("changed") and (diff.get("added") or diff.get("removed")):
            core.warn("response_shape_drift", platform=platform, username=username, **diff)

        # Extract + recover + augment
        payload, meta = _extract_with_recovery(platform, response, schema)
        payload["username"] = username  # always
        payload = _augment_computed(platform, payload, response)

        validation = core.validate_payload(payload, schema)
        if not validation["ok"]:
            core.error("validation_failed", platform=platform, username=username, errors=validation["errors"])

        return {
            "platform": platform,
            "username": username,
            "endpoint_used": endpoint,
            "data": payload,
            "meta": meta,
            "validation": validation,
            "shape_diff": diff,
            "duration_ms": int((time.monotonic() - started_at) * 1000),
        }
    finally:
        if own_session:
            await session.close()


# ── Batch helper ──────────────────────────────────────────────────────
async def scrape_batch(targets: list[tuple[str, str]], concurrency: int = 8) -> list[dict]:
    """Scrape (platform, username) tuples in parallel with a Semaphore."""
    sem = asyncio.Semaphore(concurrency)

    async with aiohttp.ClientSession() as session:
        async def one(p: str, u: str) -> dict:
            async with sem:
                try:
                    return await scrape(p, u, session=session)
                except Exception as e:
                    core.error("scrape_crash", platform=p, username=u, err=str(e)[:200])
                    return {"platform": p, "username": u, "data": None,
                            "validation": {"ok": False, "errors": [{"error": "crash", "msg": str(e)[:120]}]}}

        return await asyncio.gather(*(one(p, u) for p, u in targets))
