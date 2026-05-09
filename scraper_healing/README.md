# scraper_healing

Self-healing layer for Tracking Lab's platform scrapers. Same architecture as
`monitor/` (Playwright self-healing for the dashboard), translated to your
existing API-based scrapers (TikTok, Instagram, YouTube, LinkedIn).

## Why this exists

Your real scrapers don't read DOM — they hit JSON endpoints (yt-dlp, RapidAPI,
Supabase Edge proxies). The bug pattern is the same as DOM scrapers though:

| DOM scraper bug | API scraper bug |
|---|---|
| Class name changed → selector fails | Endpoint shadow-blocked → returns nulls |
| Layout shifted → wrong cell scraped | API field renamed → JSON path returns None |
| Site uses A/B test → JS differs per run | Platform serves stripped data to bot UAs |
| Whole page replaced → recovery impossible | yt-dlp extractor outdated → throws |

So the **architecture** translates 1:1 — only the primitives change:

| Playwright pattern | API pattern |
|---|---|
| Selector chain (primary + fallbacks) | Endpoint chain (per-platform strategies) |
| `page.locator(sel).count()` | `response.status_code != 200` |
| Selector reliability score | Endpoint reliability score |
| AI selector recovery (label proximity) | JSON path recovery (alias walk) |
| DOM snapshot diff | Response shape diff |
| Cross-field validation | Same |

## Layout

```
scraper_healing/
├── __init__.py
├── core.py            # Logger, scoring, snapshot/diff, validation, get_path
├── healing.py         # Orchestrator: scrape(platform, username) entry point
├── recovery.py        # Alias-based JSON path recovery
├── registry.py        # STRATEGIES + SCHEMAS per platform
├── instagram.py       # 3 fetch strategies (web_profile_info preferred)
├── tiktok.py          # 2 fetch strategies (yt-dlp variants)
├── youtube.py         # 2 fetch strategies (flat / detail)
├── linkedin.py        # 1 fetch strategy (Supabase proxy)
├── cli.py             # python -m scraper_healing.cli instagram natgeo
└── data/
    ├── endpoint-stats.json  # auto-trained reliability stats (commit this)
    └── snapshots/           # last 10 raw responses per (platform, user)
```

## Usage

### One-shot

```bash
python -m scraper_healing.cli instagram natgeo
python -m scraper_healing.cli tiktok mrbeast
python -m scraper_healing.cli youtube mkbhd
python -m scraper_healing.cli linkedin tomlothaire

# Batch
python -m scraper_healing.cli batch instagram:natgeo tiktok:mrbeast youtube:mkbhd
```

### Programmatic

```python
import asyncio
from scraper_healing import healing

result = asyncio.run(healing.scrape("instagram", "natgeo"))
# { "platform": "instagram", "username": "natgeo",
#   "endpoint_used": "ig_web_profile_info",
#   "data": {"username": "natgeo", "followers": 274_788_643, ...},
#   "validation": {"ok": True, "errors": []},
#   "duration_ms": 842 }
```

### Batch with concurrency

```python
results = asyncio.run(
    healing.scrape_batch([
        ("instagram", "natgeo"),
        ("tiktok", "mrbeast"),
        ("youtube", "mkbhd"),
    ], concurrency=8)
)
```

## Integrating with `scraper_async.py`

Don't replace your existing fetchers — wrap them. In `scraper_async.py`,
import `healing.scrape` and route per-platform:

```python
async def fetch_with_healing(platform: str, username: str) -> dict | None:
    from scraper_healing import healing
    res = await healing.scrape(platform, username)
    if not res.get("validation", {}).get("ok"):
        # Healing layer flagged the result. Decide: persist anyway? skip?
        return None
    return res["data"]
```

This way you keep your existing yt-dlp / aiohttp / proxy infrastructure and
just add observability + retry/fallback/validation/recovery on top.

## Auto-training

`data/endpoint-stats.json` accumulates success/failure counts per
(platform, endpoint). Commit it from CI so learning persists. After enough
runs, the orchestrator naturally prioritizes the strategy with the highest
score — even before you manually re-order them.

For JSON paths: if a field's primary path fails but the recovery walker
finds an alias match, that path is stored under `learned_paths` and tried
first on the next run.

## Risk mitigation

| Risk | Mitigation |
|---|---|
| Single endpoint stops working | 2-3 strategies per platform, scored independently |
| API renames a field (`follower_count` → `followers`) | Static fallbacks + alias-walk recovery |
| Bot detection serves zeroed-out data | Cross-field validation + alert on shape drift |
| yt-dlp breaks after platform update | Score drops, healing falls back to other strategies |
| New platform added | Drop a new module + entry in registry, no orchestrator changes |
