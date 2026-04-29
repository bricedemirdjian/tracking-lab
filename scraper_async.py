"""
Async scraper module — rewrite of the sync scraper using asyncio.

Goals (vs previous sync version):
  - 10-20× multi-account concurrency via asyncio.Semaphore (was: ThreadPool(6))
  - aiohttp connection pool reused across requests (was: new requests.Session each call)
  - In-memory TTL cache (default 5 min) to avoid duplicate fetches
  - Parallel TikTok hostname fallback (was: sequential — 4× 45s timeout worst-case)
  - DB writes dispatched to a worker thread to avoid blocking the event loop

Public sync API preserved via wrappers in tiktok_scraper.py:
  - scrape_all_accounts_for_user(user_id, on_start=None, on_done=None)
  - scrape_single_account_for_user(username, user_id, platform="tiktok")
  - fetch_instagram_data(username)   # sync wrapper for legacy callers
  - fetch_linkedin_data(username)    # sync wrapper for legacy callers

Tunables via env vars:
  SCRAPER_MAX_CONCURRENCY  default 20
  SCRAPER_CACHE_TTL        default 300 (seconds)
  SCRAPER_TIMEOUT          default 30 (seconds, per request)
  SCRAPER_MAX_RETRIES      default 3
  SCRAPER_BASE_BACKOFF     default 0.5 (seconds; exponential 0.5/1/2)
  SCRAPER_PROXY_SECRET     default "tracking-lab-2026"
"""
from __future__ import annotations

import asyncio
import os
import random
import time
from datetime import datetime
from typing import Any, Callable, Optional

import aiohttp


# ── Tunables ──────────────────────────────────────────────────────────
MAX_CONCURRENCY = int(os.environ.get("SCRAPER_MAX_CONCURRENCY", "20"))
CACHE_TTL_SEC   = int(os.environ.get("SCRAPER_CACHE_TTL", "300"))
REQUEST_TIMEOUT = int(os.environ.get("SCRAPER_TIMEOUT", "30"))
MAX_RETRIES     = int(os.environ.get("SCRAPER_MAX_RETRIES", "3"))
BASE_BACKOFF    = float(os.environ.get("SCRAPER_BASE_BACKOFF", "0.5"))
# How many parallel per-video metadata fetches for YouTube (pass 2).
# Conservative default to avoid saturating the default ThreadPoolExecutor.
YT_DETAIL_CONCURRENCY = int(os.environ.get("SCRAPER_YT_DETAIL_CONCURRENCY", "8"))

_SUPABASE_PROXY = "https://vpirlefqxnvmxbmndhmn.supabase.co/functions/v1"
_PROXY_SECRET   = os.environ.get("SCRAPER_PROXY_SECRET", "tracking-lab-2026")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# TikTok internal API hostnames. We race all 4 in parallel; first win returns.
_TIKTOK_HOSTS = [
    "api16-normal-c-useast1a.tiktokv.com",
    "api22-normal-c-useast1a.tiktokv.com",
    "api19-normal-c-useast1a.tiktokv.com",
    "api-h2.tiktokv.com",
]


# ── TTL cache (in-memory) ─────────────────────────────────────────────
# `_cache` is plain dict — safe to share across threads/loops (we always wrap
# access in a per-loop lock). The lock and semaphore must be keyed by event
# loop because asyncio primitives are bound to the loop that created them.
_cache: dict[str, tuple[float, Any]] = {}
_cache_locks_by_loop: dict[int, asyncio.Lock] = {}
_yt_sems_by_loop: dict[int, asyncio.Semaphore] = {}


def _get_yt_detail_sem() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    sem = _yt_sems_by_loop.get(loop_id)
    if sem is None:
        sem = asyncio.Semaphore(YT_DETAIL_CONCURRENCY)
        _yt_sems_by_loop[loop_id] = sem
    return sem


def _get_cache_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    lock = _cache_locks_by_loop.get(loop_id)
    if lock is None:
        lock = asyncio.Lock()
        _cache_locks_by_loop[loop_id] = lock
    return lock


async def _cache_get(key: str) -> Optional[Any]:
    async with _get_cache_lock():
        entry = _cache.get(key)
        if not entry:
            return None
        ts, val = entry
        if time.time() - ts > CACHE_TTL_SEC:
            del _cache[key]
            return None
        return val


async def _cache_set(key: str, val: Any) -> None:
    async with _get_cache_lock():
        _cache[key] = (time.time(), val)


def cache_clear() -> None:
    """Synchronous cache clear (safe to call outside loop)."""
    _cache.clear()


# ── aiohttp session — keyed by event loop ────────────────────────────
# A single global `_session` was racing across threads: aiohttp.ClientSession is
# bound to the event loop that created it, but ThreadPoolExecutor + asyncio.run
# means each worker thread has its own loop. Sharing the global produced silent
# "no_data" results and dangling Task warnings. We now key the session by loop
# id so each thread reuses its own session and never touches another's.
_sessions_by_loop: dict[int, aiohttp.ClientSession] = {}


async def _get_session() -> aiohttp.ClientSession:
    """Return the aiohttp session for the current event loop, creating if needed."""
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    sess = _sessions_by_loop.get(loop_id)
    if sess is None or sess.closed:
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=10,
            ttl_dns_cache=300,
        )
        timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT, connect=10)
        sess = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
        )
        _sessions_by_loop[loop_id] = sess
    return sess


async def close_session() -> None:
    """Close the session + drop loop-bound primitives for the current loop."""
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    sess = _sessions_by_loop.pop(loop_id, None)
    if sess is not None and not sess.closed:
        await sess.close()
    # Drop loop-bound asyncio primitives so they don't leak between thread runs
    _cache_locks_by_loop.pop(loop_id, None)
    _yt_sems_by_loop.pop(loop_id, None)


# ── HTTP helper with retries ──────────────────────────────────────────
async def _request_json(
    url: str, params: dict | None = None, label: str = "http"
) -> Optional[dict]:
    """GET JSON with exponential backoff on 429/5xx/network errors."""
    session = await _get_session()
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with session.get(url, params=params) as resp:
                if resp.status in (429, 500, 502, 503, 504):
                    wait = BASE_BACKOFF * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
                    print(f"  [{label}] HTTP {resp.status}, retry {attempt}/{MAX_RETRIES} in {wait:.1f}s")
                    await asyncio.sleep(wait)
                    continue
                if resp.status != 200:
                    text = (await resp.text())[:200]
                    print(f"  [{label}] HTTP {resp.status}: {text}")
                    return None
                try:
                    return await resp.json()
                except Exception as e:
                    print(f"  [{label}] invalid JSON: {e}")
                    return None
        except (asyncio.TimeoutError, aiohttp.ClientError) as e:
            last_exc = e
            wait = BASE_BACKOFF * (2 ** (attempt - 1)) + random.uniform(0, 0.3)
            print(f"  [{label}] {type(e).__name__}, retry {attempt}/{MAX_RETRIES} in {wait:.1f}s")
            await asyncio.sleep(wait)
        except Exception as e:
            last_exc = e
            print(f"  [{label}] unexpected error: {e}")
            break

    if last_exc:
        print(f"  [{label}] gave up after {MAX_RETRIES} attempts: {last_exc}")
    return None


# ── Instagram (via Supabase Edge Function proxy) ──────────────────────
async def fetch_instagram_async(username: str) -> Optional[dict]:
    """Fetch Instagram data via Supabase proxy with cache + retries."""
    cache_key = f"ig:{username}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        print(f"  [Instagram] cache hit @{username}")
        return cached

    url = f"{_SUPABASE_PROXY}/instagram-proxy"
    data = await _request_json(
        url,
        params={"username": username, "secret": _PROXY_SECRET},
        label=f"Instagram @{username}",
    )

    if not data or "error" in data:
        if data and "error" in data:
            print(f"  [Instagram] @{username} error: {data['error']}")
        return None

    videos = data.get("videos", []) or []
    print(
        f"  [Instagram] @{username}: {data.get('full_name')}, "
        f"{data.get('followers', 0)} followers, {len(videos)} posts"
    )

    result = {
        "username": username,
        "full_name": data.get("full_name", username),
        "followers": data.get("followers", 0),
        "following": data.get("following", 0),
        "biography": data.get("biography", ""),
        "profile_pic": data.get("profile_pic", ""),
        "videos": videos,
    }
    await _cache_set(cache_key, result)
    return result


# ── LinkedIn (via Supabase Edge Function proxy) ───────────────────────
async def fetch_linkedin_async(username: str) -> Optional[dict]:
    """Fetch LinkedIn data via Supabase proxy with cache + retries."""
    cache_key = f"li:{username}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        print(f"  [LinkedIn] cache hit {username}")
        return cached

    url = f"{_SUPABASE_PROXY}/linkedin-proxy"
    data = await _request_json(
        url,
        params={"username": username, "secret": _PROXY_SECRET},
        label=f"LinkedIn {username}",
    )

    if not data or "error" in data:
        if data and "error" in data:
            print(f"  [LinkedIn] {username} error: {data['error']}")
        return None

    posts = data.get("posts", []) or []
    print(
        f"  [LinkedIn] {username}: {data.get('full_name')}, "
        f"{data.get('followers', 0)} followers, {len(posts)} posts"
    )

    result = {
        "username": username,
        "full_name": data.get("full_name", username),
        "followers": data.get("followers", 0),
        "following": data.get("following", 0),
        "headline": data.get("headline", ""),
        "profile_pic": data.get("profile_pic", ""),
        "posts": posts,
    }
    await _cache_set(cache_key, result)
    return result


# ── TikTok (yt-dlp wrapped + parallel hostname race) ──────────────────
async def fetch_tiktok_async(username: str) -> Optional[list[dict]]:
    """
    Fetch TikTok data — try all 4 API hostnames IN PARALLEL, keep first success.

    Old code: sequential try of 4 hostnames, each with 45s socket_timeout
      → worst case 180s (all 4 fail) before fallback.
    New code: all 4 in parallel via asyncio.gather, return as soon as one wins
      → worst case ~45s, typical case ~5-15s.
    """
    cache_key = f"tt:{username}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        print(f"  [TikTok] cache hit @{username}")
        return cached

    async def try_host(host: str) -> Optional[list[dict]]:
        return await asyncio.to_thread(_ytdlp_tiktok_sync, username, host)

    tasks = [asyncio.create_task(try_host(h)) for h in _TIKTOK_HOSTS]
    winner: Optional[list[dict]] = None

    try:
        # First-completed: if it succeeds, keep it. Otherwise keep waiting.
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                if result:
                    winner = result
                    break
            except Exception:
                continue
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()

    if winner:
        print(f"  [TikTok] @{username}: {len(winner)} videos")
        await _cache_set(cache_key, winner)
    else:
        print(f"  [TikTok] @{username}: no data (all hostnames failed)")

    return winner


# ── YouTube (yt-dlp wrapped, 2-pass: listing + parallel details) ─────
async def fetch_youtube_async(username: str) -> Optional[list[dict]]:
    """
    YouTube fetch in 2 passes:
      1. Fast listing (extract_flat="in_playlist") → video IDs + views.
      2. Parallel per-video detail fetches (bounded semaphore) → likes,
         comments, timestamp, description, full thumbnails.

    Pass 2 is best-effort: if any detail fetch fails, we keep the listing
    record for that video — never regresses below v1 data quality.
    """
    cache_key = f"yt:{username}"
    cached = await _cache_get(cache_key)
    if cached is not None:
        print(f"  [YouTube] cache hit @{username}")
        return cached

    # Pass 1: fast listing
    listing = await asyncio.to_thread(_ytdlp_youtube_list_sync, username)
    if not listing:
        print(f"  [YouTube] @{username}: no data (listing empty)")
        return None

    # Pass 2: per-video detail fetches, bounded by a global semaphore
    sem = _get_yt_detail_sem()

    async def enrich(entry: dict) -> dict:
        video_url = (
            entry.get("url")
            or entry.get("webpage_url")
            or (f"https://www.youtube.com/watch?v={entry['id']}" if entry.get("id") else None)
        )
        if not video_url:
            return entry
        async with sem:
            detail = await asyncio.to_thread(_ytdlp_youtube_video_detail_sync, video_url)
        if not detail:
            return entry
        merged = dict(entry)
        # Copy only real-valued fields from detail; keep listing fallbacks otherwise.
        for k in (
            "like_count", "comment_count", "timestamp", "upload_date",
            "description", "title", "duration", "view_count",
            "thumbnail", "thumbnails", "channel_follower_count", "uploader",
            "webpage_url",
        ):
            v = detail.get(k)
            if v is not None:
                merged[k] = v
        return merged

    enriched = await asyncio.gather(*(enrich(e) for e in listing))
    enriched_count = sum(1 for v in enriched if v.get("like_count") is not None)
    print(
        f"  [YouTube] @{username}: {len(enriched)} videos "
        f"({enriched_count} with likes/comments)"
    )
    await _cache_set(cache_key, enriched)
    return enriched


# ── yt-dlp sync helpers (called via asyncio.to_thread) ────────────────
def _ytdlp_tiktok_sync(username: str, host: str) -> Optional[list[dict]]:
    """Single-hostname TikTok fetch via yt-dlp library."""
    try:
        import yt_dlp
    except ImportError:
        print("  [yt-dlp] not installed")
        return None

    url = f"https://www.tiktok.com/@{username}"
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "socket_timeout": 15,
        "retries": 1,
        "playlistend": 30,          # only fetch last 30 videos
        "ignoreerrors": True,       # skip broken entries instead of aborting
        "nocheckcertificate": True,
        "geo_bypass": True,
        "user_agent": _USER_AGENT,
        "http_headers": {
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.tiktok.com/",
        },
        "extractor_args": {"tiktok": {"api_hostname": [host]}},
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        err = str(e).lower()
        if any(p in err for p in ("unavailable", "private", "not found", "does not exist", "404")):
            # Permanent error — no point trying other hostnames
            print(f"  [yt-dlp/tt/{host}] permanent error @{username}: {e}")
        return None

    if not info:
        return None
    entries = info.get("entries", [info])
    videos = [e for e in entries if e]
    return videos or None


def _ytdlp_youtube_list_sync(username: str) -> Optional[list[dict]]:
    """
    YouTube pass 1: fast listing of last 30 shorts via extract_flat.
    Returns list of dicts with id + view_count + url (but no likes/comments/timestamp).
    """
    try:
        import yt_dlp
    except ImportError:
        print("  [yt-dlp] not installed")
        return None

    url = f"https://www.youtube.com/@{username}/shorts"
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        # "in_playlist" lists videos with basic metadata (incl. view_count on YT)
        # without trying to resolve a playable format per video — avoids the
        # "Requested format is not available" error that breaks full extraction.
        "extract_flat": "in_playlist",
        "skip_download": True,
        "socket_timeout": 20,
        "retries": 1,
        "playlistend": 30,          # only fetch last 30 shorts
        "ignoreerrors": True,       # skip broken entries instead of aborting
        "nocheckcertificate": True,
        "geo_bypass": True,
        "user_agent": _USER_AGENT,
        "http_headers": {
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.youtube.com/",
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        err = str(e).lower()
        if any(p in err for p in ("unavailable", "private", "not found", "does not exist", "404")):
            print(f"  [yt-dlp/yt-list] permanent error @{username}: {e}")
        else:
            print(f"  [yt-dlp/yt-list] error @{username}: {str(e)[:150]}")
        return None

    if not info:
        return None
    entries = info.get("entries", [info])
    videos = [e for e in entries if e]
    return videos or None


def _ytdlp_youtube_video_detail_sync(video_url: str) -> Optional[dict]:
    """
    YouTube pass 2: full metadata for a single video.

    Returns the raw yt-dlp info_dict (which includes like_count, comment_count,
    timestamp, description, etc.) or None on failure.

    IMPORTANT: we set ignore_no_formats_error=True + skip_download=True so
    yt-dlp doesn't crash with "Requested format is not available" when no
    playable format is returned by YouTube — we only care about metadata.
    """
    try:
        import yt_dlp
    except ImportError:
        return None

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignore_no_formats_error": True,   # don't crash if no format is available
        "socket_timeout": 15,
        "retries": 1,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "user_agent": _USER_AGENT,
        "getcomments": False,              # don't fetch comment bodies
        "http_headers": {
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.youtube.com/",
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(video_url, download=False)
    except Exception as e:
        # Silent for per-video fails; listing data survives
        msg = str(e)[:120]
        if "Requested format is not available" not in msg:
            print(f"  [yt-dlp/yt-detail] {video_url}: {msg}")
        return None


# ── DB storage dispatch ───────────────────────────────────────────────
async def _process_and_store(
    username: str, platform: str, data: Any, user_id: Optional[int]
) -> int:
    """Dispatch fetched data to platform-specific storage. Returns video count."""
    from database import upsert_account, upsert_video, save_daily_snapshot

    if platform == "instagram":
        def _store():
            upsert_account(
                username=username,
                display_name=data.get("full_name", username),
                followers=data.get("followers", 0),
                avatar_url=data.get("profile_pic", ""),
                user_id=user_id,
                platform="instagram",
            )
            for v in data.get("videos", []):
                upsert_video(
                    video_id=v["id"],
                    account_username=username,
                    description=v.get("description", ""),
                    create_time=v.get("create_time"),
                    duration=int(v.get("duration", 0)),
                    views=v.get("views", 0),
                    likes=v.get("likes", 0),
                    comments=v.get("comments", 0),
                    shares=0,
                    saves=0,
                    thumbnail_url=v.get("thumbnail_url", ""),
                    video_url=v.get("video_url", ""),
                    user_id=user_id,
                    platform="instagram",
                )
            save_daily_snapshot(username, user_id=user_id, platform="instagram")
            return len(data.get("videos", []))
        return await asyncio.to_thread(_store)

    if platform == "linkedin":
        def _store():
            upsert_account(
                username=username,
                display_name=data.get("full_name", username),
                followers=data.get("followers", 0),
                avatar_url=data.get("profile_pic", ""),
                bio=data.get("headline", ""),
                user_id=user_id,
                platform="linkedin",
            )
            for p in data.get("posts", []):
                upsert_video(
                    video_id=p["id"],
                    account_username=username,
                    description=p.get("text", ""),
                    create_time=p.get("create_time"),
                    duration=0,
                    views=p.get("views", 0),
                    likes=p.get("likes", 0),
                    comments=p.get("comments", 0),
                    shares=p.get("shares", 0),
                    saves=0,
                    thumbnail_url=p.get("thumbnail_url", ""),
                    video_url=p.get("post_url", ""),
                    user_id=user_id,
                    platform="linkedin",
                )
            save_daily_snapshot(username, user_id=user_id, platform="linkedin")
            return len(data.get("posts", []))
        return await asyncio.to_thread(_store)

    # TikTok / YouTube — data is list of yt-dlp video dicts
    def _store():
        followers = 0
        display_name = username
        for vdata in data:
            video_id = str(vdata.get("id", vdata.get("display_id", "")))
            if not video_id:
                continue
            uploader = vdata.get("uploader", username)
            if uploader:
                display_name = uploader
            cfc = vdata.get("channel_follower_count", 0)
            if cfc:
                followers = cfc
            # Prefer unix `timestamp`, fall back to `upload_date` (YYYYMMDD) for YouTube
            create_ts = vdata.get("timestamp")
            create_time = None
            if create_ts:
                try:
                    create_time = datetime.fromtimestamp(create_ts).isoformat()
                except (ValueError, OSError):
                    pass
            if not create_time:
                upload_date = vdata.get("upload_date")
                if upload_date and len(upload_date) == 8:
                    try:
                        create_time = datetime.strptime(upload_date, "%Y%m%d").isoformat()
                    except ValueError:
                        pass

            # Thumbnails: prefer originCover > cover > first available
            thumbnail = vdata.get("thumbnail")
            if not thumbnail:
                tl = vdata.get("thumbnails", []) or []
                for t in tl:
                    if t.get("id") == "originCover":
                        thumbnail = t.get("url")
                        break
                if not thumbnail:
                    for t in tl:
                        if t.get("id") == "cover":
                            thumbnail = t.get("url")
                            break
                if not thumbnail and tl:
                    thumbnail = tl[0].get("url")

            upsert_video(
                video_id=video_id,
                account_username=username,
                description=vdata.get("description") or vdata.get("title") or "",
                create_time=create_time,
                duration=vdata.get("duration", 0) or 0,
                views=vdata.get("view_count", 0) or 0,
                likes=vdata.get("like_count", 0) or 0,
                comments=vdata.get("comment_count", 0) or 0,
                shares=vdata.get("repost_count", 0) or 0,
                saves=vdata.get("forward_count", 0) or 0,
                thumbnail_url=thumbnail,
                video_url=vdata.get("webpage_url"),
                user_id=user_id,
                platform=platform,
            )
        upsert_account(
            username=username,
            display_name=display_name,
            followers=followers,
            user_id=user_id,
            platform=platform,
        )
        save_daily_snapshot(username, user_id=user_id, platform=platform)
        return len(data)
    return await asyncio.to_thread(_store)


def _upsert_empty_account_sync(username: str, platform: str, user_id: Optional[int]):
    """Create an empty account entry when scrape returns no data."""
    from database import upsert_account
    upsert_account(username=username, display_name=username, user_id=user_id, platform=platform)


# ── Main orchestrator ────────────────────────────────────────────────
async def scrape_accounts_async(
    accounts: list[dict],
    on_start: Optional[Callable[[str], None]] = None,
    on_done: Optional[Callable[[str, bool, int], None]] = None,
) -> dict[str, dict]:
    """
    Scrape many accounts concurrently. Accepts a list of dicts with
    {username, platform, user_id?}. Returns dict keyed by username.
    """
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    results: dict[str, dict] = {}

    async def scrape_one(acc: dict):
        username = acc["username"]
        platform = acc.get("platform", "tiktok")
        user_id = acc.get("user_id")

        async with sem:
            if on_start:
                try:
                    on_start(username)
                except Exception as e:
                    print(f"  [on_start] {username}: {e}")

            try:
                if platform == "instagram":
                    data = await fetch_instagram_async(username)
                elif platform == "linkedin":
                    data = await fetch_linkedin_async(username)
                elif platform == "youtube":
                    data = await fetch_youtube_async(username)
                else:  # tiktok (default)
                    data = await fetch_tiktok_async(username)

                if data:
                    count = await _process_and_store(username, platform, data, user_id)
                    results[username] = {
                        "username": username, "status": "success",
                        "videos": count, "platform": platform,
                    }
                    if on_done:
                        try:
                            on_done(username, True, count)
                        except Exception as e:
                            print(f"  [on_done] {username}: {e}")
                else:
                    results[username] = {
                        "username": username, "status": "no_data",
                        "videos": 0, "platform": platform,
                    }
                    # Still upsert empty account so it appears in UI
                    await asyncio.to_thread(
                        _upsert_empty_account_sync, username, platform, user_id
                    )
                    if on_done:
                        try:
                            on_done(username, True, 0)  # no_data is not an error
                        except Exception as e:
                            print(f"  [on_done] {username}: {e}")

            except Exception as e:
                print(f"  @{username} ({platform}): exception - {e}")
                results[username] = {
                    "username": username, "status": "error",
                    "videos": 0, "platform": platform,
                }
                if on_done:
                    try:
                        on_done(username, False, 0)
                    except Exception:
                        pass

    await asyncio.gather(*(scrape_one(acc) for acc in accounts))
    return results


async def scrape_one_account_async(
    username: str, user_id: Optional[int], platform: str = "tiktok"
) -> dict:
    """Scrape a single account — same contract as legacy _scrape_one_account."""
    acc = {"username": username, "platform": platform, "user_id": user_id}
    results = await scrape_accounts_async([acc])
    return results.get(username, {
        "username": username, "status": "error", "videos": 0, "platform": platform,
    })


# ── Synchronous entry points (run the event loop, for legacy callers) ─
def run_scrape_all_accounts(
    accounts: list[dict],
    on_start: Optional[Callable[[str], None]] = None,
    on_done: Optional[Callable[[str, bool, int], None]] = None,
) -> dict[str, dict]:
    """Blocking wrapper: runs the async scrape in a fresh event loop."""
    async def _main():
        try:
            return await scrape_accounts_async(accounts, on_start=on_start, on_done=on_done)
        finally:
            await close_session()

    return asyncio.run(_main())


def run_scrape_one_account(
    username: str, user_id: Optional[int], platform: str = "tiktok"
) -> dict:
    """Blocking wrapper for single-account scrape."""
    async def _main():
        try:
            return await scrape_one_account_async(username, user_id, platform)
        finally:
            await close_session()

    return asyncio.run(_main())
