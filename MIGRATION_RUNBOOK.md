# Migration: app.trackinglab.online → trackinglab.online (single domain)

**Status:** ✅ Complete (2026-05-12). Canonical domain is now `trackinglab.online` (apex, no `www.`). `www.*` and `app.*` both 308-redirect to it. This document is preserved as the post-mortem + rollback reference.

**Why we did it:** Single domain = single cookie scope = Stripe receipts that look professional, OAuth flows that don't bounce subdomains, fewer DNS/cert moving parts, cleaner brand for paying customers.

---

## Final architecture

```
                        ┌─────────────────────────────────────┐
  user                  │   trackinglab.online (CANONICAL)   │
   │                    │   Vercel project: tracking-lab-v2  │
   ▼                    │   Framework: Next.js                │
 trackinglab.online ───▶│                                     │
                        │   /              → Next landing     │
                        │   /sitemap.xml   → Next             │
                        │   /robots.txt    → Next             │
                        │   /opengraph-img → Next             │
                        │                                     │
                        │   /dashboard, /account, /billing,  │
                        │   /admin/*, /auth/*, /api/*,        │
                        │   /webhook/*, /login, /login/*,     │
                        │   /logout, /healthz                 │
                        │     │                               │
                        │     │ beforeFiles rewrites          │
                        │     ▼                               │
                        │   https://tracking-lab-nine.vercel.app  ──▶  Flask
                        └─────────────────────────────────────┘

  www.trackinglab.online ──308──▶ trackinglab.online      (Vercel domain redirect)
  app.trackinglab.online ──308──▶ trackinglab.online      (Flask WSGI middleware)
                                  EXCEPT /webhook/* and /api/cron/* — those keep
                                  serving directly on app.* as a safety net for
                                  any legacy client still pointed there.
```

**Two Vercel projects, two GitHub repos:**
- `tracking-lab-v2` (Next.js landing, bricedemirdjian/tracking-lab-v2) owns `trackinglab.online` + `www.trackinglab.online`. Acts as reverse-proxy for everything except `/`, sitemap, robots, opengraph.
- `tracking-lab` (Flask SaaS, bricedemirdjian/tracking-lab — this repo) owns `app.trackinglab.online` + the internal alias `tracking-lab-nine.vercel.app`. Customers never see either.

**Flask code that makes the migration work:**
- `app.py` `CanonicalHostMiddleware` (WSGI level, NOT `@app.before_request` — Werkzeug `cached_property` traps overrides if run after the request object is built).
  - Reads `CANONICAL_HOST` env var → rewrites `HTTP_HOST` for outbound URLs (OAuth `redirect_uri`, Stripe success URLs, flask-login `next=`, anything built via `url_for(_external=True)` or `request.host_url`).
  - Reads `LEGACY_HOSTS` env var (comma-separated) → 308-redirects requests whose original `Host` is in that list, EXCEPT `/webhook/*` and `/api/cron/*` paths.
- `auth.py` and `app.py` Stripe handlers are unchanged: they use `request.host_url` and `url_for(_external=True)` which now correctly resolve to apex thanks to the middleware.

**Required env vars on the `tracking-lab` Vercel project (Production):**
- `CANONICAL_HOST=trackinglab.online`
- `LEGACY_HOSTS=app.trackinglab.online,www.trackinglab.online`

**Required env var on the `tracking-lab` GitHub repo (Actions Variables):**
- `APP_URL=https://trackinglab.online`

---

## What got shipped, in order (commits on `bricedemirdjian/tracking-lab` main unless noted)

| # | Date | Commit | What |
|---|---|---|---|
| 1 | 2026-05-10 | `830e2c4` | Parameterize GH Actions `APP_URL`, monitor `TARGET_URL`, doc updates |
| 2 | 2026-05-10 | `aa8efae` *(v2 repo)* | `v2/landing/next.config.js` `beforeFiles` rewrites for proxied paths |
| 3 | 2026-05-10 | `97280c4` *(v2)* | Fix `:path*` empty-match bug — switched to `:path+` |
| 4 | 2026-05-10 | `ded961e` | First `CANONICAL_HOST` middleware (broken — `@app.before_request` hit Werkzeug cached_property issue) |
| 5 | 2026-05-10 | `5d5ae36` | Temp `/__debug/host` endpoint to verify what Flask sees |
| 6 | 2026-05-10 | `fd6577d` | `CanonicalHostMiddleware` rewritten at WSGI level (the actual fix) |
| 7 | 2026-05-11 | `057c3ff` | Remove `/__debug/host` after verification |
| 8 | 2026-05-11 | `552a71f` *(v2)* | Add `/login/:path+` to rewrites (OAuth init was 404) |
| 9 | 2026-05-11 | `2dd29fd` *(v2)* | Swap proxy backend `app.trackinglab.online` → `tracking-lab-nine.vercel.app` so the 308 doesn't loop |
| 10 | 2026-05-11 | `e23eaa8` | `LEGACY_HOSTS` 308-redirect middleware (excludes `/webhook/*` and `/api/cron/*`) |
| 11 | 2026-05-12 | (env var only) | `CANONICAL_HOST=trackinglab.online`, `LEGACY_HOSTS=app.trackinglab.online,www.trackinglab.online` |

---

## User-side UI steps that were performed (kept here for rollback / re-do)

### Vercel `tracking-lab-v2` project
- Domain `www.trackinglab.online` configured to **308 Permanent Redirect → trackinglab.online**

### Vercel `tracking-lab` project (Flask)
- Env var **`CANONICAL_HOST=trackinglab.online`** (Production)
- Env var **`LEGACY_HOSTS=app.trackinglab.online,www.trackinglab.online`** (Production)
- Domain `app.trackinglab.online` kept as `Connect to environment: Production` (Flask middleware handles the redirect, not Vercel — needed because Vercel UI can only redirect to domains on the SAME project, and the target domain lives on the other project)

### Google Cloud Console — OAuth 2.0 Client
- Authorized redirect URIs (in order; keep all five during the transition):
  1. `https://tracking-lab.onrender.com/auth/callback` *(legacy Render — can be removed)*
  2. `https://tracking-lab-nine.vercel.app/auth/callback` *(legacy direct — can be removed)*
  3. `https://app.trackinglab.online/auth/callback` *(legacy, keep ~1 week)*
  4. `https://trackinglab.online/auth/callback` ✅ **(canonical, used by Flask redirect_uri now)**
  5. `https://www.trackinglab.online/auth/callback` *(transitional, keep ~1 week)*

### Stripe dashboard — Webhooks
- Endpoint URL: `https://trackinglab.online/webhook/stripe`
- Signing secret: **unchanged** (the `STRIPE_WEBHOOK_SECRET` env var on Vercel still works)

### GitHub repo `bricedemirdjian/tracking-lab` — Actions Variables
- `APP_URL=https://trackinglab.online`

---

## Verification commands (re-run anytime to confirm health)

```bash
# 1. Apex serves Next landing
curl -sI https://trackinglab.online/ | head -1
# → HTTP/2 200

# 2. www. 308-redirects to apex
curl -sI https://www.trackinglab.online/ | grep -i "^location"
# → location: https://trackinglab.online/

# 3. app. 308-redirects to apex (browser paths)
curl -sI https://app.trackinglab.online/dashboard | grep -i "^location"
# → location: https://trackinglab.online/dashboard

# 4. Stripe webhook still lands on Flask via apex
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST https://trackinglab.online/webhook/stripe \
  -H "Content-Type: application/json" -d '{}'
# → HTTP 400  (signature missing, but Flask received it = good)

# 5. Stripe webhook safety net on app. (excluded from 308)
curl -s -o /dev/null -w "HTTP %{http_code}\n" -X POST https://app.trackinglab.online/webhook/stripe \
  -H "Content-Type: application/json" -d '{}'
# → HTTP 400  (still served directly, not redirected)

# 6. Cron endpoint safety net on app. (excluded from 308)
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://app.trackinglab.online/api/cron/scrape-instagram
# → HTTP 401  (auth missing, but Flask received it = good)

# 7. OAuth init builds the canonical redirect_uri
curl -sI https://trackinglab.online/login/google | grep -i "^location:" | \
  grep -oE "redirect_uri=[^&]+" | sed 's/redirect_uri=//' | \
  python3 -c "import sys, urllib.parse; print(urllib.parse.unquote(sys.stdin.read().strip()))"
# → https://trackinglab.online/auth/callback

# 8. flask-login next= param uses canonical
curl -sI https://trackinglab.online/account | grep -i "^location"
# → location: /login?next=https://trackinglab.online/account

# 9. Flask build version (proves which deploy is live)
curl -sI https://trackinglab.online/healthz | grep -i "x-build-version"
```

---

## Rollback playbook (per step, in case any future change breaks something)

- **Apex broken (Next landing 5xx):** Vercel dashboard → `tracking-lab-v2` project → Deployments → previous successful one → "..." → "Promote to Production".
- **Proxy rewrites broken (e.g. `/dashboard` 404 again):** revert `v2/landing/next.config.js` and `vercel --prod` from `v2/landing/`. Verify the FLASK_BACKEND points to `https://tracking-lab-nine.vercel.app` (NOT `app.trackinglab.online`, otherwise it loops with the WSGI 308).
- **OAuth fails ("redirect_uri mismatch"):** check Google Cloud Console has `https://trackinglab.online/auth/callback` in the authorized redirect URIs. If not, add it; takes ~5 min to propagate.
- **Stripe webhooks silently failing:** Stripe dashboard → Webhooks → click the endpoint → check the recent deliveries log. Common causes: webhook URL still pointing at `www.` or `app.` (look at the endpoint config), or signing secret rotated when it shouldn't have been (compare `STRIPE_WEBHOOK_SECRET` on Vercel).
- **Cron failing 308 instead of 200:** check GH repo Actions Variables has `APP_URL=https://trackinglab.online`. If the var is missing, workflows fall back to `https://app.trackinglab.online` which still works (the cron paths are in the LEGACY_HOSTS exclusion list).
- **All of Flask 500-ing:** check Vercel env vars on `tracking-lab` project — `CANONICAL_HOST` and `LEGACY_HOSTS` must be set. If missing, the middleware no-ops cleanly so this would only manifest as the OLD bug (URLs leaking `app.trackinglab.online`), not a 500. A 500 storm suggests a different cause.
- **Direct `app.*` access broken (browser shows redirect loop):** the LEGACY_HOSTS middleware excludes `/webhook/*` and `/api/cron/*` but redirects everything else. A loop would only occur if `app.trackinglab.online` is also in the proxy chain — verify `v2/landing/next.config.js` uses `tracking-lab-nine.vercel.app`, NOT `app.trackinglab.online`.

---

## Known gotchas discovered during this migration (preserved for future migrations)

1. **Werkzeug's `request.host` is a `cached_property`.** If you try to rewrite `HTTP_HOST` via `@app.before_request`, by the time your hook fires, some upstream hook (login_manager, CSRF, etc.) has already read `request.host`, locked the cached value, and your override has no effect. The fix is to run the rewrite at the WSGI layer, before Flask constructs the request object. See `CanonicalHostMiddleware` in `app.py`.

2. **Vercel restamps `X-Forwarded-Host` when proxying server-to-server.** The Next.js rewrites in `v2/landing/next.config.js` fetch the Flask backend over HTTP. When that internal request lands at Flask via the Vercel runtime, the X-Forwarded-Host header is set to the destination domain (`tracking-lab-nine.vercel.app`), not the original user-facing domain. That's why `ProxyFix(x_host=1)` alone isn't enough — we need `CANONICAL_HOST` to be a static config, not derived from request headers.

3. **`_execute()` in `database.py` does NOT auto-commit.** All write helpers must explicitly call `conn.commit()` afterwards. Missed this in the YouTube cache-hit refresher and the UPDATE silently rolled back. Pattern to follow: see `_refresh_tiktok_stats_only` in `scraper_async.py`.

4. **`vercel env ls` always reports `Encrypted` regardless of the Sensitive flag.** Can't verify a value via CLI. To verify, either recreate the env var via the UI with Sensitive OFF (the dashboard then shows plaintext), or deploy a temp `/__debug` endpoint that echoes `os.environ.get('VAR_NAME')`. We used the latter — invaluable for catching the cached_property bug.

5. **Next.js rewrite `:path*` matches empty.** A rewrite like `{ source: '/dashboard/:path*', destination: '$BACKEND/dashboard/:path*' }` ALSO matches `/dashboard` itself (with empty `:path*`) and proxies to `/dashboard/` (trailing slash). Flask's strict routing 404s on the trailing slash. Use `:path+` (one-or-more) when you want a true sub-path catch-all without empty match.

6. **Vercel UI's "Redirect to Another Domain" only lists domains on the SAME project.** Can't redirect `app.trackinglab.online` (on `tracking-lab` project) to `trackinglab.online` (on `tracking-lab-v2` project) via the UI. Workaround: do the redirect in Flask middleware via `LEGACY_HOSTS`, OR `vercel.json` `redirects` array with a `has: host` condition.

7. **`v2/landing/next.config.js` must NOT proxy to `app.trackinglab.online` once the 308 is live.** Doing so would cause infinite redirect loops on every proxied request. Use the Vercel-internal alias `tracking-lab-nine.vercel.app` instead — it's bound to the same Flask project but is exempt from the LEGACY_HOSTS redirect.

---

## Optional follow-ups (when steady state is reached, ~7 days post-migration)

- Remove the legacy redirect URIs from Google Cloud Console: `https://app.trackinglab.online/auth/callback`, `https://www.trackinglab.online/auth/callback`, `https://tracking-lab-nine.vercel.app/auth/callback`, `https://tracking-lab.onrender.com/auth/callback`. Keep only `https://trackinglab.online/auth/callback`.
- Decommission `app.trackinglab.online` entirely (remove domain from Vercel `tracking-lab` project Settings → Domains). At that point the LEGACY_HOSTS exclusion logic for `/webhook/*` and `/api/cron/*` is no longer load-bearing and can be simplified.
- Move the cron triggers off Vercel (per scaling-constraints memory: Vercel Hobby is non-commercial; eventually move scrape jobs to Supabase Edge Functions or a dedicated worker).
