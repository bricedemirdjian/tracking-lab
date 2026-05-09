"""LinkedIn fetch via Supabase Edge Function proxy."""
from __future__ import annotations

import os

import aiohttp

_PROXY_BASE = "https://vpirlefqxnvmxbmndhmn.supabase.co/functions/v1"
_PROXY_SECRET = os.environ.get("SCRAPER_PROXY_SECRET", "tracking-lab-2026")
_TIMEOUT = aiohttp.ClientTimeout(total=20)


async def li_proxy_default(username: str, session: aiohttp.ClientSession) -> dict:
    url = f"{_PROXY_BASE}/linkedin-proxy"
    async with session.get(url, params={"username": username, "secret": _PROXY_SECRET}, timeout=_TIMEOUT) as r:
        if r.status == 404:
            raise RuntimeError(f"user_not_found:{username}")
        if r.status >= 500:
            raise RuntimeError(f"proxy_5xx:{r.status}")
        data = await r.json()
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(f"proxy_error:{data['error']}")
        return data
