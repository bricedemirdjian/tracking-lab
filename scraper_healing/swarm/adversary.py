"""Adversary agent — chaos engine for the Python scraping pipeline.

We never bypass any real anti-bot mechanism. We simulate failure conditions
that *could* occur in the wild (provider 429s, slow networks, JSON shape
drift, partial payloads) so the healer + reviewer + evolution loop can prove
they recover. Each chaos mode is opt-in via the orchestrator's intensity
knob.

Two integration points:

1. ``AdversarialSession`` wraps ``aiohttp.ClientSession`` and intercepts
   responses returned by the per-platform fetch strategies.
2. ``mutate_payload`` runs *after* a successful scrape, optionally
   corrupting fields so the reviewer sees a degraded payload (used to
   stress-test validation + evolution).

All injections are logged with the ``adversary_event`` log key for
post-hoc analysis (see ``scoring.py``).
"""
from __future__ import annotations

import asyncio
import copy
import enum
import random
from typing import Any

import aiohttp

from .. import core


class ChaosMode(str, enum.Enum):
    NONE = "none"
    LATENCY_SPIKE = "latency_spike"          # 1.5–4.5s artificial delay before request
    HTTP_429 = "http_429"                    # synthesize a 429 Too Many Requests
    HTTP_503 = "http_503"                    # synthesize a 503 Service Unavailable
    PARTIAL_PAYLOAD = "partial_payload"      # drop random fields from the response body
    SHAPE_DRIFT = "shape_drift"              # rename keys to mimic provider schema change
    NULL_FIELD = "null_field"                # set a random required field to None
    TRUNCATED_LIST = "truncated_list"        # cut top-level list payloads to 1 item


_ALL_MODES: list[ChaosMode] = [m for m in ChaosMode if m is not ChaosMode.NONE]


def pick_mode(intensity: float, rng: random.Random | None = None) -> ChaosMode:
    """Return a chaos mode given an intensity in [0, 1]. 0 → never, 1 → always."""
    rng = rng or random
    if rng.random() >= max(0.0, min(1.0, intensity)):
        return ChaosMode.NONE
    return rng.choice(_ALL_MODES)


# ── Network-layer chaos ─────────────────────────────────────────────────
class _ChaosResponse:
    """Minimal aiohttp.ClientResponse-compatible object for synthesized HTTP errors.

    We only need the surface that ``healing.py`` and the per-platform fetch
    strategies actually touch: ``status``, ``json()``, ``text()``,
    ``raise_for_status()`` and async context manager support.
    """

    def __init__(self, status: int, body: dict | str | None = None):
        self.status = status
        self._body = body if body is not None else {"error": f"chaos_{status}"}

    async def json(self, content_type: str | None = None) -> Any:
        return self._body if isinstance(self._body, dict) else {"error": str(self._body)}

    async def text(self, encoding: str | None = None) -> str:
        return self._body if isinstance(self._body, str) else core_dumps(self._body)

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                request_info=None,  # type: ignore[arg-type]
                history=(),
                status=self.status,
                message=f"chaos_synthetic_{self.status}",
            )

    async def __aenter__(self) -> "_ChaosResponse":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


def core_dumps(obj: Any) -> str:  # tiny local helper to avoid circular import on json
    import json as _json
    return _json.dumps(obj, default=str)


class AdversarialSession:
    """Drop-in wrapper around ``aiohttp.ClientSession`` with chaos modes.

    Strategies in ``scraper_healing/{platform}.py`` accept a session arg
    and call ``session.get(...)`` / ``session.post(...)``. We intercept
    those calls. Anything we don't override is forwarded to the real
    session.
    """

    def __init__(
        self,
        inner: aiohttp.ClientSession,
        mode: ChaosMode = ChaosMode.NONE,
        rng: random.Random | None = None,
    ):
        self._inner = inner
        self.mode = mode
        self._rng = rng or random.Random()

    def __getattr__(self, name: str) -> Any:
        # Forward anything we don't override (close, closed, etc.)
        return getattr(self._inner, name)

    async def __aenter__(self) -> "AdversarialSession":
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._inner.__aexit__(*exc)

    def _maybe_delay(self) -> float:
        if self.mode is ChaosMode.LATENCY_SPIKE:
            return 1.5 + self._rng.random() * 3.0
        return 0.0

    def _intercept_status(self) -> int | None:
        if self.mode is ChaosMode.HTTP_429:
            return 429
        if self.mode is ChaosMode.HTTP_503:
            return 503
        return None

    async def _maybe_chaos(self) -> _ChaosResponse | None:
        delay = self._maybe_delay()
        if delay:
            core.warn("adversary_event", mode=self.mode.value, delay_ms=int(delay * 1000))
            await asyncio.sleep(delay)
        synth = self._intercept_status()
        if synth:
            core.warn("adversary_event", mode=self.mode.value, status=synth)
            return _ChaosResponse(synth)
        return None

    def get(self, url: str, **kwargs: Any) -> Any:
        return _ChaosWrappedRequest(self, "GET", url, kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        return _ChaosWrappedRequest(self, "POST", url, kwargs)


class _ChaosWrappedRequest:
    """Yields either a synth chaos response or the real one, supports
    both ``async with session.get(...)`` and ``await session.get(...)``."""

    def __init__(self, parent: AdversarialSession, method: str, url: str, kwargs: dict):
        self._parent = parent
        self._method = method
        self._url = url
        self._kwargs = kwargs
        self._real_cm: Any = None

    async def __aenter__(self) -> Any:
        synth = await self._parent._maybe_chaos()
        if synth is not None:
            return synth
        # Real request — delegate
        self._real_cm = self._parent._inner.request(self._method, self._url, **self._kwargs)
        return await self._real_cm.__aenter__()

    async def __aexit__(self, *exc: Any) -> None:
        if self._real_cm is not None:
            await self._real_cm.__aexit__(*exc)


# ── Payload-layer chaos ─────────────────────────────────────────────────
def mutate_payload(payload: dict, mode: ChaosMode, rng: random.Random | None = None) -> dict:
    """Apply payload-level chaos. Returns a (possibly) corrupted copy."""
    rng = rng or random
    if mode is ChaosMode.NONE:
        return payload
    out = copy.deepcopy(payload)

    if mode is ChaosMode.PARTIAL_PAYLOAD and isinstance(out, dict):
        keys = list(out.keys())
        if keys:
            n = max(1, len(keys) // 3)
            for k in rng.sample(keys, k=min(n, len(keys))):
                out.pop(k, None)
            core.warn("adversary_event", mode=mode.value, dropped_n=n)

    elif mode is ChaosMode.NULL_FIELD and isinstance(out, dict):
        keys = [k for k, v in out.items() if v is not None]
        if keys:
            k = rng.choice(keys)
            out[k] = None
            core.warn("adversary_event", mode=mode.value, field=k)

    elif mode is ChaosMode.SHAPE_DRIFT and isinstance(out, dict):
        keys = list(out.keys())
        renamed = {}
        for k in keys:
            new_k = k + "_v2" if rng.random() < 0.4 else k
            renamed[new_k] = out[k]
        out = renamed
        core.warn("adversary_event", mode=mode.value, renamed=len(keys))

    elif mode is ChaosMode.TRUNCATED_LIST and isinstance(out, dict):
        for k, v in list(out.items()):
            if isinstance(v, list) and len(v) > 1:
                out[k] = v[:1]
                core.warn("adversary_event", mode=mode.value, field=k, kept=1)
                break

    return out


class AdversaryAgent:
    """Public façade orchestrators talk to. Holds the current chaos mode
    selection per cycle and provides both network + payload integration
    points.
    """

    def __init__(self, intensity: float = 0.3, seed: int | None = None):
        self.intensity = intensity
        self._rng = random.Random(seed)
        self.last_mode: ChaosMode = ChaosMode.NONE

    def roll(self) -> ChaosMode:
        self.last_mode = pick_mode(self.intensity, self._rng)
        if self.last_mode is not ChaosMode.NONE:
            core.info("adversary_event", picked=self.last_mode.value, intensity=self.intensity)
        return self.last_mode

    def wrap_session(self, session: aiohttp.ClientSession) -> AdversarialSession:
        return AdversarialSession(session, mode=self.last_mode, rng=self._rng)

    def mutate(self, payload: dict) -> dict:
        # Payload-layer chaos applies only for non-network modes
        payload_modes = {
            ChaosMode.PARTIAL_PAYLOAD,
            ChaosMode.NULL_FIELD,
            ChaosMode.SHAPE_DRIFT,
            ChaosMode.TRUNCATED_LIST,
        }
        if self.last_mode in payload_modes:
            return mutate_payload(payload, self.last_mode, self._rng)
        return payload
