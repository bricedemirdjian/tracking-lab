import os
import json
from datetime import datetime, timedelta

# ==================== Dual backend: PostgreSQL (Supabase) or SQLite ====================

DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    print("[DB] Using PostgreSQL (Supabase)")
else:
    import sqlite3
    print("[DB] Using SQLite (local)")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tiktok_tracking.db")


def get_connection():
    if DATABASE_URL:
        from urllib.parse import urlparse, unquote
        parsed = urlparse(DATABASE_URL)
        username = unquote(parsed.username or '')
        password = unquote(parsed.password or '')
        host = parsed.hostname or ''
        port = parsed.port or 5432
        dbname = (parsed.path or '/postgres').lstrip('/')
        print(f"[DB] Connecting as user={username} to {host}:{port}/{dbname}")
        conn = psycopg2.connect(
            user=username,
            password=password,
            host=host,
            port=port,
            dbname=dbname,
            sslmode='require'
        )
        return conn
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _q(query):
    """Convert %s placeholders to ? for SQLite. Write all queries with %s."""
    if not DATABASE_URL:
        return query.replace('%s', '?')
    return query


def _cur(conn):
    """Get a dict-returning cursor."""
    if DATABASE_URL:
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn.cursor()


def _fetchone(conn, query, params=None):
    cur = _cur(conn)
    cur.execute(_q(query), params or ())
    row = cur.fetchone()
    return dict(row) if row else None


def _fetchall(conn, query, params=None):
    cur = _cur(conn)
    cur.execute(_q(query), params or ())
    return [dict(r) for r in cur.fetchall()]


def _execute(conn, query, params=None):
    cur = _cur(conn)
    cur.execute(_q(query), params or ())
    return cur


def _date_cast(column):
    """Cast column to text for date comparison (PostgreSQL returns timestamp, not text)."""
    if DATABASE_URL:
        return f"CAST({column} AS TEXT)"
    return column


# ==================== Schema ====================

def init_db():
    conn = get_connection()

    auto_id = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"

    _execute(conn, f"""
        CREATE TABLE IF NOT EXISTS users (
            id {auto_id},
            google_id TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            name TEXT,
            avatar_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    """)

    _execute(conn, f"""
        CREATE TABLE IF NOT EXISTS accounts (
            id {auto_id},
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

    _execute(conn, f"""
        CREATE TABLE IF NOT EXISTS videos (
            id {auto_id},
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

    _execute(conn, f"""
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            id {auto_id},
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

    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_videos_account ON videos(account_username)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_videos_create_time ON videos(create_time)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(snapshot_date)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_videos_user ON videos(user_id)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_snapshots_user ON daily_snapshots(user_id)")

    conn.commit()
    conn.close()

    # SQLite-only migration for old schemas
    if not DATABASE_URL:
        migrate_db()


def migrate_db():
    """Migrate existing SQLite database to multi-user schema if needed."""
    conn = get_connection()
    cursor = conn.cursor()

    columns = [col[1] for col in cursor.execute("PRAGMA table_info(accounts)").fetchall()]
    if "user_id" not in columns:
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
    _execute(conn, """
        INSERT INTO users (google_id, email, name, avatar_url, last_login)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT(google_id) DO UPDATE SET
            email = excluded.email,
            name = COALESCE(excluded.name, users.name),
            avatar_url = COALESCE(excluded.avatar_url, users.avatar_url),
            last_login = excluded.last_login
    """, (google_id, email, name, avatar_url, datetime.now().isoformat()))
    conn.commit()
    user = _fetchone(conn, "SELECT * FROM users WHERE google_id = %s", (google_id,))
    conn.close()
    return user


def get_user_by_id(user_id):
    conn = get_connection()
    user = _fetchone(conn, "SELECT * FROM users WHERE id = %s", (user_id,))
    conn.close()
    return user


# ==================== Account management ====================

def add_tracked_account(user_id, username):
    conn = get_connection()
    _execute(conn, """
        INSERT INTO accounts (username, display_name, user_id, last_updated)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (username, user_id) DO NOTHING
    """, (username, username, user_id, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def remove_tracked_account(user_id, username):
    conn = get_connection()
    _execute(conn, "DELETE FROM daily_snapshots WHERE account_username = %s AND user_id = %s", (username, user_id))
    _execute(conn, "DELETE FROM videos WHERE account_username = %s AND user_id = %s", (username, user_id))
    _execute(conn, "DELETE FROM accounts WHERE username = %s AND user_id = %s", (username, user_id))
    conn.commit()
    conn.close()


# ==================== Data functions (all filtered by user_id) ====================

def upsert_account(username, display_name=None, avatar_url=None, followers=0, following=0, total_likes=0, bio=None, user_id=None):
    conn = get_connection()
    _execute(conn, """
        INSERT INTO accounts (username, display_name, avatar_url, followers, following, total_likes, bio, last_updated, user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(username, user_id) DO UPDATE SET
            display_name = COALESCE(excluded.display_name, accounts.display_name),
            avatar_url = COALESCE(excluded.avatar_url, accounts.avatar_url),
            followers = excluded.followers,
            following = excluded.following,
            total_likes = excluded.total_likes,
            bio = COALESCE(excluded.bio, accounts.bio),
            last_updated = excluded.last_updated
    """, (username, display_name, avatar_url, followers, following, total_likes, bio, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()


def upsert_video(video_id, account_username, description="", create_time=None, duration=0,
                 views=0, likes=0, comments=0, shares=0, saves=0, thumbnail_url=None, video_url=None, user_id=None):
    conn = get_connection()
    _execute(conn, """
        INSERT INTO videos (video_id, account_username, description, create_time, duration,
                           views, likes, comments, shares, saves, thumbnail_url, video_url, last_updated, user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(video_id, user_id) DO UPDATE SET
            description = COALESCE(excluded.description, videos.description),
            views = excluded.views,
            likes = excluded.likes,
            comments = excluded.comments,
            shares = excluded.shares,
            saves = excluded.saves,
            thumbnail_url = COALESCE(excluded.thumbnail_url, videos.thumbnail_url),
            last_updated = excluded.last_updated
    """, (video_id, account_username, description, create_time, duration,
          views, likes, comments, shares, saves, thumbnail_url, video_url, datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()


def save_daily_snapshot(account_username, user_id=None):
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")

    query = "SELECT COUNT(*) as total_videos, COALESCE(SUM(views), 0) as total_views, COALESCE(SUM(likes), 0) as total_likes, COALESCE(SUM(comments), 0) as total_comments, COALESCE(SUM(shares), 0) as total_shares, COALESCE(SUM(saves), 0) as total_saves FROM videos WHERE account_username = %s"
    params = [account_username]
    if user_id is not None:
        query += " AND user_id = %s"
        params.append(user_id)

    stats = _fetchone(conn, query, params)

    acc_query = "SELECT followers FROM accounts WHERE username = %s"
    acc_params = [account_username]
    if user_id is not None:
        acc_query += " AND user_id = %s"
        acc_params.append(user_id)

    account = _fetchone(conn, acc_query, acc_params)
    followers = account["followers"] if account else 0

    total_views = stats["total_views"]
    total_engagement = stats["total_likes"] + stats["total_comments"] + stats["total_shares"] + stats["total_saves"]
    engagement_rate = (total_engagement / total_views * 100) if total_views > 0 else 0

    _execute(conn, """
        INSERT INTO daily_snapshots (account_username, snapshot_date, total_videos, total_views,
                                    total_likes, total_comments, total_shares, total_saves, followers, engagement_rate, user_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        results = _fetchall(conn, "SELECT * FROM accounts WHERE user_id = %s ORDER BY username", (user_id,))
    else:
        results = _fetchall(conn, "SELECT * FROM accounts ORDER BY username")
    conn.close()
    return results


def get_videos(account_username=None, date_from=None, date_to=None, sort_by="create_time", sort_order="DESC", user_id=None):
    conn = get_connection()
    query = "SELECT * FROM videos WHERE 1=1"
    params = []

    if user_id is not None:
        query += " AND user_id = %s"
        params.append(user_id)
    if account_username and account_username != "all":
        query += " AND account_username = %s"
        params.append(account_username)
    if date_from:
        query += f" AND {_date_cast('create_time')} >= %s"
        params.append(date_from)
    if date_to:
        query += f" AND {_date_cast('create_time')} <= %s"
        params.append(date_to + "T23:59:59")

    allowed_sorts = {"create_time", "views", "likes", "comments", "shares", "saves"}
    if sort_by not in allowed_sorts:
        sort_by = "create_time"
    if sort_order not in ("ASC", "DESC"):
        sort_order = "DESC"
    query += f" ORDER BY {sort_by} {sort_order}"

    results = _fetchall(conn, query, params)
    conn.close()
    return results


def _compute_period_deltas(date_from, date_to, user_id=None, account_username=None):
    """Compute engagement deltas between two dates using daily_snapshots.
    Returns dict keyed by account_username with deltas for all metrics.

    Logic: delta = snapshot_at(date_to) - snapshot_before(date_from)
    This gives the engagement GAINED during the period, regardless of when videos were posted.
    """
    conn = get_connection()
    query = """
        SELECT account_username, snapshot_date, total_videos, total_views,
               total_likes, total_comments, total_shares, total_saves
        FROM daily_snapshots WHERE 1=1
    """
    params = []
    if user_id is not None:
        query += " AND user_id = %s"
        params.append(user_id)
    if account_username and account_username != "all":
        query += " AND account_username = %s"
        params.append(account_username)
    query += " ORDER BY account_username, snapshot_date ASC"

    snapshots = _fetchall(conn, query, params)
    conn.close()

    if not snapshots:
        return {}

    # Check if we have at least 2 different snapshot dates
    # With only 1 date, deltas can't provide meaningful filtering
    unique_dates = set()
    for s in snapshots:
        # PostgreSQL returns date objects, SQLite returns strings
        d = s['snapshot_date']
        unique_dates.add(str(d))
    if len(unique_dates) < 2:
        return {}

    # Group by account
    account_snaps = {}
    for s in snapshots:
        acc = s['account_username']
        # Normalize snapshot_date to string for comparison
        s['snapshot_date'] = str(s['snapshot_date'])
        if acc not in account_snaps:
            account_snaps[acc] = []
        account_snaps[acc].append(s)

    metrics = ['total_videos', 'total_views', 'total_likes', 'total_comments', 'total_shares', 'total_saves']
    results = {}

    for acc, snaps in account_snaps.items():
        # Find end snapshot: latest snapshot ON or BEFORE date_to
        end_snap = None
        if date_to:
            for s in reversed(snaps):
                if s['snapshot_date'] <= date_to:
                    end_snap = s
                    break
        else:
            end_snap = snaps[-1] if snaps else None

        # Find start snapshot: latest snapshot STRICTLY BEFORE date_from
        start_snap = None
        if date_from:
            for s in reversed(snaps):
                if s['snapshot_date'] < date_from:
                    start_snap = s
                    break

        if end_snap is None:
            continue

        # If date_from is set but no snapshot exists before that date,
        # we can't compute a meaningful delta → skip and let fallback handle it
        if date_from and start_snap is None:
            continue

        delta = {'account_username': acc}
        for m in metrics:
            end_val = end_snap.get(m, 0) or 0
            start_val = (start_snap.get(m, 0) or 0) if start_snap else 0
            delta[m] = max(0, end_val - start_val)

        current_videos = end_snap.get('total_videos', 0) or 1
        delta['avg_views'] = delta['total_views'] / max(1, current_videos)
        delta['avg_likes'] = delta['total_likes'] / max(1, current_videos)
        delta['avg_comments'] = delta['total_comments'] / max(1, current_videos)
        delta['avg_shares'] = delta['total_shares'] / max(1, current_videos)
        delta['avg_saves'] = delta['total_saves'] / max(1, current_videos)

        results[acc] = delta

    return results


def get_aggregated_stats(account_username=None, date_from=None, date_to=None, user_id=None):
    """Get per-account aggregated stats.
    Without dates: current totals from videos table.
    With dates: engagement GAINED during the period (deltas from daily_snapshots).
    Fallback: filter videos by create_time when no snapshots available."""

    if date_from or date_to:
        deltas = _compute_period_deltas(date_from, date_to, user_id, account_username)
        if deltas:
            return list(deltas.values())

    conn = get_connection()
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
        query += " AND user_id = %s"
        params.append(user_id)
    if account_username and account_username != "all":
        query += " AND account_username = %s"
        params.append(account_username)
    if date_from:
        query += f" AND {_date_cast('create_time')} >= %s"
        params.append(date_from)
    if date_to:
        query += f" AND {_date_cast('create_time')} <= %s"
        params.append(date_to + "T23:59:59")
    query += " GROUP BY account_username"

    results = _fetchall(conn, query, params)
    conn.close()
    return results


def get_global_stats(date_from=None, date_to=None, user_id=None):
    """Get global stats.
    Without dates: current totals from videos table.
    With dates: engagement GAINED during the period (deltas from daily_snapshots).
    Fallback: filter videos by create_time when no snapshots available."""

    if date_from or date_to:
        deltas = _compute_period_deltas(date_from, date_to, user_id)
        if deltas:
            result = {
                'total_videos': 0, 'total_views': 0, 'total_likes': 0,
                'total_comments': 0, 'total_shares': 0, 'total_saves': 0,
            }
            for acc_delta in deltas.values():
                for key in result:
                    result[key] += acc_delta.get(key, 0)
            return result

    conn = get_connection()
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
        query += " AND user_id = %s"
        params.append(user_id)
    if date_from:
        query += f" AND {_date_cast('create_time')} >= %s"
        params.append(date_from)
    if date_to:
        query += f" AND {_date_cast('create_time')} <= %s"
        params.append(date_to + "T23:59:59")

    result = _fetchone(conn, query, params)
    conn.close()
    return result


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
        query += " AND user_id = %s"
        params.append(user_id)
    if account_username and account_username != "all":
        query += " AND account_username = %s"
        params.append(account_username)
    if date_from:
        query += " AND snapshot_date >= %s"
        params.append(date_from)
    if date_to:
        query += " AND snapshot_date <= %s"
        params.append(date_to)

    query += " ORDER BY snapshot_date ASC"

    results = _fetchall(conn, query, params)
    conn.close()
    # Normalize date objects to strings for JSON serialization
    for r in results:
        if r.get('date'):
            r['date'] = str(r['date'])
    return results


def seed_user_data(user_id):
    """Seed historical data for a user if they have no accounts yet."""
    conn = get_connection()
    existing = _fetchone(conn, "SELECT COUNT(*) as cnt FROM accounts WHERE user_id = %s", (user_id,))
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

    for acc in seed.get("accounts", []):
        _execute(conn, """
            INSERT INTO accounts (username, display_name, avatar_url, followers, following, total_likes, bio, last_updated, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (username, user_id) DO NOTHING
        """, (acc["username"], acc.get("display_name"), acc.get("avatar_url"),
              acc.get("followers", 0), acc.get("following", 0), acc.get("total_likes", 0),
              acc.get("bio"), datetime.now().isoformat(), user_id))

    for vid in seed.get("videos", []):
        _execute(conn, """
            INSERT INTO videos (video_id, account_username, description, create_time, duration,
                                         views, likes, comments, shares, saves, thumbnail_url, video_url, last_updated, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (video_id, user_id) DO NOTHING
        """, (vid["video_id"], vid["account_username"], vid.get("description", ""),
              vid.get("create_time"), vid.get("duration", 0), vid.get("views", 0),
              vid.get("likes", 0), vid.get("comments", 0), vid.get("shares", 0),
              vid.get("saves", 0), vid.get("thumbnail_url"), vid.get("video_url"),
              datetime.now().isoformat(), user_id))

    for snap in seed.get("daily_snapshots", []):
        _execute(conn, """
            INSERT INTO daily_snapshots (account_username, snapshot_date, total_videos, total_views,
                                                  total_likes, total_comments, total_shares, total_saves,
                                                  followers, engagement_rate, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_username, snapshot_date, user_id) DO NOTHING
        """, (snap["account_username"], snap["snapshot_date"], snap.get("total_videos", 0),
              snap.get("total_views", 0), snap.get("total_likes", 0), snap.get("total_comments", 0),
              snap.get("total_shares", 0), snap.get("total_saves", 0), snap.get("followers", 0),
              snap.get("engagement_rate", 0), user_id))

    conn.commit()
    conn.close()
    print(f"[Seed] Done: {len(seed.get('accounts', []))} accounts, {len(seed.get('videos', []))} videos, {len(seed.get('daily_snapshots', []))} snapshots")
    return True


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
