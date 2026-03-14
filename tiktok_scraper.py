import subprocess
import json
import re
import time
import random
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from database import upsert_account, upsert_video, save_daily_snapshot, get_all_accounts


def fetch_account_data_ytdlp(username):
    """Fetch TikTok account data using yt-dlp."""
    url = f"https://www.tiktok.com/@{username}"
    print(f"  [yt-dlp] Fetching data for @{username}...")

    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--dump-json",
                "--flat-playlist",
                "--no-download",
                "--no-warnings",
                "--quiet",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            print(f"  [yt-dlp] Error for @{username}: {result.stderr[:200]}")
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
            print(f"  [yt-dlp] No videos found for @{username}")
            return None

        print(f"  [yt-dlp] Found {len(videos)} videos for @{username}")
        return videos

    except subprocess.TimeoutExpired:
        print(f"  [yt-dlp] Timeout for @{username}")
        return None
    except FileNotFoundError:
        print("  [yt-dlp] yt-dlp not installed. Install with: pip install yt-dlp")
        return None
    except Exception as e:
        print(f"  [yt-dlp] Exception for @{username}: {e}")
        return None

def process_ytdlp_data(username, videos_data, user_id=None):
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
        )

    upsert_account(
        username=username,
        display_name=display_name,
        followers=followers,
        user_id=user_id,
    )
    save_daily_snapshot(username, user_id=user_id)


def _scrape_one_account(username, user_id):
    """Scrape a single account (used by thread pool)."""
    videos_data = fetch_account_data_ytdlp(username)
    if videos_data:
        process_ytdlp_data(username, videos_data, user_id=user_id)
        print(f"  @{username}: {len(videos_data)} videos OK")
        return {"username": username, "status": "success", "videos": len(videos_data)}
    else:
        upsert_account(username=username, display_name=username, user_id=user_id)
        print(f"  @{username}: no data")
        return {"username": username, "status": "no_data", "videos": 0}


def scrape_all_accounts_for_user(user_id, on_start=None, on_done=None):
    """Scrape all accounts tracked by a specific user (parallel)."""
    accounts = get_all_accounts(user_id=user_id)
    print("=" * 60)
    print(f"TikTok Scraper - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Scraping {len(accounts)} accounts for user #{user_id} (parallel)")
    print("=" * 60)

    results = {}
    # Scrape up to 3 accounts in parallel
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_scrape_one_account_with_callback, acc['username'], user_id, on_start, on_done): acc['username']
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


def _scrape_one_account_with_callback(username, user_id, on_start=None, on_done=None):
    """Scrape a single account with progress callbacks."""
    if on_start:
        on_start(username)
    result = _scrape_one_account(username, user_id)
    if on_done:
        on_done(username, result["status"] == "success", result["videos"])
    return result

def scrape_single_account_for_user(username, user_id):
    """Scrape a single account for a specific user."""
    print(f"\nScraping @{username} for user #{user_id}...")
    videos_data = fetch_account_data_ytdlp(username)
    if videos_data:
        process_ytdlp_data(username, videos_data, user_id=user_id)
        return {"status": "success", "videos": len(videos_data)}
    else:
        upsert_account(username=username, display_name=username, user_id=user_id)
        return {"status": "no_data", "videos": 0}


if __name__ == "__main__":
    from database import init_db
    init_db()
    print("Use the web interface to manage and scrape accounts.")
