"""YouTube fetch strategies. Two passes: list + per-video detail.

The flat pass is fast but misses likes/comments/upload_date. The detail pass
fills those in but is much slower (one HTTP per video). We bound parallelism
to avoid rate-limiting.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

_DETAIL_CONCURRENCY = int(os.environ.get("HEALING_YT_DETAIL_CONCURRENCY", "8"))
_DETAIL_LIMIT = int(os.environ.get("HEALING_YT_DETAIL_LIMIT", "30"))


async def _run_ytdlp(url: str, opts: dict) -> Any:
    from yt_dlp import YoutubeDL

    def _sync():
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)

    return await asyncio.to_thread(_sync)


async def yt_ytdlp_flat(username: str, session=None) -> dict:
    """Pass 1 — fast listing, no per-video detail."""
    handle = username.lstrip("@")
    url = f"https://www.youtube.com/@{handle}/videos"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "ignore_no_formats_error": True,
        "socket_timeout": 30,
    }
    info = await _run_ytdlp(url, opts)
    entries = info.get("entries") or []
    if not entries:
        raise RuntimeError("no_entries")
    return {
        "username": username,
        "channel_follower_count": info.get("channel_follower_count"),
        "entries": entries,
        "_first": entries[0] if entries else None,
    }


async def yt_ytdlp_video_detail(username: str, session=None) -> dict:
    """Pass 1 + bounded-parallel pass 2 for likes/comments/upload_date."""
    listing = await yt_ytdlp_flat(username)
    sem = asyncio.Semaphore(_DETAIL_CONCURRENCY)
    entries = listing["entries"][:_DETAIL_LIMIT]

    async def detail(entry: dict) -> dict | None:
        async with sem:
            try:
                opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "ignore_no_formats_error": True,
                    "socket_timeout": 30,
                }
                vid_url = entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id')}"
                info = await _run_ytdlp(vid_url, opts)
                return {
                    "id": entry.get("id"),
                    "title": info.get("title"),
                    "view_count": info.get("view_count"),
                    "like_count": info.get("like_count"),
                    "comment_count": info.get("comment_count"),
                    "timestamp": info.get("timestamp"),
                    "upload_date": info.get("upload_date"),  # YYYYMMDD fallback
                    "duration": info.get("duration"),
                }
            except Exception:
                return None

    enriched = await asyncio.gather(*(detail(e) for e in entries))
    enriched = [e for e in enriched if e]
    return {
        **listing,
        "entries": enriched,
        "enriched_count": len(enriched),
    }
