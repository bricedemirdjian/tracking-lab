import os
import csv
import io
import threading
import time
import requests
import stripe
from datetime import datetime
from flask import Flask, render_template, jsonify, request, Response, redirect, url_for
from flask_login import login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from database import (
    init_db, get_all_accounts, get_videos, get_aggregated_stats,
    get_global_stats, get_daily_evolution, get_posts_per_day_aggregated,
    upsert_video, upsert_account,
    save_daily_snapshot, add_tracked_account, remove_tracked_account,
    create_project, rename_project, delete_project, get_projects,
    get_project_accounts, set_project_accounts, get_account_usernames_for_project,
    get_all_users, set_user_blocked, set_user_role, delete_user_and_data,
    get_user_subscription, upsert_subscription, get_subscription_by_customer,
    set_user_plan, get_user_plan,
)
from functools import wraps
from tiktok_scraper import scrape_all_accounts_for_user, scrape_single_account_for_user
from auth import auth_bp, init_auth
from stripe_billing import PLANS, get_plan, create_checkout_session, create_portal_session, get_price_plan
from analytics import (
    compute_hashtag_stats, get_viral_videos, detect_trends,
    get_growth_metrics, get_top_content, generate_insights, run_full_analysis
)

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# Global scraping status tracker per user
scrape_status = {}

app = Flask(__name__)

# Production config
IS_PRODUCTION = bool(
    os.environ.get('RENDER') or os.environ.get('PRODUCTION') or os.environ.get('VERCEL')
)

_secret_key = os.environ.get('SECRET_KEY')
if IS_PRODUCTION and not _secret_key:
    raise RuntimeError(
        "SECRET_KEY env var is required in production. "
        "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(64))'"
    )
app.config['SECRET_KEY'] = _secret_key or 'tiktok-tracker-dev-secret-2024'
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')

# Debug: log OAuth config status at startup
print(f"[Config] GOOGLE_CLIENT_ID present: {app.config['GOOGLE_CLIENT_ID'] is not None}")
print(f"[Config] GOOGLE_CLIENT_SECRET present: {app.config['GOOGLE_CLIENT_SECRET'] is not None}")
print(f"[Config] SECRET_KEY length: {len(app.config['SECRET_KEY'])}")

# Trust Render's load balancer (1 proxy hop) so request.remote_addr is the
# real client IP — required for Flask-Limiter keying on IP.
if IS_PRODUCTION:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


# When the Flask app sits behind the Next.js landing proxy on
# trackinglab.online, the Vercel infra restamps X-Forwarded-Host with the
# internal destination (app.trackinglab.online), so ProxyFix(x_host=1) ends
# up returning the wrong host. Result: url_for(_external=True) and
# request.host_url generate https://app.trackinglab.online/... leaking the
# internal subdomain into OAuth redirect_uri, Stripe success URLs, and the
# flask-login `next=` query param.
#
# Fix: inject a WSGI middleware AFTER ProxyFix that forces HTTP_HOST to
# CANONICAL_HOST. WSGI level (not @app.before_request) because Werkzeug's
# request.host is a cached_property — by the time before_request fires,
# downstream hooks may have already cached the wrong value.
#
# Order matters: this wrapper goes OUTSIDE ProxyFix so it runs FIRST in the
# request chain (`outer(inner(app))` → outer's __call__ runs first), giving
# Flask a fully canonicalized environ before any cached_property fires.
_CANONICAL_HOST = os.environ.get('CANONICAL_HOST', '').strip()
# Hosts that should 308-redirect to CANONICAL_HOST (deprecated subdomains).
# Comma-separated env var; e.g. "app.trackinglab.online" during migration.
# Exclude /webhook/* from the redirect so Stripe webhooks with the old URL
# in flight still land cleanly.
_LEGACY_HOSTS = {
    h.strip().lower()
    for h in os.environ.get('LEGACY_HOSTS', '').split(',')
    if h.strip()
}
if _CANONICAL_HOST:
    class CanonicalHostMiddleware:
        def __init__(self, wsgi_app, host, legacy_hosts=None):
            self.wsgi_app = wsgi_app
            self.host = host
            self.legacy_hosts = legacy_hosts or set()

        def __call__(self, environ, start_response):
            original_host = environ.get('HTTP_HOST', '').split(':')[0].lower()
            path = environ.get('PATH_INFO', '/')
            # 308-redirect deprecated subdomains to the canonical host, but
            # keep /webhook/* and /api/cron/* live on the old URL as a safety
            # net for any legacy callers still pointed there.
            if (original_host in self.legacy_hosts
                    and not path.startswith('/webhook/')
                    and not path.startswith('/api/cron/')):
                query = environ.get('QUERY_STRING', '')
                target = f'https://{self.host}{path}'
                if query:
                    target = f'{target}?{query}'
                start_response('308 Permanent Redirect', [
                    ('Location', target),
                    ('Content-Type', 'text/plain; charset=utf-8'),
                    ('Cache-Control', 'no-store'),
                ])
                return [b'Moved to ' + target.encode('utf-8')]
            # Otherwise rewrite host to the canonical so downstream URL builders
            # (host_url, url_for _external, flask-login next=) use it.
            environ['HTTP_HOST'] = self.host
            environ['SERVER_NAME'] = self.host
            environ['wsgi.url_scheme'] = 'https'
            environ['HTTP_X_FORWARDED_HOST'] = self.host
            environ['HTTP_X_FORWARDED_PROTO'] = 'https'
            return self.wsgi_app(environ, start_response)

    app.wsgi_app = CanonicalHostMiddleware(app.wsgi_app, _CANONICAL_HOST, _LEGACY_HOSTS)

# Rate limiting — in-memory storage (fine for single-instance Render).
# If we scale horizontally, swap storage_uri to Redis.
def _rate_limit_key():
    """Prefer authenticated user id over IP when available."""
    try:
        if current_user and current_user.is_authenticated:
            return f"user:{current_user.id}"
    except Exception:
        pass
    return get_remote_address()


limiter = Limiter(
    app=app,
    key_func=_rate_limit_key,
    default_limits=["200 per minute", "2000 per hour"],
    storage_uri="memory://",
    strategy="fixed-window",
)


@app.errorhandler(429)
def ratelimit_handler(e):
    """Return JSON for rate-limit errors so the frontend can handle them."""
    return jsonify({
        "error": "Trop de requêtes",
        "detail": str(e.description),
        "retry_after": getattr(e, "retry_after", None),
    }), 429


@app.after_request
def _security_headers(response):
    """
    Add baseline security headers to every response.

    Notes:
      - HSTS: set preload=False until the domain is verified on hstspreload.org
      - CSP: allow inline scripts because dashboard/landing currently use them;
        relax to strict-dynamic later after moving inline scripts to files.
      - frame-ancestors 'none' replaces X-Frame-Options for modern browsers.
    """
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=(), payment=()",
    )
    # Build identifier for ops debugging — bump when shipping fixes that
    # need to be confirmed visible at the edge. Curl-able without auth.
    response.headers.setdefault("X-Build-Version", "2026-05-12-ig-retry")
    # Force fresh HTML on every load. Chrome was caching the dashboard HTML
    # despite `max-age=0, must-revalidate` (only re-fetched while DevTools was
    # open with "Disable cache" toggled). `no-store` is the strict bypass.
    # Static assets (CSS/JS) keep their long cache via the `?v=` query string.
    if request.path in ("/", "/dashboard") or request.path.startswith("/dashboard?"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    if IS_PRODUCTION:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response

# Initialize database and auth
init_db()
init_auth(app)
app.register_blueprint(auth_bp)




def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            return jsonify({"error": "Admin requis"}), 403
        return f(*args, **kwargs)
    return decorated


@app.route("/healthz")
@limiter.exempt
def healthz():
    """Lightweight liveness probe for Render / uptime monitors.
    Checks DB connectivity. Returns 200 only if the DB round-trips."""
    try:
        from database import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)[:200]}), 503


@app.route("/")
def index():
    return render_template("landing.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", user=current_user)


@app.route("/dashboard/preview")
@login_required
def dashboard_preview():
    """Legacy preview route — Salesia design has been promoted to /dashboard.
    Redirect any old bookmarks so users always land on the live UI.
    """
    return redirect("/dashboard", code=301)


@app.route("/admin")
@login_required
def admin_page():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    return render_template("admin.html", user=current_user)


# ── Swarm Health (admin-only ops dashboard) ───────────────────────────
@app.route("/admin/swarm")
@login_required
def swarm_page():
    """Multi-agent swarm observability — admin only.

    Renders the shell; the metrics + history are loaded via AJAX from
    the JSON endpoint below so the page stays snappy even if the swarm
    history file grows large.
    """
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    return render_template("swarm.html", user=current_user)


@app.route("/api/admin/swarm/metrics")
@admin_required
def api_admin_swarm_metrics():
    """Returns the 5 L7 scores + recent cycles + endpoint stats.

    Lazy-import keeps the startup path clean if the swarm module ever
    fails to import (e.g. missing optional dep).
    """
    try:
        from scraper_healing.swarm.scoring import metric_summary_for_dashboard
        from scraper_healing import core as healing_core
        summary = metric_summary_for_dashboard(history_limit=200)
        # Surface raw endpoint stats for the per-platform reliability table.
        stats = healing_core._load_stats()  # noqa: SLF001 — internal helper, single-process
        summary["endpoint_stats"] = stats.get("endpoints", {})
        summary["learned_paths"] = stats.get("learned_paths", {})
        return jsonify(summary)
    except ImportError:
        # scraper_healing/ is excluded from the Vercel bundle (see .vercelignore).
        # The swarm is a local-only debug tool — cycles are written to a JSONL
        # on the developer's machine. Return empty defaults so the dashboard
        # renders its existing empty state instead of HTTP 500.
        return jsonify({
            "metrics": {
                "success_rate": 0.0,
                "failure_rate": 0.0,
                "data_completeness_score": 0.0,
                "selector_stability_score": 0.0,
                "adversarial_resilience_score": 0.0,
                "evolution_effectiveness_score": 0.0,
                "n_cycles": 0,
                "n_success": 0,
                "n_failure": 0,
                "n_adversarial_cycles": 0,
            },
            "recent_cycles": [],
            "endpoint_stats": {},
            "learned_paths": {},
            "swarm_unavailable": True,
        })
    except Exception as e:
        app.logger.exception("swarm_metrics_failed")
        return jsonify({"error": str(e)[:200]}), 500


@app.route("/api/admin/users")
@admin_required
def api_admin_users():
    users = get_all_users()
    return jsonify(users)


@app.route("/api/admin/scraping-health")
@admin_required
def api_admin_scraping_health():
    """Per-account scraping health: who's failing, who's stale, who's healthy.

    Computes per-account staleness against the cadence the cron uses
    (admin override always 1h via get_scrape_cadence_hours). An account
    is 'stale' if last_updated > 2× cadence. 'Failing' if
    consecutive_failures >= 3. Returns counters + the list of accounts
    sorted by severity.
    """
    from database import get_connection, _fetchall
    from stripe_billing import get_scrape_cadence_hours

    cadence_h = get_scrape_cadence_hours("agency", is_admin=True)  # = 1h for admin

    # Stale threshold accounts for the scheduled overnight pause: the cron
    # only fires 9h-21h Paris time, so during the off window we'd see ~12h
    # of legitimate gap. Tolerate up to 14h (12h pause + 2h margin) when
    # outside business hours, otherwise enforce the tight 2× cadence.
    try:
        from zoneinfo import ZoneInfo
        paris_hour = datetime.now(ZoneInfo("Europe/Paris")).hour
    except Exception:
        paris_hour = datetime.utcnow().hour  # fallback, may drift by DST
    in_business = 9 <= paris_hour <= 21
    stale_threshold_h = cadence_h * 2 if in_business else 14

    conn = get_connection()
    try:
        rows = _fetchall(conn, """
            SELECT
                a.user_id, a.username, a.platform,
                a.last_updated,
                a.consecutive_failures,
                a.last_error_msg,
                a.last_success_at,
                COALESCE(a.is_competitor, FALSE) AS is_competitor,
                EXTRACT(EPOCH FROM (NOW() - a.last_updated))::bigint AS sec_since_update,
                EXTRACT(EPOCH FROM (NOW() - a.last_success_at))::bigint AS sec_since_success
            FROM accounts a
            WHERE a.user_id = %s
            ORDER BY a.consecutive_failures DESC, a.last_updated ASC NULLS FIRST
        """, (current_user.data_user_id,))
    finally:
        conn.close()

    healthy = []
    stale = []
    failing = []
    for r in rows:
        item = {
            "username": r.get("username"),
            "platform": r.get("platform"),
            "is_competitor": bool(r.get("is_competitor")),
            "consecutive_failures": int(r.get("consecutive_failures") or 0),
            "last_error_msg": r.get("last_error_msg") or None,
            "sec_since_update": int(r.get("sec_since_update") or 0) if r.get("sec_since_update") is not None else None,
            "sec_since_success": int(r.get("sec_since_success") or 0) if r.get("sec_since_success") is not None else None,
        }
        if item["consecutive_failures"] >= 3:
            failing.append(item)
        elif item["sec_since_update"] is not None and item["sec_since_update"] > stale_threshold_h * 3600:
            stale.append(item)
        else:
            healthy.append(item)

    return jsonify({
        "cadence_hours": cadence_h,
        "stale_threshold_hours": stale_threshold_h,
        "summary": {
            "total": len(rows),
            "healthy": len(healthy),
            "stale": len(stale),
            "failing": len(failing),
        },
        "failing": failing,
        "stale": stale,
        "healthy": healthy,
    })


@app.route("/api/admin/block/<int:user_id>", methods=["POST"])
@admin_required
def api_admin_block(user_id):
    if user_id == current_user.id:
        return jsonify({"error": "Impossible de se bloquer soi-meme"}), 400
    set_user_blocked(user_id, True)
    return jsonify({"status": "success"})


@app.route("/api/admin/unblock/<int:user_id>", methods=["POST"])
@admin_required
def api_admin_unblock(user_id):
    set_user_blocked(user_id, False)
    return jsonify({"status": "success"})


@app.route("/api/admin/delete/<int:user_id>", methods=["POST"])
@admin_required
def api_admin_delete(user_id):
    if user_id == current_user.id:
        return jsonify({"error": "Impossible de se supprimer soi-meme"}), 400
    delete_user_and_data(user_id)
    return jsonify({"status": "success"})


@app.route("/api/admin/plan/<int:user_id>", methods=["POST"])
@admin_required
def api_admin_set_plan(user_id):
    plan = request.json.get("plan", "").strip() if request.json else ""
    if plan not in ("starter", "pro", "agency"):
        return jsonify({"error": "Plan invalide (starter / pro / agency)"}), 400
    try:
        set_user_plan(user_id, plan)
        return jsonify({"status": "success", "plan": plan})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/role/<int:user_id>", methods=["POST"])
@admin_required
def api_admin_set_role(user_id):
    """Change user role. Manager = voit les donnees de l'admin. User = ses propres donnees."""
    if user_id == current_user.id:
        return jsonify({"error": "Impossible de modifier son propre role"}), 400
    role = request.json.get("role", "").strip() if request.json else ""
    if role not in ("user", "manager"):
        return jsonify({"error": "Role invalide (user / manager)"}), 400
    try:
        set_user_role(user_id, role)
        return jsonify({"status": "success", "role": role})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/plans")
@admin_required
def api_admin_plans():
    """Return plan catalog (name + limits) for admin UI."""
    return jsonify(PLANS)


def _current_plan():
    """Return plan dict for the current user."""
    plan_name = get_user_plan(current_user.data_user_id)
    return get_plan(plan_name)


def _resolve_project_usernames(user_id, project_id):
    """Return list of usernames for a project, or None for 'all'."""
    if not project_id or project_id == "all":
        return None
    return get_account_usernames_for_project(user_id, int(project_id))


# ==================== Billing routes ====================

@app.route("/billing")
@login_required
def billing():
    sub = get_user_subscription(current_user.id)
    plan = get_plan(sub.get('plan', 'starter'))

    # Detect a pending cadence switch (Stripe SubscriptionSchedule) so the
    # template can show "Vous passez à l'annuel le YYYY-MM-DD" instead of
    # the normal renewal line. Failure is silent — the page still renders,
    # just without the pending-switch indicator.
    pending_switch = None
    sub_id = sub.get('stripe_subscription_id')
    if sub_id:
        try:
            stripe_sub = stripe.Subscription.retrieve(sub_id, expand=['schedule'])
            sched_field = _stripe_get(stripe_sub, 'schedule')
            sub_status = _stripe_get(stripe_sub, 'status')
            if sched_field and sub_status in ('active', 'trialing'):
                if isinstance(sched_field, str):
                    sched = stripe.SubscriptionSchedule.retrieve(sched_field)
                else:
                    sched = sched_field
                # Stripe API 2024-09+ moved current_period_end to items[].
                current_period_end = 0
                try:
                    if 'items' in stripe_sub:
                        _items = stripe_sub['items']
                        _data = _items['data'] if 'data' in _items else []
                        if _data and 'current_period_end' in _data[0]:
                            current_period_end = _data[0]['current_period_end']
                except Exception:
                    pass
                if not current_period_end and 'current_period_end' in stripe_sub:
                    current_period_end = stripe_sub['current_period_end']
                future_phase = None
                if current_period_end:
                    for p in _stripe_get(sched, 'phases', []) or []:
                        if (_stripe_get(p, 'start_date') or 0) >= current_period_end:
                            future_phase = p
                            break
                if future_phase and current_period_end:
                    items = _stripe_get(future_phase, 'items', []) or []
                    target_price = _stripe_get(items[0] if items else {}, 'price') if items else None
                    if target_price and not isinstance(target_price, str):
                        target_price = _stripe_get(target_price, 'id')
                    target_plan = get_price_plan(target_price) if target_price else 'starter'
                    from datetime import datetime
                    months_fr = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin',
                                 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre']
                    dt = datetime.utcfromtimestamp(current_period_end)
                    switch_date_human = f"{dt.day} {months_fr[dt.month - 1]} {dt.year}"
                    pending_switch = {
                        'switch_at': current_period_end,
                        'switch_at_human': switch_date_human,
                        'target_plan': target_plan,
                        'target_label': PLANS.get(target_plan, {}).get('name'),
                    }
        except Exception as e:
            print(f"[billing] could not load pending schedule for sub {sub_id}: {e}")

    return render_template("billing.html", user=current_user, sub=sub, plan=plan,
                           plans=PLANS,
                           pending_switch=pending_switch,
                           stripe_pub_key=os.environ.get('STRIPE_PUBLISHABLE_KEY'))


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


class _ScheduleSkip(Exception):
    """Raised inside the cadence-switch path when we want to silently fall
    through to a fresh Checkout Session (sub not active, missing data, etc).
    Separate from stripe.error.* so we don't accidentally swallow real Stripe
    errors with the same fallback semantics."""


def _stripe_get(obj, key, default=None):
    """Safe accessor for Stripe SDK objects.

    Modern stripe-python returns typed resources that don't expose dict.get(),
    so `obj.get('x')` raises AttributeError. This helper uses bracket access
    + `in` membership check, which both StripeObject (dict subclass) and the
    newer typed resources support.
    """
    try:
        return obj[key] if key in obj else default
    except Exception:
        return default


@app.route("/api/billing/create-subscription-intent", methods=["POST"])
@login_required
def api_billing_create_subscription_intent():
    """Inline-payment endpoint used by /signup with Stripe Elements.

    Creates a Stripe Customer (or reuses one if the user already has one),
    then creates a Subscription with payment_behavior='default_incomplete'.
    Stripe returns the latest_invoice.payment_intent.client_secret which
    the frontend uses to confirm the payment via stripe.confirmPayment().

    No redirect to Checkout — the entire payment UI lives on /signup via
    Stripe Payment Element (card + Apple Pay + Link auto-detected).
    """
    body = request.json or {}
    plan_name = body.get("plan")
    period = body.get("period", "annual")
    if plan_name not in ('pro', 'agency'):
        return jsonify({"error": "Plan invalide"}), 400
    if period not in ('monthly', 'annual'):
        return jsonify({"error": "Période invalide"}), 400
    plan_cfg = PLANS[plan_name]
    price_id = plan_cfg.get('price_id_annual') if period == 'annual' else plan_cfg.get('price_id')
    if not price_id:
        price_id = plan_cfg.get('price_id') or plan_cfg.get('price_id_annual')
    if not price_id:
        return jsonify({"error": "Prix non configuré"}), 500

    sub = get_user_subscription(current_user.id)
    customer_id = sub.get('stripe_customer_id')

    try:
        # 1. Get or create the Stripe Customer.
        if not customer_id:
            customer = stripe.Customer.create(
                email=current_user.email,
                name=current_user.name or current_user.email,
                metadata={'tl_user_id': str(current_user.id)},
            )
            customer_id = customer.id
            # Persist so subsequent retries reuse the same customer.
            from database import upsert_subscription
            upsert_subscription(
                current_user.id, 'pending', 'incomplete',
                stripe_customer_id=customer_id,
            )

        # 2. Create the Subscription with default_incomplete so we get a
        # PaymentIntent client_secret to confirm client-side.
        subscription = stripe.Subscription.create(
            customer=customer_id,
            items=[{'price': price_id}],
            payment_behavior='default_incomplete',
            payment_settings={
                'save_default_payment_method': 'on_subscription',
                'payment_method_types': ['card'],  # 'card' includes Apple Pay & Link via Payment Element
            },
            expand=['latest_invoice.payment_intent'],
            metadata={
                'tl_user_id': str(current_user.id),
                'tl_plan': plan_name,
                'tl_period': period,
            },
        )

        invoice = subscription['latest_invoice']
        if isinstance(invoice, str):
            return jsonify({"error": "Payment intent not expanded"}), 500
        payment_intent = invoice['payment_intent'] if 'payment_intent' in invoice else None
        if not payment_intent or isinstance(payment_intent, str):
            return jsonify({"error": "Payment intent missing"}), 500

        return jsonify({
            "client_secret": payment_intent['client_secret'],
            "subscription_id": subscription['id'],
            "customer_id": customer_id,
            "publishable_key": os.environ.get('STRIPE_PUBLISHABLE_KEY'),
        })
    except stripe.error.StripeError as e:
        print(f"[STRIPE] create-subscription-intent failed: {e}")
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[STRIPE ERROR] create-subscription-intent: {e}")
        return jsonify({"error": str(e) or "Erreur interne"}), 500


@app.route("/api/billing/checkout", methods=["POST"])
@login_required
def api_billing_checkout():
    body = request.json or {}
    plan_name = body.get("plan")
    period = body.get("period", "annual")  # default to annual — matches landing UX
    if plan_name not in ('starter', 'pro', 'agency'):
        return jsonify({"error": "Plan invalide"}), 400
    if period not in ('monthly', 'annual'):
        return jsonify({"error": "Période invalide"}), 400
    # Annual price IDs live under 'price_id_annual'. Fall back to monthly if
    # the annual env var isn't set, so the checkout still works during the
    # transition window when only one of the two has been wired in Stripe.
    plan_cfg = PLANS[plan_name]
    price_id = plan_cfg.get('price_id_annual') if period == 'annual' else plan_cfg.get('price_id')
    if not price_id:
        price_id = plan_cfg.get('price_id') or plan_cfg.get('price_id_annual')
    if not price_id:
        return jsonify({"error": "Prix non configuré"}), 500

    sub = get_user_subscription(current_user.id)
    customer_id = sub.get('stripe_customer_id')
    subscription_id = sub.get('stripe_subscription_id')
    base_url = request.host_url.rstrip('/')
    success_url = f"{base_url}/billing?success=1"
    cancel_url = f"{base_url}/billing?cancelled=1"

    # Cadence-switch path — user already has an active Stripe subscription
    # and is switching between monthly ↔ annual. Stripe REJECTS
    # Subscription.modify with billing_cycle_anchor='unchanged' when the
    # interval changes ("Changing plan intervals. There's no way to leave
    # billing cycle unchanged."), so we must use SubscriptionSchedule —
    # the only Stripe primitive that supports delayed cadence transitions
    # without proration.
    #
    # Approach:
    #   1. Retrieve sub with expand=['schedule'] to detect orphan schedules
    #      left over from previous failed attempts.
    #   2. Release any orphan — a sub already controlled by a schedule
    #      rejects a fresh create(from_subscription=...).
    #   3. Create a new schedule from the current sub (phase 1 = current
    #      sub state).
    #   4. Modify the schedule to add phase 2 (the target price for 1
    #      iteration, end_behavior='release' so post-phase-2 it renews
    #      normally on the new cadence).
    #
    # Net effect for user: pays 29€ for current month (already done),
    # then 79€ at period_end, then 79€/year. Total year 1: 108€.
    if customer_id and subscription_id:
        step = "init"
        try:
            step = "retrieve_subscription"
            existing = stripe.Subscription.retrieve(
                subscription_id, expand=['schedule']
            )
            sub_status = existing['status'] if 'status' in existing else None
            if sub_status not in ('active', 'trialing'):
                raise _ScheduleSkip(f"subscription not active (status={sub_status})")

            step = "extract_subscription_state"
            items_data = []
            if 'items' in existing:
                items_obj = existing['items']
                if 'data' in items_obj:
                    items_data = items_obj['data']
            if not items_data:
                raise _ScheduleSkip("subscription has no items")
            current_price_id = items_data[0]['price']['id']
            if current_price_id == price_id:
                return jsonify({"error": "Vous êtes déjà sur cette formule."}), 400

            period_end_ts = 0
            if 'current_period_end' in items_data[0]:
                period_end_ts = items_data[0]['current_period_end']
            if not period_end_ts and 'current_period_end' in existing:
                period_end_ts = existing['current_period_end']
            if not period_end_ts:
                return jsonify({
                    "error": "[extract_period_end] Stripe did not return current_period_end on this subscription.",
                    "step": "extract_period_end",
                }), 400

            # Release any leftover schedule before creating a fresh one —
            # Stripe rejects create(from_subscription=X) if X already has
            # a schedule attached.
            step = "release_orphan_schedule"
            sched_field = existing['schedule'] if 'schedule' in existing else None
            if sched_field:
                sched_id = sched_field if isinstance(sched_field, str) else sched_field['id']
                try:
                    stripe.SubscriptionSchedule.release(sched_id)
                    print(f"[STRIPE] released orphan schedule {sched_id} on sub {subscription_id}")
                except stripe.error.InvalidRequestError as rel_err:
                    print(f"[STRIPE] release of orphan {sched_id} failed (continuing): {rel_err}")

            step = "create_schedule_from_subscription"
            schedule = stripe.SubscriptionSchedule.create(from_subscription=subscription_id)

            step = "extract_phase_1_data"
            current_phase = schedule['phases'][0]
            cp_items = current_phase['items']
            cp_price = cp_items[0]['price']
            if not isinstance(cp_price, str):
                cp_price = cp_price['id'] if 'id' in cp_price else None

            # Compute phase 2's end_date from the target price's interval.
            # The user's Stripe API version doesn't accept phases[].iterations
            # ("Received unknown parameter: phases[iterations]"), so we
            # have to provide an explicit end timestamp. Approximate seconds
            # are fine — end_behavior='release' lets the sub renew normally
            # afterward, so a few hours off from the exact anniversary
            # doesn't affect billing alignment.
            step = "retrieve_target_price_interval"
            target_price = stripe.Price.retrieve(price_id)
            recurring = target_price['recurring']
            t_interval = recurring['interval']
            t_count = recurring['interval_count'] if 'interval_count' in recurring else 1
            seconds_per_unit = {
                'day': 24 * 3600,
                'week': 7 * 24 * 3600,
                'month': 30 * 24 * 3600,
                'year': 365 * 24 * 3600,
            }
            phase_2_length = seconds_per_unit.get(t_interval, 365 * 24 * 3600) * t_count
            phase_2_end = current_phase['end_date'] + phase_2_length

            step = "modify_schedule_add_phase_2"
            stripe.SubscriptionSchedule.modify(
                schedule['id'],
                end_behavior='release',
                phases=[
                    {
                        'items': [{'price': cp_price, 'quantity': 1}],
                        'start_date': current_phase['start_date'],
                        'end_date': current_phase['end_date'],
                        'proration_behavior': 'none',
                    },
                    {
                        'items': [{'price': price_id, 'quantity': 1}],
                        'end_date': phase_2_end,
                        'proration_behavior': 'none',
                    },
                ],
            )

            return jsonify({
                "scheduled": True,
                "switch_date": period_end_ts,
                "target_price_id": price_id,
            })
        except _ScheduleSkip as e:
            print(f"[STRIPE] cadence-switch skipped at step={step}: {e}")
        except stripe.error.InvalidRequestError as e:
            print(f"[STRIPE] cadence-switch InvalidRequestError at step={step}: {e}")
            return jsonify({
                "error": f"[{step}] Stripe: {str(e)}",
                "step": step,
            }), 400
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[STRIPE ERROR] cadence-switch failed at step={step}:\n{tb}")
            return jsonify({
                "error": f"[{step}] {type(e).__name__}: {str(e) or '(no message)'}",
                "step": step,
            }), 500

    # Signup path — no active Stripe subscription (or portal flow failed).
    # Create a fresh Checkout Session.
    try:
        session = create_checkout_session(
            user_email=current_user.email,
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_id=customer_id,
        )
        return jsonify({"url": session.url})
    except Exception as e:
        print(f"[STRIPE ERROR] checkout: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/billing/portal", methods=["POST"])
@login_required
def api_billing_portal():
    sub = get_user_subscription(current_user.id)
    customer_id = sub.get('stripe_customer_id')
    if not customer_id:
        return jsonify({"error": "Pas d'abonnement actif"}), 400
    base_url = request.host_url.rstrip('/')
    session = create_portal_session(customer_id, f"{base_url}/billing")
    return jsonify({"url": session.url})


@app.route("/api/billing/subscription")
@login_required
def api_billing_subscription():
    sub = get_user_subscription(current_user.id)
    plan = get_plan(sub.get('plan', 'starter'))
    return jsonify({"subscription": sub, "plan": plan})


@app.route("/webhook/stripe", methods=["POST"])
@limiter.limit("120 per minute", key_func=get_remote_address)
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')

    # Signature is MANDATORY — never accept unsigned events. An attacker could
    # otherwise forge checkout.session.completed and grant themselves a plan.
    if not webhook_secret:
        print("[Stripe] STRIPE_WEBHOOK_SECRET not configured — rejecting webhook")
        return jsonify({"error": "Webhook not configured"}), 503
    if not sig_header:
        return jsonify({"error": "Missing Stripe-Signature"}), 400
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    # StripeObject doesn't expose .get() — use bracket access with `in` check.
    def _so_get(obj, key, default=None):
        try:
            return obj[key] if key in obj else default
        except Exception:
            return default

    if event.type == 'checkout.session.completed':
        session = event.data.object
        customer_id = _so_get(session, 'customer')
        subscription_id = _so_get(session, 'subscription')
        details = _so_get(session, 'customer_details') or {}
        customer_email = (
            _so_get(session, 'customer_email')
            or _so_get(details, 'email')
        )
        if subscription_id:
            try:
                sub = stripe.Subscription.retrieve(subscription_id)
                price_id = sub['items']['data'][0]['price']['id']
                plan_name = get_price_plan(price_id)
                # Stripe API 2024-09+: current_period_end moved to items.data[0].
                # Use 'in' check (StripeObject.get can collide with dict-style access).
                _item = sub['items']['data'][0]
                if 'current_period_end' in _item:
                    period_end_ts = _item['current_period_end']
                elif 'current_period_end' in sub:
                    period_end_ts = sub['current_period_end']
                else:
                    period_end_ts = 0
                period_end = datetime.fromtimestamp(period_end_ts).isoformat()
                from database import get_connection, _fetchone
                conn = get_connection()
                # Case-insensitive lookup to defeat Gmail/OAuth case-normalization
                # mismatches (Stripe lowercases, our DB might have mixed case).
                user = _fetchone(
                    conn, "SELECT id, name, email FROM users WHERE LOWER(email) = LOWER(%s)",
                    (customer_email,),
                )
                conn.close()
                if user:
                    upsert_subscription(
                        user['id'], plan_name, 'active',
                        stripe_customer_id=customer_id,
                        stripe_subscription_id=subscription_id,
                        current_period_end=period_end,
                    )
                    # Clear the 'pending' marker on users.plan that the signup
                    # form set. set_user_plan also handles the legacy case
                    # where users.plan was 'starter' (Google OAuth → upgrade).
                    try:
                        from database import set_user_plan
                        set_user_plan(user['id'], plan_name)
                    except Exception as e:
                        print(f"[Stripe] set_user_plan failed (non-fatal, sub already active): {e}")
                    # Fire welcome/confirmation emails (best-effort, non-blocking)
                    try:
                        from emailer import send_payment_confirmation
                        send_payment_confirmation(
                            to_email=user['email'],
                            user_name=user.get('name') or user['email'].split('@')[0],
                            plan_name=plan_name,
                            period_end_iso=period_end,
                        )
                    except Exception as em:
                        print(f"[Stripe] email send failed: {em}")
                else:
                    # User hasn't signed up yet — stash the subscription intent
                    # under email so it's claimed on first login.
                    print(f"[Stripe] subscription for unknown email {customer_email} — "
                          f"will claim on first login")
            except Exception as e:
                print(f"[Stripe] checkout.session.completed handler error: {e}")

    elif event.type in ('customer.subscription.updated', 'customer.subscription.deleted'):
        sub = event.data.object
        customer_id = _so_get(sub, 'customer')
        status = _so_get(sub, 'status')
        plan_name = 'starter'
        if status == 'active':
            price_id = sub['items']['data'][0]['price']['id']
            plan_name = get_price_plan(price_id)
        db_sub = get_subscription_by_customer(customer_id)
        if db_sub:
            # Stripe API 2024-09+: current_period_end moved to items.data[0]
            period_end_ts = 0
            try:
                items_data = sub['items']['data'] if 'items' in sub else []
                if items_data and 'current_period_end' in items_data[0]:
                    period_end_ts = items_data[0]['current_period_end']
            except Exception:
                pass
            if not period_end_ts and 'current_period_end' in sub:
                period_end_ts = sub['current_period_end']
            period_end = datetime.fromtimestamp(period_end_ts).isoformat()
            upsert_subscription(
                db_sub['user_id'], plan_name,
                'active' if status == 'active' else 'cancelled',
                stripe_subscription_id=sub.id,
                current_period_end=period_end,
            )

    return jsonify({"status": "ok"})


# ==================== Project routes ====================

@app.route("/api/projects")
@login_required
def api_projects():
    projects = get_projects(user_id=current_user.data_user_id)
    return jsonify(projects)


@app.route("/api/projects", methods=["POST"])
@login_required
def api_create_project():
    name = request.json.get("name", "").strip() if request.json else ""
    if not name:
        return jsonify({"error": "Nom du projet requis"}), 400

    # Plan limit: max_projects (admins bypass)
    if not current_user.is_admin:
        plan = _current_plan()
        existing = get_projects(user_id=current_user.data_user_id)
        if len(existing) >= plan.get("max_projects", 1):
            return jsonify({
                "error": f"Limite de {plan['max_projects']} projet(s) atteinte sur le plan {plan['name']}. Passez au plan superieur.",
                "upgrade_required": True
            }), 403

    try:
        project = create_project(user_id=current_user.data_user_id, name=name)
        return jsonify(project)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/projects/<int:project_id>/rename", methods=["POST"])
@login_required
def api_rename_project(project_id):
    name = request.json.get("name", "").strip() if request.json else ""
    if not name:
        return jsonify({"error": "Nom requis"}), 400
    rename_project(user_id=current_user.data_user_id, project_id=project_id, new_name=name)
    return jsonify({"status": "success"})


@app.route("/api/projects/<int:project_id>/delete", methods=["POST"])
@login_required
def api_delete_project(project_id):
    delete_project(user_id=current_user.data_user_id, project_id=project_id)
    return jsonify({"status": "success"})


def _assert_project_owner(project_id):
    """Raise 403/404-style tuple (body, status) if current user doesn't own project."""
    from database import get_connection, _fetchone
    conn = get_connection()
    row = _fetchone(
        conn,
        "SELECT id, user_id FROM projects WHERE id = %s",
        (project_id,),
    )
    conn.close()
    if not row:
        return jsonify({"error": "Projet introuvable"}), 404
    if row['user_id'] != current_user.data_user_id and not current_user.is_admin:
        return jsonify({"error": "Accès refusé"}), 403
    return None


@app.route("/api/projects/<int:project_id>/accounts")
@login_required
def api_project_accounts(project_id):
    denial = _assert_project_owner(project_id)
    if denial:
        return denial
    accounts = get_project_accounts(project_id)
    return jsonify(accounts)


@app.route("/api/projects/<int:project_id>/accounts", methods=["POST"])
@login_required
def api_set_project_accounts(project_id):
    denial = _assert_project_owner(project_id)
    if denial:
        return denial
    account_ids = request.json.get("account_ids", []) if request.json else []
    set_project_accounts(project_id, account_ids)
    return jsonify({"status": "success"})


# ==================== Account routes ====================

@app.route("/api/accounts")
@login_required
def api_accounts():
    project_id = request.args.get("project_id", None)
    competitor = request.args.get("competitor", None)
    is_competitor = True if competitor == "true" else False if competitor == "false" else None
    if project_id and project_id != "all":
        accounts = get_project_accounts(int(project_id))
        # Filter by competitor flag if specified
        if is_competitor is not None:
            accounts = [a for a in accounts if a.get('is_competitor') == is_competitor]
        # Manually merge last_post_at from a single videos query (project_accounts
        # doesn't natively join videos). One extra round-trip — acceptable.
        if accounts:
            from database import get_connection, _fetchall
            usernames = list({a["username"] for a in accounts})
            ph = ", ".join(["%s"] * len(usernames))
            uid = current_user.data_user_id
            conn = get_connection()
            rows = _fetchall(conn,
                f"SELECT account_username AS username, platform, MAX(create_time) AS last_post_at "
                f"FROM videos WHERE account_username IN ({ph}) AND user_id = %s "
                f"GROUP BY account_username, platform",
                list(usernames) + [uid])
            conn.close()
            last_map = {(r["username"], r.get("platform") or "tiktok"): r["last_post_at"] for r in rows}
            for a in accounts:
                lp = last_map.get((a["username"], a.get("platform") or "tiktok"))
                a["last_post_at"] = lp.isoformat() if lp else None
    else:
        # `with_last_post=True` adds last_post_at — used by the dashboard to flag
        # inactive accounts that fall outside the current date window.
        accounts = get_all_accounts(user_id=current_user.data_user_id, is_competitor=is_competitor, with_last_post=True)
    # Sidebar 'Plateformes' filter — keep at the end so it works for both
    # project-scoped and global account fetches above.
    plat = request.args.get("platform")
    if plat in _SUPPORTED_PLATFORMS:
        accounts = [a for a in accounts if a.get("platform") == plat]
    return jsonify(accounts)


@app.route("/api/accounts/add", methods=["POST"])
@login_required
def api_add_account():
    username = request.json.get("username", "").strip().lstrip("@").lower() if request.json else ""
    platform = request.json.get("platform", "tiktok") if request.json else "tiktok"
    is_competitor = request.json.get("is_competitor", False) if request.json else False
    if not username:
        return jsonify({"error": "Nom d'utilisateur requis"}), 400
    if platform not in ("tiktok", "instagram", "youtube", "linkedin"):
        platform = "tiktok"

    # Admins bypass plan limits (they don't have a paying plan themselves)
    if not current_user.is_admin:
        plan = _current_plan()
        # Platform restriction
        if platform not in plan.get("platforms", []):
            return jsonify({
                "error": f"La plateforme {platform} nest pas disponible sur le plan {plan['name']}. Passez au plan Pro ou Entreprises.",
                "upgrade_required": True
            }), 403
        # Competitor tracking requires Agency
        if is_competitor and not plan.get("competitor_access"):
            return jsonify({
                "error": f"Le suivi des concurrents est reserve au plan Entreprises.",
                "upgrade_required": True
            }), 403
        # Max accounts
        existing = get_all_accounts(user_id=current_user.data_user_id)
        if len(existing) >= plan.get("max_accounts", 1):
            return jsonify({
                "error": f"Limite de {plan['max_accounts']} compte(s) atteinte sur le plan {plan['name']}. Passez au plan superieur.",
                "upgrade_required": True
            }), 403

    add_tracked_account(user_id=current_user.data_user_id, username=username, platform=platform, is_competitor=is_competitor)

    # Synchronously trigger the first scrape so a brand-new user sees their
    # stats the moment they land on /dashboard. Previously this was a Vercel
    # no-op (waited for next cron — 0-60min, felt broken) and a local thread.
    # Single-account scrape typically fits well inside Vercel's 60s function
    # budget: TikTok ~15-25s, Instagram ~5-15s, LinkedIn ~3-5s, YouTube scales
    # with channel size. If it fails or times out, the account row is still
    # in DB with last_updated=NULL, so the next cron pass picks it up.
    user_id = current_user.data_user_id
    first_scrape = "skipped"
    try:
        result = scrape_single_account_for_user(username, user_id, platform=platform)
        first_scrape = result.get("status", "error") if isinstance(result, dict) else "error"
    except Exception as e:
        # Don't fail the request — account is added, cron will retry the scrape.
        print(f"[add_account] first scrape failed for @{username}: {e}")
        first_scrape = "deferred"

    return jsonify({"status": "success", "username": username, "first_scrape": first_scrape})


@app.route("/api/accounts/remove", methods=["POST"])
@login_required
def api_remove_account():
    username = request.json.get("username", "").strip() if request.json else ""
    if not username:
        return jsonify({"error": "Nom d'utilisateur requis"}), 400
    remove_tracked_account(user_id=current_user.data_user_id, username=username)
    return jsonify({"status": "success"})


def _resolve_competitor_usernames(user_id, competitor_param, project_usernames):
    """If competitor param is set and no project filter, restrict to competitor/non-competitor accounts."""
    if competitor_param in ("true", "false") and not project_usernames:
        is_comp = competitor_param == "true"
        comp_accounts = get_all_accounts(user_id=user_id, is_competitor=is_comp)
        unames = [a['username'] for a in comp_accounts]
        return unames if unames else ["__none__"]
    return project_usernames


_SUPPORTED_PLATFORMS = ("tiktok", "instagram", "youtube", "linkedin")


def _apply_platform_filter(user_id, platform_param, project_usernames):
    """Intersect project_usernames with accounts on the given platform.

    Frontend sidebar 'Plateformes' section sends ?platform=tiktok|instagram|youtube|linkedin
    to scope the whole dashboard to one platform. We resolve here so every data
    endpoint applies the filter consistently (videos, stats, evolution, today).
    Returns ['__none__'] if the intersection is empty so downstream IN-clauses
    match zero rows (cleaner than passing an empty list).
    """
    if platform_param not in _SUPPORTED_PLATFORMS:
        return project_usernames
    from database import get_connection, _fetchall
    conn = get_connection()
    try:
        rows = _fetchall(conn,
            "SELECT username FROM accounts WHERE user_id = %s AND platform = %s",
            (user_id, platform_param))
    finally:
        conn.close()
    plat_unames = [r["username"] for r in rows]
    if project_usernames:
        intersected = [u for u in project_usernames if u in plat_unames]
        return intersected if intersected else ["__none__"]
    return plat_unames if plat_unames else ["__none__"]


@app.route("/api/video/analyze", methods=["POST"])
@login_required
@limiter.limit("20 per day; 5 per minute", key_func=lambda: str(current_user.id) if current_user.is_authenticated else get_remote_address())
def api_video_analyze():
    """Per-video AI analysis — agency plan only, on-demand.

    Reads video_id + platform from the request, looks up the cache, otherwise
    fetches thumbnail + metadata via yt-dlp and asks Gemini Flash 2.0 (free
    tier) for a structured analysis. Cached forever per (video_id, platform)
    so re-clicks are free.

    Cost: zero on cache hits; ~free-tier Gemini on misses. Rate-limited per
    user so a runaway script can't burn through the daily quota.
    """
    # Plan gate — agency (Entreprises) only, admin always allowed.
    plan = _current_plan()
    if not (plan.get('ai_video_analysis') or current_user.is_admin):
        return jsonify({
            "error": "Disponible sur l'offre Entreprises",
            "upgrade_required": True,
            "current_plan": plan.get('name', 'starter'),
        }), 403

    if not request.is_json:
        return jsonify({"error": "JSON requis"}), 400
    body = request.get_json(silent=True) or {}
    video_id = (body.get("video_id") or "").strip()
    platform = (body.get("platform") or "tiktok").strip().lower()
    if not video_id:
        return jsonify({"error": "video_id requis"}), 400
    if platform not in ("tiktok", "youtube", "instagram", "linkedin"):
        return jsonify({"error": "plateforme invalide"}), 400

    # Cache check — re-clicks are instant + free.
    from database import get_video_analysis, upsert_video_analysis
    cached = get_video_analysis(video_id, platform)
    if cached:
        cached["_cached"] = True
        return jsonify(cached)

    # API key check — graceful 503 if the env var is missing rather than a
    # 500 crash. Surfaces a setup hint to the admin.
    import os
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({
            "error": "AI vision désactivée (GEMINI_API_KEY non configuré sur Vercel)",
            "setup_hint": "Crée une clé gratuite sur aistudio.google.com/apikey puis ajoute-la dans Vercel env vars",
        }), 503

    # Lookup the video row to get account_username + thumbnail_url + the
    # context metadata we'll feed to Gemini's prompt.
    from database import get_connection, _fetchone
    conn = get_connection()
    try:
        vrow = _fetchone(conn,
            "SELECT account_username, description, duration, views, likes, comments, shares, video_url, thumbnail_url, create_time FROM videos WHERE video_id = %s AND platform = %s AND user_id = %s",
            (video_id, platform, current_user.data_user_id))
    finally:
        conn.close()
    if not vrow:
        return jsonify({"error": "vidéo introuvable dans ton catalogue"}), 404

    # Use the thumbnail we already stored at scrape time — skips a slow,
    # rate-limit-prone yt-dlp round-trip. This was the original blocker on
    # Instagram videos: yt-dlp's IG extractor needs cookies or a logged-in
    # session, so a public fetch returned "rate-limit reached or login
    # required" and the whole analysis failed. We already have the cover
    # image URL in DB (populated for every platform during the regular
    # scrape pipeline) — use it directly.
    thumb_url = vrow.get("thumbnail_url")
    if not thumb_url:
        # Final fallback: try yt-dlp only when DB is empty (very old rows).
        post_url = vrow.get("video_url")
        if not post_url and platform == "tiktok":
            post_url = f"https://www.tiktok.com/@{vrow['account_username']}/video/{video_id}"
        if not post_url:
            return jsonify({"error": "aucune image de couverture en DB ni URL de fallback"}), 404
        try:
            import yt_dlp
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "socket_timeout": 15, "retries": 1, "nocheckcertificate": True, "geo_bypass": True}) as ydl:
                info = ydl.extract_info(post_url, download=False)
            thumb_url = info.get("thumbnail") or (info.get("thumbnails") or [{}])[-1].get("url")
        except Exception as e:
            return jsonify({"error": f"pas de thumbnail en DB et fallback yt-dlp KO ({platform}): {str(e)[:120]}"}), 502
        if not thumb_url:
            return jsonify({"error": "aucune image de couverture disponible"}), 502

    # Download thumbnail bytes (we send inline base64 to Gemini — its URL
    # input mode requires the File API which has cleanup overhead we don't need).
    try:
        r = requests.get(thumb_url, timeout=10)
        r.raise_for_status()
        img_bytes = r.content
    except Exception as e:
        return jsonify({"error": f"téléchargement thumbnail échoué: {str(e)[:120]}"}), 502

    # Build the prompt — French because the user is, and structured JSON so
    # the frontend can render predictably.
    desc = vrow.get("description") or info.get("description") or ""
    duration = vrow.get("duration") or info.get("duration") or 0
    views = vrow.get("views") or 0
    likes = vrow.get("likes") or 0
    comments = vrow.get("comments") or 0
    shares = vrow.get("shares") or 0
    eng_rate = ((likes + comments + shares) / views * 100) if views else 0

    prompt = f"""Tu es un coach en création de contenu social media. Tu vas analyser une vidéo {platform} via son image de couverture (cover frame) et sa metadata, puis donner un retour détaillé et actionable au créateur.

CONTEXTE de la vidéo :
- Compte : @{vrow.get('account_username')}
- Durée : {duration}s
- Description : "{desc[:280]}"
- Performance : {views:,} vues · {likes:,} likes · {comments:,} commentaires · {shares:,} partages · {eng_rate:.2f}% engagement

À FAIRE :
Analyse l'image (souvent le 1er frame, donc LE hook visuel sur TikTok/Reels) ET la description, puis renvoie UNIQUEMENT un JSON conforme à ce schéma exact (pas de texte avant/après, pas de markdown) :

{{
  "hook_quality": "excellent" | "bon" | "moyen" | "faible",
  "hook_observation": "ce que tu vois sur la cover et pourquoi ça stoppe (ou pas) le scroll, 1-2 phrases",
  "visual_style": "description courte du style visuel (cadrage, lumière, ambiance, personnage si présent)",
  "content_type": "humour" | "tuto" | "lifestyle" | "témoignage" | "publicité" | "actualité" | "challenge" | "autre",
  "target_audience": "qui regarde probablement ça, 1 phrase",
  "strengths": ["3 max — chaque point concret et observable depuis l'image/description"],
  "weaknesses": ["2 max — soyez honnête, signaler ce qui pourrait expliquer une sous-perf si la perf est faible"],
  "why_it_performed": "pourquoi cette vidéo a fait {views:,} vues (ou n'en a pas fait), en lien avec ton observation visuelle, 2-3 phrases",
  "recommendations": ["3 max — actions concrètes pour reproduire le succès ou corriger les faiblesses, formulées à la 2e personne ('Garde…', 'Évite…', 'Teste…')"]
}}

Sois direct, concret, basé sur ce que tu VOIS et sur la perf chiffrée. Pas de banalités. Réponse en français."""

    # Call Gemini (free tier on newer models — switched from 2.0-flash to
    # gemini-2.5-flash after seeing 429 RESOURCE_EXHAUSTED on the user's
    # brand-new key, which seems to start with a tighter per-key warmup
    # quota on 2.0-flash). 2.5-flash has the most generous free tier as of
    # 2026-05 + still supports vision + structured JSON output.
    import base64, json as jsonmod, time as _time
    last_err = None
    analysis = None
    try:
        from google import genai
        from google.genai import types as gtypes
        client = genai.Client(api_key=api_key)
        # Detect image MIME from first bytes — JPEGs start with 0xFFD8, PNGs with 0x89504E47.
        mime = "image/jpeg" if img_bytes[:2] == b"\xff\xd8" else "image/png" if img_bytes[:4] == b"\x89PNG" else "image/jpeg"
        # Retry once on transient 429 — Gemini free tier sometimes throttles
        # the first request from a cold IP. Wait 2s then try one more time.
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        gtypes.Part.from_bytes(data=img_bytes, mime_type=mime),
                        prompt,
                    ],
                    config=gtypes.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.6,
                        # Bumped from 1500 — was truncating mid-string on
                        # videos with richer analyses (3 recos + strengths +
                        # weaknesses + why_it_performed multi-sentence). 4000
                        # is enough headroom for the most verbose output we've
                        # seen, still well under the model's ceiling.
                        max_output_tokens=4000,
                    ),
                )
                raw = response.text or "{}"
                try:
                    analysis = jsonmod.loads(raw)
                except jsonmod.JSONDecodeError as je:
                    # Log the malformed payload so we can see what shape
                    # Gemini actually returned (truncation, markdown wrap,
                    # extra prose, etc.) — then fail explicitly rather than
                    # surface the cryptic "Unterminated string" trace.
                    app.logger.warning(f"video_analyze_json_parse_failed: {je}; raw[:500]={raw[:500]!r}")
                    raise RuntimeError(f"Gemini a renvoyé du JSON invalide ({je.msg} à la position {je.pos}). Réessaie — il peut hallucinier le format.")
                break
            except Exception as inner:
                last_err = inner
                msg = str(inner)
                if attempt == 0 and ("429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower()):
                    _time.sleep(2)
                    continue
                raise
    except Exception as e:
        app.logger.exception("video_analyze_gemini_failed")
        msg = str(e)
        # Detect the common error shapes and surface a UX-friendly message
        # rather than the raw JSON-stringified API response.
        if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
            return jsonify({
                "error": "Quota Gemini dépassé — réessaie dans 1 min (free tier limite à 15 req/min)",
                "raw": msg[:200],
            }), 429
        if "400" in msg and "API key" in msg:
            return jsonify({"error": "Clé Gemini invalide — vérifie GEMINI_API_KEY sur Vercel"}), 400
        return jsonify({"error": f"analyse IA échouée: {msg[:200]}"}), 502

    # Persist + return.
    try:
        upsert_video_analysis(video_id, platform, analysis, "gemini-2.0-flash-001")
    except Exception as e:
        # Cache write is non-blocking — return the analysis even if persist fails.
        app.logger.warning(f"video_analysis cache write failed: {e}")
    analysis["_cached"] = False
    analysis["_meta"] = {"model": "gemini-2.0-flash-001"}
    return jsonify(analysis)


@app.route("/api/videos")
@login_required
def api_videos():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)
    sort_by = request.args.get("sort_by", "create_time")
    sort_order = request.args.get("sort_order", "DESC")
    project_usernames = _resolve_project_usernames(current_user.data_user_id, request.args.get("project_id"))
    project_usernames = _resolve_competitor_usernames(current_user.data_user_id, request.args.get("competitor"), project_usernames)
    project_usernames = _apply_platform_filter(current_user.data_user_id, request.args.get("platform"), project_usernames)

    videos = get_videos(account, date_from, date_to, sort_by, sort_order, user_id=current_user.data_user_id, account_usernames=project_usernames)
    return jsonify(videos)


@app.route("/api/stats")
@login_required
def api_stats():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)

    project_usernames = _resolve_project_usernames(current_user.data_user_id, request.args.get("project_id"))
    # Competitor filter: restrict to competitor/non-competitor account usernames
    competitor = request.args.get("competitor", None)
    if competitor in ("true", "false") and not project_usernames:
        is_comp = competitor == "true"
        comp_accounts = get_all_accounts(user_id=current_user.data_user_id, is_competitor=is_comp)
        project_usernames = [a['username'] for a in comp_accounts]
        if not project_usernames:
            project_usernames = ["__none__"]  # Force empty result
    project_usernames = _apply_platform_filter(current_user.data_user_id, request.args.get("platform"), project_usernames)
    try:
        per_account = get_aggregated_stats(account, date_from, date_to, user_id=current_user.data_user_id, account_usernames=project_usernames)
        global_stats = get_global_stats(date_from, date_to, user_id=current_user.data_user_id, account_usernames=project_usernames)
    except Exception as e:
        # Previously this caught all exceptions and silently returned an
        # all-zeros dict with HTTP 200. The frontend's cachedJSON cached that
        # fake-success response for 60s, so a transient DB hiccup (pool
        # exhausted, query timeout) made every KPI display 0 for a full
        # minute — the "stats à 0 desfois" bug. Now we return HTTP 500 with
        # the error message, cachedJSON refuses to cache, and the dashboard
        # keeps the previous values instead of flashing zeros.
        app.logger.exception("api_stats_failed")
        return jsonify({"error": str(e)[:200]}), 500

    # Ensure all values are numeric (PostgreSQL may return None)
    for key in ["total_videos", "total_views", "total_likes", "total_comments", "total_shares", "total_saves", "total_followers"]:
        global_stats[key] = global_stats.get(key) or 0
    # follower_gain can be negative — preserve the sign, only coerce None -> 0
    if global_stats.get("follower_gain") is None:
        global_stats["follower_gain"] = 0

    total_engagement = (global_stats["total_likes"] + global_stats["total_comments"]
                        + global_stats["total_shares"] + global_stats["total_saves"])
    engagement_rate = (total_engagement / global_stats["total_views"] * 100) if global_stats["total_views"] > 0 else 0

    return jsonify({
        "global": {
            **global_stats,
            "total_engagement": total_engagement,
            "engagement_rate": round(engagement_rate, 2),
        },
        "per_account": per_account,
    })


@app.route("/api/evolution")
@login_required
def api_evolution():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)

    project_usernames = _resolve_project_usernames(current_user.data_user_id, request.args.get("project_id"))
    project_usernames = _resolve_competitor_usernames(current_user.data_user_id, request.args.get("competitor"), project_usernames)
    project_usernames = _apply_platform_filter(current_user.data_user_id, request.args.get("platform"), project_usernames)
    data = get_daily_evolution(account, date_from, date_to, user_id=current_user.data_user_id, account_usernames=project_usernames)
    return jsonify(data)


@app.route("/api/today")
@login_required
def api_today():
    """Posts published today + views gained today, computed server-side.

    Replaces the JS-side delta computation that was producing 0 views even
    when daily_snapshots had clear positive deltas — the cause appeared to
    be timezone or cache-staleness in /api/evolution. By computing here
    against CURRENT_DATE in Postgres, we get one source of truth tied to
    server-local time.

    Returns:
      {
        "date":       "YYYY-MM-DD",      # CURRENT_DATE on the DB server
        "posts": {
          "total":       int,
          "by_platform": { "tiktok": int, ... },
          "list":        [ { platform, username, views, title } ],
        },
        "views": {
          "total":       int,
          "by_platform": { "tiktok": int, ... },
          "list":        [ { platform, username, delta } ],
        }
      }
    """
    from database import get_connection, _fetchall, _fetchone
    uid = current_user.data_user_id
    project_id = request.args.get("project_id")
    is_competitor = request.args.get("competitor") == "true"
    project_usernames = _resolve_project_usernames(uid, project_id)
    project_usernames = _resolve_competitor_usernames(uid, request.args.get("competitor"), project_usernames)
    project_usernames = _apply_platform_filter(uid, request.args.get("platform"), project_usernames)

    conn = get_connection()
    try:
        # ── 1. Posts published today (videos.create_time on today's local date) ──
        posts_q = """
            SELECT v.platform, v.account_username AS username,
                   COALESCE(v.views, 0) AS views,
                   COALESCE(v.description, '') AS title
            FROM videos v
            WHERE v.user_id = %s
              AND v.create_time::date = CURRENT_DATE
        """
        posts_params = [uid]
        if project_usernames:
            posts_q += " AND v.account_username IN (" + ",".join(["%s"] * len(project_usernames)) + ")"
            posts_params.extend(project_usernames)
        posts_q += " ORDER BY v.views DESC NULLS LAST LIMIT 200"
        post_rows = _fetchall(conn, posts_q, posts_params)

        # ── 2. Views gained today (today's snapshot minus the most-recent prior) ──
        # JOIN today's snapshot row to the most recent snapshot strictly before
        # today for the same (account, platform). LATERAL is the cleanest way.
        views_q = """
            SELECT t.account_username AS username, t.platform,
                   GREATEST(0, t.total_views - p.total_views) AS delta
            FROM daily_snapshots t
            JOIN LATERAL (
                SELECT total_views FROM daily_snapshots
                WHERE user_id = t.user_id
                  AND account_username = t.account_username
                  AND platform = t.platform
                  AND snapshot_date < t.snapshot_date
                ORDER BY snapshot_date DESC
                LIMIT 1
            ) p ON true
            WHERE t.user_id = %s
              AND t.snapshot_date = CURRENT_DATE
        """
        views_params = [uid]
        if project_usernames:
            views_q += " AND t.account_username IN (" + ",".join(["%s"] * len(project_usernames)) + ")"
            views_params.extend(project_usernames)
        views_q += " ORDER BY delta DESC"
        view_rows = _fetchall(conn, views_q, views_params)
    finally:
        conn.close()

    posts_by_platform = {"tiktok": 0, "instagram": 0, "youtube": 0, "linkedin": 0}
    posts_list = []
    for r in post_rows:
        platform = r.get("platform") or "tiktok"
        if platform in posts_by_platform:
            posts_by_platform[platform] += 1
        posts_list.append({
            "platform": platform,
            "username": r.get("username") or "",
            "views": int(r.get("views") or 0),
            "title": (r.get("title") or "")[:60],
        })

    views_by_platform = {"tiktok": 0, "instagram": 0, "youtube": 0, "linkedin": 0}
    views_list = []
    total_views = 0
    for r in view_rows:
        delta = int(r.get("delta") or 0)
        if delta <= 0:
            continue
        platform = r.get("platform") or "tiktok"
        if platform in views_by_platform:
            views_by_platform[platform] += delta
        total_views += delta
        views_list.append({
            "platform": platform,
            "username": r.get("username") or "",
            "delta": delta,
        })

    # Use server-local current date so JS doesn't have to guess timezones
    from datetime import date as _date
    return jsonify({
        "date": _date.today().isoformat(),
        "posts": {
            "total": len(posts_list),
            "by_platform": posts_by_platform,
            "list": posts_list,
        },
        "views": {
            "total": total_views,
            "by_platform": views_by_platform,
            "list": views_list,
        },
    })


@app.route("/api/best-videos")
@login_required
def api_best_videos():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)
    limit = int(request.args.get("limit", 10))
    # `sort` toggles between two ranking modes for "Meilleures vidéos":
    #   - views (default): pure reach. Excludes IG photos/carousels which
    #     have no view count exposed by Meta.
    #   - engagement:      weighted score (views + likes×100 + comments×500
    #                      + shares×200). Surfaces high-engagement carousels
    #                      alongside viral videos.
    sort_param = request.args.get("sort", "views")
    sort_by = "engagement" if sort_param == "engagement" else "views"

    project_usernames = _resolve_project_usernames(current_user.data_user_id, request.args.get("project_id"))
    project_usernames = _resolve_competitor_usernames(current_user.data_user_id, request.args.get("competitor"), project_usernames)
    videos = get_videos(account, date_from, date_to, sort_by=sort_by, sort_order="DESC", user_id=current_user.data_user_id, account_usernames=project_usernames, limit=limit)
    return jsonify(videos)


@app.route("/api/latest-videos")
@login_required
def api_latest_videos():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)
    limit = int(request.args.get("limit", 10))

    project_usernames = _resolve_project_usernames(current_user.data_user_id, request.args.get("project_id"))
    project_usernames = _resolve_competitor_usernames(current_user.data_user_id, request.args.get("competitor"), project_usernames)
    videos = get_videos(account, date_from, date_to, sort_by="create_time", sort_order="DESC", user_id=current_user.data_user_id, account_usernames=project_usernames, exclude_no_date=True, limit=limit)
    return jsonify(videos)


@app.route("/api/posts-per-day")
@login_required
def api_posts_per_day():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)
    project_usernames = _resolve_project_usernames(current_user.data_user_id, request.args.get("project_id"))
    project_usernames = _resolve_competitor_usernames(current_user.data_user_id, request.args.get("competitor"), project_usernames)
    day_map = get_posts_per_day_aggregated(
        account, date_from, date_to,
        user_id=current_user.data_user_id,
        account_usernames=project_usernames,
    )
    return jsonify(day_map)


@app.route("/api/scrape", methods=["POST"])
@login_required
@limiter.limit("10 per minute; 60 per hour")
def api_scrape():
    username = request.json.get("username") if request.json else None
    user_id = current_user.data_user_id

    # Check if already scraping
    if user_id in scrape_status and scrape_status[user_id].get("active"):
        return jsonify({"status": "already_running", "message": "Scraping deja en cours"})

    accounts = get_all_accounts(user_id=user_id)
    account_list = [username] if username else [a["username"] for a in accounts]

    scrape_status[user_id] = {
        "active": True,
        "started_at": time.time(),
        "total": len(account_list),
        "completed": 0,
        "done_accounts": [],
        "current_account": None,
        "errors": [],
    }

    def on_account_start(uname):
        scrape_status[user_id]["current_account"] = uname

    def on_account_done(uname, success, video_count):
        # "success" is True when videos were fetched OR when the profile
        # legitimately has no content yet. Only true scrape exceptions go to errors.
        status = scrape_status[user_id]
        status["completed"] += 1
        status["done_accounts"].append({
            "username": uname,
            "success": success,
            "videos": video_count,
        })
        status["current_account"] = None
        if not success:
            status["errors"].append(uname)

    def run_scrape():
        try:
            if username:
                on_account_start(username)
                result = scrape_single_account_for_user(username, user_id)
                is_ok = result.get("status") in ("success", "no_data")
                on_account_done(username, is_ok, result.get("videos", 0))
            else:
                scrape_all_accounts_for_user(user_id, on_start=on_account_start, on_done=on_account_done)
        finally:
            scrape_status[user_id]["active"] = False
            scrape_status[user_id]["finished_at"] = time.time()

    # On Vercel (serverless), run synchronously with parallel execution
    if os.environ.get('VERCEL'):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        account_objs = {a["username"]: a for a in accounts}

        def scrape_one(acc):
            uname = acc["username"]
            platform = acc.get("platform", "tiktok")
            on_account_start(uname)
            try:
                result = scrape_single_account_for_user(uname, user_id, platform=platform)
                is_ok = result.get("status") in ("success", "no_data")
                on_account_done(uname, is_ok, result.get("videos", 0))
                return result
            except Exception as e:
                print(f"  @{uname} ({platform}): exception - {e}")
                on_account_done(uname, False, 0)
                return {"status": "error", "videos": 0}

        target_accounts = accounts if not username else [a for a in accounts if a["username"] == username]
        # Higher concurrency = ~2x faster scrape on Vercel (limited by yt-dlp/HTTP, not CPU).
        with ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(scrape_one, target_accounts))

        scrape_status[user_id]["active"] = False
        scrape_status[user_id]["finished_at"] = time.time()
        return jsonify({"status": "completed", "total": len(account_list),
                        "done": scrape_status[user_id].get("done_accounts", [])})
    else:
        thread = threading.Thread(target=run_scrape)
        thread.start()
        return jsonify({"status": "started", "total": len(account_list)})


@app.route("/api/scrape-status")
@login_required
def api_scrape_status():
    user_id = current_user.data_user_id
    status = scrape_status.get(user_id, {"active": False, "total": 0, "completed": 0})
    return jsonify(status)


def _cron_auth_check():
    """Verify CRON_SECRET header. Returns error response or None if OK."""
    cron_secret = os.environ.get("CRON_SECRET")
    # Enforce presence in production — no "open cron" fallback.
    if IS_PRODUCTION and not cron_secret:
        print("[Cron] CRON_SECRET not set in production — rejecting request")
        return jsonify({"error": "Cron not configured"}), 503
    auth_header = request.headers.get("Authorization", "")
    if cron_secret and auth_header != f"Bearer {cron_secret}":
        return jsonify({"error": "Unauthorized"}), 401
    return None


def _cron_scrape(platform_filter=None):
    """
    Shared cron scrape logic.
    platform_filter: list of platforms to scrape, e.g. ["tiktok", "youtube"].
                     None = all platforms.

    Tier-based throttling (added 2026-05-09): each account is skipped if its
    user's plan cadence hasn't elapsed since `last_updated`. Cadence comes from
    PLANS[plan_name].scrape_cadence_hours (starter 6h / pro 4h / agency 1h).
    Admins (role='admin') always get 1h regardless of plan. Accounts with
    last_updated NULL are always due (first-time scrape).
    """
    from database import get_connection, _fetchall
    from stripe_billing import get_scrape_cadence_hours

    started = time.time()
    max_duration = 55  # leave 5s margin before Vercel timeout

    if platform_filter:
        placeholders = ",".join(["%s"] * len(platform_filter))
        query = f"SELECT DISTINCT user_id FROM accounts WHERE user_id IS NOT NULL AND platform IN ({placeholders})"
        conn = get_connection()
        users = _fetchall(conn, query, platform_filter)
        conn.close()
    else:
        conn = get_connection()
        users = _fetchall(conn, "SELECT DISTINCT user_id FROM accounts WHERE user_id IS NOT NULL")
        conn.close()

    if not users:
        label = ", ".join(platform_filter) if platform_filter else "all"
        return jsonify({"status": "ok", "message": "Aucun utilisateur", "platforms": label, "users": 0})

    # Parallel scrape to fit within the 60s Vercel function budget. With
    # `max_workers=12`, 12 accounts run simultaneously; latency = max(per-account)
    # rather than sum(per-account). The previous serial version was scraping
    # only 2 of 6 IG accounts before hitting the 55s ceiling.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def scrape_one(uid_acc):
        uid, acc = uid_acc
        uname = acc["username"]
        plat = acc.get("platform", "tiktok")
        try:
            r = scrape_single_account_for_user(uname, uid, platform=plat)
            return uid, uname, r.get("status", "error")
        except Exception as e:
            return uid, uname, f"error: {str(e)[:100]}"

    # Resolve each user's plan + admin status once. Cron runs without an
    # authenticated user, so we look it up from the DB. The cadence below
    # determines which of their accounts are "due" for re-scrape.
    conn = get_connection()
    user_meta = {}  # uid -> { plan, role, cadence_h }
    for u in users:
        uid = u["user_id"]
        row = _fetchall(conn, "SELECT plan, role FROM users WHERE id = %s", (uid,))
        plan = (row[0]["plan"] if row else None) or "starter"
        role = (row[0]["role"] if row else None) or "user"
        user_meta[uid] = {
            "plan": plan,
            "role": role,
            "cadence_h": get_scrape_cadence_hours(plan, is_admin=(role == "admin")),
        }
    conn.close()

    from datetime import datetime, timedelta

    def _is_due(acc, cadence_h):
        """Return True if this account hasn't been scraped within its cadence."""
        lu = acc.get("last_updated")
        if not lu:
            return True  # never scraped → always due
        try:
            # last_updated is stored as ISO string. Use fromisoformat for both
            # postgres timestamp and sqlite text formats; handle naive datetimes
            # as UTC since cron compares against datetime.utcnow().
            if isinstance(lu, str):
                lu_dt = datetime.fromisoformat(lu.replace("Z", "+00:00").split("+")[0])
            else:
                lu_dt = lu
            age = datetime.utcnow() - lu_dt
            return age >= timedelta(hours=cadence_h)
        except (ValueError, TypeError):
            return True  # parse failure → be safe, scrape it

    results = {}
    user_account_pairs = []  # [(user_id, account), ...]
    skipped_not_due = 0
    for user_row in users:
        uid = user_row["user_id"]
        meta = user_meta.get(uid, {"plan": "starter", "role": "user", "cadence_h": 6})
        try:
            accounts = get_all_accounts(user_id=uid)
            if platform_filter:
                accounts = [a for a in accounts if a.get("platform", "tiktok") in platform_filter]
            results[str(uid)] = {
                "accounts": len(accounts),
                "scraped": 0,
                "skipped_not_due": 0,
                "by_status": {},
                "plan": meta["plan"],
                "cadence_h": meta["cadence_h"],
            }
            for acc in accounts:
                if _is_due(acc, meta["cadence_h"]):
                    user_account_pairs.append((uid, acc))
                else:
                    results[str(uid)]["skipped_not_due"] += 1
                    skipped_not_due += 1
        except Exception as e:
            results[str(uid)] = {"error": str(e)[:200]}

    # Stale-first ordering: scrape accounts whose `last_updated` is oldest (or
    # never set) first. This guarantees that even if a cron call times out
    # before finishing all accounts, the next call picks up the ones missed
    # rather than re-scraping the same fast-completing accounts forever.
    def _staleness_key(pair):
        _, acc = pair
        lu = acc.get("last_updated")
        # NULL / never-scraped → priority 0 (most stale). Else use timestamp string
        # which sorts lexicographically same as chronologically for ISO-8601.
        return (1 if lu else 0, str(lu) if lu else "")
    user_account_pairs.sort(key=_staleness_key)

    if user_account_pairs:
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = {executor.submit(scrape_one, pair): pair for pair in user_account_pairs}
            for fut in as_completed(futures):
                if time.time() - started > max_duration:
                    results["_timeout"] = True
                    # Cancel remaining and break — any in-flight will finish on their own
                    for f in futures:
                        f.cancel()
                    break
                try:
                    uid, uname, status = fut.result(timeout=max(1, max_duration - (time.time() - started)))
                    bucket = results.get(str(uid))
                    if isinstance(bucket, dict) and "error" not in bucket:
                        bucket["scraped"] += 1
                        bucket["by_status"][status] = bucket["by_status"].get(status, 0) + 1
                except Exception as e:
                    # Future raised or timed out — record but don't crash the whole cron
                    print(f"[cron] future error: {e}")

    elapsed = round(time.time() - started, 1)
    label = ", ".join(platform_filter) if platform_filter else "all"
    return jsonify({
        "status": "ok",
        "platforms": label,
        "users": len(users),
        "results": results,
        "skipped_not_due_total": skipped_not_due,
        "elapsed_s": elapsed,
    })


@app.route("/api/cron/daily-scrape", methods=["GET"])
@limiter.limit("20 per hour", key_func=get_remote_address)
def api_cron_daily_scrape():
    """Legacy endpoint — scrapes all platforms."""
    err = _cron_auth_check()
    if err:
        return err
    return _cron_scrape(platform_filter=None)


@app.route("/api/cron/scrape-tiktok-youtube", methods=["GET"])
@limiter.limit("20 per hour", key_func=get_remote_address)
def api_cron_scrape_tiktok_youtube():
    """Hourly cron — TikTok + YouTube + LinkedIn.

    Route name kept for backwards-compat with the existing GitHub Actions
    workflow + .env-pinned monitors. LinkedIn was added 2026-05-11 because
    it had no cron of its own and was drifting >24h stale.
    """
    err = _cron_auth_check()
    if err:
        return err
    return _cron_scrape(platform_filter=["tiktok", "youtube", "linkedin"])


@app.route("/api/cron/scrape-instagram", methods=["GET"])
@limiter.limit("20 per hour", key_func=get_remote_address)
def api_cron_scrape_instagram():
    """Twice daily cron (9h & 18h) — Instagram only."""
    err = _cron_auth_check()
    if err:
        return err
    return _cron_scrape(platform_filter=["instagram"])


# ──────────────────────────────────────────────
# ANALYTICS ENDPOINTS
# ──────────────────────────────────────────────

@app.route("/api/analytics/hashtags", methods=["GET"])
@login_required
def api_analytics_hashtags():
    """Top hashtags ranked by composite score."""
    days = int(request.args.get("days", 30))
    data = compute_hashtag_stats(user_id=current_user.data_user_id, days=days)
    return jsonify(data)


@app.route("/api/analytics/virality", methods=["GET"])
@login_required
def api_analytics_virality():
    """Videos ranked by virality score."""
    days = int(request.args.get("days", 30))
    limit = int(request.args.get("limit", 20))
    data = get_viral_videos(user_id=current_user.data_user_id, limit=limit, days=days)
    return jsonify(data)


@app.route("/api/analytics/trends", methods=["GET"])
@login_required
def api_analytics_trends():
    """Emerging trends: hashtags, formats, week-over-week metrics."""
    data = detect_trends(user_id=current_user.data_user_id)
    return jsonify(data)


@app.route("/api/analytics/growth", methods=["GET"])
@login_required
def api_analytics_growth():
    """Growth metrics per account (followers, engagement, posting frequency)."""
    days = int(request.args.get("days", 30))
    data = get_growth_metrics(user_id=current_user.data_user_id, days=days)
    return jsonify(data)


@app.route("/api/analytics/top-content", methods=["GET"])
@login_required
def api_analytics_top_content():
    """Top & flop content by virality score."""
    days = int(request.args.get("days", 30))
    limit = int(request.args.get("limit", 10))
    data = get_top_content(user_id=current_user.data_user_id, days=days, limit=limit)
    return jsonify(data)


@app.route("/api/analytics/insights", methods=["GET"])
@login_required
def api_analytics_insights():
    """Auto-generated marketing insights and recommendations."""
    data = generate_insights(user_id=current_user.data_user_id)
    return jsonify(data)


@app.route("/api/analytics/report", methods=["GET"])
@login_required
def api_analytics_report():
    """Full analysis pipeline — consolidated report."""
    data = run_full_analysis(user_id=current_user.data_user_id)
    return jsonify(data)


@app.route("/api/import-csv", methods=["POST"])
@login_required
def api_import_csv():
    # Plan limit: import CSV reserve au plan Entreprises
    if not current_user.is_admin:
        plan = _current_plan()
        if not plan.get("import_csv"):
            return jsonify({
                "error": f"Limport CSV est reserve au plan Entreprises.",
                "upgrade_required": True
            }), 403

    if "file" not in request.files:
        return jsonify({"error": "Aucun fichier fourni"}), 400

    file = request.files["file"]
    if not file.filename.endswith(".csv"):
        return jsonify({"error": "Le fichier doit etre un CSV"}), 400

    try:
        stream = io.StringIO(file.stream.read().decode("utf-8-sig"))
        reader = csv.DictReader(stream, delimiter=";")
        count = 0
        usernames_seen = set()

        for row in reader:
            username = row.get("username", "").strip().lstrip("@")
            video_id = row.get("video_id", "").strip()
            if not username or not video_id:
                continue

            usernames_seen.add(username)

            upsert_video(
                video_id=video_id,
                account_username=username,
                description=row.get("description", ""),
                create_time=row.get("date", None),
                views=int(row.get("views", 0) or 0),
                likes=int(row.get("likes", 0) or 0),
                comments=int(row.get("comments", 0) or 0),
                shares=int(row.get("shares", 0) or 0),
                saves=int(row.get("saves", 0) or 0),
                user_id=current_user.data_user_id,
            )
            upsert_account(username=username, display_name=username, user_id=current_user.data_user_id)
            count += 1

        for username in usernames_seen:
            save_daily_snapshot(username, user_id=current_user.data_user_id)

        return jsonify({"status": "success", "imported": count})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export-csv")
@login_required
def api_export_csv():
    # Plan limit: export CSV (Pro + Agency)
    if not current_user.is_admin:
        plan = _current_plan()
        if not plan.get("export_csv"):
            return jsonify({
                "error": f"Lexport CSV est disponible sur le plan Pro ou Entreprises.",
                "upgrade_required": True
            }), 403

    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)

    project_usernames = _resolve_project_usernames(current_user.data_user_id, request.args.get("project_id"))
    videos = get_videos(account, date_from, date_to, user_id=current_user.data_user_id, account_usernames=project_usernames)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["username", "video_id", "description", "date", "views", "likes",
                      "comments", "shares", "saves", "video_url"])

    for v in videos:
        writer.writerow([
            v["account_username"], v["video_id"], v["description"],
            v["create_time"], v["views"], v["likes"], v["comments"],
            v["shares"], v["saves"], v["video_url"],
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=tiktok_export.csv"},
    )


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Tracking Lab")
    print("  http://localhost:5555")
    print("=" * 60 + "\n")
    app.run(debug=True, port=5555, host="0.0.0.0")
