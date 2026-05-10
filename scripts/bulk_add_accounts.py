#!/usr/bin/env python3
"""
Bulk-add tracked accounts directly via database.add_tracked_account().

Bypasses /api/accounts/add (no HTTP, no OAuth session, no plan ceiling).
Idempotent: re-running on the same list won't duplicate (ON CONFLICT in
add_tracked_account upserts).

Does NOT auto-scrape — run `python daily_scrape.py` afterward, or trigger
the cron via:
  curl -H "Authorization: Bearer $CRON_SECRET" \\
       "${APP_URL:-https://app.trackinglab.online}/api/cron/scrape-tiktok-youtube"

Run:
    set -a && . ./.env.local && set +a    # load DATABASE_URL
    python3 scripts/bulk_add_accounts.py
"""
from __future__ import annotations

import os
import sys

# Make the project root importable when running from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import add_tracked_account, get_all_accounts


USER_ID = 3

# (username, platform). Platform must be one of: tiktok, instagram, youtube, linkedin.
# Username is normalized (lowercase, leading @ stripped) to match /api/accounts/add.
ACCOUNTS: list[tuple[str, str]] = [
    # ── TikTok ──────────────────────────────────────────────
    ('bricho92',           'tiktok'),
    ('camillelocatelli',   'tiktok'),
    ('noaprudence',        'tiktok'),
    ('maxdu7762',          'tiktok'),
    ('sam.lazard2',        'tiktok'),
    ('htrecelamalaa',      'tiktok'),
    ('larvflash93',        'tiktok'),
    ('mercinternetspam',   'tiktok'),
    ('merci.internet',     'tiktok'),
    ('lauterre',           'tiktok'),

    # ── Instagram ───────────────────────────────────────────
    ('brioche92ii',        'instagram'),
    ('noaprudence',        'instagram'),
    ('camillelocatellii',  'instagram'),
    ('merciinternet_',     'instagram'),
    ('tom.lothaire',       'instagram'),

    # ── YouTube ─────────────────────────────────────────────
    ('tomlothaire',        'youtube'),

    # ── LinkedIn ────────────────────────────────────────────
    ('tom-lothaire',       'linkedin'),
]


VALID_PLATFORMS = {"tiktok", "instagram", "youtube", "linkedin"}


def main() -> int:
    if not ACCOUNTS:
        sys.exit("ACCOUNTS list is empty — open this file and paste your 30 entries.")

    if not os.environ.get("DATABASE_URL"):
        sys.exit("DATABASE_URL not set. Run: set -a && . ./.env.local && set +a")

    existing = {(a["username"], a["platform"]) for a in get_all_accounts(user_id=USER_ID)}
    print(f"User {USER_ID} currently tracks {len(existing)} accounts.\n")

    added = skipped = errors = 0
    for raw_username, raw_platform in ACCOUNTS:
        username = raw_username.strip().lstrip("@").lower()
        platform = raw_platform.strip().lower()

        if not username:
            print(f"  SKIP  empty username")
            errors += 1
            continue
        if platform not in VALID_PLATFORMS:
            print(f"  SKIP  @{username}: invalid platform '{platform}'")
            errors += 1
            continue

        key = (username, platform)
        if key in existing:
            print(f"  ====  @{username} ({platform}) already tracked")
            skipped += 1
            continue

        try:
            add_tracked_account(USER_ID, username, platform)
            print(f"  +     @{username} ({platform})")
            added += 1
        except Exception as e:
            print(f"  FAIL  @{username} ({platform}): {e}")
            errors += 1

    print(f"\nDone — added: {added}, already-tracked: {skipped}, errors: {errors}")
    print(f"Run `python daily_scrape.py` to populate videos for the new accounts.")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
