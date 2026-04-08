import os
import csv
import io
import threading
import time
import stripe
from datetime import datetime
from flask import Flask, render_template, jsonify, request, Response, redirect, url_for
from flask_login import login_required, current_user
from database import (
    init_db, get_all_accounts, get_videos, get_aggregated_stats,
    get_global_stats, get_daily_evolution, upsert_video, upsert_account,
    save_daily_snapshot, add_tracked_account, remove_tracked_account,
    create_project, rename_project, delete_project, get_projects,
    get_project_accounts, set_project_accounts, get_account_usernames_for_project,
    get_all_users, set_user_blocked, set_user_role, delete_user_and_data,
    get_user_subscription, upsert_subscription, get_subscription_by_customer,
)
from functools import wraps
from tiktok_scraper import scrape_all_accounts_for_user, scrape_single_account_for_user
from auth import auth_bp, init_auth
from stripe_billing import PLANS, get_plan, create_checkout_session, create_portal_session, get_price_plan

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# Global scraping status tracker per user
scrape_status = {}

app = Flask(__name__)

# Production config
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tiktok-tracker-dev-secret-2024')
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')
IS_PRODUCTION = os.environ.get('RENDER', False) or os.environ.get('PRODUCTION', False) or os.environ.get('VERCEL', False)

# Debug: log OAuth config status at startup
print(f"[Config] GOOGLE_CLIENT_ID present: {app.config['GOOGLE_CLIENT_ID'] is not None}")
print(f"[Config] GOOGLE_CLIENT_SECRET present: {app.config['GOOGLE_CLIENT_SECRET'] is not None}")
print(f"[Config] SECRET_KEY length: {len(app.config['SECRET_KEY'])}")

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


@app.route("/")
def index():
    if current_user.is_authenticated:
        return render_template("dashboard.html", user=current_user)
    return render_template("landing.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", user=current_user)


@app.route("/admin")
@login_required
def admin_page():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    return render_template("admin.html", user=current_user)


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
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET')
    try:
        if webhook_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        else:
            event = stripe.Event.construct_from(request.json, stripe.api_key)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if event.type == 'checkout.session.completed':
        session = event.data.object
        customer_id = session.get('customer')
        subscription_id = session.get('subscription')
        customer_email = session.get('customer_email') or session.get('customer_details', {}).get('email')
        if subscription_id:
            sub = stripe.Subscription.retrieve(subscription_id)
            price_id = sub['items']['data'][0]['price']['id']
            plan_name = get_price_plan(price_id)
            period_end = datetime.fromtimestamp(sub['current_period_end']).isoformat()
            # Find user by email
            from database import get_connection, _fetchone, _q
            conn = get_connection()
            user = _fetchone(conn, "SELECT id FROM users WHERE email = %s", (customer_email,))
            conn.close()
            if user:
                upsert_subscription(user['id'], plan_name, 'active',
                                    stripe_customer_id=customer_id,
                                    stripe_subscription_id=subscription_id,
                                    current_period_end=period_end)

    elif event.type in ('customer.subscription.updated', 'customer.subscription.deleted'):
        sub = event.data.object
        customer_id = sub.get('customer')
        status = sub.get('status')
        plan_name = 'starter'
        if status == 'active':
            price_id = sub['items']['data'][0]['price']['id']
            plan_name = get_price_plan(price_id)
        db_sub = get_subscription_by_customer(customer_id)
        if db_sub:
            period_end = datetime.fromtimestamp(sub.get('current_period_end', 0)).isoformat()
            upsert_subscription(db_sub['user_id'], plan_name,
                                'active' if status == 'active' else 'cancelled',
                                stripe_subscription_id=sub.id,
                                current_period_end=period_end)

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


@app.route("/api/projects/<int:project_id>/accounts")
@login_required
def api_project_accounts(project_id):
    accounts = get_project_accounts(project_id)
    return jsonify(accounts)


@app.route("/api/projects/<int:project_id>/accounts", methods=["POST"])
@login_required
def api_set_project_accounts(project_id):
    account_ids = request.json.get("account_ids", []) if request.json else []
    set_project_accounts(project_id, account_ids)
    return jsonify({"status": "success"})


# ==================== Account routes ====================

@app.route("/api/accounts")
@login_required
def api_accounts():
    project_id = request.args.get("project_id", None)
    if project_id and project_id != "all":
        accounts = get_project_accounts(int(project_id))
    else:
        accounts = get_all_accounts(user_id=current_user.data_user_id)
    return jsonify(accounts)


@app.route("/api/accounts/add", methods=["POST"])
@login_required
def api_add_account():
    username = request.json.get("username", "").strip().lstrip("@").lower() if request.json else ""
    platform = request.json.get("platform", "tiktok") if request.json else "tiktok"
    if not username:
        return jsonify({"error": "Nom d'utilisateur requis"}), 400
    if platform not in ("tiktok", "instagram", "youtube"):
        platform = "tiktok"
    add_tracked_account(user_id=current_user.data_user_id, username=username, platform=platform)

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


@app.route("/api/videos")
@login_required
def api_videos():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)
    sort_by = request.args.get("sort_by", "create_time")
    sort_order = request.args.get("sort_order", "DESC")
    project_usernames = _resolve_project_usernames(current_user.data_user_id, request.args.get("project_id"))

    videos = get_videos(account, date_from, date_to, sort_by, sort_order, user_id=current_user.data_user_id, account_usernames=project_usernames)
    return jsonify(videos)


@app.route("/api/stats")
@login_required
def api_stats():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)

    project_usernames = _resolve_project_usernames(current_user.data_user_id, request.args.get("project_id"))
    try:
        per_account = get_aggregated_stats(account, date_from, date_to, user_id=current_user.data_user_id, account_usernames=project_usernames)
        global_stats = get_global_stats(date_from, date_to, user_id=current_user.data_user_id, account_usernames=project_usernames)
    except Exception as e:
        print(f"[API] Error in /api/stats: {e}")
        global_stats = {"total_videos": 0, "total_views": 0, "total_likes": 0,
                        "total_comments": 0, "total_shares": 0, "total_saves": 0}
        per_account = []

    # Ensure all values are numeric (PostgreSQL may return None)
    for key in ["total_videos", "total_views", "total_likes", "total_comments", "total_shares", "total_saves"]:
        global_stats[key] = global_stats.get(key) or 0

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
    data = get_daily_evolution(account, date_from, date_to, user_id=current_user.data_user_id, account_usernames=project_usernames)
    return jsonify(data)


@app.route("/api/best-videos")
@login_required
def api_best_videos():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)
    limit = int(request.args.get("limit", 10))

    project_usernames = _resolve_project_usernames(current_user.data_user_id, request.args.get("project_id"))
    videos = get_videos(account, date_from, date_to, sort_by="views", sort_order="DESC", user_id=current_user.data_user_id, account_usernames=project_usernames)
    return jsonify(videos[:limit])


@app.route("/api/latest-videos")
@login_required
def api_latest_videos():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)
    limit = int(request.args.get("limit", 10))

    project_usernames = _resolve_project_usernames(current_user.data_user_id, request.args.get("project_id"))
    videos = get_videos(account, date_from, date_to, sort_by="create_time", sort_order="DESC", user_id=current_user.data_user_id, account_usernames=project_usernames, exclude_no_date=True)
    return jsonify(videos[:limit])


@app.route("/api/posts-per-day")
@login_required
def api_posts_per_day():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)
    project_usernames = _resolve_project_usernames(current_user.data_user_id, request.args.get("project_id"))
    videos = get_videos(account, date_from, date_to, sort_by="create_time", sort_order="ASC", user_id=current_user.data_user_id, account_usernames=project_usernames, exclude_no_date=True)

    # Group by date and account+platform
    day_map = {}
    for v in videos:
        if not v.get("create_time"):
            continue
        date_str = str(v["create_time"])[:10]
        key = v["account_username"] + ":" + (v.get("platform") or "tiktok")
        if date_str not in day_map:
            day_map[date_str] = {}
        day_map[date_str][key] = day_map[date_str].get(key, 0) + 1

    return jsonify(day_map)


@app.route("/api/scrape", methods=["POST"])
@login_required
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
                on_account_done(username, result.get("status") == "success", result.get("videos", 0))
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
            result = scrape_single_account_for_user(uname, user_id, platform=platform)
            on_account_done(uname, result.get("status") == "success", result.get("videos", 0))
            return result

        target_accounts = accounts if not username else [a for a in accounts if a["username"] == username]
        with ThreadPoolExecutor(max_workers=6) as executor:
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


@app.route("/api/import-csv", methods=["POST"])
@login_required
def api_import_csv():
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
