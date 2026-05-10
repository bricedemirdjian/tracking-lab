# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Parent CLAUDE.md disambiguation

A `CLAUDE.md` in `/Users/briique/Desktop/CLAUDE CODE/` describes the **ConvAnalyzer** project and warns "Autre projet à NE JAMAIS toucher : `tracking-lab`." That warning is from ConvAnalyzer's perspective — **this directory IS Tracking Lab**, so when working here, ignore that warning. Do not apply ConvAnalyzer's Supabase rules (schema `convanalyzer`, project ref `rltnjcetrfohvrxefzyy`, RLS policies) to this project. Tracking Lab is a separate Supabase project accessed via `DATABASE_URL` — no shared tables, no RLS pattern, no `current_user_in_app()` requirement.

## Project

**Tracking Lab** — Flask web app that scrapes public TikTok / YouTube / Instagram / LinkedIn account stats and surfaces them in a dashboard. Production: `trackinglab.online` (target single domain post-migration; currently transitioning from `app.trackinglab.online`). Both run on Vercel; landing on `tracking-lab-v2` (Next.js), Flask app on `tracking-lab` project. See `MIGRATION_RUNBOOK.md` for the cutover plan.

## Common commands

```bash
# Local dev (creates venv, installs deps, runs database.init_db() once)
./setup.sh
./start.sh                       # starts Flask on http://localhost:5555

# Run app directly (after venv activated)
python3 app.py

# Self-healing scraper one-shot (per-platform debug)
python -m scraper_healing.cli instagram natgeo
python -m scraper_healing.cli tiktok mrbeast
python -m scraper_healing.cli batch instagram:natgeo tiktok:mrbeast

# Trigger cron locally (requires CRON_SECRET env var)
curl -H "Authorization: Bearer $CRON_SECRET" \
     http://localhost:5555/api/cron/scrape-instagram

# Deploy
vercel --prod                    # production deploy

# UI monitor (separate Node/Playwright project under monitor/)
cd monitor && npm install && npx playwright install --with-deps chromium
npm run auth:save                # one-time Google login
npm run scrape                   # single run
```

There is **no test suite** in this repo. Don't fabricate one — if you need to verify behavior, run the app and exercise endpoints manually, or use the `scraper_healing.cli` for scraper changes.

## Architecture

### Top-level layout

- `app.py` — single-file Flask app (~1200 lines). All HTTP routes live here: pages, `/api/*` JSON, `/api/admin/*`, `/api/cron/*`, `/api/billing/*`, `/webhook/stripe`, `/healthz`. Initializes the DB and auth at import time.
- `database.py` — **dual-backend** data layer. If `DATABASE_URL` is set, uses `psycopg2` against Postgres (Supabase). Otherwise SQLite at `tiktok_tracking.db` (or `/tmp/...` on Vercel — ephemeral). Internal helpers `_q`, `_cur`, `_fetchone`, `_fetchall` paper over the dialect; **always write SQL with `%s` placeholders** — `_q()` rewrites them to `?` for SQLite. `init_db()` runs idempotent CREATE TABLE + a chain of `_migrate_*` helpers on every boot.
- `auth.py` — Google OAuth via `authlib`, Flask-Login session. The `User` class has a `data_user_id` property: **managers see the admin's data (user_id=1)** instead of their own — keep this in mind whenever filtering by user.
- `scraper_async.py` — asyncio + aiohttp scraping engine (the real one). `tiktok_scraper.py` is a thin sync facade preserved for legacy callers (`daily_scrape.py`, `app.py`).
- `analytics.py` — pure read-only computations over the DB (hashtag stats, virality, trends, growth, top content, insights).
- `stripe_billing.py` — `PLANS` dict (starter / pro / agency) + checkout/portal session helpers. Plan limits (`max_accounts`, `max_videos`, `max_projects`, platform allowlist, feature flags) are enforced inline in `app.py` routes.
- `emailer.py` — Resend transactional emails. No-ops silently if `RESEND_API_KEY` is unset.
- `api/index.py` — Vercel entrypoint. Sets `VERCEL=1`, adds parent dir to `sys.path`, imports `app` from `app.py`. Vercel routes everything to this function (see `vercel.json`).

### Templates / static

- `templates/` — Jinja: `landing.html`, `dashboard.html`, `admin.html`, `swarm.html` (admin ops), `billing.html`, `login.html`, `blocked.html`.
- `public/` — Vercel-served static (`public/css/`, `public/js/`). `vercel.json` rewrites `/static/css/*` → `/public/css/*` so Flask's `url_for('static', ...)` URLs keep working in production.
- `static/` — Flask's local static dir (used in dev). Keep both in sync if shipping new CSS/JS.

### Scraping pipeline

1. **`scraper_async.py`** owns the actual fetchers (`fetch_instagram_async`, `fetch_tiktok_async`, etc.). TikTok races 4 internal API hostnames in parallel — first one wins. Instagram and LinkedIn go through Supabase Edge functions at `vpirlefqxnvmxbmndhmn.supabase.co/functions/v1` (proxy is auth'd by `SCRAPER_PROXY_SECRET`). YouTube uses yt-dlp.
2. **`scraper_healing/`** is an *optional* self-healing layer that wraps the fetchers: strategy registry per platform, reliability scoring (`data/endpoint-stats.json`), response snapshots, alias-walk recovery for renamed JSON fields, schema validation. Entry point: `await scraper_healing.healing.scrape(platform, username)`. **Don't replace `scraper_async.py` with this** — wrap call sites one at a time.
3. **`scraper_healing/swarm/`** — a multi-agent observability layer (orchestrator + adversary + scoring + evolution) that drives the `/admin/swarm` dashboard. Read by `app.py` lazily — failures here must not break startup.

### Cron / scheduled scrapes

Two trigger sources, both hit the same endpoints:

- **Vercel crons** (`vercel.json`): `/api/cron/scrape-tiktok-youtube` daily 06:00 UTC, `/api/cron/scrape-instagram` daily 12:30 UTC. Hobby plan limit = 2 daily crons total.
- **GitHub Actions** (`.github/workflows/scrape-cron.yml`): every 2-3 hours, hits `https://app.trackinglab.online/api/cron/*`. Loops with up to 3 passes per call to handle Vercel's 60s function timeout — endpoints stamp `"_timeout":true` in the response when they bail early so the next pass picks up the staleest accounts. **All cron endpoints require** `Authorization: Bearer $CRON_SECRET`.

### Production / config

- **Vercel function budget = 60s.** Long scrapes deliberately exit early and rely on the multi-pass cron loop. If you add a slow code path, make sure it can resume mid-work.
- `IS_PRODUCTION` is true when any of `RENDER`, `PRODUCTION`, `VERCEL` env vars are set. In prod, `SECRET_KEY`, `CRON_SECRET`, and `STRIPE_WEBHOOK_SECRET` must be present or startup raises.
- `ProxyFix(x_for=1)` is applied in production so `request.remote_addr` is the real client IP (Flask-Limiter relies on it).
- Security headers (`X-Content-Type-Options`, `Referrer-Policy`, HSTS, etc.) are set globally in `_security_headers()`. CSP currently allows inline scripts because the templates use them — note this if you tighten CSP.
- Rate limiting via Flask-Limiter (in-memory, single-instance only — swap `storage_uri` for Redis if scaling horizontally).

### Data model conventions

- All tables that hold user-scoped data have a `user_id` column referencing `users.id`. **Filter every query by `current_user.data_user_id`** (not `.id`) so the manager-sees-admin-data behavior holds.
- `accounts` rows are keyed by `(user_id, username, platform)`.
- Plan enforcement happens at the route layer via `_current_plan()` + inline checks against `PLANS[...]['max_*']`. There is no DB-side enforcement.

## Hard rules

- ❌ Don't add a real `tests/` directory or import a test framework "to be safe" — there's no CI for it. The user runs scrapers via `scraper_healing.cli` and dogfoods the UI.
- ❌ Don't introduce a third DB dialect or an ORM. The `_q()`/`_cur()` shim is intentional; replacing it is a much bigger change than it looks.
- ❌ Don't push to `main` or run `vercel --prod` unless explicitly asked. Deploys are user-triggered.
- ❌ Don't touch `v2/` from this repo — it's a separate project with its own git history (gitignored).
- ✅ Write SQL with `%s` placeholders, not `?`. `_q()` rewrites for SQLite; the reverse doesn't work.
- ✅ When adding a new column, also add a `_migrate_*` helper called from `migrate_db()` so existing prod DBs upgrade on next boot.
- ✅ When adding a `/api/cron/*` route, it MUST start with `_cron_auth_check()` and respect the 60s budget (return early with `"_timeout": true` and let the next pass continue).
- ✅ Keep the `data/endpoint-stats.json` files (under `scraper_healing/data/` and `monitor/data/`) committed — they're the persisted learning state.
