import os
import csv
import io
import threading
import time
from datetime import datetime
from flask import Flask, render_template, jsonify, request, Response
from flask_login import login_required, current_user
from database import (
    init_db, get_all_accounts, get_videos, get_aggregated_stats,
    get_global_stats, get_daily_evolution, upsert_video, upsert_account,
    save_daily_snapshot, add_tracked_account, remove_tracked_account,
)
from tiktok_scraper import scrape_all_accounts_for_user, scrape_single_account_for_user
from auth import auth_bp, init_auth

# Global scraping status tracker per user
scrape_status = {}

app = Flask(__name__)

# Production config
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tiktok-tracker-dev-secret-2024')
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')
IS_PRODUCTION = os.environ.get('RENDER', False) or os.environ.get('PRODUCTION', False)

# Debug: log OAuth config status at startup
print(f"[Config] GOOGLE_CLIENT_ID present: {app.config['GOOGLE_CLIENT_ID'] is not None}")
print(f"[Config] GOOGLE_CLIENT_SECRET present: {app.config['GOOGLE_CLIENT_SECRET'] is not None}")
print(f"[Config] SECRET_KEY length: {len(app.config['SECRET_KEY'])}")

# Initialize database and auth
init_db()
init_auth(app)
app.register_blueprint(auth_bp)


@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html", user=current_user)


@app.route("/api/accounts")
@login_required
def api_accounts():
    accounts = get_all_accounts(user_id=current_user.id)
    return jsonify(accounts)


@app.route("/api/accounts/add", methods=["POST"])
@login_required
def api_add_account():
    username = request.json.get("username", "").strip().lstrip("@").lower() if request.json else ""
    if not username:
        return jsonify({"error": "Nom d'utilisateur requis"}), 400
    add_tracked_account(user_id=current_user.id, username=username)

    # Auto-scrape the new account in background
    user_id = current_user.id
    thread = threading.Thread(target=scrape_single_account_for_user, args=(username, user_id))
    thread.start()

    return jsonify({"status": "success", "username": username})


@app.route("/api/accounts/remove", methods=["POST"])
@login_required
def api_remove_account():
    username = request.json.get("username", "").strip() if request.json else ""
    if not username:
        return jsonify({"error": "Nom d'utilisateur requis"}), 400
    remove_tracked_account(user_id=current_user.id, username=username)
    return jsonify({"status": "success"})


@app.route("/api/videos")
@login_required
def api_videos():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)
    sort_by = request.args.get("sort_by", "create_time")
    sort_order = request.args.get("sort_order", "DESC")

    videos = get_videos(account, date_from, date_to, sort_by, sort_order, user_id=current_user.id)
    return jsonify(videos)


@app.route("/api/stats")
@login_required
def api_stats():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)

    try:
        per_account = get_aggregated_stats(account, date_from, date_to, user_id=current_user.id)
        global_stats = get_global_stats(date_from, date_to, user_id=current_user.id)
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

    data = get_daily_evolution(account, date_from, date_to, user_id=current_user.id)
    return jsonify(data)


@app.route("/api/best-videos")
@login_required
def api_best_videos():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)
    limit = int(request.args.get("limit", 10))

    videos = get_videos(account, date_from, date_to, sort_by="views", sort_order="DESC", user_id=current_user.id)
    return jsonify(videos[:limit])


@app.route("/api/latest-videos")
@login_required
def api_latest_videos():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)
    limit = int(request.args.get("limit", 10))

    videos = get_videos(account, date_from, date_to, sort_by="create_time", sort_order="DESC", user_id=current_user.id)
    return jsonify(videos[:limit])


@app.route("/api/scrape", methods=["POST"])
@login_required
def api_scrape():
    username = request.json.get("username") if request.json else None
    user_id = current_user.id

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

    thread = threading.Thread(target=run_scrape)
    thread.start()

    return jsonify({"status": "started", "total": len(account_list)})


@app.route("/api/scrape-status")
@login_required
def api_scrape_status():
    user_id = current_user.id
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
                user_id=current_user.id,
            )
            upsert_account(username=username, display_name=username, user_id=current_user.id)
            count += 1

        for username in usernames_seen:
            save_daily_snapshot(username, user_id=current_user.id)

        return jsonify({"status": "success", "imported": count})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export-csv")
@login_required
def api_export_csv():
    account = request.args.get("account", "all")
    date_from = request.args.get("date_from", None)
    date_to = request.args.get("date_to", None)

    videos = get_videos(account, date_from, date_to, user_id=current_user.id)

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
