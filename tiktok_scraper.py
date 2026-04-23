"""
tiktok_scraper.py — backward-compatible sync facade.

Historical module that used requests + ThreadPoolExecutor(max_workers=6) for
multi-account scraping. Now a thin wrapper over `scraper_async.py`, which uses
asyncio + aiohttp + TTL cache for 10-20× the throughput.

Public API kept identical for existing callers (daily_scrape.py, app.py):
  - scrape_all_accounts_for_user(user_id, on_start=None, on_done=None)
  - scrape_single_account_for_user(username, user_id, platform="tiktok")

Legacy helpers kept as sync wrappers around the async implementation so any
other importer continues to work without changes:
  - fetch_instagram_data(username)        -> dict | None
  - fetch_linkedin_data(username)         -> dict | None
  - fetch_account_data_ytdlp(username, platform) -> list[dict] | None
  - process_instagram_data / process_linkedin_data / process_ytdlp_data
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Callable, Optional

from database import (
    upsert_account,
    upsert_video,
    save_daily_snapshot,
    get_all_accounts,
)

# Import the new async engine
from scraper_async import (
    close_session,
    fetch_instagram_async,
    fetch_linkedin_async,
    fetch_tiktok_async,
    fetch_youtube_async,
    run_scrape_all_accounts,
    run_scrape_one_account,
)


# ── Public API used by app.py and daily_scrape.py ────────────────────
def scrape_all_accounts_for_user(
    user_id: int,
    on_start: Optional[Callable[[str], None]] = None,
    on_done: Optional[Callable[[str, bool, int], None]] = None,
) -> dict:
    """Scrape all accounts tracked by `user_id` across every platform."""
    accounts = get_all_accounts(user_id=user_id)
    print("=" * 60)
    print(f"Scraper (async) - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Summary line — unchanged to preserve log parsing on Render
    platforms: dict[str, int] = {}
    for a in accounts:
        p = a.get("platform", "tiktok")
        platforms[p] = platforms.get(p, 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in platforms.items())
    print(f"Scraping {len(accounts)} accounts for user #{user_id} ({summary})")
    print("=" * 60)

    # Normalize shape expected by scraper_async
    normalized = [
        {
            "username": a["username"],
            "platform": a.get("platform", "tiktok"),
            "user_id": user_id,
        }
        for a in accounts
    ]

    results = run_scrape_all_accounts(normalized, on_start=on_start, on_done=on_done)

    print("\n" + "=" * 60)
    print("Scraping complete!")
    print("=" * 60)
    return results


def scrape_single_account_for_user(
    username: str, user_id: int, platform: str = "tiktok"
) -> dict:
    """Scrape one specific account for `user_id`."""
    print(f"\nScraping @{username} ({platform}) for user #{user_id}...")
    return run_scrape_one_account(username, user_id, platform=platform)


# ── Legacy sync helpers (kept for backward compat) ───────────────────
def _run_async(coro):
    """Run a coroutine in a fresh event loop, close the shared session after."""
    async def _wrap():
        try:
            return await coro
        finally:
            await close_session()
    return asyncio.run(_wrap())


def fetch_instagram_data(username: str) -> Optional[dict]:
    """Legacy sync wrapper; returns the same dict shape as before."""
    return _run_async(fetch_instagram_async(username))


def fetch_linkedin_data(username: str) -> Optional[dict]:
    """Legacy sync wrapper."""
    return _run_async(fetch_linkedin_async(username))


def fetch_account_data_ytdlp(
    username: str, platform: str = "tiktok"
) -> Optional[list[dict]]:
    """Legacy sync wrapper. Returns yt-dlp-shaped list of video dicts."""
    if platform == "instagram":
        # Old code returned None here and expected callers to use fetch_instagram_data
        return None
    if platform == "youtube":
        return _run_async(fetch_youtube_async(username))
    return _run_async(fetch_tiktok_async(username))


# ── Processors (still sync — unchanged from previous behavior) ───────
def process_instagram_data(username: str, ig_data: dict, user_id: Optional[int] = None):
    """Persist Instagram scrape results (sync; kept for legacy callers)."""
    if not ig_data:
        return

    upsert_account(
        username=username,
        display_name=ig_data.get("full_name", username),
        followers=ig_data.get("followers", 0),
        avatar_url=ig_data.get("profile_pic", ""),
        user_id=user_id,
        platform="instagram",
    )

    for v in ig_data.get("videos", []):
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
    print(f"  [Instagram] Saved {len(ig_data.get('videos', []))} posts for @{username}")


def process_linkedin_data(username: str, li_data: dict, user_id: Optional[int] = None):
    """Persist LinkedIn scrape results (sync; kept for legacy callers)."""
    if not li_data:
        return

    upsert_account(
        username=username,
        display_name=li_data.get("full_name", username),
        followers=li_data.get("followers", 0),
        avatar_url=li_data.get("profile_pic", ""),
        bio=li_data.get("headline", ""),
        user_id=user_id,
        platform="linkedin",
    )

    for p in li_data.get("posts", []):
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
    print(f"  [LinkedIn] Saved {len(li_data.get('posts', []))} posts for {username}")


def process_ytdlp_data(
    username: str,
    videos_data: list,
    user_id: Optional[int] = None,
    platform: str = "tiktok",
):
    """Persist yt-dlp shaped data (sync; kept for legacy callers)."""
    if not videos_data:
        return

    followers = 0
    display_name = username

    for vdata in videos_data:
        video_id = str(vdata.get("id", vdata.get("display_id", "")))
        if not video_id:
            continue

        uploader = vdata.get("uploader", username)
        if uploader:
            display_name = uploader

        cfc = vdata.get("channel_follower_count", 0)
        if cfc:
            followers = cfc

        create_ts = vdata.get("timestamp", None)
        create_time = (
            datetime.fromtimestamp(create_ts).isoformat() if create_ts else None
        )

        views = vdata.get("view_count", 0) or 0
        likes = vdata.get("like_count", 0) or 0
        comments = vdata.get("comment_count", 0) or 0
        shares = vdata.get("repost_count", 0) or 0
        saves = vdata.get("forward_count", 0) or 0
        duration = vdata.get("duration", 0) or 0
        description = vdata.get("description", "") or vdata.get("title", "") or ""

        # Thumbnails: prefer originCover > cover > first
        thumbnail = vdata.get("thumbnail", None)
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
            description=description,
            create_time=create_time,
            duration=duration,
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
            saves=saves,
            thumbnail_url=thumbnail,
            video_url=vdata.get("webpage_url", None),
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


if __name__ == "__main__":
    from database import init_db
    init_db()
    print("Use the web interface to manage and scrape accounts.")
