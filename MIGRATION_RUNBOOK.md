# Migration: app.trackinglab.online → trackinglab.online (single domain)

**Goal:** All user-facing URLs live under `trackinglab.online`. Marketing landing on `/`, authenticated SaaS app on `/dashboard`, `/account`, `/billing`, `/admin`, `/api/*`, `/auth/*`, `/login`, `/logout`, `/webhook/*`, `/healthz`. The `app.trackinglab.online` subdomain becomes a transitional alias and eventually 301-redirects to the apex.

**Why:** Single domain = single cookie scope = Stripe receipts that look professional, OAuth flows that don't bounce subdomains, fewer DNS/cert moving parts, cleaner brand for paying customers.

**Architecture after migration:**
- `trackinglab.online` → Vercel project `tracking-lab-v2` (Next.js landing) acting as reverse-proxy. Marketing routes (`/`, `/sitemap.xml`, `/robots.txt`) served by Next; everything else proxied to Flask via `next.config.js` `beforeFiles` rewrites.
- `tracking-lab` Vercel project (Flask) keeps `app.trackinglab.online` as a hidden internal domain that Next.js calls server-to-server. Customers never see it.

---

## Code changes already shipped (this commit)

- `.github/workflows/scrape-cron.yml` — both cron triggers read `${{ vars.APP_URL || 'https://app.trackinglab.online' }}`. Defaults preserved, flip via repo variable.
- `.github/workflows/keep-warm.yml` — same `APP_URL` env pattern.
- `monitor/.github/workflows/scraper.yml` — `TARGET_URL` reads `vars.APP_URL`.
- `monitor/README.md`, `monitor/package.json`, `scripts/bulk_add_accounts.py`, `CLAUDE.md` — text references updated.
- `v2/landing/next.config.js` — `beforeFiles` rewrites added for every authenticated path → Flask backend (env-overridable via `FLASK_BACKEND_URL`).

**Nothing in `app.py` / `auth.py` needs to change.** Flask uses `request.host_url` for OAuth callback URL (`auth.py:100`) and Stripe success/cancel URLs (`app.py:367, 389`), so it self-adapts to whatever domain the request arrived on.

---

## User-side UI steps (in order — each one is a hard checkpoint)

### 1. Deploy the v2 landing with new rewrites (BLOCKER for everything else)

The `v2/landing/next.config.js` change must reach prod before users will see any of the new routing.

```bash
cd "/Users/briique/Desktop/CLAUDE CODE/TRACKING LAB/v2/landing"
vercel --prod --yes
```

Or, if you've fixed the GitHub→Vercel auto-deploy (see "Permanent fix" in the project memory): a `git push` will do it.

**Verify:** `curl -sI https://trackinglab.online/healthz` should return `200 OK` (proxied through Next → Flask). Before this step, `/healthz` returns the Next 404. If you see the 404 you got it wrong — check the rewrite block in `next.config.js`.

### 2. Add the new OAuth callback URL in Google Cloud Console

The Flask `auth_callback` route uses `url_for(..., _external=True)` which derives the redirect URI from `request.host_url`. When users start the OAuth flow on `trackinglab.online`, Google must accept `https://trackinglab.online/auth/callback` as a valid redirect URI.

- Open https://console.cloud.google.com/apis/credentials
- Pick the OAuth 2.0 Client ID for Tracking Lab
- "Authorized redirect URIs" → ADD `https://trackinglab.online/auth/callback`
- KEEP the existing `https://app.trackinglab.online/auth/callback` (transitional safety net)
- Save

**Verify:** open `https://trackinglab.online/login` in an incognito window, click "Continue with Google". The Google consent screen should NOT show the "this app's request is invalid" error. If it does, the redirect URI hasn't propagated yet (can take up to 5 min), or you typed it wrong.

### 3. Update the Stripe webhook URL

Stripe POSTs subscription events to a fixed URL. Currently set to `app.trackinglab.online/webhook/stripe`. After migration we want events on the apex.

- Open https://dashboard.stripe.com/webhooks
- Pick the Tracking Lab endpoint
- "Endpoint URL" → change to `https://trackinglab.online/webhook/stripe`
- Save (Stripe re-issues a signing secret if you click "Roll signing secret" — DO NOT roll, keep current secret so existing `STRIPE_WEBHOOK_SECRET` env var keeps working)

**Verify:** in Stripe dashboard → Webhooks → click the endpoint → "Send test webhook" → choose `customer.subscription.updated` → send. Within 10s a green check should appear in the dashboard event log. If red, check Vercel function logs of the `tracking-lab` project for the inbound POST.

### 4. Flip the GitHub Actions to hit the new domain

Once steps 1-3 work end-to-end on `trackinglab.online`, update the cron + keep-warm workflows to use the apex:

- GitHub repo `bricedemirdjian/tracking-lab` → Settings → Secrets and variables → Actions → "Variables" tab → "New repository variable"
- Name: `APP_URL`
- Value: `https://trackinglab.online`
- Save

The next workflow run will pick it up. The fallback in the YAML keeps `app.trackinglab.online` working if the variable is unset, so this step is reversible.

**Verify:** trigger the workflow manually (Actions → "Hourly Scrape Cron" → "Run workflow") and check the log shows `https://trackinglab.online/api/cron/...` in the curl output.

### 5. (Optional, after steady state) 301-redirect app.* to apex

Once you've watched `trackinglab.online` for a week without auth/billing regressions, retire the `app.*` subdomain:

**Option A — Vercel domain config (no code change):**
- Vercel dashboard → `tracking-lab` project → Settings → Domains → `app.trackinglab.online` → "Redirect to" → `trackinglab.online` → 301

**Option B — Flask middleware (more control):** add to `app.py` `_security_headers()`:
```python
if request.host == 'app.trackinglab.online' and not request.path.startswith('/webhook/'):
    return redirect(f'https://trackinglab.online{request.full_path}', code=301)
```
(Keep `/webhook/` accessible directly so any Stripe webhook still pinned to the old URL during a window keeps delivering.)

**Verify:** `curl -sI https://app.trackinglab.online/dashboard` returns `301` and `Location: https://trackinglab.online/dashboard`.

---

## Rollback plan

If anything breaks at any step:

- **Step 1 broken** (rewrites bad): redeploy the previous v2 landing build via Vercel dashboard → `tracking-lab-v2` project → Deployments → previous successful one → "..." → "Promote to Production"
- **Step 2 broken** (OAuth): revert nothing — adding a redirect URI is purely additive. Just remove the new one from Google Console.
- **Step 3 broken** (Stripe): change the webhook URL back to `app.trackinglab.online/webhook/stripe`.
- **Step 4 broken** (cron): delete the `APP_URL` repo variable. Workflows fall back to the hardcoded default.
- **Step 5 broken** (redirect): remove the redirect rule from Vercel or revert the app.py middleware patch.

---

## What CANNOT be done from CLI / code

- Vercel custom domain reconfiguration → user UI step
- Google Cloud Console OAuth changes → user UI step
- Stripe dashboard webhook URL → user UI step
- GitHub repo Variables → user UI step

These are all 2-3 minute clicks per platform. Total user time end-to-end: ~30 minutes including verification curls.

---

## Open question: GitHub→Vercel auto-deploy on tracking-lab-v2

Per `project_two_vercel_projects.md`, the v2 Vercel project has `link: NONE` — no Git connection. Step 1 above requires manual `vercel --prod` from the v2 directory. Until you connect the project to its GitHub repo (Vercel dashboard → Settings → Git → Connect Repository), every landing change requires the manual CLI deploy. Fix that hookup at any time; it's independent of the migration.
