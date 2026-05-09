"""TikTok fetch strategies. Wraps yt-dlp with multiple host strategies.

yt-dlp is flaky against TikTok — some hostnames work some weeks, fail others.
The healing layer scores each so the live winner gets priority.
"""
from __future__ import annotations

import asyncio
from typing import Any

# yt-dlp is heavy and bundled in the main app — import lazily so this module
# can be imported in environments without it (tests, lint).


async def _run_ytdlp(url: str, opts: dict) -> Any:
    from yt_dlp import YoutubeDL

    def _sync():
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    return await asyncio.to_thread(_sync)


_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": "in_playlist",
    "ignore_no_formats_error": True,
    "socket_timeout": 30,
}


async def tt_ytdlp_default(username: str, session=None) -> dict:
    """Standard yt-dlp scrape via tiktok.com."""
    url = f"https://www.tiktok.com/@{username}"
    info = await _run_ytdlp(url, _BASE_OPTS)
    entries = info.get("entries") or []
    if not entries:
        raise RuntimeError("no_entries")
    return {
        "username": username,
        "entries": entries,
        "_first": entries[0],
        "channel_follower_count": info.get("channel_follower_count")
        or entries[0].get("channel_follower_count"),
    }


async def tt_ytdlp_alt_host(username: str, session=None) -> dict:
    """Alt host hint via Cookie / extractor args. Sometimes wins when default fails."""
    url = f"https://www.tiktok.com/@{username}"
    opts = {
        **_BASE_OPTS,
        "extractor_args": {"tiktok": {"api_hostname": ["api16-normal-c-useast1a.tiktokv.com"]}},
    }
    info = await _run_ytdlp(url, opts)
    entries = info.get("entries") or []
    if not entries:
        raise RuntimeError("no_entries")
    return {
        "username": username,
        "entries": entries,
        "_first": entries[0],
        "channel_follower_count": info.get("channel_follower_count")
        or entries[0].get("channel_follower_count"),
    }
