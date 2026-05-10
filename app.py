import os
import csv
import io
import threading
import time
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
    response.headers.setdefault("X-Build-Version", "2026-05-10-chart-polish")
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
    """Standalone preview of the Salesia-cloned redesign.

    Independent route — does NOT touch /dashboard. Self-contained template
    (own CSS+JS inline). Hits /api/stats and /api/accounts via plain fetch.
    Once the user validates visually, dashboard-salesia.html can be promoted
    to dashboard.html with proper wiring of the legacy app.js handlers.
    """
    return render_template("dashboard-salesia.html", user=current_user)


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
    except Exception as e:
        app.logger.exception("swarm_metrics_failed")
        return jsonify({"error": str(e)[:200]}), 500


@app.route("/api/admin/users")
@admin_required
def api_admin_users():
    users = get_all_users()
    return jsonify(users)


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
    return render_template("billing.html", user=current_user, sub=sub, plan=plan,
                           plans=PLANS,
                           stripe_pub_key=os.environ.get('STRIPE_PUBLISHABLE_KEY'))


@app.route("/api/billing/checkout", methods=["POST"])
@login_required
def api_billing_checkout():
    plan_name = request.json.get("plan") if request.json else None
    if plan_name not in ('pro', 'agency'):
        return jsonify({"error": "Plan invalide"}), 400
    price_id = PLANS[plan_name].get('price_id')
    if not price_id:
        return jsonify({"error": "Prix non configuré"}), 500
    sub = get_user_subscription(current_user.id)
    customer_id = sub.get('stripe_customer_id')
    base_url = request.host_url.rstrip('/')
    try:
        session = create_checkout_session(
            user_email=current_user.email,
            price_id=price_id,
            success_url=f"{base_url}/billing?success=1",
            cancel_url=f"{base_url}/billing?cancelled=1",
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
                user = _fetchone(
                    conn, "SELECT id, name, email FROM users WHERE email = %s",
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

    # On Vercel: don't auto-scrape (too slow, timeout risk). User clicks "Scraper" instead.
    # Locally: scrape in background thread.
    if not os.environ.get('VERCEL'):
        user_id = current_user.data_user_id
        thread = threading.Thread(target=scrape_single_account_for_user, args=(username, user_id, platform))
        thread.start()

    return jsonify({"status": "success", "username": username})


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
    try:
        per_account = get_aggregated_stats(account, date_from, date_to, user_id=current_user.data_user_id, account_usernames=project_usernames)
        global_stats = get_global_stats(date_from, date_to, user_id=current_user.data_user_id, account_usernames=project_usernames)
    except Exception as e:
        print(f"[API] Error in /api/stats: {e}")
        global_stats = {"total_videos": 0, "total_views": 0, "total_likes": 0,
                        "total_comments": 0, "total_shares": 0, "total_saves": 0}
        per_account = []

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
    data = get_daily_evolution(account, date_from, date_to, user_id=current_user.data_user_id, account_usernames=project_usernames)
    return jsonify(data)


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
    """Hourly cron — TikTok + YouTube only."""
    err = _cron_auth_check()
    if err:
        return err
    return _cron_scrape(platform_filter=["tiktok", "youtube"])


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
