#!/usr/bin/env python3
"""
One-shot migration: re-mirror thumbnails for the Top N videos by views.

The regular cron only re-scrapes the latest 100 videos per account, so very
old viral content (3+ months back, beyond the latest-100 window) keeps its
expired CDN URL forever. This script targets those specifically by hitting
each video's direct URL with yt-dlp (TikTok) or the instagram-proxy with
the matching slug (Instagram).

Run:
    DB=$(vercel env pull .env.tmp --environment=production --yes >/dev/null \
         && grep ^DATABASE_URL .env.tmp | sed 's/DATABASE_URL=//' | tr -d '"' \
         && rm -f .env.tmp) python3 scripts/migrate_top_thumbnails.py [N]

Default N = 100. Idempotent (already-mirrored thumbs are skipped). Safe to
re-run; bug-tolerant (one failed video doesn't stop the batch).
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import psycopg2
import psycopg2.extras
import requests
import yt_dlp

DB_URL = os.environ.get("DB") or os.environ.get("DATABASE_URL")
if not DB_URL:
    sys.exit("Missing DB env var. Pull from Vercel first.")

PROXY_BASE = "https://vpirlefqxnvmxbmndhmn.supabase.co/functions/v1"
PROXY_SECRET = "tracking-lab-2026"
TOP_N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
USER_ID = 1
WORKERS = 8

# yt-dlp options for single-video metadata fetch. extract_flat=False so we
# get the full thumbnail list, not just IDs.
YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "socket_timeout": 15,
    "retries": 1,
    "ignoreerrors": True,
    "nocheckcertificate": True,
    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}


def pick_thumbnail(info: dict) -> str:
    """Same logic as scraper_async._pick_thumbnail. Prefer originCover > cover > first."""
    if not info:
        return ""
    if info.get("thumbnail"):
        return info["thumbnail"]
    tl = info.get("thumbnails") or []
    for t in tl:
        if t.get("id") == "originCover":
            return t.get("url") or ""
    for t in tl:
        if t.get("id") == "cover":
            return t.get("url") or ""
    return tl[0].get("url") if tl else ""


def mirror(url: str, video_id: str, platform: str) -> Optional[str]:
    """Call the mirror-thumbnail Edge Function. Returns mirrored URL or None."""
    try:
        r = requests.post(
            f"{PROXY_BASE}/mirror-thumbnail",
            json={"url": url, "video_id": str(video_id), "platform": platform, "secret": PROXY_SECRET},
            timeout=30,
        )
        if r.status_code == 200:
            return r.json().get("url")
        return None
    except Exception:
        return None


def update_db(video_id: str, platform: str, new_url: str) -> bool:
    conn = psycopg2.connect(DB_URL)
    conn.autocommit = True
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE videos SET thumbnail_url=%s WHERE video_id=%s AND user_id=%s AND platform=%s",
            (new_url, video_id, USER_ID, platform),
        )
        return cur.rowcount > 0
    finally:
        cur.close()
        conn.close()


def process_tiktok(v: dict) -> tuple[str, str]:
    """yt-dlp by direct video URL → fresh thumb → mirror → DB update."""
    video_url = v.get("video_url")
    video_id = v["video_id"]
    if not video_url:
        return video_id, "no_video_url"
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception as e:
        return video_id, f"ytdlp_err:{str(e)[:30]}"
    if not info:
        return video_id, "ytdlp_no_info"
    thumb = pick_thumbnail(info)
    if not thumb:
        return video_id, "no_fresh_thumb"
    mirrored = mirror(thumb, video_id, "tiktok")
    if not mirrored or "supabase.co/storage" not in mirrored:
        return video_id, "mirror_failed"
    if update_db(video_id, "tiktok", mirrored):
        return video_id, "OK"
    return video_id, "db_no_match"


def process_instagram(v: dict) -> tuple[str, str]:
    """yt-dlp by direct IG post URL → fresh thumb → mirror → DB update.

    Works for any age of post (unlike the IG proxy which only returns the
    latest ~12-50 posts of a profile)."""
    video_url = v.get("video_url")
    video_id = v["video_id"]
    if not video_url:
        return video_id, "no_video_url"
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception as e:
        return video_id, f"ytdlp_err:{str(e)[:30]}"
    if not info:
        return video_id, "ytdlp_no_info"
    thumb = pick_thumbnail(info)
    if not thumb:
        return video_id, "no_fresh_thumb"
    mirrored = mirror(thumb, video_id, "instagram")
    if not mirrored or "supabase.co/storage" not in mirrored:
        return video_id, "mirror_failed"
    if update_db(video_id, "instagram", mirrored):
        return video_id, "OK"
    return video_id, "db_no_match"


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        """
        SELECT video_id, account_username, platform, views, video_url, thumbnail_url
        FROM videos
        WHERE user_id = %s
          AND platform IN ('tiktok', 'instagram')
          AND (thumbnail_url IS NULL OR thumbnail_url NOT LIKE '%%supabase.co/storage%%')
        ORDER BY views DESC
        LIMIT %s
        """,
        (USER_ID, TOP_N),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    print(f"\n  ─── Top {len(rows)} videos to migrate ───")
    by_platform: dict[str, list] = {}
    for r in rows:
        by_platform.setdefault(r["platform"], []).append(dict(r))
    for platform, items in by_platform.items():
        print(f"    {platform}: {len(items)}")

    results: dict[str, str] = {}

    # ── TikTok: parallel yt-dlp on direct URLs ──
    tt_videos = by_platform.get("tiktok", [])
    if tt_videos:
        print(f"\n  ── TikTok: yt-dlp + mirror, {WORKERS} workers ──")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(process_tiktok, v): v["video_id"] for v in tt_videos}
            done = 0
            for fut in as_completed(futures):
                vid, status = fut.result()
                results[vid] = status
                done += 1
                if done % 10 == 0:
                    print(f"    {done}/{len(tt_videos)} done")
        print(f"  TikTok done in {time.time() - t0:.1f}s")

    # ── Instagram: parallel yt-dlp on individual /reel/ or /p/ URLs ──
    ig_videos = by_platform.get("instagram", [])
    if ig_videos:
        print(f"\n  ── Instagram: yt-dlp + mirror, {WORKERS} workers ──")
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(process_instagram, v): v["video_id"] for v in ig_videos}
            done = 0
            for fut in as_completed(futures):
                vid, status = fut.result()
                results[vid] = status
                done += 1
                if done % 10 == 0:
                    print(f"    {done}/{len(ig_videos)} done")
        print(f"  Instagram done in {time.time() - t0:.1f}s")

    # ── Summary ──
    counts: dict[str, int] = {}
    for status in results.values():
        # bucket detailed errors
        bucket = status if status in ("OK", "no_video_url", "ytdlp_no_info", "no_fresh_thumb", "mirror_failed", "db_no_match") else (status[:25] if status.startswith("ytdlp_err") else "other_error")
        counts[bucket] = counts.get(bucket, 0) + 1

    print(f"\n  ─── Summary ({len(results)} videos processed) ───")
    for bucket, n in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"    {bucket}: {n}")


if __name__ == "__main__":
    main()
