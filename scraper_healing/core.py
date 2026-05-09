"""Core infrastructure: scoring, response memory, validation, structured logging.

All persistent state lives in scraper_healing/data/. Safe to commit
endpoint-stats.json — it's the auto-training memory carried across runs.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

# ── Paths ────────────────────────────────────────────────────────────
_DATA = Path(__file__).parent / "data"
_DATA.mkdir(parents=True, exist_ok=True)
_STATS_FILE = _DATA / "endpoint-stats.json"
_SNAPSHOT_DIR = _DATA / "snapshots"
_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

# ── Logger (structured JSONL) ────────────────────────────────────────
_LOG_DIR = _DATA / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / f"healing-{time.strftime('%Y-%m-%d')}.jsonl"


def log(level: str, msg: str, **ctx) -> None:
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": level,
        "msg": msg,
        **ctx,
    }
    line = json.dumps(record, default=str)
    print(line, flush=True)
    try:
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def info(msg: str, **ctx): log("info", msg, **ctx)
def warn(msg: str, **ctx): log("warn", msg, **ctx)
def error(msg: str, **ctx): log("error", msg, **ctx)


# ── Endpoint reliability store (auto-training) ───────────────────────
def _load_stats() -> dict:
    if not _STATS_FILE.exists():
        return {"version": 1, "endpoints": {}, "learned_paths": {}}
    try:
        return json.loads(_STATS_FILE.read_text())
    except Exception:
        return {"version": 1, "endpoints": {}, "learned_paths": {}}


def _save_stats(state: dict) -> None:
    tmp = _STATS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(_STATS_FILE)


def _ensure(state: dict, platform: str, endpoint: str) -> dict:
    state["endpoints"].setdefault(platform, {})
    state["endpoints"][platform].setdefault(
        endpoint,
        {"success": 0, "fail": 0, "last_success": None, "last_fail": None, "p95_ms": None},
    )
    return state["endpoints"][platform][endpoint]


def record_success(platform: str, endpoint: str, latency_ms: int = 0) -> None:
    state = _load_stats()
    s = _ensure(state, platform, endpoint)
    s["success"] += 1
    s["last_success"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if latency_ms > 0:
        s["p95_ms"] = latency_ms if not s["p95_ms"] else int(0.95 * s["p95_ms"] + 0.05 * latency_ms)
    _save_stats(state)


def record_failure(platform: str, endpoint: str, reason: str = "") -> None:
    state = _load_stats()
    s = _ensure(state, platform, endpoint)
    s["fail"] += 1
    s["last_fail"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    s["last_reason"] = reason[:120]
    _save_stats(state)


def score(platform: str, endpoint: str) -> float:
    """Laplace-smoothed reliability: (success+1) / (total+2). Unknown = 0.5."""
    state = _load_stats()
    s = state["endpoints"].get(platform, {}).get(endpoint)
    if not s:
        return 0.5
    total = s["success"] + s["fail"]
    return (s["success"] + 1) / (total + 2)


def rank_endpoints(platform: str, endpoints: Iterable[str]) -> list[str]:
    seen, ranked = set(), []
    for e in endpoints:
        if e in seen:
            continue
        seen.add(e)
        ranked.append((e, score(platform, e)))
    ranked.sort(key=lambda x: x[1], reverse=True)
    return [e for e, _ in ranked]


def remember_path(platform: str, field_name: str, json_path: str) -> None:
    """When recovery finds a working path, promote it for next runs."""
    state = _load_stats()
    state["learned_paths"].setdefault(platform, {})
    state["learned_paths"][platform][field_name] = json_path
    _save_stats(state)


def learned_path(platform: str, field_name: str) -> Optional[str]:
    state = _load_stats()
    return state["learned_paths"].get(platform, {}).get(field_name)


# ── Response memory (snapshot + diff) ────────────────────────────────
_SNAPSHOT_KEEP = 10  # per (platform, username)


def snapshot(platform: str, username: str, response: Any) -> None:
    safe = re.sub(r"[^\w.-]", "_", username)
    fp = _SNAPSHOT_DIR / f"{platform}_{safe}_{int(time.time())}.json"
    try:
        fp.write_text(json.dumps(response, indent=2, default=str))
    except Exception as e:
        warn("snapshot_write_failed", platform=platform, username=username, err=str(e))
        return
    # Rotate
    siblings = sorted(
        _SNAPSHOT_DIR.glob(f"{platform}_{safe}_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in siblings[_SNAPSHOT_KEEP:]:
        try:
            old.unlink()
        except Exception:
            pass


def latest_snapshot(platform: str, username: str) -> Optional[Any]:
    safe = re.sub(r"[^\w.-]", "_", username)
    siblings = sorted(
        _SNAPSHOT_DIR.glob(f"{platform}_{safe}_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if len(siblings) < 2:
        return None  # 0 means empty, 1 is the one we just wrote
    try:
        return json.loads(siblings[1].read_text())
    except Exception:
        return None


def shape_diff(prev: Any, current: Any) -> dict:
    """Compare top-level key set + numeric magnitudes between two JSON responses."""
    if prev is None or current is None:
        return {"changed": True, "reason": "no_baseline"}

    def keys(obj, prefix="", out=None):
        out = out if out is not None else set()
        if isinstance(obj, dict):
            for k, v in obj.items():
                out.add(prefix + k)
                if isinstance(v, (dict, list)) and len(prefix) < 32:
                    keys(v, prefix + k + ".", out)
        elif isinstance(obj, list) and obj:
            keys(obj[0], prefix + "[0].", out)
        return out

    prev_keys, cur_keys = keys(prev), keys(current)
    added = cur_keys - prev_keys
    removed = prev_keys - cur_keys
    changed = bool(added or removed)
    return {
        "changed": changed,
        "added": sorted(added)[:10],
        "removed": sorted(removed)[:10],
    }


# ── Self-healing extraction core ─────────────────────────────────────
@dataclass
class FieldSpec:
    """How to pull one field out of a JSON response."""

    path: str  # dotted path, e.g. "data.user.edge_followed_by.count"
    fallbacks: list[str] = field(default_factory=list)
    type: str = "number"  # number | percent | string | url | iso_date
    required: bool = True
    label: str = ""  # human-readable, used by recovery
    aliases: list[str] = field(default_factory=list)  # words a recovery walker can look for


def get_path(obj: Any, path: str) -> Any:
    """Resolve a dotted path. Supports `.[0].` array indices.

    Hardened against payload shape drift — when an upstream provider
    starts returning a dict where we expected a list (or vice versa),
    fail soft to None so the recovery walker downstream gets a chance
    instead of bubbling the exception. We catch:
      - IndexError: list index out of range
      - TypeError:  e.g. trying to subscript a string with int in unexpected ways
      - KeyError:   the value is a dict, and we tried to index it with a number
    """
    if obj is None:
        return None
    cur = obj
    for part in re.split(r"\.|\[(\d+)\]", path):
        if part is None or part == "":
            continue
        if part.isdigit():
            try:
                cur = cur[int(part)]
            except (IndexError, TypeError, KeyError):
                return None
        else:
            if isinstance(cur, dict):
                cur = cur.get(part)
            elif isinstance(cur, list):
                # Provider returned a list where we expected a dict — try the
                # first element so the rest of the path still has a shot.
                if cur and isinstance(cur[0], dict):
                    cur = cur[0].get(part)
                else:
                    return None
            else:
                return None
        if cur is None:
            return None
    return cur


# ── Validation ───────────────────────────────────────────────────────
_VALIDATORS: dict[str, Callable[[Any], bool]] = {
    "number": lambda v: isinstance(v, (int, float)) and v >= 0 and not (isinstance(v, float) and v != v),
    "signed_number": lambda v: isinstance(v, (int, float)) and not (isinstance(v, float) and v != v),
    "percent": lambda v: isinstance(v, (int, float)) and 0 <= v <= 100,
    "string": lambda v: isinstance(v, str) and bool(v.strip()),
    "url": lambda v: isinstance(v, str) and v.startswith(("http://", "https://")),
    "iso_date": lambda v: isinstance(v, str) and bool(re.match(r"\d{4}-\d{2}-\d{2}", v)),
}


def is_valid(type_: str, value: Any) -> bool:
    fn = _VALIDATORS.get(type_)
    return fn(value) if fn else value is not None


def validate_payload(payload: dict, schema: dict[str, FieldSpec]) -> dict:
    errors = []
    for name, spec in schema.items():
        v = payload.get(name)
        # Empty string and None are treated identically — they mean "absent".
        is_empty = v is None or (isinstance(v, str) and v.strip() == "")
        if spec.required and is_empty:
            errors.append({"field": name, "error": "missing"})
            continue
        if not is_empty and not is_valid(spec.type, v):
            errors.append({"field": name, "error": "invalid", "value": v, "expected": spec.type})
    return {"ok": not errors, "errors": errors}
