"""Instagram fetch strategies.

Each strategy is async, takes a username, returns a raw dict (or raises).
The healing layer ranks them by reliability score and tries them in order.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import aiohttp

from . import core

_PROXY_BASE = "https://vpirlefqxnvmxbmndhmn.supabase.co/functions/v1"
_PROXY_SECRET = os.environ.get("SCRAPER_PROXY_SECRET", "tracking-lab-2026")
_TIMEOUT = aiohttp.ClientTimeout(total=20)


async def ig_web_profile_info(username: str, session: aiohttp.ClientSession) -> dict:
    """Preferred path: Supabase Edge Function v4 uses web_profile_info internally."""
    url = f"{_PROXY_BASE}/instagram-proxy"
    async with session.get(url, params={"username": username, "secret": _PROXY_SECRET}, timeout=_TIMEOUT) as r:
        if r.status == 404:
            raise RuntimeError(f"user_not_found:{username}")
        if r.status >= 500:
            raise RuntimeError(f"proxy_5xx:{r.status}")
        data = await r.json()
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(f"proxy_error:{data['error']}")
        return data


async def ig_users_pk_info(username: str, session: aiohttp.ClientSession) -> dict:
    """Fallback: hit IG private API directly. Often shadow-blocked → returns nulls.

    Kept here so the healing layer can score it as unreliable and drop priority,
    rather than removing it entirely (it occasionally works for some accounts).
    """
    sess_id = os.environ.get("INSTAGRAM_SESSION_ID")
    if not sess_id:
        raise RuntimeError("no_session_id")
    headers = {
        "User-Agent": "Instagram 275.0.0.27.98 Android (33/13; 420dpi; 1080x2400; samsung; SM-G991B; o1s; exynos2100)",
        "X-IG-App-ID": "936619743392459",
        "Cookie": f"sessionid={sess_id}",
    }
    # First resolve pk via web_profile_info
    async with session.get(
        "https://i.instagram.com/api/v1/users/web_profile_info/",
        params={"username": username},
        headers=headers,
        timeout=_TIMEOUT,
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"pk_resolve_status_{r.status}")
        wpi = await r.json()
        pk = wpi.get("data", {}).get("user", {}).get("id")
        if not pk:
            raise RuntimeError("no_pk")
    async with session.get(
        f"https://i.instagram.com/api/v1/users/{pk}/info/", headers=headers, timeout=_TIMEOUT
    ) as r:
        data = await r.json()
        return data


async def ig_search_then_info(username: str, session: aiohttp.ClientSession) -> dict:
    """Last resort. Often blocked; included for completeness."""
    sess_id = os.environ.get("INSTAGRAM_SESSION_ID")
    if not sess_id:
        raise RuntimeError("no_session_id")
    headers = {
        "User-Agent": "Instagram 275.0.0.27.98 Android (33/13)",
        "X-IG-App-ID": "936619743392459",
        "Cookie": f"sessionid={sess_id}",
    }
    async with session.get(
        "https://i.instagram.com/api/v1/users/search/",
        params={"q": username},
        headers=headers,
        timeout=_TIMEOUT,
    ) as r:
        if r.status != 200:
            raise RuntimeError(f"search_status_{r.status}")
        data = await r.json()
        users = data.get("users") or []
        match = next((u for u in users if u.get("username", "").lower() == username.lower()), None)
        if not match:
            raise RuntimeError("not_in_search")
        pk = match.get("pk")
        if not pk:
            raise RuntimeError("no_pk")
    async with session.get(
        f"https://i.instagram.com/api/v1/users/{pk}/info/", headers=headers, timeout=_TIMEOUT
    ) as r:
        data = await r.json()
        return data
