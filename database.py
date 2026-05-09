import os
import json
from datetime import datetime, timedelta

# ==================== Dual backend: PostgreSQL (Supabase) or SQLite ====================

DATABASE_URL = os.environ.get('DATABASE_URL')

if DATABASE_URL:
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
    print("[DB] Using PostgreSQL (Supabase)")
else:
    import sqlite3
    print("[DB] Using SQLite (local)")


# Lazy-initialized connection pool. Each get_connection() borrows; .close() returns.
# Backed by a thin wrapper so the existing `conn.close()` API keeps working
# unchanged across all call sites — no codebase-wide refactor needed.
_pg_pool = None


def _get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        from urllib.parse import urlparse, unquote
        parsed = urlparse(DATABASE_URL)
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=int(os.environ.get("DB_POOL_MIN", "2")),
            maxconn=int(os.environ.get("DB_POOL_MAX", "20")),
            user=unquote(parsed.username or ''),
            password=unquote(parsed.password or ''),
            host=parsed.hostname or '',
            port=parsed.port or 5432,
            dbname=(parsed.path or '/postgres').lstrip('/'),
            sslmode='require',
        )
        print(f"[DB] Pool initialized (min=2, max=20) → {parsed.hostname}:{parsed.port}")
    return _pg_pool


class _PooledConn:
    """Drop-in connection wrapper. Delegates every attr to the real connection,
    routes .close() back to the pool instead of really closing the socket.
    Existing callers (`conn = get_connection(); ...; conn.close()`) work unchanged."""
    __slots__ = ("_pool", "_conn", "_returned")

    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn
        self._returned = False

    def close(self):
        if self._returned:
            return
        self._returned = True
        try:
            # If the underlying conn is in a broken state psycopg2's pool
            # discards it; otherwise it goes back to the pool for reuse.
            self._pool.putconn(self._conn)
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

# On Vercel, use /tmp for SQLite fallback (ephemeral but writable)
if os.environ.get('VERCEL'):
    DB_PATH = "/tmp/tiktok_tracking.db"
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tiktok_tracking.db")


def get_connection():
    if DATABASE_URL:
        pool = _get_pg_pool()
        return _PooledConn(pool, pool.getconn())
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


def _ts_cast():
    """Return SQL suffix to cast date parameter to timestamp for PostgreSQL."""
    if DATABASE_URL:
        return "::timestamp"
    return ""


# ==================== Schema ====================

# Bump this string whenever you add a CREATE TABLE / migration helper or
# change anything the init_db() flow does. On Vercel cold start init_db()
# does a single SELECT against schema_meta — if the stored version matches,
# every CREATE / migration is skipped (saves ~640ms per cold start). On
# version mismatch, full init runs once and writes the new value.
SCHEMA_VERSION = "2026-05-09-v1"


def _is_schema_current(conn) -> bool:
    """Single quick lookup, swallows any error (table missing on first run).
    Rolls the conn back on error so the failed SELECT doesn't poison the
    surrounding transaction (Postgres aborts the whole tx on any error)."""
    try:
        row = _fetchone(
            conn,
            "SELECT value FROM schema_meta WHERE key = %s",
            ("schema_version",),
        )
        return bool(row) and row.get("value") == SCHEMA_VERSION
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return False


def _mark_schema_current(conn):
    """Persist the version after a successful init run."""
    try:
        _execute(
            conn,
            "INSERT INTO schema_meta (key, value, updated_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
            ("schema_version", SCHEMA_VERSION, datetime.now().isoformat()),
        )
    except Exception as e:
        print(f"[Schema] Could not stamp version: {e}")


def init_db():
    conn = get_connection()

    # Fast path: schema_meta says we're already at the current version.
    # Skips ~7 CREATE TABLE IF NOT EXISTS + 8 migration helpers (~640ms).
    if _is_schema_current(conn):
        conn.close()
        return

    auto_id = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"

    # Always-present meta table (created early so subsequent runs short-circuit
    # in _is_schema_current). Tiny, single-row use case.
    _execute(conn, f"""
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

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
            UNIQUE(username, user_id, platform)
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
            platform TEXT NOT NULL DEFAULT 'tiktok',
            UNIQUE(account_username, platform, snapshot_date, user_id)
        )
    """)

    # Projects table
    _execute(conn, f"""
        CREATE TABLE IF NOT EXISTS projects (
            id {auto_id},
            user_id INTEGER REFERENCES users(id),
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, user_id)
        )
    """)

    # Junction table: project <-> accounts (many-to-many)
    _execute(conn, f"""
        CREATE TABLE IF NOT EXISTS project_accounts (
            id {auto_id},
            project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
            account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
            UNIQUE(project_id, account_id)
        )
    """)

    # Subscriptions table (one per user)
    _execute(conn, f"""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id {auto_id},
            user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            plan TEXT NOT NULL DEFAULT 'starter',
            status TEXT NOT NULL DEFAULT 'active',
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            current_period_end TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_videos_account ON videos(account_username)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_videos_create_time ON videos(create_time)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(snapshot_date)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_accounts_user ON accounts(user_id)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_videos_user ON videos(user_id)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_snapshots_user ON daily_snapshots(user_id)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_project_accounts_project ON project_accounts(project_id)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_project_accounts_account ON project_accounts(account_id)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id)")
    _execute(conn, "CREATE INDEX IF NOT EXISTS idx_subscriptions_customer ON subscriptions(stripe_customer_id)")

    conn.commit()

    # Migration: add platform column to accounts if missing
    _migrate_platform_column(conn)
    # Migration: add platform column to daily_snapshots if missing
    _migrate_snapshots_platform_column(conn)
    # Migration: add role/blocked columns to users if missing
    _migrate_user_roles(conn)
    # Migration: add plan/stripe_customer_id columns to users if missing
    _migrate_user_plan_columns(conn)
    # Migration: add is_competitor column to accounts if missing
    _migrate_competitor_column(conn)
    # Migration: add total_views/total_comments aggregated stats columns
    _migrate_engagement_totals_columns(conn)
    # Migration: composite indices used by hot dashboard queries
    _migrate_composite_indices(conn)
    # Migration: create default project for users without projects
    _migrate_default_projects(conn)

    # Stamp the version so the next cold start hits the fast-path.
    _mark_schema_current(conn)

    conn.commit()
    conn.close()

    # SQLite-only migration for old schemas
    if not DATABASE_URL:
        migrate_db()


def _migrate_platform_column(conn):
    """Add platform column to accounts table if missing."""
    try:
        if DATABASE_URL:
            cols = _fetchall(conn, "SELECT column_name FROM information_schema.columns WHERE table_name='accounts' AND column_name='platform'")
            if not cols:
                _execute(conn, "ALTER TABLE accounts ADD COLUMN platform TEXT NOT NULL DEFAULT 'tiktok'")
                print("[Migration] Added platform column to accounts (PostgreSQL)")
        else:
            cur = conn.cursor()
            columns = [col[1] for col in cur.execute("PRAGMA table_info(accounts)").fetchall()]
            if "platform" not in columns:
                cur.execute("ALTER TABLE accounts ADD COLUMN platform TEXT NOT NULL DEFAULT 'tiktok'")
                print("[Migration] Added platform column to accounts (SQLite)")
    except Exception as e:
        print(f"[Migration] platform column: {e}")


def _migrate_snapshots_platform_column(conn):
    """Add platform column to daily_snapshots table if missing."""
    try:
        if DATABASE_URL:
            cols = _fetchall(conn, "SELECT column_name FROM information_schema.columns WHERE table_name='daily_snapshots' AND column_name='platform'")
            if not cols:
                _execute(conn, "ALTER TABLE daily_snapshots ADD COLUMN platform TEXT NOT NULL DEFAULT 'tiktok'")
                print("[Migration] Added platform column to daily_snapshots (PostgreSQL)")
                # Drop old unique constraint and create new one including platform
                try:
                    _execute(conn, "ALTER TABLE daily_snapshots DROP CONSTRAINT IF EXISTS daily_snapshots_account_username_snapshot_date_user_id_key")
                    _execute(conn, "ALTER TABLE daily_snapshots ADD CONSTRAINT daily_snapshots_acc_plat_date_user_unique UNIQUE (account_username, platform, snapshot_date, user_id)")
                    print("[Migration] Updated unique constraint on daily_snapshots (PostgreSQL)")
                except Exception as e:
                    print(f"[Migration] daily_snapshots constraint: {e}")
        else:
            cur = conn.cursor()
            columns = [col[1] for col in cur.execute("PRAGMA table_info(daily_snapshots)").fetchall()]
            if "platform" not in columns:
                cur.execute("ALTER TABLE daily_snapshots ADD COLUMN platform TEXT NOT NULL DEFAULT 'tiktok'")
                print("[Migration] Added platform column to daily_snapshots (SQLite)")
    except Exception as e:
        print(f"[Migration] daily_snapshots platform column: {e}")


def _migrate_user_roles(conn):
    """Add role and blocked columns to users table if missing."""
    try:
        if DATABASE_URL:
            cols = _fetchall(conn, "SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='role'")
            if not cols:
                _execute(conn, "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
                _execute(conn, "ALTER TABLE users ADD COLUMN blocked BOOLEAN NOT NULL DEFAULT FALSE")
                print("[Migration] Added role and blocked columns to users (PostgreSQL)")
        else:
            cur = conn.cursor()
            columns = [col[1] for col in cur.execute("PRAGMA table_info(users)").fetchall()]
            if "role" not in columns:
                cur.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
                cur.execute("ALTER TABLE users ADD COLUMN blocked BOOLEAN NOT NULL DEFAULT 0")
                print("[Migration] Added role and blocked columns to users (SQLite)")
    except Exception as e:
        print(f"[Migration] user roles: {e}")


def _migrate_user_plan_columns(conn):
    """Add plan and stripe_customer_id columns to users table if missing."""
    try:
        if DATABASE_URL:
            cols = _fetchall(conn, "SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='plan'")
            if not cols:
                _execute(conn, "ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'starter'")
                print("[Migration] Added plan column to users (PostgreSQL)")
            cols = _fetchall(conn, "SELECT column_name FROM information_schema.columns WHERE table_name='users' AND column_name='stripe_customer_id'")
            if not cols:
                _execute(conn, "ALTER TABLE users ADD COLUMN stripe_customer_id TEXT")
                print("[Migration] Added stripe_customer_id column to users (PostgreSQL)")
        else:
            cur = conn.cursor()
            columns = [col[1] for col in cur.execute("PRAGMA table_info(users)").fetchall()]
            if "plan" not in columns:
                cur.execute("ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'starter'")
                print("[Migration] Added plan column to users (SQLite)")
            if "stripe_customer_id" not in columns:
                cur.execute("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT")
                print("[Migration] Added stripe_customer_id column to users (SQLite)")
    except Exception as e:
        print(f"[Migration] user plan columns: {e}")


def _migrate_competitor_column(conn):
    """Add is_competitor column to accounts table if missing."""
    try:
        if DATABASE_URL:
            cols = _fetchall(conn, "SELECT column_name FROM information_schema.columns WHERE table_name='accounts' AND column_name='is_competitor'")
            if not cols:
                _execute(conn, "ALTER TABLE accounts ADD COLUMN is_competitor BOOLEAN NOT NULL DEFAULT FALSE")
                print("[Migration] Added is_competitor column to accounts (PostgreSQL)")
        else:
            cur = conn.cursor()
            columns = [col[1] for col in cur.execute("PRAGMA table_info(accounts)").fetchall()]
            if "is_competitor" not in columns:
                cur.execute("ALTER TABLE accounts ADD COLUMN is_competitor BOOLEAN NOT NULL DEFAULT 0")
                print("[Migration] Added is_competitor column to accounts (SQLite)")
    except Exception as e:
        print(f"[Migration] is_competitor column: {e}")


def _migrate_engagement_totals_columns(conn):
    """Add aggregated stats columns to accounts (idempotent).
    BIGINT for counters, BOOLEAN/TEXT for the platform-extra metadata."""
    bigint_cols = ("total_views", "total_comments", "last_media_count", "friend_count")
    bool_cols   = ("verified", "private_account")
    text_cols   = ("region",)
    for col in bigint_cols:
        try:
            if DATABASE_URL:
                exists = _fetchall(conn, "SELECT column_name FROM information_schema.columns WHERE table_name='accounts' AND column_name=%s", (col,))
                if not exists:
                    _execute(conn, f"ALTER TABLE accounts ADD COLUMN {col} BIGINT DEFAULT 0")
                    print(f"[Migration] Added {col} column to accounts (PostgreSQL)")
            else:
                cur = conn.cursor()
                columns = [c[1] for c in cur.execute("PRAGMA table_info(accounts)").fetchall()]
                if col not in columns:
                    cur.execute(f"ALTER TABLE accounts ADD COLUMN {col} INTEGER DEFAULT 0")
                    print(f"[Migration] Added {col} column to accounts (SQLite)")
        except Exception as e:
            print(f"[Migration] {col} column: {e}")
    for col in bool_cols:
        try:
            if DATABASE_URL:
                exists = _fetchall(conn, "SELECT column_name FROM information_schema.columns WHERE table_name='accounts' AND column_name=%s", (col,))
                if not exists:
                    _execute(conn, f"ALTER TABLE accounts ADD COLUMN {col} BOOLEAN DEFAULT FALSE")
                    print(f"[Migration] Added {col} column to accounts (PostgreSQL)")
            else:
                cur = conn.cursor()
                columns = [c[1] for c in cur.execute("PRAGMA table_info(accounts)").fetchall()]
                if col not in columns:
                    cur.execute(f"ALTER TABLE accounts ADD COLUMN {col} BOOLEAN DEFAULT 0")
                    print(f"[Migration] Added {col} column to accounts (SQLite)")
        except Exception as e:
            print(f"[Migration] {col} column: {e}")
    for col in text_cols:
        try:
            if DATABASE_URL:
                exists = _fetchall(conn, "SELECT column_name FROM information_schema.columns WHERE table_name='accounts' AND column_name=%s", (col,))
                if not exists:
                    _execute(conn, f"ALTER TABLE accounts ADD COLUMN {col} TEXT")
                    print(f"[Migration] Added {col} column to accounts (PostgreSQL)")
            else:
                cur = conn.cursor()
                columns = [c[1] for c in cur.execute("PRAGMA table_info(accounts)").fetchall()]
                if col not in columns:
                    cur.execute(f"ALTER TABLE accounts ADD COLUMN {col} TEXT")
                    print(f"[Migration] Added {col} column to accounts (SQLite)")
        except Exception as e:
            print(f"[Migration] {col} column: {e}")


def _migrate_composite_indices(conn):
    """Composite indices that match the hot WHERE/ORDER BY shapes used by
    dashboard endpoints. Skipped silently if Postgres declines (e.g. existing).
    Postgres-only — SQLite path keeps the simpler single-column indices."""
    if not DATABASE_URL:
        return
    indices = [
        # Filter+sort pattern in get_videos / get_aggregated_stats / best+latest
        ("idx_videos_user_platform_created",
         "CREATE INDEX IF NOT EXISTS idx_videos_user_platform_created "
         "ON videos (user_id, platform, create_time DESC)"),
        # IN-clause + filter pattern in project / competitor scoping
        ("idx_videos_user_account",
         "CREATE INDEX IF NOT EXISTS idx_videos_user_account "
         "ON videos (user_id, account_username)"),
        # daily_snapshots sort/filter pattern in evolution + period deltas
        ("idx_snapshots_user_account_date",
         "CREATE INDEX IF NOT EXISTS idx_snapshots_user_account_date "
         "ON daily_snapshots (user_id, account_username, snapshot_date DESC)"),
    ]
    for name, sql in indices:
        try:
            _execute(conn, sql)
            print(f"[Migration] Index ensured: {name}")
        except Exception as e:
            print(f"[Migration] Index {name}: {e}")


def _migrate_default_projects(conn):
    """Create a default project for users who have accounts but no projects."""
    try:
        users_without = _fetchall(conn, """
            SELECT DISTINCT a.user_id FROM accounts a
            LEFT JOIN projects p ON p.user_id = a.user_id
            WHERE p.id IS NULL AND a.user_id IS NOT NULL
        """)
        for u in users_without:
            uid = u['user_id']
            _execute(conn, "INSERT INTO projects (user_id, name) VALUES (%s, %s)", (uid, "Tous les comptes"))
            proj = _fetchone(conn, "SELECT id FROM projects WHERE user_id = %s AND name = %s", (uid, "Tous les comptes"))
            if proj:
                _execute(conn, """
                    INSERT INTO project_accounts (project_id, account_id)
                    SELECT %s, id FROM accounts WHERE user_id = %s
                """, (proj['id'], uid))
                print(f"[Migration] Created default project for user {uid}")
    except Exception as e:
        print(f"[Migration] default projects: {e}")


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


# ==================== Subscription functions ====================

def get_user_subscription(user_id):
    conn = get_connection()
    sub = _fetchone(conn, "SELECT * FROM subscriptions WHERE user_id = %s", (user_id,))
    conn.close()
    if not sub:
        return {'plan': 'starter', 'status': 'active', 'stripe_customer_id': None, 'stripe_subscription_id': None}
    return sub


def upsert_subscription(user_id, plan, status, stripe_customer_id=None, stripe_subscription_id=None, current_period_end=None):
    conn = get_connection()
    _execute(conn, """
        INSERT INTO subscriptions (user_id, plan, status, stripe_customer_id, stripe_subscription_id, current_period_end, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            plan = EXCLUDED.plan,
            status = EXCLUDED.status,
            stripe_customer_id = COALESCE(EXCLUDED.stripe_customer_id, subscriptions.stripe_customer_id),
            stripe_subscription_id = COALESCE(EXCLUDED.stripe_subscription_id, subscriptions.stripe_subscription_id),
            current_period_end = COALESCE(EXCLUDED.current_period_end, subscriptions.current_period_end),
            updated_at = EXCLUDED.updated_at
    """, (user_id, plan, status, stripe_customer_id, stripe_subscription_id,
          current_period_end, datetime.now().isoformat()))
    # Also update users.plan for quick access
    _execute(conn, "UPDATE users SET plan = %s WHERE id = %s", (plan, user_id))
    if stripe_customer_id:
        _execute(conn, "UPDATE users SET stripe_customer_id = %s WHERE id = %s", (stripe_customer_id, user_id))
    conn.commit()
    conn.close()


def get_subscription_by_customer(stripe_customer_id):
    conn = get_connection()
    sub = _fetchone(conn, "SELECT * FROM subscriptions WHERE stripe_customer_id = %s", (stripe_customer_id,))
    conn.close()
    return sub


# ==================== User functions ====================

def create_or_update_user(google_id, email, name, avatar_url):
    """Upsert a user. Returns (user_dict, is_new: bool).

    is_new is True only on the very first signup for this google_id — used to
    gate side effects like the welcome email.
    """
    conn = get_connection()
    existing = _fetchone(
        conn, "SELECT id FROM users WHERE google_id = %s", (google_id,)
    )
    is_new = existing is None
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
    return user, is_new


def get_user_by_id(user_id):
    conn = get_connection()
    user = _fetchone(conn, "SELECT * FROM users WHERE id = %s", (user_id,))
    conn.close()
    return user


# ==================== Account management ====================

def add_tracked_account(user_id, username, platform="tiktok", is_competitor=False):
    conn = get_connection()
    _execute(conn, """
        INSERT INTO accounts (username, display_name, platform, user_id, is_competitor, last_updated)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (username, user_id, platform) DO UPDATE SET is_competitor = EXCLUDED.is_competitor
    """, (username, username, platform, user_id, is_competitor, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def remove_tracked_account(user_id, username):
    conn = get_connection()
    _execute(conn, "DELETE FROM daily_snapshots WHERE account_username = %s AND user_id = %s", (username, user_id))
    _execute(conn, "DELETE FROM videos WHERE account_username = %s AND user_id = %s", (username, user_id))
    _execute(conn, "DELETE FROM accounts WHERE username = %s AND user_id = %s", (username, user_id))
    conn.commit()
    conn.close()


# ==================== Project management ====================

def create_project(user_id, name):
    conn = get_connection()
    _execute(conn, """
        INSERT INTO projects (user_id, name) VALUES (%s, %s)
    """, (user_id, name))
    conn.commit()
    project = _fetchone(conn, "SELECT * FROM projects WHERE user_id = %s AND name = %s", (user_id, name))
    conn.close()
    return project


def rename_project(user_id, project_id, new_name):
    conn = get_connection()
    _execute(conn, "UPDATE projects SET name = %s WHERE id = %s AND user_id = %s", (new_name, project_id, user_id))
    conn.commit()
    conn.close()


def delete_project(user_id, project_id):
    conn = get_connection()
    _execute(conn, "DELETE FROM projects WHERE id = %s AND user_id = %s", (project_id, user_id))
    conn.commit()
    conn.close()


def get_projects(user_id):
    conn = get_connection()
    results = _fetchall(conn, "SELECT * FROM projects WHERE user_id = %s ORDER BY name", (user_id,))
    conn.close()
    return results


def get_project_accounts(project_id):
    conn = get_connection()
    results = _fetchall(conn, """
        SELECT a.* FROM accounts a
        JOIN project_accounts pa ON pa.account_id = a.id
        WHERE pa.project_id = %s
        ORDER BY a.username
    """, (project_id,))
    conn.close()
    return results


def set_project_accounts(project_id, account_ids):
    conn = get_connection()
    _execute(conn, "DELETE FROM project_accounts WHERE project_id = %s", (project_id,))
    for aid in account_ids:
        _execute(conn, """
            INSERT INTO project_accounts (project_id, account_id) VALUES (%s, %s)
            ON CONFLICT (project_id, account_id) DO NOTHING
        """, (project_id, aid))
    conn.commit()
    conn.close()


def get_account_usernames_for_project(user_id, project_id):
    """Return list of usernames belonging to a project."""
    conn = get_connection()
    results = _fetchall(conn, """
        SELECT a.username FROM accounts a
        JOIN project_accounts pa ON pa.account_id = a.id
        JOIN projects p ON p.id = pa.project_id
        WHERE pa.project_id = %s AND p.user_id = %s
    """, (project_id, user_id))
    conn.close()
    return [r['username'] for r in results]


# ==================== Data functions (all filtered by user_id) ====================

def upsert_account(username, display_name=None, avatar_url=None, followers=0, following=0, total_likes=0, total_views=0, total_comments=0, last_media_count=0, friend_count=0, verified=None, private_account=None, region=None, bio=None, user_id=None, platform="tiktok"):
    conn = get_connection()
    # On conflict, only overwrite numeric stats if the new value is non-zero —
    # otherwise an empty/error scrape (e.g. transient 404) wipes good data.
    # Genuine "0 followers" still gets persisted on the initial INSERT path.
    # Booleans (verified, private_account) and TEXT (region) only overwrite
    # when the new value is provided (None == "no signal" = preserve old).
    _execute(conn, """
        INSERT INTO accounts (username, display_name, avatar_url, followers, following, total_likes, total_views, total_comments, last_media_count, friend_count, verified, private_account, region, bio, last_updated, user_id, platform)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(username, user_id, platform) DO UPDATE SET
            display_name     = COALESCE(excluded.display_name, accounts.display_name),
            avatar_url       = COALESCE(excluded.avatar_url, accounts.avatar_url),
            followers        = CASE WHEN excluded.followers        > 0 THEN excluded.followers        ELSE accounts.followers        END,
            following        = CASE WHEN excluded.following        > 0 THEN excluded.following        ELSE accounts.following        END,
            total_likes      = CASE WHEN excluded.total_likes      > 0 THEN excluded.total_likes      ELSE accounts.total_likes      END,
            total_views      = CASE WHEN excluded.total_views      > 0 THEN excluded.total_views      ELSE accounts.total_views      END,
            total_comments   = CASE WHEN excluded.total_comments   > 0 THEN excluded.total_comments   ELSE accounts.total_comments   END,
            last_media_count = CASE WHEN excluded.last_media_count > 0 THEN excluded.last_media_count ELSE accounts.last_media_count END,
            friend_count     = CASE WHEN excluded.friend_count     > 0 THEN excluded.friend_count     ELSE accounts.friend_count     END,
            verified         = COALESCE(excluded.verified, accounts.verified),
            private_account  = COALESCE(excluded.private_account, accounts.private_account),
            region           = COALESCE(excluded.region, accounts.region),
            bio = COALESCE(excluded.bio, accounts.bio),
            last_updated = excluded.last_updated
    """, (username, display_name, avatar_url, followers, following, total_likes, total_views, total_comments, last_media_count, friend_count, verified, private_account, region, bio, datetime.now().isoformat(), user_id, platform))
    conn.commit()
    conn.close()


def upsert_video(video_id, account_username, description="", create_time=None, duration=0,
                 views=0, likes=0, comments=0, shares=0, saves=0, thumbnail_url=None, video_url=None, user_id=None, platform="tiktok"):
    conn = get_connection()
    _execute(conn, """
        INSERT INTO videos (video_id, account_username, description, create_time, duration,
                           views, likes, comments, shares, saves, thumbnail_url, video_url, last_updated, user_id, platform)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(video_id, user_id) DO UPDATE SET
            -- DB constraint is (user_id, video_id) without platform. We rely on
            -- the fact that platform-specific video IDs don't collide in practice
            -- (TikTok IDs ≠ YouTube IDs ≠ Instagram IDs by construction).
            description = COALESCE(excluded.description, videos.description),
            views = excluded.views,
            likes = excluded.likes,
            comments = excluded.comments,
            shares = excluded.shares,
            saves = excluded.saves,
            thumbnail_url = COALESCE(excluded.thumbnail_url, videos.thumbnail_url),
            last_updated = excluded.last_updated
    """, (video_id, account_username, description, create_time, duration,
          views, likes, comments, shares, saves, thumbnail_url, video_url, datetime.now().isoformat(), user_id, platform))
    conn.commit()
    conn.close()


def save_daily_snapshot(account_username, user_id=None, platform="tiktok"):
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")

    query = "SELECT COUNT(*) as total_videos, COALESCE(SUM(views), 0) as total_views, COALESCE(SUM(likes), 0) as total_likes, COALESCE(SUM(comments), 0) as total_comments, COALESCE(SUM(shares), 0) as total_shares, COALESCE(SUM(saves), 0) as total_saves FROM videos WHERE account_username = %s AND platform = %s"
    params = [account_username, platform]
    if user_id is not None:
        query += " AND user_id = %s"
        params.append(user_id)

    stats = _fetchone(conn, query, params)

    acc_query = "SELECT followers FROM accounts WHERE username = %s AND platform = %s"
    acc_params = [account_username, platform]
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
                                    total_likes, total_comments, total_shares, total_saves, followers, engagement_rate, user_id, platform)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT(account_username, platform, snapshot_date, user_id) DO UPDATE SET
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
          stats["total_saves"], followers, engagement_rate, user_id, platform))
    conn.commit()
    conn.close()


def get_all_accounts(user_id=None, is_competitor=None, with_last_post=False):
    """Fetch tracked accounts, optionally enriched with the most recent post date.

    `with_last_post=True` joins the `videos` table to surface MAX(create_time)
    per (username, platform). Used by the dashboard to flag accounts that have
    not posted recently — distinct from the per-period stats which only count
    posts inside the current date filter.
    """
    conn = get_connection()
    query = "SELECT * FROM accounts WHERE 1=1"
    params = []
    if user_id is not None:
        query += " AND user_id = %s"
        params.append(user_id)
    if is_competitor is not None:
        query += " AND is_competitor = %s"
        params.append(is_competitor)
    query += " ORDER BY username"
    results = _fetchall(conn, query, params)

    if with_last_post and results:
        # One round-trip — compute MAX(create_time) AND COUNT(*) for each
        # (username, platform) tied to the same user_id. Avoids N queries
        # when there are many accounts. video_count is what the dashboard's
        # account cards display in the "Vidéos" column.
        usernames = list({r["username"] for r in results})
        ph = ", ".join(["%s"] * len(usernames))
        last_q = f"""
            SELECT account_username AS username, platform,
                   MAX(create_time) AS last_post_at,
                   COUNT(*)         AS video_count
            FROM videos
            WHERE account_username IN ({ph})
        """
        last_params = list(usernames)
        if user_id is not None:
            last_q += " AND user_id = %s"
            last_params.append(user_id)
        last_q += " GROUP BY account_username, platform"
        last_rows = _fetchall(conn, last_q, last_params)
        last_map = {
            (r["username"], r.get("platform") or "tiktok"): r
            for r in last_rows
        }
        for r in results:
            key = (r["username"], r.get("platform") or "tiktok")
            row = last_map.get(key) or {}
            lp = row.get("last_post_at")
            r["last_post_at"] = lp.isoformat() if lp else None
            r["video_count"]  = int(row.get("video_count") or 0)

    conn.close()
    return results


def get_videos(account_username=None, date_from=None, date_to=None, sort_by="create_time", sort_order="DESC", user_id=None, account_usernames=None, exclude_no_date=False, limit=None):
    # If project filter yields empty list, return empty
    if account_usernames is not None and len(account_usernames) == 0:
        return []
    conn = get_connection()
    query = "SELECT * FROM videos WHERE 1=1"
    params = []

    if user_id is not None:
        query += " AND user_id = %s"
        params.append(user_id)
    if account_usernames:
        placeholders = ', '.join(['%s'] * len(account_usernames))
        query += f" AND account_username IN ({placeholders})"
        params.extend(account_usernames)
    elif account_username and account_username != "all":
        query += " AND account_username = %s"
        params.append(account_username)
    if exclude_no_date:
        query += " AND create_time IS NOT NULL"
    if date_from:
        query += f" AND create_time >= %s{_ts_cast()}"
        params.append(date_from)
    if date_to:
        query += f" AND create_time <= %s{_ts_cast()}"
        params.append(date_to + " 23:59:59")

    # "engagement" is a synthetic sort that combines reach (views) with active
    # interactions (likes/comments/shares). The weights make 1 like worth ~100
    # views, 1 comment worth ~500, 1 share worth ~200 — calibrated so that an
    # Instagram carousel with 0 views but high likes/comments still surfaces
    # alongside high-view videos. Without this, photos and carousels are
    # invisible in "Top by views" because IG doesn't expose view counts for
    # non-video media.
    allowed_sorts = {"create_time", "views", "likes", "comments", "shares", "saves", "engagement"}
    if sort_by not in allowed_sorts:
        sort_by = "create_time"
    if sort_order not in ("ASC", "DESC"):
        sort_order = "DESC"
    if sort_by == "engagement":
        order_expr = (
            "(COALESCE(views, 0) "
            "+ COALESCE(likes, 0) * 100 "
            "+ COALESCE(comments, 0) * 500 "
            "+ COALESCE(shares, 0) * 200)"
        )
        query += f" ORDER BY {order_expr} {sort_order}"
    else:
        query += f" ORDER BY {sort_by} {sort_order}"

    if limit is not None and limit > 0:
        query += " LIMIT %s"
        params.append(int(limit))

    results = _fetchall(conn, query, params)
    conn.close()
    return results


def get_posts_per_day_aggregated(account_username=None, date_from=None, date_to=None, user_id=None, account_usernames=None):
    """
    Returns {date_str: {"username:platform": count}} via SQL GROUP BY.
    Massively faster than fetching all videos and counting in Python:
    on 1.7k videos this drops the route from ~4.5s to ~50ms.
    """
    if account_usernames is not None and len(account_usernames) == 0:
        return {}
    conn = get_connection()
    # Cast create_time to date for grouping. Postgres handles the cast natively;
    # SQLite needs DATE() since create_time is stored as ISO text.
    if DATABASE_URL:
        date_expr = "DATE(create_time)"
    else:
        date_expr = "DATE(create_time)"
    query = (
        f"SELECT {date_expr} AS day, account_username, "
        "COALESCE(platform, 'tiktok') AS platform, COUNT(*) AS n "
        "FROM videos WHERE create_time IS NOT NULL"
    )
    params = []
    if user_id is not None:
        query += " AND user_id = %s"
        params.append(user_id)
    if account_usernames:
        placeholders = ", ".join(["%s"] * len(account_usernames))
        query += f" AND account_username IN ({placeholders})"
        params.extend(account_usernames)
    elif account_username and account_username != "all":
        query += " AND account_username = %s"
        params.append(account_username)
    if date_from:
        query += f" AND create_time >= %s{_ts_cast()}"
        params.append(date_from)
    if date_to:
        query += f" AND create_time <= %s{_ts_cast()}"
        params.append(date_to + " 23:59:59")
    query += " GROUP BY day, account_username, platform ORDER BY day"

    rows = _fetchall(conn, query, params)
    conn.close()

    out: dict = {}
    for r in rows:
        date_str = str(r["day"])[:10]
        key = f"{r['account_username']}:{r['platform']}"
        out.setdefault(date_str, {})[key] = int(r["n"])
    return out


def _enrich_with_account_fields(results, user_id):
    """Add account-level fields (display_name, avatar_url, bio, account totals,
    is_competitor, etc.) onto a list of per-(account, platform) dicts in place.
    One IN-clause query — no N+1. Called by both code paths in get_aggregated_stats
    so the API contract is identical regardless of date filter.
    """
    if not results:
        return
    usernames_in = list({r['account_username'] for r in results})
    if not usernames_in:
        return
    conn = get_connection()
    ph = ', '.join(['%s'] * len(usernames_in))
    accounts_q = f"""
        SELECT username, platform, display_name, avatar_url, bio,
               followers, following,
               total_likes      AS account_total_likes,
               total_views      AS account_total_views,
               total_comments   AS account_total_comments,
               last_media_count, friend_count, verified, private_account,
               region, is_competitor, last_updated
        FROM accounts
        WHERE username IN ({ph})
    """
    aparams = list(usernames_in)
    if user_id is not None:
        accounts_q += " AND user_id = %s"
        aparams.append(user_id)
    rows = _fetchall(conn, accounts_q, aparams)
    conn.close()
    accounts_map = {(r['username'], r.get('platform') or 'tiktok'): r for r in rows}
    for r in results:
        key = (r['account_username'], r.get('platform') or 'tiktok')
        acc = accounts_map.get(key) or {}
        # followers may already be set by the deltas path — only fill if missing.
        r.setdefault('followers', acc.get('followers') or 0)
        r.setdefault('follower_gain', 0)
        r['following']              = acc.get('following') or 0
        r['display_name']           = acc.get('display_name')
        r['avatar_url']             = acc.get('avatar_url')
        r['bio']                    = acc.get('bio')
        r['is_competitor']          = bool(acc.get('is_competitor'))
        r['last_updated']           = acc.get('last_updated')
        r['account_total_likes']    = acc.get('account_total_likes') or 0
        r['account_total_views']    = acc.get('account_total_views') or 0
        r['account_total_comments'] = acc.get('account_total_comments') or 0
        r['media_count']            = acc.get('last_media_count') or 0
        r['friend_count']           = acc.get('friend_count') or 0
        r['verified']               = bool(acc.get('verified'))
        r['private_account']        = bool(acc.get('private_account'))
        r['region']                 = acc.get('region')


def _compute_period_deltas(date_from, date_to, user_id=None, account_username=None, account_usernames=None):
    """Compute engagement deltas per (account, platform) using daily_snapshots.

    Returns a list of dicts: [{account_username, platform, total_videos, total_views, ...}, ...]
    Each entry represents the engagement GAINED during [date_from, date_to] for that
    (account, platform), regardless of when the videos were originally posted.

    Logic: delta = snapshot_at(date_to) - snapshot_before(date_from)
    - end_snap: latest snapshot ON or BEFORE date_to (or latest if no date_to)
    - start_snap: latest snapshot STRICTLY BEFORE date_from (or 0 if no snapshot before)

    If no start_snap exists (account just started being tracked), we treat the baseline
    as 0 and the end_snap as the gain. This is correct for "all-time" queries but may
    over-attribute for partial-history accounts — caller should be aware.
    """
    if account_usernames is not None and len(account_usernames) == 0:
        return []
    conn = get_connection()

    # Try to query with platform column; fall back without if it doesn't exist
    try:
        query = """
            SELECT account_username, platform, snapshot_date, total_videos, total_views,
                   total_likes, total_comments, total_shares, total_saves, followers
            FROM daily_snapshots WHERE 1=1
        """
        params = []
        if user_id is not None:
            query += " AND user_id = %s"
            params.append(user_id)
        if account_usernames:
            placeholders = ', '.join(['%s'] * len(account_usernames))
            query += f" AND account_username IN ({placeholders})"
            params.extend(account_usernames)
        elif account_username and account_username != "all":
            query += " AND account_username = %s"
            params.append(account_username)
        query += " ORDER BY account_username, platform, snapshot_date ASC"
        snapshots = _fetchall(conn, query, params)
    except Exception:
        # Fallback for legacy schemas without platform column
        query = """
            SELECT account_username, snapshot_date, total_videos, total_views,
                   total_likes, total_comments, total_shares, total_saves, followers
            FROM daily_snapshots WHERE 1=1
        """
        params = []
        if user_id is not None:
            query += " AND user_id = %s"
            params.append(user_id)
        if account_usernames:
            placeholders = ', '.join(['%s'] * len(account_usernames))
            query += f" AND account_username IN ({placeholders})"
            params.extend(account_usernames)
        elif account_username and account_username != "all":
            query += " AND account_username = %s"
            params.append(account_username)
        query += " ORDER BY account_username, snapshot_date ASC"
        snapshots = _fetchall(conn, query, params)
        for s in snapshots:
            s['platform'] = 'tiktok'

    conn.close()

    if not snapshots:
        return []

    # Group by (account, platform)
    grouped = {}
    for s in snapshots:
        # PostgreSQL returns date objects, SQLite returns strings
        s['snapshot_date'] = str(s['snapshot_date'])
        key = (s['account_username'], s.get('platform') or 'tiktok')
        grouped.setdefault(key, []).append(s)

    metrics = ['total_videos', 'total_views', 'total_likes', 'total_comments', 'total_shares', 'total_saves']
    results = []

    for (acc, plat), snaps in grouped.items():
        # Find end snapshot: latest snapshot ON or BEFORE date_to (or latest if no date_to)
        end_snap = None
        if date_to:
            for s in reversed(snaps):
                if s['snapshot_date'] <= date_to:
                    end_snap = s
                    break
        else:
            end_snap = snaps[-1]

        # Find start snapshot: latest snapshot STRICTLY BEFORE date_from
        start_snap = None
        if date_from:
            for s in reversed(snaps):
                if s['snapshot_date'] < date_from:
                    start_snap = s
                    break

        if end_snap is None:
            continue

        # If we have no snapshot strictly before date_from, the delta would
        # collapse to (end_snap - 0) = full cumulative — which makes the
        # value identical for every date range and breaks the date filter
        # in the UI. Skip the row instead so the caller falls through to
        # the create_time-based per-video aggregation, which IS responsive
        # to the date filter.
        if date_from and not start_snap:
            continue

        delta = {'account_username': acc, 'platform': plat}
        for m in metrics:
            end_val = end_snap.get(m, 0) or 0
            start_val = (start_snap.get(m, 0) or 0) if start_snap else 0
            delta[m] = max(0, end_val - start_val)

        # Followers: keep END value as the "current" count + signed delta (can be
        # negative if the account loses followers). Don't max(0, ...) the gain.
        end_followers = end_snap.get('followers', 0) or 0
        start_followers = (start_snap.get('followers', 0) or 0) if start_snap else end_followers
        delta['followers'] = end_followers
        delta['follower_gain'] = end_followers - start_followers

        # Averages computed from current totals (snapshot at end of period)
        current_videos = end_snap.get('total_videos', 0) or 1
        delta['avg_views'] = delta['total_views'] / max(1, current_videos)
        delta['avg_likes'] = delta['total_likes'] / max(1, current_videos)
        delta['avg_comments'] = delta['total_comments'] / max(1, current_videos)
        delta['avg_shares'] = delta['total_shares'] / max(1, current_videos)
        delta['avg_saves'] = delta['total_saves'] / max(1, current_videos)

        results.append(delta)

    return results


def get_aggregated_stats(account_username=None, date_from=None, date_to=None, user_id=None, account_usernames=None):
    """Get per-account aggregated stats.

    Without dates: current cumulative totals from videos table (one row per (account, platform)).
    With dates: engagement GAINED during the period, computed as deltas from daily_snapshots.
                 Views/likes/etc. are attributed to the snapshot date when they were observed,
                 NOT to the original video post date. This means a video posted on 02/10
                 that gains 100 views on 04/10 will have those 100 views counted in any range
                 that includes 04/10.
    """
    if account_usernames is not None and len(account_usernames) == 0:
        return []

    # When dates are provided, use snapshot-based deltas (views attributed to scrape date)
    if date_from or date_to:
        deltas = _compute_period_deltas(
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
            account_username=account_username,
            account_usernames=account_usernames,
        )
        # If no snapshot data available, fall through to videos-table fallback below
        if deltas:
            _enrich_with_account_fields(deltas, user_id)
            return deltas

    # No date filter, OR snapshots are too thin to compute period deltas
    # (typical for accounts with only a few days of cron history). When
    # dates ARE given we still respect them by filtering videos on
    # create_time — the per-account row then represents "engagement on
    # videos POSTED in the window" instead of "engagement gained during
    # the window". Different semantic, but it's at least responsive to
    # the filter so the UI behaves predictably.
    conn = get_connection()
    query = """
        SELECT
            account_username,
            platform,
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
    if account_usernames:
        placeholders = ', '.join(['%s'] * len(account_usernames))
        query += f" AND account_username IN ({placeholders})"
        params.extend(account_usernames)
    elif account_username and account_username != "all":
        query += " AND account_username = %s"
        params.append(account_username)
    if date_from:
        query += f" AND create_time >= %s{_ts_cast()}"
        params.append(date_from)
    if date_to:
        query += f" AND create_time <= %s{_ts_cast()}"
        params.append(date_to + " 23:59:59")
    query += " GROUP BY account_username, platform"

    results = _fetchall(conn, query, params)

    conn.close()

    # Enrich every per-(account, platform) row with the full account record.
    # Frontends consume per_account directly; without this enrichment they'd
    # need a second /api/accounts call and a manual join.
    _enrich_with_account_fields(results, user_id)
    return results


def get_global_stats(date_from=None, date_to=None, user_id=None, account_usernames=None):
    """Get global stats summed across all selected accounts.

    Without dates: current cumulative totals from videos table.
    With dates: engagement GAINED during the period, computed as deltas from daily_snapshots.
                 Views are attributed to the snapshot date when they were observed,
                 NOT to the original video post date.
    """
    if account_usernames is not None and len(account_usernames) == 0:
        return {'total_videos': 0, 'total_views': 0, 'total_likes': 0,
                'total_comments': 0, 'total_shares': 0, 'total_saves': 0}

    # When dates are provided, sum the per-(account,platform) deltas computed from snapshots.
    if date_from or date_to:
        deltas = _compute_period_deltas(
            date_from=date_from,
            date_to=date_to,
            user_id=user_id,
            account_usernames=account_usernames,
        )
        if deltas:
            # total_videos = posts whose create_time falls in the period (matches
            # /api/posts-per-day). The snapshot delta would count videos that
            # *appeared* in our scraping, including old posts only just discovered,
            # which is confusing for users — the KPI label says "Contenus" so it
            # must reflect "publications postées dans la période".
            conn = get_connection()
            count_q = """
                SELECT COUNT(*) AS total_videos
                FROM videos
                WHERE create_time IS NOT NULL
            """
            count_params = []
            if user_id is not None:
                count_q += " AND user_id = %s"
                count_params.append(user_id)
            if account_usernames:
                placeholders = ', '.join(['%s'] * len(account_usernames))
                count_q += f" AND account_username IN ({placeholders})"
                count_params.extend(account_usernames)
            if date_from:
                count_q += " AND create_time >= %s"
                count_params.append(date_from)
            if date_to:
                count_q += " AND create_time <= %s"
                count_params.append(date_to + " 23:59:59")
            posts_in_period = _fetchone(conn, count_q, count_params)
            conn.close()
            videos_count = (posts_in_period or {}).get('total_videos', 0) or 0

            # Pull current account-level cumulatives (followers, account totals)
            # so the response is shape-equivalent to the no-date path.
            conn = get_connection()
            acc_q = """
                SELECT
                    COALESCE(SUM(followers), 0)        AS total_followers,
                    COALESCE(SUM(following), 0)        AS total_following,
                    COALESCE(SUM(total_likes), 0)      AS account_total_likes,
                    COALESCE(SUM(total_views), 0)      AS account_total_views,
                    COALESCE(SUM(total_comments), 0)   AS account_total_comments,
                    COUNT(*)                            AS accounts_count
                FROM accounts WHERE 1=1
            """
            acc_params = []
            if user_id is not None:
                acc_q += " AND user_id = %s"
                acc_params.append(user_id)
            if account_usernames:
                placeholders = ', '.join(['%s'] * len(account_usernames))
                acc_q += f" AND username IN ({placeholders})"
                acc_params.extend(account_usernames)
            acc_row = _fetchone(conn, acc_q, acc_params) or {}
            conn.close()

            return {
                'total_videos': videos_count,
                'total_views':    sum(d.get('total_views', 0) for d in deltas),
                'total_likes':    sum(d.get('total_likes', 0) for d in deltas),
                'total_comments': sum(d.get('total_comments', 0) for d in deltas),
                'total_shares':   sum(d.get('total_shares', 0) for d in deltas),
                'total_saves':    sum(d.get('total_saves', 0) for d in deltas),
                # Account-level cumulatives (current snapshot, not period-delta)
                'total_followers':        acc_row.get('total_followers') or sum(d.get('followers', 0) for d in deltas),
                'total_following':        acc_row.get('total_following') or 0,
                'account_total_likes':    acc_row.get('account_total_likes') or 0,
                'account_total_views':    acc_row.get('account_total_views') or 0,
                'account_total_comments': acc_row.get('account_total_comments') or 0,
                'accounts_count':         acc_row.get('accounts_count') or 0,
                # follower_gain stays a true period delta
                'follower_gain': sum(d.get('follower_gain', 0) for d in deltas),
            }
        # Fall through if no snapshot data available (e.g. very fresh accounts)

    # No date filter: cumulative totals from videos table
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
    if account_usernames:
        placeholders = ', '.join(['%s'] * len(account_usernames))
        query += f" AND account_username IN ({placeholders})"
        params.extend(account_usernames)
    # Mirror the per-account fallback: when dates are given but the
    # snapshot deltas branch fell through (insufficient history), filter
    # videos by create_time so the totals respond to the date filter.
    if date_from:
        query += f" AND create_time >= %s{_ts_cast()}"
        params.append(date_from)
    if date_to:
        query += f" AND create_time <= %s{_ts_cast()}"
        params.append(date_to + " 23:59:59")

    result = _fetchone(conn, query, params) or {}

    # Account-level totals (followers + heart counts that are richer than the
    # per-video sums above — TT heartCount, IG aggregated reels, etc.). Same
    # filter as the video query so global numbers stay consistent.
    fq = """
        SELECT
            COALESCE(SUM(followers), 0)         AS total_followers,
            COALESCE(SUM(following), 0)         AS total_following,
            COALESCE(SUM(total_likes), 0)       AS account_total_likes,
            COALESCE(SUM(total_views), 0)       AS account_total_views,
            COALESCE(SUM(total_comments), 0)    AS account_total_comments,
            COUNT(*)                             AS accounts_count
        FROM accounts WHERE 1=1
    """
    fparams = []
    if user_id is not None:
        fq += " AND user_id = %s"
        fparams.append(user_id)
    if account_usernames:
        placeholders = ', '.join(['%s'] * len(account_usernames))
        fq += f" AND username IN ({placeholders})"
        fparams.extend(account_usernames)
    fresult = _fetchone(conn, fq, fparams) or {}
    conn.close()

    result['total_followers']        = fresult.get('total_followers') or 0
    result['total_following']        = fresult.get('total_following') or 0
    result['account_total_likes']    = fresult.get('account_total_likes') or 0
    result['account_total_views']    = fresult.get('account_total_views') or 0
    result['account_total_comments'] = fresult.get('account_total_comments') or 0
    result['accounts_count']         = fresult.get('accounts_count') or 0
    result['follower_gain']          = 0
    return result


def get_daily_evolution(account_username=None, date_from=None, date_to=None, user_id=None, account_usernames=None):
    """Get daily evolution from daily_snapshots (stats by scraping date, not video publication date)."""
    if account_usernames is not None and len(account_usernames) == 0:
        return []
    conn = get_connection()
    query = """
        SELECT
            snapshot_date as date,
            account_username,
            platform,
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
    if account_usernames:
        placeholders = ', '.join(['%s'] * len(account_usernames))
        query += f" AND account_username IN ({placeholders})"
        params.extend(account_usernames)
    elif account_username and account_username != "all":
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
            INSERT INTO accounts (username, display_name, avatar_url, followers, following, total_likes, bio, last_updated, user_id, platform)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (username, user_id, platform) DO NOTHING
        """, (acc["username"], acc.get("display_name"), acc.get("avatar_url"),
              acc.get("followers", 0), acc.get("following", 0), acc.get("total_likes", 0),
              acc.get("bio"), datetime.now().isoformat(), user_id, acc.get("platform", "tiktok")))

    for vid in seed.get("videos", []):
        _execute(conn, """
            INSERT INTO videos (video_id, account_username, description, create_time, duration,
                                         views, likes, comments, shares, saves, thumbnail_url, video_url, last_updated, user_id, platform)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (video_id, user_id) DO NOTHING
        """, (vid["video_id"], vid["account_username"], vid.get("description", ""),
              vid.get("create_time"), vid.get("duration", 0), vid.get("views", 0),
              vid.get("likes", 0), vid.get("comments", 0), vid.get("shares", 0),
              vid.get("saves", 0), vid.get("thumbnail_url"), vid.get("video_url"),
              datetime.now().isoformat(), user_id, vid.get("platform", "tiktok")))

    for snap in seed.get("daily_snapshots", []):
        _execute(conn, """
            INSERT INTO daily_snapshots (account_username, snapshot_date, total_videos, total_views,
                                                  total_likes, total_comments, total_shares, total_saves,
                                                  followers, engagement_rate, user_id, platform)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (account_username, platform, snapshot_date, user_id) DO NOTHING
        """, (snap["account_username"], snap["snapshot_date"], snap.get("total_videos", 0),
              snap.get("total_views", 0), snap.get("total_likes", 0), snap.get("total_comments", 0),
              snap.get("total_shares", 0), snap.get("total_saves", 0), snap.get("followers", 0),
              snap.get("engagement_rate", 0), user_id, snap.get("platform", "tiktok")))

    conn.commit()
    conn.close()
    print(f"[Seed] Done: {len(seed.get('accounts', []))} accounts, {len(seed.get('videos', []))} videos, {len(seed.get('daily_snapshots', []))} snapshots")
    return True


# ==================== Admin functions ====================

def get_all_users():
    conn = get_connection()
    results = _fetchall(conn, """
        SELECT u.*,
            COALESCE(u.plan, 'starter') as plan,
            (SELECT COUNT(*) FROM accounts a WHERE a.user_id = u.id) as account_count,
            (SELECT COUNT(*) FROM videos v WHERE v.user_id = u.id) as video_count,
            (SELECT s.status FROM subscriptions s WHERE s.user_id = u.id LIMIT 1) as subscription_status
        FROM users u ORDER BY u.created_at DESC
    """)
    conn.close()
    return results


def set_user_plan(user_id, plan):
    """Admin-driven plan change. Updates both users.plan and subscriptions row."""
    if plan not in ('starter', 'pro', 'agency'):
        raise ValueError(f"Invalid plan: {plan}")
    conn = get_connection()
    _execute(conn, "UPDATE users SET plan = %s WHERE id = %s", (plan, user_id))
    # Upsert subscription row so billing page stays in sync
    _execute(conn, """
        INSERT INTO subscriptions (user_id, plan, status, updated_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            plan = EXCLUDED.plan,
            status = EXCLUDED.status,
            updated_at = EXCLUDED.updated_at
    """, (user_id, plan, 'active', datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_user_plan(user_id):
    """Return the plan name for a user (starter/pro/agency)."""
    conn = get_connection()
    user = _fetchone(conn, "SELECT plan FROM users WHERE id = %s", (user_id,))
    conn.close()
    if not user or not user.get('plan'):
        return 'starter'
    return user['plan']


def set_user_blocked(user_id, blocked):
    conn = get_connection()
    _execute(conn, "UPDATE users SET blocked = %s WHERE id = %s", (blocked, user_id))
    conn.commit()
    conn.close()


def set_user_role(user_id, role):
    conn = get_connection()
    _execute(conn, "UPDATE users SET role = %s WHERE id = %s", (role, user_id))
    conn.commit()
    conn.close()
    # Invalidate the admin cache — role change may affect the admin lookup.
    global _admin_user_id_cache
    _admin_user_id_cache = None


# ── Admin user_id resolver (cached per process) ─────────────────────────
# Managers see admin's data: data_user_id returns this value for them.
# We look it up dynamically rather than hard-coding `user_id = 1`,
# because the admin may have a different id in the DB.
_admin_user_id_cache = None

def get_admin_user_id():
    """Return the user_id of the admin (role='admin'), or None if not set.

    Cached for the process lifetime — Vercel function instances are short-lived
    so this is effectively per-request.
    """
    global _admin_user_id_cache
    if _admin_user_id_cache is not None:
        return _admin_user_id_cache
    conn = get_connection()
    try:
        row = _fetchone(conn, "SELECT id FROM users WHERE role = %s ORDER BY id LIMIT 1", ('admin',))
        if row:
            _admin_user_id_cache = row['id'] if isinstance(row, dict) else row[0]
            return _admin_user_id_cache
        return None
    finally:
        conn.close()


def delete_user_and_data(user_id):
    conn = get_connection()
    _execute(conn, "DELETE FROM project_accounts WHERE project_id IN (SELECT id FROM projects WHERE user_id = %s)", (user_id,))
    _execute(conn, "DELETE FROM projects WHERE user_id = %s", (user_id,))
    _execute(conn, "DELETE FROM daily_snapshots WHERE user_id = %s", (user_id,))
    _execute(conn, "DELETE FROM videos WHERE user_id = %s", (user_id,))
    _execute(conn, "DELETE FROM accounts WHERE user_id = %s", (user_id,))
    _execute(conn, "DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
