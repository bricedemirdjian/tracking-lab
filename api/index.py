import os
import sys

# Set VERCEL env if not already set
os.environ.setdefault('VERCEL', '1')

# Add parent directory to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# Watchdog blueprint — registered AFTER `from app import app` so that
# app.py owns the base routes and the watchdog only layers on the
# /api/cron/watchdog, /status, and /api/admin/watchdog/* paths.
#
# Wired here (not inside app.py) deliberately: a parallel refactor agent
# is currently rewriting app.py's connection-handling patterns and we
# must not touch that file mid-flight. Registering in api/index.py keeps
# the watchdog fully decoupled and trivially removable.
try:
    from watchdog import register as _register_watchdog
    _register_watchdog(app)
except Exception as _wdg_exc:
    # The watchdog is defense-in-depth; if it fails to import, the rest
    # of the app must still boot cleanly. Log to stdout so Vercel runtime
    # logs surface it without blocking the function.
    print(f"[Boot] watchdog blueprint failed to register: "
          f"{type(_wdg_exc).__name__}: {_wdg_exc}", flush=True)

# Vercel expects the WSGI app to be named 'app'
