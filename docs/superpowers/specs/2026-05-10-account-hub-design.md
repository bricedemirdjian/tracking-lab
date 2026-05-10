# Mon Compte — Hub Page Design

**Date:** 2026-05-10
**Status:** Approved by user, ready for implementation plan
**Project:** Tracking Lab

## Goal

A dedicated `/account` page that consolidates everything user-account
related into one entry point: profile info, current plan + usage, links to
existing standalone pages (Billing, Admin, Swarm), and logout. Replaces the
3-item "Compte" sub-section in the sidebar with a single "Mon compte" link.

## Why

Right now the sidebar exposes Facturation / Administration / Swarm as 3
separate items, with Déconnexion bottom-anchored. New users have no single
place that says "this is your account." The hub solves that and gives a
home for future account-scoped settings (plan upgrades, profile, eventual
2FA, notifications) without further bloating the sidebar.

## Architecture

**Route:** New Flask route `@app.route("/account")` (login_required) in
`app.py`, returning `render_template("account.html", user=current_user,
plan=plan_name, plan_meta=PLANS[plan_name], usage={...})`. Standalone page,
not a SPA view — matches the pattern of `/billing`, `/admin`,
`/admin/swarm`. Keeps `templates/dashboard.html` from growing further (it's
already 4000+ lines).

**Template:** New `templates/account.html`. No shared base layout exists
in this repo (every page is standalone), so the file embeds its own
minimal head + nav-back-to-dashboard link. Reuses CSS variables from the
inline dashboard styles (`--border`, `--accent`, `--red`, Inter font) by
declaring them locally — no external CSS dependency.

**Sidebar change in `templates/dashboard.html`:**
- Remove the `<div class="sb-section">` Compte block (the 3 sub-items).
- Replace it with a single `<a class="sb-item" href="/account"
  data-nav="account">Mon compte</a>` placed where the section header used
  to be (between "Gérer tes projets" and `.sb-bottom`).
- The `.sb-bottom` Déconnexion link **stays** — it's the always-available
  emergency logout from any view. The `/account` page also has its own
  Déconnexion button (in-context), but we don't remove the sidebar one.

**Same change applied to other templates** that have a sidebar with the
old Compte structure (`templates/admin.html`, `templates/swarm.html`,
`templates/billing.html` — verify during implementation which ones share
the pattern; only patch the ones that need it).

## Page layout (top-to-bottom)

### 1. Profile header
- Circular avatar with the user's initials on a colored background (color
  derived deterministically from email hash so it's stable across visits)
- Display name (`user.name` if set, otherwise the local-part of
  `user.email`)
- Email
- Plan badge (Starter / Pro / Agency, color-coded)
- "Membre depuis {created_at formatted in French}" — requires
  `users.created_at` column. Verify it exists; add a `_migrate_*` helper
  if not (per CLAUDE.md migration rules).

### 2. Plan & usage card
- Plan name + tagline (e.g. "Pro — pour les créateurs établis")
- Three usage gauges, each as `current / max` with a horizontal
  progress bar. If `max` is `None` (unlimited), show "Illimité" instead of
  a bar.
  - Comptes : `accounts_count` / `PLANS[plan]['max_accounts']`
  - Projets : `projects_count` / `PLANS[plan]['max_projects']`
  - Vidéos : `videos_count` / `PLANS[plan]['max_videos']`
- CTA button "Gérer mon abonnement" → links to `/billing`

### 3. Quick-access grid
- 3 cards laid out in a responsive grid (1 col on mobile, 2-3 on desktop).
  Each card: icon + title + 1-line description + chevron arrow on the
  right. Whole card clickable.
- **Facturation** → `/billing` (always visible)
  - Description: "Plan, paiement et factures"
- **Administration** → `/admin` (admin only — gated by `{% if user.is_admin %}`)
  - Description: "Gérer les utilisateurs et plans"
- **Swarm** → `/admin/swarm` (admin only)
  - Description: "Observabilité du scraping multi-agents"

### 4. Logout footer
- Full-width red button "Déconnexion" → `/logout`
- Visually separated (top border + extra margin) so it can't be misclicked
  while scanning the cards above.

## Backend data flow

The route handler computes everything synchronously in one DB round-trip:

```python
@app.route("/account")
@login_required
def account():
    plan_name = get_user_plan(current_user.data_user_id)
    plan_meta = PLANS[plan_name]
    usage = {
        "accounts_count": _count_user_accounts(current_user.data_user_id),
        "projects_count": _count_user_projects(current_user.data_user_id),
        "videos_count":   _count_user_videos(current_user.data_user_id),
    }
    return render_template(
        "account.html",
        user=current_user,
        plan_name=plan_name,
        plan_meta=plan_meta,
        usage=usage,
    )
```

The `_count_*` helpers may already exist (used for plan-limit enforcement
in import routes); during implementation, search for them before writing
new ones.

## Visual / styling

- Page wrapped in `.account-container { max-width: 720px; margin: 0 auto;
  padding: 40px 24px }` for a focused single-column read.
- Cards use the same 12px border-radius and 1px `--border` style as the
  dashboard widgets, so the visual language matches.
- Plan badge colors:
  - Starter → neutral gray
  - Pro → accent blue
  - Agency → premium gold
- Avatar background: deterministic hue from `hash(email) % 360`, fixed
  saturation/lightness — gives every user a stable personal color without
  requiring uploads.
- Mobile: cards stack to 1-col under 600px viewport.

## Out of scope (deliberate)

The following were explicitly excluded to keep v1 shippable:

- **Profile editing** — Google OAuth controls name/avatar; we don't fight
  it. If they want to change their name, they change it in their Google
  account.
- **2FA / password / security settings** — there is no password auth in
  Tracking Lab, so there's nothing to manage. OAuth is single-source.
- **Notification preferences** — no transactional email beyond billing
  receipts (which Stripe sends), no in-app notifications. YAGNI.
- **Activity log / login history** — useful eventually but not requested.
- **API keys / tokens** — no public API exists today. When/if we expose
  one, this hub is the natural home.
- **Account deletion** — requires GDPR data-deletion flow; out of scope
  for v1, will be its own feature when needed.

## Risks / things to verify during implementation

1. **`users.created_at` column** — verify it exists in the production DB.
   If not, add a `_migrate_users_created_at` helper to `database.py` and
   call it from `migrate_db()`.
2. **Usage count helpers** — find existing `_count_*` functions in
   `app.py` / `database.py`. If they don't exist with the right shape, the
   new ones must be efficient (single COUNT query each, indexed by
   `user_id`).
3. **PLANS dict shape** — confirm `max_accounts`, `max_projects`,
   `max_videos` keys exist. If a value is `None` or `-1` for "unlimited",
   the template must handle that.
4. **Sidebar duplication across templates** — if `admin.html`,
   `swarm.html`, `billing.html` all duplicate the dashboard sidebar, the
   refactor must touch each of them. If they share a partial / macro,
   touch the partial. Investigate before patching.

## Success criteria

- User clicks "Mon compte" in sidebar → lands on `/account` in <500ms
- All 4 zones render without errors regardless of plan / admin status
- Admin-only cards hidden for non-admin users
- Plan badge color matches the user's actual plan
- Usage gauges show real numbers that match what's enforced at the route
  layer (no off-by-one between display and enforcement)
- Logout button works (existing `/logout` route)
- Sidebar Compte section in `dashboard.html` is fully replaced by the
  single "Mon compte" item
- `.sb-bottom` Déconnexion still works from any view

---

*Approved by user on 2026-05-10. Next step: writing-plans skill to produce
the implementation plan, then execution.*
