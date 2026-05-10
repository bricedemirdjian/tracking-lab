# /account Hub Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a standalone `/account` page that consolidates profile, plan/usage, links to Facturation/Admin/Swarm, and logout — replacing the 3-item Compte sidebar section with a single "Mon compte" item.

**Architecture:** New Flask route `/account` (login_required) renders a new `templates/account.html` standalone page. Sidebar in `dashboard.html` collapses the Compte section to one link. `.sb-bottom` Déconnexion stays as the always-available emergency logout. No new dependencies, no new database columns (`users.created_at` already exists).

**Tech Stack:** Flask, Jinja2, vanilla CSS (inline in template), psycopg2 via existing `_fetchone` helper, existing `get_user_plan()` and `PLANS` dict from `stripe_billing.py`.

**Project conventions to respect (from CLAUDE.md):**
- ❌ No test suite — manual verification via curl + browser is the test. Steps below substitute "verify in browser/curl" for "run pytest".
- ✅ SQL uses `%s` placeholders (rewritten by `_q()` for SQLite)
- ✅ Filter all user-scoped queries by `current_user.data_user_id` (manager-sees-admin pattern)

---

## File Structure

| Action | File | Responsibility |
|---|---|---|
| Create | `templates/account.html` | Self-contained Mon Compte page (HTML + inline CSS) |
| Modify | `app.py` (after `/billing` route, ~line 322) | Add `/account` route handler |
| Modify | `templates/dashboard.html` (sidebar lines 1666-1683) | Replace Compte section with single sb-item link |

Three files, three responsibilities. No shared partials needed (no other template has the sidebar).

---

## Task 1: Add the `/account` Flask route

**Files:**
- Modify: `app.py` — insert new route after `/billing` (currently at line 314)

- [ ] **Step 1: Verify the existing `/billing` route to mirror its pattern**

Run: `grep -n "@app.route(\"/billing\")" app.py`
Expected output: `314:@app.route("/billing")`

Read lines 314-322 of `app.py` so you know exactly what handler shape to mirror.

- [ ] **Step 2: Add the new route handler immediately after `/billing`**

Insert this block in `app.py` right after the closing of the `/billing` handler (around line 322, before `@app.route("/api/billing/checkout", methods=["POST"])`):

```python
@app.route("/account")
@login_required
def account():
    """Mon Compte hub: profile, plan/usage, links to Facturation/Admin/Swarm, logout."""
    from database import get_connection, _fetchone
    plan_name = get_user_plan(current_user.data_user_id)
    plan_meta = PLANS.get(plan_name, PLANS['starter'])
    uid = current_user.data_user_id
    with get_connection() as conn:
        accounts_count = (_fetchone(conn,
            "SELECT COUNT(*) AS cnt FROM accounts WHERE user_id = %s", (uid,)
        ) or {}).get('cnt', 0)
        projects_count = (_fetchone(conn,
            "SELECT COUNT(*) AS cnt FROM projects WHERE user_id = %s", (uid,)
        ) or {}).get('cnt', 0)
        videos_count = (_fetchone(conn,
            "SELECT COUNT(*) AS cnt FROM videos WHERE user_id = %s", (uid,)
        ) or {}).get('cnt', 0)
    usage = {
        "accounts_count": accounts_count,
        "projects_count": projects_count,
        "videos_count": videos_count,
    }
    return render_template(
        "account.html",
        user=current_user,
        plan_name=plan_name,
        plan_meta=plan_meta,
        usage=usage,
    )
```

Notes for the implementer:
- `from database import get_connection, _fetchone` is already used inside other handlers (see line 154, 422, 538) — the local import pattern is intentional in this codebase.
- `_fetchone` returns a dict-like row (psycopg2 RealDictRow or sqlite Row depending on backend). Both support `.get()` after dict() conversion, but to stay safe across both backends, the `(_fetchone(...) or {}).get('cnt', 0)` pattern handles None rows.
- If the `videos` table column for ownership is named differently (e.g. derived via JOIN through `accounts`), this query will silently return 0 or fail. Verify in Step 3.

- [ ] **Step 3: Verify the `videos` table has a `user_id` column directly**

Run: `grep -n "CREATE TABLE.*videos\|videos\s*(" database.py | head -5`

If `videos` does NOT have a direct `user_id` column (common pattern: videos belong to an account which belongs to a user), replace the videos count query in Step 2 with:

```python
videos_count = (_fetchone(conn,
    "SELECT COUNT(*) AS cnt FROM videos v "
    "JOIN accounts a ON a.id = v.account_id "
    "WHERE a.user_id = %s", (uid,)
) or {}).get('cnt', 0)
```

Pick the variant that matches the actual schema. Document which one was used in the commit message.

- [ ] **Step 4: Verify the route boots without error**

Run: `cd "/Users/briique/Desktop/CLAUDE CODE/TRACKING LAB" && python3 -c "import app; print('OK:', sorted([r.rule for r in app.app.url_map.iter_rules() if r.rule == '/account']))"`

Expected output: `OK: ['/account']`

If you get an `ImportError` or `SyntaxError`, fix it before continuing. The route must register cleanly.

- [ ] **Step 5: Smoke-test the route locally with a stub template**

The template doesn't exist yet, so this step verifies the handler logic only. Create `templates/account.html` as a one-line stub for now:

```html
<!DOCTYPE html><html><body>OK plan={{ plan_name }} accounts={{ usage.accounts_count }}</body></html>
```

Then start the app and curl it (you'll need a logged-in session cookie — easier to verify in the browser):

Run: `./start.sh &` then visit `http://localhost:5555/account` in your browser (already logged in via Google OAuth).

Expected: a one-line page showing `OK plan=starter accounts=N` (or whatever your real plan and account count are). 200 status.

If you get 500: check the Flask logs. Most likely the videos query needs the JOIN variant from Step 3.

- [ ] **Step 6: Commit Task 1**

```bash
git add app.py templates/account.html
git commit -m "$(cat <<'EOF'
feat(account): add /account route stub returning plan + usage

Backend half of the Mon Compte hub. The route reads the current plan
via get_user_plan(), counts accounts/projects/videos for the user,
and renders templates/account.html (stub for now — full template lands
in next commit).

Login-required. Uses data_user_id so managers see the admin's data
(consistent with the rest of the app).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Build the full `account.html` template

**Files:**
- Modify: `templates/account.html` (replace the stub from Task 1 with the real page)

- [ ] **Step 1: Replace the stub with the full template**

Open `templates/account.html` and replace its entire contents with the block below. This is one self-contained file — head, inline CSS, body — no shared base layout (matches the convention of `billing.html` and `admin.html`).

```html
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mon compte · Tracking Lab</title>
  <link rel="icon" href="{{ url_for('static', filename='favicon.ico') }}">
  <style>
    :root {
      --bg: #fafafa;
      --card: #ffffff;
      --border: #e5e5e5;
      --text: #111;
      --muted: #6b6b6b;
      --accent: #0066ff;
      --red: #ff3b30;
      --gold: #c89b3c;
      --radius: 12px;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }
    .topbar {
      display: flex; align-items: center; justify-content: space-between;
      padding: 14px 24px;
      border-bottom: 1px solid var(--border);
      background: #fff;
    }
    .topbar a { color: var(--muted); text-decoration: none; font-size: 14px; }
    .topbar a:hover { color: var(--text); }
    .container { max-width: 720px; margin: 0 auto; padding: 40px 24px 80px; }

    /* Profile header */
    .profile {
      display: flex; gap: 20px; align-items: center;
      padding: 24px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      margin-bottom: 24px;
    }
    .avatar {
      width: 72px; height: 72px; border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      color: #fff; font-weight: 600; font-size: 28px;
      flex-shrink: 0;
    }
    .profile-info { flex: 1; min-width: 0; }
    .profile-name { font-size: 20px; font-weight: 600; margin: 0 0 2px; }
    .profile-email { color: var(--muted); font-size: 14px; margin: 0 0 8px; word-break: break-all; }
    .profile-meta { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .badge {
      padding: 3px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
    }
    .badge-starter { background: #f0f0f0; color: #555; }
    .badge-pro     { background: #e6f0ff; color: var(--accent); }
    .badge-agency  { background: #fcf2dc; color: var(--gold); }
    .since { color: var(--muted); font-size: 13px; }

    /* Plan card */
    .plan-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 24px;
      margin-bottom: 24px;
    }
    .plan-title { font-size: 16px; font-weight: 600; margin: 0 0 4px; }
    .plan-tagline { color: var(--muted); font-size: 14px; margin: 0 0 20px; }
    .gauge { margin-bottom: 14px; }
    .gauge:last-of-type { margin-bottom: 0; }
    .gauge-row {
      display: flex; justify-content: space-between; font-size: 13px;
      margin-bottom: 6px;
    }
    .gauge-label { color: var(--muted); }
    .gauge-value { font-weight: 600; font-variant-numeric: tabular-nums; }
    .gauge-bar {
      height: 6px; background: #f0f0f0; border-radius: 999px; overflow: hidden;
    }
    .gauge-fill {
      height: 100%; background: var(--accent); border-radius: 999px;
      transition: width 200ms ease;
    }
    .gauge-fill.warn { background: #ff9500; }
    .gauge-fill.full { background: var(--red); }
    .plan-cta {
      display: inline-flex; align-items: center; gap: 6px;
      margin-top: 20px;
      padding: 10px 18px;
      background: var(--text); color: #fff;
      border-radius: 8px; text-decoration: none; font-size: 14px; font-weight: 500;
    }
    .plan-cta:hover { background: #000; }

    /* Quick-access grid */
    .grid {
      display: grid; gap: 12px;
      grid-template-columns: 1fr;
      margin-bottom: 32px;
    }
    @media (min-width: 600px) {
      .grid { grid-template-columns: 1fr 1fr; }
    }
    .tile {
      display: flex; align-items: center; gap: 14px;
      padding: 18px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      text-decoration: none; color: inherit;
      transition: transform 100ms ease, border-color 100ms ease;
    }
    .tile:hover { transform: translateY(-1px); border-color: #ccc; }
    .tile-icon {
      width: 40px; height: 40px; border-radius: 10px;
      display: flex; align-items: center; justify-content: center;
      background: #f4f4f4; flex-shrink: 0;
    }
    .tile-icon svg { width: 20px; height: 20px; stroke: var(--text); }
    .tile-body { flex: 1; min-width: 0; }
    .tile-title { font-size: 15px; font-weight: 600; margin: 0 0 2px; }
    .tile-desc { font-size: 13px; color: var(--muted); margin: 0; }
    .tile-chev { color: var(--muted); flex-shrink: 0; }

    /* Logout footer */
    .logout-zone {
      border-top: 1px solid var(--border);
      padding-top: 24px;
      margin-top: 16px;
    }
    .logout-btn {
      display: flex; align-items: center; justify-content: center; gap: 8px;
      width: 100%;
      padding: 14px;
      background: transparent;
      border: 1px solid var(--red);
      color: var(--red);
      border-radius: 10px;
      text-decoration: none;
      font-weight: 600; font-size: 14px;
      transition: background 100ms ease;
    }
    .logout-btn:hover { background: rgba(255, 59, 48, 0.06); }
    .logout-btn svg { width: 16px; height: 16px; }
  </style>
</head>
<body>

  <div class="topbar">
    <a href="/dashboard">← Retour au tableau de bord</a>
    <span style="font-size:13px;color:var(--muted)">Tracking Lab</span>
  </div>

  <main class="container">

    <!-- 1. Profile header -->
    <section class="profile">
      {% set initials = (user.name or user.email).split(' ') | map('first') | join('') | upper %}
      {% set hue = (user.email | hash) % 360 if user.email else 200 %}
      <div class="avatar" style="background: hsl({{ hue }}, 60%, 50%);">
        {{ initials[:2] }}
      </div>
      <div class="profile-info">
        <h1 class="profile-name">{{ user.name or user.email.split('@')[0] }}</h1>
        <p class="profile-email">{{ user.email }}</p>
        <div class="profile-meta">
          {% set badge_class = 'badge-' + (plan_name if plan_name in ['starter','pro'] else 'agency') %}
          <span class="badge {{ badge_class }}">{{ plan_meta.name }}</span>
          {% if user.created_at %}
            <span class="since">Membre depuis {{ user.created_at.strftime('%B %Y') if user.created_at.strftime else user.created_at }}</span>
          {% endif %}
        </div>
      </div>
    </section>

    <!-- 2. Plan & usage -->
    <section class="plan-card">
      <h2 class="plan-title">Plan {{ plan_meta.name }}</h2>
      <p class="plan-tagline">
        {% if plan_name == 'starter' %}Pour découvrir l'outil
        {% elif plan_name == 'pro' %}Pour les créateurs établis
        {% else %}Pour les équipes et les agences{% endif %}
      </p>

      {% macro gauge(label, current, maximum) %}
        {% set pct = (100 * current / maximum) if maximum and maximum > 0 else 0 %}
        {% set cls = 'full' if pct >= 100 else ('warn' if pct >= 80 else '') %}
        <div class="gauge">
          <div class="gauge-row">
            <span class="gauge-label">{{ label }}</span>
            <span class="gauge-value">
              {% if maximum >= 9999 %}{{ current }} / illimité
              {% else %}{{ current }} / {{ maximum }}{% endif %}
            </span>
          </div>
          <div class="gauge-bar">
            <div class="gauge-fill {{ cls }}" style="width: {{ [pct, 100] | min }}%;"></div>
          </div>
        </div>
      {% endmacro %}

      {{ gauge('Comptes suivis', usage.accounts_count, plan_meta.max_accounts) }}
      {{ gauge('Projets',         usage.projects_count, plan_meta.max_projects) }}
      {{ gauge('Vidéos archivées', usage.videos_count,   plan_meta.max_videos) }}

      <a class="plan-cta" href="/billing">
        Gérer mon abonnement
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
      </a>
    </section>

    <!-- 3. Quick access -->
    <section class="grid">
      <a class="tile" href="/billing">
        <div class="tile-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><rect x="2" y="6" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/><line x1="6" y1="14" x2="10" y2="14"/></svg>
        </div>
        <div class="tile-body">
          <h3 class="tile-title">Facturation</h3>
          <p class="tile-desc">Plan, paiement et factures</p>
        </div>
        <svg class="tile-chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
      </a>

      {% if user.is_admin %}
      <a class="tile" href="/admin">
        <div class="tile-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </div>
        <div class="tile-body">
          <h3 class="tile-title">Administration</h3>
          <p class="tile-desc">Utilisateurs et plans</p>
        </div>
        <svg class="tile-chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
      </a>

      <a class="tile" href="/admin/swarm">
        <div class="tile-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="2"><circle cx="12" cy="12" r="2"/><circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/><line x1="12" y1="12" x2="6" y2="6"/><line x1="12" y1="12" x2="18" y2="6"/><line x1="12" y1="12" x2="6" y2="18"/><line x1="12" y1="12" x2="18" y2="18"/></svg>
        </div>
        <div class="tile-body">
          <h3 class="tile-title">Swarm</h3>
          <p class="tile-desc">Observabilité du scraping multi-agents</p>
        </div>
        <svg class="tile-chev" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
      </a>
      {% endif %}
    </section>

    <!-- 4. Logout footer -->
    <div class="logout-zone">
      <a class="logout-btn" href="/logout">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
        Déconnexion
      </a>
    </div>

  </main>
</body>
</html>
```

Notes for the implementer:
- Jinja's built-in `hash` filter doesn't exist by default. If `{{ user.email | hash }}` raises a `TemplateSyntaxError`, replace that line with: `{% set hue = (user.email | length * 37) % 360 if user.email else 200 %}` — deterministic enough, no Python-side change needed.
- The `[pct, 100] | min` syntax requires Jinja2 ≥ 2.10 with `min` filter enabled. Flask ships it. If it errors, fall back to: `{% set capped = pct if pct <= 100 else 100 %}` then `style="width: {{ capped }}%;"`
- `user.created_at` may be a `datetime` (psycopg2) or a string (SQLite text). The template handles both via the conditional `if user.created_at.strftime else user.created_at`.

- [ ] **Step 2: Verify the template renders without Jinja errors**

Restart the app (kill any running `./start.sh`, restart it):

Run: `./start.sh`

Visit `http://localhost:5555/account` in your browser. You should see the full page render: profile card with your initials in a colored circle, plan card with 3 gauges, 1-3 quick-access tiles (depending on admin), and a red Déconnexion button at the bottom.

If you see a Jinja TemplateSyntaxError in the browser:
- For `hash` filter error: apply the fallback from the notes above.
- For `min` filter error: apply the fallback from the notes above.
- Re-test after the fix.

- [ ] **Step 3: Verify the gauges display correctly for your plan**

Manually check:
- Each gauge label matches its row (Comptes / Projets / Vidéos)
- Numbers in the right column match what you'd expect (compare against the dashboard counts)
- For an admin on Entreprises plan: gauges should read "X / illimité" (since max=9999 triggers the special label)
- Bar fill width is proportional to current/max
- A gauge ≥80% full turns orange; ≥100% turns red

If the displayed counts look wrong (e.g. videos=0 when you know there are videos), revisit Task 1 Step 3 — the videos count query may need the JOIN variant.

- [ ] **Step 4: Verify admin-only tiles are gated correctly**

If you're admin: you see Facturation + Administration + Swarm (3 tiles).
Verify by inspecting the HTML source — the `{% if user.is_admin %}` block should be rendered.

If you can, switch to a non-admin test user (or temporarily comment out `is_admin` check in `auth.py`) and confirm only the Facturation tile renders. Restore `auth.py` afterwards.

- [ ] **Step 5: Verify all links work**

Click each:
- "Gérer mon abonnement" CTA → goes to `/billing`
- Facturation tile → `/billing`
- Administration tile → `/admin` (admin only)
- Swarm tile → `/admin/swarm` (admin only)
- "← Retour au tableau de bord" topbar link → `/dashboard`

Don't click Déconnexion yet — you'll need your session for the next tasks.

- [ ] **Step 6: Commit Task 2**

```bash
git add templates/account.html
git commit -m "$(cat <<'EOF'
feat(account): full Mon Compte hub template

Standalone Jinja page rendered by /account. Layout:
1. Profile header — avatar (initials on hue derived from email), name,
   email, plan badge, "Membre depuis"
2. Plan card — 3 usage gauges (comptes/projets/vidéos) with current/max
   from PLANS dict. ≥80% turns orange, ≥100% red. "illimité" label when
   max ≥ 9999 (Entreprises tier). CTA → /billing.
3. Quick-access grid — 1 tile for everyone (Facturation), 2 admin-only
   (Administration, Swarm). Hover lift + chevron. Responsive 2-col.
4. Red logout button bottom — separated from cards by border-top so it's
   not misclickable while scanning.

Self-contained (own <head>, inline CSS), matches the standalone-page
convention of billing.html / admin.html. Reuses CSS variable names
from the dashboard so visual language is consistent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Replace the Compte sidebar section in dashboard.html

**Files:**
- Modify: `templates/dashboard.html` lines 1666-1683 (the `<div class="sb-section">` Compte block)

- [ ] **Step 1: Identify the exact block to replace**

Run: `grep -n "sb-section-label\">Compte" templates/dashboard.html`

Expected output: a single line like `1668:        <span class="sb-section-label">Compte</span><span class="sb-chev">▾</span>`

Read lines 1666-1683 to confirm the structure (a `<div class="sb-section">` with the Compte header + 3 sb-item links, ending with `</div>`).

- [ ] **Step 2: Replace the Compte section with a single sb-item link**

Use the Edit tool to swap the entire block. Old block (the existing 18 lines starting at 1666):

```html
    <div class="sb-section">
      <div class="sb-section-head">
        <span class="sb-section-label">Compte</span><span class="sb-chev">▾</span>
      </div>
      <a class="sb-item" href="/billing">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="20" height="14" rx="2"/><line x1="2" y1="10" x2="22" y2="10"/><line x1="6" y1="14" x2="10" y2="14"/></svg>
        Facturation
      </a>
      {% if user.is_admin %}
      <a class="sb-item" href="/admin">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        Administration
      </a>
      <a class="sb-item" href="/admin/swarm">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="2"/><circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="18" r="2"/><line x1="12" y1="12" x2="6" y2="6"/><line x1="12" y1="12" x2="18" y2="6"/><line x1="12" y1="12" x2="6" y2="18"/><line x1="12" y1="12" x2="18" y2="18"/></svg>
        Swarm
      </a>
      {% endif %}
    </div>
```

New block (1 sb-item — keep it as a top-level item like the Analytics/Concurrents items, no enclosing section header):

```html
    <a class="sb-item sb-item-standalone" href="/account" data-nav="account">
      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
      Mon compte
    </a>
```

The new item is **outside** any `.sb-section` wrapper because the previous Concurrents section already closed (line 1617). It sits at the same indent level as the `.sb-mgr` blocks before it.

- [ ] **Step 3: Add minimal CSS so the standalone sb-item matches the dashboard nav links visually**

The existing `.sb-item` styles already give it the right look (font, padding, hover). The `.sb-item-standalone` class is purely a marker for future targeting — no new CSS needed in v1. If during the visual check (next step) the spacing looks off (too tight against the .sb-mgr above it), add this once near the other `.sb-item` rules in the inline CSS:

```css
.sb-item-standalone { margin: 8px 14px; border-radius: 8px; }
```

Look for the existing `.sb-item {` declaration in `dashboard.html` (around line 290-340) and place this new rule immediately after it. Only add it if the visual check requires it.

- [ ] **Step 4: Bump the build version**

Run: `grep -n "X-Build-Version" app.py`

Expected: a single line in `_security_headers()`. Edit it to:

```python
response.headers.setdefault("X-Build-Version", "2026-05-10-account-page")
```

- [ ] **Step 5: Verify in the browser**

Hard-refresh `http://localhost:5555/dashboard`. You should see:
- Sidebar order: Logo → ANALYTICS section → CONCURRENTS section → Gérer tes comptes (dropdown) → Gérer tes projets (dropdown) → **Mon compte** (single item, replacing the old Compte section) → Déconnexion (bottom)
- Click "Mon compte" → navigates to `/account` (full page reload, NOT SPA — that's expected)
- The page renders correctly (already verified in Task 2)

If "Mon compte" looks visually misaligned (too close to the dropdown above, or the icon is misaligned), apply the optional CSS rule from Step 3.

- [ ] **Step 6: Commit Task 3**

```bash
git add templates/dashboard.html app.py
git commit -m "$(cat <<'EOF'
feat(sidebar): collapse Compte section into single Mon compte link

The 3-item Compte sub-section (Facturation/Admin/Swarm) is now reachable
through one /account hub page. Sidebar gets a single "Mon compte" item
in its place — cleaner nav, room for future account-scoped features.

The bottom-anchored Déconnexion link stays as the always-available
emergency logout from any view; the /account page also has its own
in-context logout button.

Build bumped to 2026-05-10-account-page so the no-store guard is
curl-verifiable.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Push and verify on production

**Files:** none (git only)

- [ ] **Step 1: Push the 3 commits**

Run: `git push origin main`

Expected: 3 commits go up. Vercel will auto-deploy on push.

- [ ] **Step 2: Wait for the Vercel deploy to finish**

Run: `gh run list --limit 3` (if applicable) or watch the Vercel dashboard. Typical deploy: 60-90 seconds.

- [ ] **Step 3: Verify on production**

Hard-refresh `https://app.trackinglab.online/dashboard` in your browser.

Curl the build header to confirm the new version is live (no auth needed for the header):

Run: `curl -sI https://app.trackinglab.online/dashboard | grep -i x-build-version`

Expected: `x-build-version: 2026-05-10-account-page`

If you see the old version, the deploy hasn't finished yet — wait 30s and retry.

- [ ] **Step 4: Visit /account on production**

Open `https://app.trackinglab.online/account` in your browser.

Verify:
- Profile renders with your real name + email
- Badge shows your real plan (Starter/Pro/Entreprises)
- Gauges show real, accurate counts
- All links navigate correctly
- Logout works (test it last — you'll need to log back in)

If anything is broken in production but worked locally, the most likely culprit is an env var difference or the videos count query (production uses Postgres, dev may use SQLite — the `_q()` shim should handle the placeholder difference but JOIN syntax is identical).

---

## Self-Review Notes

Spec coverage check:
- ✅ §Profile header → Task 2 Step 1 (`<section class="profile">`)
- ✅ §Plan & usage card → Task 2 Step 1 (`<section class="plan-card">`)
- ✅ §Quick-access grid → Task 2 Step 1 (`<section class="grid">`)
- ✅ §Logout footer → Task 2 Step 1 (`<div class="logout-zone">`)
- ✅ §Backend data flow → Task 1 Step 2 (route handler)
- ✅ §Sidebar replacement → Task 3 Step 2
- ✅ §Risk #1 (`users.created_at`) → Resolved during plan-writing (column exists in CREATE TABLE)
- ✅ §Risk #2 (`_count_*` helpers) → Resolved: inline COUNT queries with `_fetchone` in Task 1
- ✅ §Risk #3 (PLANS dict) → Resolved: confirmed `name/max_accounts/max_videos/max_projects` keys, plan ID `agency` is actually `entreprises` in the dict (handled in template badge logic)
- ✅ §Risk #4 (sidebar duplication) → Resolved: only `dashboard.html` has the sidebar
- ✅ §Out-of-scope items → Not implemented (correct per spec)

No placeholders. Type consistency confirmed (`plan_name`, `plan_meta`, `usage` shape stays the same Task 1 → Task 2 → Task 4).

The plan is complete and ready to execute.
