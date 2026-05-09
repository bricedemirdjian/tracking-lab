"""Per-platform field registry. Each platform has:

  - A list of fetch strategies (named endpoints, in priority order). The
    healing layer ranks them by historical reliability score.
  - A schema mapping output field names to FieldSpec (path + fallbacks +
    type + aliases for AI recovery).

The fetch strategies are named — actual implementation lives in <platform>.py
modules and is wired in `healing.STRATEGIES` (see healing.py).
"""
from __future__ import annotations

from .core import FieldSpec

# ── Strategy catalogs (names only — implementations in <platform>.py) ──
STRATEGIES: dict[str, list[str]] = {
    "instagram": [
        "ig_web_profile_info",   # /users/web_profile_info/?username=… (preferred, full data)
        "ig_users_pk_info",      # /users/{pk}/info/ (often shadow-blocked)
        "ig_search_then_info",   # search → /users/{pk}/info/ (search blocked too lately)
    ],
    "tiktok": [
        "tt_ytdlp_default",      # yt-dlp on www.tiktok.com/@user
        "tt_ytdlp_alt_host",     # yt-dlp via api16-normal-c-useast1a (race against tikwm)
    ],
    "youtube": [
        "yt_ytdlp_flat",         # yt-dlp extract_flat (fast, lists vid IDs)
        "yt_ytdlp_video_detail", # per-video detail pass for likes/comments
    ],
    "linkedin": [
        "li_proxy_default",      # Supabase Edge proxy
    ],
}


# ── Schemas: same field names across platforms when meaningful, but ──
# ── each platform may have its own paths/aliases for that field. ────
INSTAGRAM_SCHEMA: dict[str, FieldSpec] = {
    "username": FieldSpec(path="username", type="string", required=True, aliases=["username"]),
    "full_name": FieldSpec(path="full_name", type="string", required=False, aliases=["full_name", "name"]),
    "followers": FieldSpec(
        path="followers",
        fallbacks=["data.user.edge_followed_by.count", "user.follower_count"],
        type="number",
        required=True,
        label="Followers IG",
        aliases=["follower_count", "edge_followed_by", "followers"],
    ),
    "following": FieldSpec(
        path="following",
        fallbacks=["data.user.edge_follow.count", "user.following_count"],
        type="number",
        required=False,
        aliases=["following_count", "edge_follow", "following"],
    ),
    "media_count": FieldSpec(
        path="media_count",
        fallbacks=["data.user.edge_owner_to_timeline_media.count", "user.media_count"],
        type="number",
        required=False,
        aliases=["media_count", "post_count", "edge_owner_to_timeline_media"],
    ),
    "biography": FieldSpec(path="biography", type="string", required=False, aliases=["biography", "bio"]),
    "profile_pic": FieldSpec(
        path="profile_pic",
        fallbacks=["data.user.profile_pic_url_hd", "data.user.profile_pic_url"],
        type="url",
        required=False,
        aliases=["profile_pic", "profile_pic_url", "hd_profile_pic_url"],
    ),
    "videos": FieldSpec(path="videos", type="string", required=False),  # list, validated separately
}


TIKTOK_SCHEMA: dict[str, FieldSpec] = {
    "username": FieldSpec(path="username", type="string", required=True),
    # TikTok comes back as a list of video dicts via yt-dlp; followers live on
    # each entry's `channel_follower_count` (yt-dlp >= 2024.10) or `uploader_url`.
    "followers": FieldSpec(
        path="[0].channel_follower_count",
        fallbacks=["[0].uploader_follower_count", "[0].channel.follower_count"],
        type="number",
        required=False,
        aliases=["follower_count", "channel_follower_count", "subscribers"],
    ),
    "videos_count": FieldSpec(path="__videos_count__", type="number", required=True),  # computed
}


YOUTUBE_SCHEMA: dict[str, FieldSpec] = {
    "username": FieldSpec(path="username", type="string", required=True),
    "subscribers": FieldSpec(
        path="[0].channel_follower_count",
        fallbacks=["[0].subscriber_count"],
        type="number",
        required=False,
        aliases=["channel_follower_count", "subscriber_count", "subscribers"],
    ),
    "videos_count": FieldSpec(path="__videos_count__", type="number", required=True),
}


LINKEDIN_SCHEMA: dict[str, FieldSpec] = {
    "username": FieldSpec(path="username", type="string", required=True),
    "full_name": FieldSpec(path="full_name", type="string", required=False),
    "followers": FieldSpec(
        path="followers",
        type="number",
        required=False,
        aliases=["follower_count", "followers"],
    ),
    "headline": FieldSpec(path="headline", type="string", required=False, aliases=["headline", "title"]),
    "profile_pic": FieldSpec(path="profile_pic", type="url", required=False, aliases=["profile_pic", "image"]),
    "posts_count": FieldSpec(path="__posts_count__", type="number", required=True),  # computed
}


SCHEMAS: dict[str, dict[str, FieldSpec]] = {
    "instagram": INSTAGRAM_SCHEMA,
    "tiktok": TIKTOK_SCHEMA,
    "youtube": YOUTUBE_SCHEMA,
    "linkedin": LINKEDIN_SCHEMA,
}
