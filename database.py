import sqlite3
import os
import json
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tiktok_tracking.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Users table (Google OAuth)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            google_id TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            avatar_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            display_name TEXT,
            avatar_url TEXT,
            followers INTEGER DEFAULT 0,
            following INTEGER DEFAULT 0,
            total_likes INTEGER DEFAULT 0,
            bio TEXT,
            last_updated TIMESTAMP,
            user_id INTEGER REFERENCES users(id),
            UNIQUE(username, user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            account_username TEXT NOT NULL,
            description TEXT,
            create_time TIMESTAMP,
            duration INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            saves INTEGER DEFAULT 0,
            thumbnail_url TEXT,
            video_url TEXT,
            last_updated TIMESTAMP,
            user_id INTEGER REFERENCES users(id),
            UNIQUE(video_id, user_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_username TEXT NOT NULL,
            snapshot_date DATE NOT NULL,
            total_videos INTEGER DEFAULT 0,
            total_views INTEGER DEFAULT 0,
            total_likes INTEGER DEFAULT 0,
            total_comments INTEGER DEFAULT 0,
            total_shares INTEGER DEFAULT 0,
            total_saves INTEGER DEFAULT 0,
            followers INTEGER DEFAULT 0,
            engagement_rate REAL DEFAULT 0,
            user_id INTEGER REFERENCES users(id),
            UNIQUE(account_username, snapshot_date, user_id)
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_videos_account ON videos(account_username)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_videos_create_time ON videos(create_time)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(snapshot_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_videos_user ON videos(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_user ON daily_snapshots(user_id)")

    conn.commit()
    conn.close()

    # Run migration for existing databases
    migrate_db()


def migrate_db():
    """Migrate existing database to multi-user schema if needed."""
    conn = get_connection()
    cursor = conn.cursor()

    # Check if user_id column exists in accounts
    columns = [col[1] for col in cursor.execute("PRAGMA table_info(accounts)").fetchall()]
    if "user_id" not in columns:
        # Old schema detected - need to migrate
        print("[Migration] Adding user_id columns to existing tables...")

        try:
            cursor.execute("ALTER TABLE accounts ADD COLUMN user_id INTEGER REFERENCES users(id)")
            cursor.execute("ALTER TABLE videos ADD COLUMN user_id INTEGER REFERENCES users(id)")

            snap_columns = [col[1] for col in cursor.execute("PRAGMA table_info(daily_snapshots)").fetchall()]
            if "user_id" not in snap_columns:
                cursor.execute("ALTER TABLE daily_snapshots ADD COLUMN user_id INTEGER REFERENCES users(id)")

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_videos_user ON videos(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_user ON daily_snapshots(user_id)")

            conn.commit()
            print("[Migration] Migration complete.")
        except Exception as e:
            print(f"[Migration] Error: {e}")

    conn.close()


# ==================== User functions ====================

def create_or_update_user(google_id, email, name, avatar_url):
    conn = get_connection()
    conn.execute("""
        INSERT INTO users (google_id, email, name, avatar_url, last_login)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(google_id) DO UPDATE SET
            email = excluded.email,
            name = COALESCE(excluded.name, name),
            avatar_url = COALESCE(excluded.avatar_url, avatar_url),
            last_login = excluded.last_login
    """, (google_id, email, name, avatar_url, datetime.now().isoformat()))
    conn.commit()
    user = conn.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()
    conn.close()
    return dict(user)

def get_user_by_id(user_id):
    conn = get_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(user) if user else None


# ==================== Account management ====================

def add_tracked_account(user_id, username):
    conn = get_connection()
    conn.execute("""
        INSERT OR IGNORE INTO accounts (username, display_name, user_id, last_updated)
        VALUES (?, ?, ?, ?)
    """, (username, username, user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def remove_tracked_account(user_id, username):
    conn = get_connection()
    conn.execute("DELETE FROM daily_snapshots WHERE account_username = ? AND user_id = ?", (username, user_id))
    conn.execute("DELETE FROM videos WHERE account_username = ? AND user_id = ?", (username, user_id))
    conn.execute("DELETE FROM accounts WHERE username = ? AND user_id = ?", (username, user_id))
    conn.commit()
    conn.close()


# ==================== Data functions (all filtered by user_id) ====================

def upsert_account(username, display_name=None, avatar_url=None, followers=0, following=0, total_likes=0, bio=None, user_id=None):
    conn = get_connection()
    conn.execute("""
        INSERT INTO accounts (username, display_name, avatar_url, followers, following, total_likes, bio, last_updated, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(username, user_id) DO UPDATE SET
            display_name = COALESCE(excluded.display_name, display_name),
            avatar_url = COALESCE(excluded.avatar_url, avatar_url),
            followers = excluded.followers,
            following = excluded.following,
            total_likes = excluded.total_likes,
            bio = COALESCE(excluded.bio, bio),
            last_updated = excluded.last_updated
    """, (username, display_name, avatar_url, followers, following, total_likes, bio, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

def upsert_video(video_id, account_username, description="", create_time=None, duration=0,
                 views=0, likes=0, comments=0, shares=0, saves=0, thumbnail_url=None, video_url=None, user_id=None):
    conn = get_connection()
    conn.execute("""
        INSERT INTO videos (video_id, account_username, description, create_time, duration,
                           views, likes, comments, shares, saves, thumbnail_url, video_url, last_updated, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_id, user_id) DO UPDATE SET
            description = COALESCE(excluded.description, description),
            views = excluded.views,
            likes = excluded.likes,
            comments = excluded.comments,
            shares = excluded.shares,
            saves = excluded.saves,
            thumbnail_url = COALESCE(excluded.thumbnail_url, thumbnail_url),
            last_updated = excluded.last_updated
    """, (video_id, account_username, description, create_time, duration,
          views, likes, comments, shares, saves, thumbnail_url, video_url, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

def save_daily_snapshot(account_username, user_id=None):
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor = conn.cursor()

    query = "SELECT COUNT(*) as total_videos, COALESCE(SUM(views), 0) as total_views, COALESCE(SUM(likes), 0) as total_likes, COALESCE(SUM(comments), 0) as total_comments, COALESCE(SUM(shares), 0) as total_shares, COALESCE(SUM(saves), 0) as total_saves FROM videos WHERE account_username = ?"
    params = [account_username]
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(user_id)

    cursor.execute(query, params)
    stats = cursor.fetchone()

    acc_query = "SELECT followers FROM accounts WHERE username = ?"
    acc_params = [account_username]
    if user_id is not None:
        acc_query += " AND user_id = ?"
        acc_params.append(user_id)

    cursor.execute(acc_query, acc_params)
    account = cursor.fetchone()
    followers = account["followers"] if account else 0

    total_views = stats["total_views"]
    total_engagement = stats["total_likes"] + stats["total_comments"] + stats["total_shares"] + stats["total_saves"]
    engagement_rate = (total_engagement / total_views * 100) if total_views > 0 else 0

    conn.execute("""
        INSERT INTO daily_snapshots (account_username, snapshot_date, total_videos, total_views,
                                    total_likes, total_comments, total_shares, total_saves, followers, engagement_rate, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_username, snapshot_date, user_id) DO UPDATE SET
            total_videos = excluded.total_videos,
            total_views = excluded.total_views,
            total_likes = excluded.total_likes,
            total_comments = excluded.total_comments,
            total_shares = excluded.total_shares,
            total_saves = excluded.total_saves,
            followers = excluded.followers,
            engagement_rate = excluded.engagement_rate
    """, (account_username, today, stats["total_videos"], total_views,
          stats["total_likes"], stats["total_comments"], stats["total_shares"],
          stats["total_saves"], followers, engagement_rate, user_id))
    conn.commit()
    conn.close()

def get_all_accounts(user_id=None):
    conn = get_connection()
    if user_id is not None:
        accounts = conn.execute("SELECT * FROM accounts WHERE user_id = ? ORDER BY username", (user_id,)).fetchall()
    else:
        accounts = conn.execute("SELECT * FROM accounts ORDER BY username").fetchall()
    conn.close()
    return [dict(a) for a in accounts]

def get_videos(account_username=None, date_from=None, date_to=None, sort_by="create_time", sort_order="DESC", user_id=None):
    conn = get_connection()
    query = "SELECT * FROM videos WHERE 1=1"
    params = []

    if user_id is not None:
        query += " AND user_id = ?"
        params.append(user_id)
    if account_username and account_username != "all":
        query += " AND account_username = ?"
        params.append(account_username)
    if date_from:
        query += " AND create_time >= ?"
        params.append(date_from)
    if date_to:
        query += " AND create_time <= ?"
        params.append(date_to + " 23:59:59")

    allowed_sorts = {"create_time", "views", "likes", "comments", "shares", "saves"}
    if sort_by not in allowed_sorts:
        sort_by = "create_time"
    if sort_order not in ("ASC", "DESC"):
        sort_order = "DESC"
    query += f" ORDER BY {sort_by} {sort_order}"

    videos = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(v) for v in videos]

def get_aggregated_stats(account_username=None, date_from=None, date_to=None, user_id=None):
    conn = get_connection()

    if date_from or date_to:
        # Use daily_snapshots: get the LATEST snapshot within the date range per account
        query = """
            SELECT
                s.account_username,
                s.total_videos,
                s.total_views,
                s.total_likes,
                s.total_comments,
                s.total_shares,
                s.total_saves,
                CASE WHEN s.total_videos > 0 THEN CAST(s.total_views AS REAL) / s.total_videos ELSE 0 END as avg_views,
                CASE WHEN s.total_videos > 0 THEN CAST(s.total_likes AS REAL) / s.total_videos ELSE 0 END as avg_likes,
                CASE WHEN s.total_videos > 0 THEN CAST(s.total_comments AS REAL) / s.total_videos ELSE 0 END as avg_comments,
                CASE WHEN s.total_videos > 0 THEN CAST(s.total_shares AS REAL) / s.total_videos ELSE 0 END as avg_shares,
                CASE WHEN s.total_videos > 0 THEN CAST(s.total_saves AS REAL) / s.total_videos ELSE 0 END as avg_saves
            FROM daily_snapshots s
            INNER JOIN (
                SELECT account_username, MAX(snapshot_date) as max_date
                FROM daily_snapshots WHERE 1=1
        """
        params = []
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        if account_username and account_username != "all":
            query += " AND account_username = ?"
            params.append(account_username)
        if date_from:
            query += " AND snapshot_date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND snapshot_date <= ?"
            params.append(date_to)
        query += " GROUP BY account_username"
        query += """
            ) latest ON s.account_username = latest.account_username AND s.snapshot_date = latest.max_date
        """
        if user_id is not None:
            query += " WHERE s.user_id = ?"
            params.append(user_id)
    else:
        # No date filter: use current video stats
        query = """
            SELECT
                account_username,
                COUNT(*) as total_videos,
                COALESCE(SUM(views), 0) as total_views,
                COALESCE(SUM(likes), 0) as total_likes,
                COALESCE(SUM(comments), 0) as total_comments,
                COALESCE(SUM(shares), 0) as total_shares,
                COALESCE(SUM(saves), 0) as total_saves,
                COALESCE(AVG(views), 0) as avg_views,
                COALESCE(AVG(likes), 0) as avg_likes,
                COALESCE(AVG(comments), 0) as avg_comments,
                COALESCE(AVG(shares), 0) as avg_shares,
                COALESCE(AVG(saves), 0) as avg_saves
            FROM videos WHERE 1=1
        """
        params = []
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        if account_username and account_username != "all":
            query += " AND account_username = ?"
            params.append(account_username)
        query += " GROUP BY account_username"

    results = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in results]

def get_global_stats(date_from=None, date_to=None, user_id=None):
    conn = get_connection()

    if date_from or date_to:
        # Use daily_snapshots: get the LATEST snapshot per account within range, then sum
        query = """
            SELECT
                COALESCE(SUM(s.total_videos), 0) as total_videos,
                COALESCE(SUM(s.total_views), 0) as total_views,
                COALESCE(SUM(s.total_likes), 0) as total_likes,
                COALESCE(SUM(s.total_comments), 0) as total_comments,
                COALESCE(SUM(s.total_shares), 0) as total_shares,
                COALESCE(SUM(s.total_saves), 0) as total_saves
            FROM daily_snapshots s
            INNER JOIN (
                SELECT account_username, MAX(snapshot_date) as max_date
                FROM daily_snapshots WHERE 1=1
        """
        params = []
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)
        if date_from:
            query += " AND snapshot_date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND snapshot_date <= ?"
            params.append(date_to)
        query += " GROUP BY account_username"
        query += """
            ) latest ON s.account_username = latest.account_username AND s.snapshot_date = latest.max_date
        """
        if user_id is not None:
            query += " WHERE s.user_id = ?"
            params.append(user_id)
    else:
        # No date filter: use current video stats
        query = """
            SELECT
                COUNT(*) as total_videos,
                COALESCE(SUM(views), 0) as total_views,
                COALESCE(SUM(likes), 0) as total_likes,
                COALESCE(SUM(comments), 0) as total_comments,
                COALESCE(SUM(shares), 0) as total_shares,
                COALESCE(SUM(saves), 0) as total_saves
            FROM videos WHERE 1=1
        """
        params = []
        if user_id is not None:
            query += " AND user_id = ?"
            params.append(user_id)

    result = conn.execute(query, params).fetchone()
    conn.close()
    return dict(result)

def get_daily_evolution(account_username=None, date_from=None, date_to=None, user_id=None):
    """Get daily evolution from daily_snapshots (stats by scraping date, not video publication date)."""
    conn = get_connection()
    query = """
        SELECT
            snapshot_date as date,
            account_username,
            total_videos as videos,
            total_views as views,
            total_likes as likes,
            total_comments as comments,
            total_shares as shares,
            total_saves as saves
        FROM daily_snapshots WHERE 1=1
    """
    params = []
    if user_id is not None:
        query += " AND user_id = ?"
        params.append(user_id)
    if account_username and account_username != "all":
        query += " AND account_username = ?"
        params.append(account_username)
    if date_from:
        query += " AND snapshot_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND snapshot_date <= ?"
        params.append(date_to)

    query += " ORDER BY snapshot_date ASC"

    results = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in results]

def seed_user_data(user_id):
    """Seed historical data for a user if they have no accounts yet."""
    conn = get_connection()
    existing = conn.execute("SELECT COUNT(*) as cnt FROM accounts WHERE user_id = ?", (user_id,)).fetchone()
    if existing["cnt"] > 0:
        conn.close()
        return False

    seed_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_data.json")
    if not os.path.exists(seed_path):
        conn.close()
        return False

    print(f"[Seed] Importing historical data for user {user_id}...")
    with open(seed_path, "r", encoding="utf-8") as f:
        seed = json.load(f)

    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF")

    for acc in seed.get("accounts", []):
        cursor.execute("""
            INSERT OR IGNORE INTO accounts (username, display_name, avatar_url, followers, following, total_likes, bio, last_updated, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (acc["username"], acc.get("display_name"), acc.get("avatar_url"),
              acc.get("followers", 0), acc.get("following", 0), acc.get("total_likes", 0),
              acc.get("bio"), datetime.now().isoformat(), user_id))

    for vid in seed.get("videos", []):
        cursor.execute("""
            INSERT OR IGNORE INTO videos (video_id, account_username, description, create_time, duration,
                                         views, likes, comments, shares, saves, thumbnail_url, video_url, last_updated, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (vid["video_id"], vid["account_username"], vid.get("description", ""),
              vid.get("create_time"), vid.get("duration", 0), vid.get("views", 0),
              vid.get("likes", 0), vid.get("comments", 0), vid.get("shares", 0),
              vid.get("saves", 0), vid.get("thumbnail_url"), vid.get("video_url"),
              datetime.now().isoformat(), user_id))

    for snap in seed.get("daily_snapshots", []):
        cursor.execute("""
            INSERT OR IGNORE INTO daily_snapshots (account_username, snapshot_date, total_videos, total_views,
                                                  total_likes, total_comments, total_shares, total_saves,
                                                  followers, engagement_rate, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (snap["account_username"], snap["snapshot_date"], snap.get("total_videos", 0),
              snap.get("total_views", 0), snap.get("total_likes", 0), snap.get("total_comments", 0),
              snap.get("total_shares", 0), snap.get("total_saves", 0), snap.get("followers", 0),
              snap.get("engagement_rate", 0), user_id))

    cursor.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    conn.close()
    print(f"[Seed] Done: {len(seed.get('accounts', []))} accounts, {len(seed.get('videos', []))} videos, {len(seed.get('daily_snapshots', []))} snapshots")
    return True


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
