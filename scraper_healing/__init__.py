"""scraper_healing — self-healing layer for Tracking Lab's platform scrapers.

Translates the Playwright self-healing pattern (selector registry + fallbacks +
scoring + AI-like recovery) to API-based scrapers. Platforms work via JSON
endpoints (yt-dlp, RapidAPI, Supabase Edge proxies) so 'selectors' here are
(endpoint, json_path) pairs.

Usage:
    from scraper_healing import healing
    result = await healing.scrape("instagram", "natgeo")
    # → {"username": "natgeo", "followers": 274_788_643, ...}

Integration:
    Wrap your existing fetch_*_async() inside the scrape() entry point —
    don't replace them. This module orchestrates retry/fallback/validation
    around them.
"""
from . import healing, registry, core  # noqa: F401
