import subprocess
import json
import os
import re
import time
import random
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import upsert_account, upsert_video, save_daily_snapshot, get_all_accounts


def _get_platform_url(username, platform="tiktok"):
    """Build the profile/channel URL for each platform."""
    urls = {
        "tiktok": f"https://www.tiktok.com/@{username}",
        "youtube": f"https://www.youtube.com/@{username}/shorts",
        "instagram": f"https://www.instagram.com/{username}/",
        "snapchat": f"https://www.snapchat.com/add/{username}",
    }
    return urls.get(platform, urls["tiktok"])


def fetch_instagram_data(username):
    """Fetch Instagram data via Supabase Edge Function proxy."""
    proxy_url = "https://vpirlefqxnvmxbmndhmn.supabase.co/functions/v1/instagram-proxy"
    secret = "tracking-lab-2026"

    try:
        print(f"  [Instagram] Fetching @{username} via proxy...")
        resp = requests.get(proxy_url, params={"username": username, "secret": secret}, timeout=45)

        if resp.status_code != 200:
            print(f"  [Instagram] Proxy error {resp.status_code}: {resp.text[:200]}")
            return None

        data = resp.json()
        if 'error' in data:
            print(f"  [Instagram] Error: {data['error']}")
            return None

        videos = data.get('videos', [])
        print(f"  [Instagram] @{username}: {data.get('full_name')}, {data.get('followers')} followers, {len(videos)} posts/reels")

        return {
            'username': username,
            'full_name': data.get('full_name', username),
            'followers': data.get('followers', 0),
            'following': data.get('following', 0),
            'biography': data.get('biography', ''),
            'profile_pic': data.get('profile_pic', ''),
            'videos': videos,
        }

    except Exception as e:
        print(f"  [Instagram] Exception for @{username}: {e}")
        return None


def process_instagram_data(username, ig_data, user_id=None):
    """Process Instagram data and store in database."""
    if not ig_data:
        return

    upsert_account(
        username=username,
        display_name=ig_data.get('full_name', username),
        followers=ig_data.get('followers', 0),
        avatar_url=ig_data.get('profile_pic', ''),
        user_id=user_id,
        platform="instagram",
    )

    for v in ig_data.get('videos', []):
        upsert_video(
            video_id=v['id'],
            account_username=username,
            description=v.get('description', ''),
            create_time=v.get('create_time'),
            duration=int(v.get('duration', 0)),
            views=v.get('views', 0),
            likes=v.get('likes', 0),
            comments=v.get('comments', 0),
            shares=0,
            saves=0,
            thumbnail_url=v.get('thumbnail_url', ''),
            video_url=v.get('video_url', ''),
            user_id=user_id,
            platform="instagram",
        )

    save_daily_snapshot(username, user_id=user_id, platform="instagram")
    print(f"  [Instagram] Saved {len(ig_data.get('videos', []))} posts for @{username}")


def fetch_account_data_ytdlp(username, platform="tiktok"):
    """Fetch account data using yt-dlp. Supports TikTok, YouTube Shorts, Instagram, Snapchat."""
    # For Instagram, use dedicated scraper
    if platform == "instagram":
        return None  # Handled separately by fetch_instagram_data

    url = _get_platform_url(username, platform)
    print(f"  [yt-dlp] Fetching {platform} data for @{username}...")

    # Realistic browser user-agent to avoid TikTok datacenter IP blocking
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )

    # Try Python library first (works on Vercel serverless), fallback to subprocess
    videos = _fetch_ytdlp_library(url, username, platform, user_agent)
    if videos is not None:
        return videos

    return _fetch_ytdlp_subprocess(url, username, platform, user_agent)


def _fetch_ytdlp_library(url, username, platform, user_agent):
    """Fetch using yt-dlp as a Python library (no subprocess needed)."""
    try:
        import yt_dlp

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'skip_download': True,
            'socket_timeout': 30,
            'retries': 2,
            'nocheckcertificate': True,
            'geo_bypass': True,
            'user_agent': user_agent,
            'http_headers': {
                'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
            },
        }

        if platform == "tiktok":
            ydl_opts['http_headers']['Referer'] = 'https://www.tiktok.com/'
            ydl_opts['extractor_args'] = {'tiktok': {'api_hostname': ['api16-normal-c-useast1a.tiktokv.com']}}
        elif platform == "youtube":
            ydl_opts['http_headers']['Referer'] = 'https://www.youtube.com/'
            # Don't use extract_flat for YouTube - need full stats (views, likes, etc.)
            ydl_opts['extract_flat'] = False
        elif platform == "instagram":
            ydl_opts['http_headers']['Referer'] = 'https://www.instagram.com/'

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            print(f"  [yt-dlp/lib] No data for @{username}")
            return None

        # Handle playlist (channel page) vs single video
        entries = info.get('entries', [info])
        videos = [e for e in entries if e]

        if not videos:
            print(f"  [yt-dlp/lib] No videos found for @{username}")
            return None

        print(f"  [yt-dlp/lib] Found {len(videos)} videos for @{username}")
        return videos

    except ImportError:
        print("  [yt-dlp/lib] yt-dlp not installed")
        return None
    except Exception as e:
        print(f"  [yt-dlp/lib] Error for @{username}: {e}")
        # Return None to fallback to subprocess
        return None


def _fetch_ytdlp_subprocess(url, username, platform, user_agent):
    """Fetch using yt-dlp as a subprocess (original method)."""
    try:
        import sys
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--dump-json",
            "--flat-playlist",
            "--no-download",
            "--no-warnings",
            "--quiet",
            "--socket-timeout", "30",
            "--retries", "2",
            "--no-check-certificates",
            "--geo-bypass",
            "--user-agent", user_agent,
            "--add-header", "Accept-Language:fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        ]
        # Platform-specific args
        if platform == "tiktok":
            cmd += ["--add-header", "Referer:https://www.tiktok.com/",
                    "--extractor-args", "tiktok:api_hostname=api16-normal-c-useast1a.tiktokv.com"]
        elif platform == "youtube":
            cmd += ["--add-header", "Referer:https://www.youtube.com/"]
        elif platform == "instagram":
            cmd += ["--add-header", "Referer:https://www.instagram.com/"]
        cmd.append(url)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            print(f"  [yt-dlp/sub] Error for @{username}: {result.stderr[:300]}")
            return None

        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                videos.append(data)
            except json.JSONDecodeError:
                continue

        if not videos:
            print(f"  [yt-dlp/sub] No videos found for @{username}")
            return None

        print(f"  [yt-dlp/sub] Found {len(videos)} videos for @{username}")
        return videos

    except subprocess.TimeoutExpired:
        print(f"  [yt-dlp/sub] Timeout for @{username}")
        return None
    except FileNotFoundError:
        print("  [yt-dlp/sub] yt-dlp not installed.")
        return None
    except Exception as e:
        print(f"  [yt-dlp/sub] Exception for @{username}: {e}")
        return None

def process_ytdlp_data(username, videos_data, user_id=None, platform="tiktok"):
    """Process yt-dlp JSON data and store in database."""
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

        channel_follower_count = vdata.get("channel_follower_count", 0)
        if channel_follower_count:
            followers = channel_follower_count

        create_timestamp = vdata.get("timestamp", None)
        create_time = None
        if create_timestamp:
            create_time = datetime.fromtimestamp(create_timestamp).isoformat()

        views = vdata.get("view_count", 0) or 0
        likes = vdata.get("like_count", 0) or 0
        comments = vdata.get("comment_count", 0) or 0
        shares = vdata.get("repost_count", 0) or 0
        saves = vdata.get("forward_count", 0) or 0
        duration = vdata.get("duration", 0) or 0
        description = vdata.get("description", "") or vdata.get("title", "") or ""
        # Extract thumbnail: try 'thumbnail' first, then 'thumbnails' array
        thumbnail = vdata.get("thumbnail", None)
        if not thumbnail:
            thumbnails_list = vdata.get("thumbnails", [])
            if thumbnails_list:
                # Prefer originCover > cover > first available
                for t in thumbnails_list:
                    if t.get("id") == "originCover":
                        thumbnail = t.get("url")
                        break
                if not thumbnail:
                    for t in thumbnails_list:
                        if t.get("id") == "cover":
                            thumbnail = t.get("url")
                            break
                if not thumbnail:
                    thumbnail = thumbnails_list[0].get("url")

        video_url = vdata.get("webpage_url", None)

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
            video_url=video_url,
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


def _scrape_one_account(username, user_id, platform="tiktok"):
    """Scrape a single account (used by thread pool)."""
    # Instagram: use dedicated scraper
    if platform == "instagram":
        ig_data = fetch_instagram_data(username)
        if ig_data:
            process_instagram_data(username, ig_data, user_id=user_id)
            count = len(ig_data.get('videos', []))
            print(f"  @{username} (instagram): {count} posts OK")
            return {"username": username, "status": "success", "videos": count}
        else:
            upsert_account(username=username, display_name=username, user_id=user_id, platform="instagram")
            print(f"  @{username} (instagram): no data")
            return {"username": username, "status": "no_data", "videos": 0}

    # Other platforms: use yt-dlp
    videos_data = fetch_account_data_ytdlp(username, platform=platform)
    if videos_data:
        process_ytdlp_data(username, videos_data, user_id=user_id, platform=platform)
        print(f"  @{username} ({platform}): {len(videos_data)} videos OK")
        return {"username": username, "status": "success", "videos": len(videos_data)}
    else:
        upsert_account(username=username, display_name=username, user_id=user_id, platform=platform)
        print(f"  @{username} ({platform}): no data")
        return {"username": username, "status": "no_data", "videos": 0}


def scrape_all_accounts_for_user(user_id, on_start=None, on_done=None):
    """Scrape all accounts tracked by a specific user (parallel, all platforms)."""
    accounts = get_all_accounts(user_id=user_id)
    print("=" * 60)
    print(f"Scraper - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    platforms = {}
    for a in accounts:
        p = a.get('platform', 'tiktok')
        platforms[p] = platforms.get(p, 0) + 1
    platform_summary = ', '.join(f"{v} {k}" for k, v in platforms.items())
    print(f"Scraping {len(accounts)} accounts for user #{user_id} ({platform_summary})")
    print("=" * 60)

    results = {}
    # Scrape up to 6 accounts in parallel for speed
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_scrape_one_account_with_callback, acc['username'], user_id, on_start, on_done, acc.get('platform', 'tiktok')): acc['username']
            for acc in accounts
        }
        for future in as_completed(futures):
            username = futures[future]
            try:
                result = future.result()
                results[username] = result
            except Exception as e:
                print(f"  @{username}: error - {e}")
                results[username] = {"status": "error", "videos": 0}
                if on_done:
                    on_done(username, False, 0)

    print("\n" + "=" * 60)
    print("Scraping complete!")
    print("=" * 60)
    return results


def _scrape_one_account_with_callback(username, user_id, on_start=None, on_done=None, platform="tiktok"):
    """Scrape a single account with progress callbacks."""
    if on_start:
        on_start(username)
    result = _scrape_one_account(username, user_id, platform=platform)
    if on_done:
        on_done(username, result["status"] == "success", result["videos"])
    return result

def scrape_single_account_for_user(username, user_id, platform="tiktok"):
    """Scrape a single account for a specific user."""
    print(f"\nScraping @{username} ({platform}) for user #{user_id}...")
    return _scrape_one_account(username, user_id, platform=platform)


if __name__ == "__main__":
    from database import init_db
    init_db()
    print("Use the web interface to manage and scrape accounts.")
