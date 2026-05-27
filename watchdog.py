"""
watchdog.py — proactive auto-heal + transparency layer for Tracking Lab.

WHY THIS EXISTS
---------------
The existing 15-min health-monitor + 6h data-accuracy-check are *reactive*:
they only kick in once degradation has already crossed an alert threshold
(account stale >12h, video sum drift >5%, etc). For a paid SaaS that's far
too late — a 12h gap is an entire workday where customers see stale stats.

The watchdog runs every 5 MINUTES and catches degradation at the earliest
possible moment, then *auto-heals* in-process before any customer notices.
Email alerts only fire when an auto-heal *fails* across two consecutive
ticks (10 minutes) — eliminating noise from transient blips.

ARCHITECTURE
------------
- One Flask blueprint registered onto the existing `app` from `api/index.py`
  (no edits to `app.py` while the parallel `with`-block refactor is in
  flight on that file).
- Two public-facing routes:
    GET /api/cron/watchdog   — CRON_SECRET-protected; the actual tick
    GET /status              — public, no auth; humble status page
- Two admin-only JSON helpers used by the dashboard widget:
    GET /api/admin/watchdog/summary
    GET /api/admin/watchdog/degradations
- Self-contained: it talks to the DB via `database.py` helpers and emails
  through `emailer.send_admin_alert` — no other module imports it.

WHAT IT CHECKS (every 5 min)
----------------------------
  C1  endpoints       — /healthz returns 200
  C2  pool_health     — acquire+release 5 conns rapidly; PoolError => corrupted
  C3  data_freshness  — per (user_id, platform), max age <2h in 9-22 Paris
  C4  stripe_webhook  — last subscription event received <72h
  C5  scrape_loop     — at least one scrape attempt logged in the last 30 min

WHAT IT AUTO-HEALS
------------------
  C2 corrupted → database._force_pool_reset()   (next request rebuilds fresh)
  C3 stale     → internal_trigger('/api/cron/scrape-<platform>')
  C4 webhook   → record-only (no auto-heal — Stripe webhooks aren't ours)
  C5 quiet     → internal_trigger('/api/cron/health-monitor')

WHAT IT ALERTS ON
-----------------
Only when the SAME check fails TWO consecutive ticks (10 min) WITH an
auto-heal attempted on the first. This means a single bad tick (network
blip during the watchdog itself) never wakes Brice — only a real failure
that survives our attempt to fix it does.

WHAT IT DOES NOT DO
-------------------
- It does not own the original 15-min health-monitor or 6h accuracy-check;
  those continue to run as the "second line" of defense.
- It does not modify customer data. Every write goes through the existing
  cron endpoints which already log, alert, and retry on their own.
- It does not deploy code or restart Vercel functions (we don't have the
  privileges; Vercel's runtime is the unit of restart).

OBSERVABILITY
-------------
Every check writes one row to `watchdog_events` (see database.py). The
admin dashboard widget (templates/admin.html / dashboard.html) and the
public /status page both render off those rows.
"""
from __future__ import annotations

import os
import time
import json
import traceback
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple

from flask import Blueprint, jsonify, render_template, request, Response


# ── Module-level config ────────────────────────────────────────────────
_CRON_SECRET = os.environ.get("CRON_SECRET", "").strip()
_BASE_URL = (os.environ.get("APP_BASE_URL") or "https://trackinglab.online").rstrip("/")
_PARIS_BIZ_START = 9   # business hours start (Europe/Paris, 24h)
_PARIS_BIZ_END = 22    # business hours end   (exclusive)
_FRESHNESS_BIZ_MAX_HOURS = 2.0    # data older than this in biz hours = degradation
_FRESHNESS_OFF_MAX_HOURS = 8.0    # outside biz hours we're more lenient
_STRIPE_WEBHOOK_MAX_AGE_H = 72    # any subscription event in last 3 days is fine
_POOL_PROBE_CONNS = 5
_SCRAPE_QUIET_MAX_MINUTES = 60    # if no scrape attempt in 60 min, ping health-monitor

# The watchdog must NEVER block longer than this. Vercel function budget is
# 60s; we cap our own work well below to leave headroom for the response.
_WATCHDOG_DEADLINE_S = 40

# Per-platform freshness check: query `accounts` grouped by platform.
_PLATFORMS = ("tiktok", "youtube", "instagram", "linkedin")


# ── Blueprint ──────────────────────────────────────────────────────────
watchdog_bp = Blueprint("watchdog", __name__)


# ── Auth helpers ───────────────────────────────────────────────────────
def _cron_auth_ok() -> bool:
    """Same gate as app._cron_auth_check() but local — keeps the watchdog
    blueprint independent of app.py so the parallel refactor agent can
    rewrite that file freely."""
    if not _CRON_SECRET:
        # In dev with no secret configured, allow anonymous (matches existing
        # behaviour of /api/cron/* when CRON_SECRET is unset locally).
        return not _is_production()
    return request.headers.get("Authorization", "") == f"Bearer {_CRON_SECRET}"


def _is_production() -> bool:
    return bool(
        os.environ.get("RENDER")
        or os.environ.get("PRODUCTION")
        or os.environ.get("VERCEL")
    )


def _is_admin_request() -> bool:
    """Best-effort admin gate using flask-login. Used by /api/admin/watchdog/*."""
    try:
        from flask_login import current_user
        return bool(getattr(current_user, "is_authenticated", False)
                    and getattr(current_user, "is_admin", False))
    except Exception:
        return False


# ── Time helpers ───────────────────────────────────────────────────────
def _is_paris_business_hours(now_utc: Optional[datetime] = None) -> bool:
    """Return True if it's 09:00-22:00 in Europe/Paris RIGHT NOW.

    We do this manually (UTC offset table) instead of pulling pytz/zoneinfo
    so the watchdog has zero new dependencies and stays sub-100ms.
    Europe/Paris is UTC+1 in winter, UTC+2 in summer (DST). Last Sunday of
    March → last Sunday of October = +2; rest = +1.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    year = now_utc.year
    # Compute last Sundays
    def _last_sunday(month):
        # Start at the 31st (or whichever day exists) and walk backward.
        from calendar import monthrange
        last_day = monthrange(year, month)[1]
        d = datetime(year, month, last_day, tzinfo=timezone.utc)
        while d.weekday() != 6:  # Monday=0..Sunday=6
            d -= timedelta(days=1)
        return d
    dst_start = _last_sunday(3).replace(hour=1)   # 01:00 UTC → 02:00 → 03:00 local
    dst_end = _last_sunday(10).replace(hour=1)
    offset = 2 if dst_start <= now_utc < dst_end else 1
    paris_hour = (now_utc.hour + offset) % 24
    return _PARIS_BIZ_START <= paris_hour < _PARIS_BIZ_END


# ── Telemetry: was the same check degraded on the previous tick? ───────
def _previous_tick_degraded(check_name: str, within_minutes: int = 12) -> bool:
    """Look back at most one tick window. We use 12 min (slightly wider than
    the 5-min schedule) so a watchdog run that fires a touch late still
    catches the previous one.
    """
    try:
        from database import get_connection, _fetchall, DATABASE_URL
        conn = get_connection()
        try:
            if DATABASE_URL:
                rows = _fetchall(conn, """
                    SELECT degradation_detected, healed_successfully
                    FROM watchdog_events
                    WHERE check_name = %s
                      AND ts >= NOW() - (%s || ' minutes')::interval
                    ORDER BY ts DESC
                    LIMIT 1
                """, (check_name, str(int(within_minutes))))
            else:
                rows = _fetchall(conn, """
                    SELECT degradation_detected, healed_successfully
                    FROM watchdog_events
                    WHERE check_name = %s
                      AND ts >= datetime('now', %s)
                    ORDER BY ts DESC
                    LIMIT 1
                """, (check_name, f'-{int(within_minutes)} minutes'))
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if not rows:
            return False
        prev = rows[0]
        # Postgres returns Python bools; SQLite returns 0/1 ints.
        prev_degraded = bool(prev.get("degradation_detected"))
        prev_healed = prev.get("healed_successfully")
        # If we *healed* successfully last tick, today's failure is a fresh
        # one, not the same issue persisting — don't escalate.
        if prev_degraded and prev_healed is True:
            return False
        return prev_degraded
    except Exception:
        # If we can't read history, default to NOT escalating (avoids a
        # cascading alert if the DB itself is the issue — the DB outage
        # would already trip /healthz alerting elsewhere).
        return False


# ── Internal endpoint trigger (server-to-self) ─────────────────────────
def _internal_trigger(path: str, *, timeout_s: float = 20.0) -> Tuple[bool, str]:
    """Fire a self-request to an internal /api/cron/* path with CRON_SECRET.

    We use HTTP rather than calling the Flask view function directly so:
      1. We don't have to mess with the active Flask request context.
      2. The cron's own rate-limit / auth flow runs exactly as a real
         GitHub Actions ping would (no special-case code path).
      3. The Vercel platform sees it as a normal HTTPS request, so the
         function's 60s budget is per-call (not shared with the watchdog).
    """
    import urllib.request
    import urllib.error
    url = f"{_BASE_URL}{path}"
    headers = {}
    if _CRON_SECRET:
        headers["Authorization"] = f"Bearer {_CRON_SECRET}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            code = resp.getcode()
            body = resp.read(2048).decode("utf-8", errors="replace")
            ok = 200 <= code < 300
            return ok, f"HTTP {code}: {body[:300]}"
    except urllib.error.HTTPError as e:
        return False, f"HTTPError {e.code}: {e.reason}"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


# ── Individual checks ──────────────────────────────────────────────────
def _check_endpoint(path: str, *, expect_status: int = 200,
                    timeout_s: float = 8.0) -> Dict[str, Any]:
    """C1: probe a critical endpoint. /healthz is the canonical one — it
    already covers DB connectivity, boot status, and pooler detection.
    Returns {'ok': bool, 'detail': ...}."""
    import urllib.request
    import urllib.error
    url = f"{_BASE_URL}{path}"
    headers = {}
    # /healthz and /status are public; /api/cron/* require the bearer.
    if path.startswith("/api/cron/") and _CRON_SECRET:
        headers["Authorization"] = f"Bearer {_CRON_SECRET}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            code = resp.getcode()
            elapsed_ms = int((time.time() - t0) * 1000)
            ok = code == expect_status
            return {"ok": ok, "status": code, "elapsed_ms": elapsed_ms, "path": path}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "path": path,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "error": f"HTTPError {e.code}"}
    except Exception as e:
        return {"ok": False, "status": None, "path": path,
                "elapsed_ms": int((time.time() - t0) * 1000),
                "error": f"{type(e).__name__}: {str(e)[:120]}"}


def _check_pool_health() -> Dict[str, Any]:
    """C2: acquire+release N connections rapidly. If any acquire raises
    PoolError or the borrowed conn fails a SELECT 1, the pool is corrupted
    on this Vercel function instance and needs to be torn down.

    Returns: {'ok': bool, 'attempted': N, 'failed': K, 'errors': [...]}
    """
    from database import get_connection, _cur, DATABASE_URL
    if not DATABASE_URL:
        return {"ok": True, "attempted": 0, "failed": 0, "skipped": "sqlite_backend"}
    attempted = 0
    failed = 0
    errors: List[str] = []
    conns: List[Any] = []
    try:
        # First pass: hold N conns at once to probe pool *capacity*.
        for i in range(_POOL_PROBE_CONNS):
            attempted += 1
            try:
                c = get_connection()
                conns.append(c)
                cur = _cur(c)
                cur.execute("SELECT 1")
                cur.fetchone()
                cur.close()
            except Exception as e:
                failed += 1
                errors.append(f"#{i}: {type(e).__name__}: {str(e)[:120]}")
                # Continue probing — partial failure is still useful signal.
    finally:
        for c in conns:
            try:
                c.close()
            except Exception:
                pass
    return {
        "ok": failed == 0,
        "attempted": attempted,
        "failed": failed,
        "errors": errors[:5],
    }


def _check_data_freshness() -> Dict[str, Any]:
    """C3: per-platform max(NOW() - last_updated) across all paying users'
    accounts. Threshold is tighter during Paris business hours.

    Returns a dict like:
        {
          "ok": False,
          "biz_hours": True,
          "threshold_h": 2.0,
          "stale_platforms": ["tiktok"],
          "per_platform": {
              "tiktok":   {"max_age_h": 4.2, "accounts": 12, "stale": True},
              "instagram":{"max_age_h": 0.7, "accounts": 18, "stale": False},
              ...
          }
        }
    """
    from database import get_connection, _fetchall, DATABASE_URL
    biz = _is_paris_business_hours()
    threshold_h = _FRESHNESS_BIZ_MAX_HOURS if biz else _FRESHNESS_OFF_MAX_HOURS
    per_platform: Dict[str, Dict[str, Any]] = {}
    stale_platforms: List[str] = []
    try:
        conn = get_connection()
        try:
            if DATABASE_URL:
                rows = _fetchall(conn, """
                    SELECT
                        a.platform,
                        COUNT(*)                                                        AS accounts,
                        MAX(EXTRACT(EPOCH FROM (NOW() - a.last_updated)) / 3600.0)::float AS max_age_h,
                        AVG(EXTRACT(EPOCH FROM (NOW() - a.last_updated)) / 3600.0)::float AS avg_age_h
                    FROM accounts a
                    JOIN users u ON u.id = a.user_id
                    WHERE a.last_updated IS NOT NULL
                      AND COALESCE(u.blocked, FALSE) = FALSE
                      AND COALESCE(u.plan, 'pending') NOT IN ('pending')
                    GROUP BY a.platform
                """)
            else:
                # SQLite doesn't have EXTRACT(EPOCH FROM ...); use julianday().
                rows = _fetchall(conn, """
                    SELECT
                        a.platform,
                        COUNT(*) AS accounts,
                        MAX((julianday('now') - julianday(a.last_updated)) * 24.0) AS max_age_h,
                        AVG((julianday('now') - julianday(a.last_updated)) * 24.0) AS avg_age_h
                    FROM accounts a
                    JOIN users u ON u.id = a.user_id
                    WHERE a.last_updated IS NOT NULL
                      AND COALESCE(u.blocked, 0) = 0
                      AND COALESCE(u.plan, 'pending') NOT IN ('pending')
                    GROUP BY a.platform
                """)
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}",
                "biz_hours": biz, "threshold_h": threshold_h,
                "stale_platforms": [], "per_platform": {}}

    seen_platforms = set()
    for r in rows or []:
        plat = r.get("platform") or "unknown"
        seen_platforms.add(plat)
        max_age = float(r.get("max_age_h") or 0)
        is_stale = max_age > threshold_h
        per_platform[plat] = {
            "max_age_h": round(max_age, 2),
            "avg_age_h": round(float(r.get("avg_age_h") or 0), 2),
            "accounts": int(r.get("accounts") or 0),
            "stale": is_stale,
        }
        if is_stale:
            stale_platforms.append(plat)

    # Platforms with ZERO paying-customer accounts aren't a degradation — they
    # genuinely have nothing to scrape. We only report platforms we actually
    # observed data for.
    return {
        "ok": not stale_platforms,
        "biz_hours": biz,
        "threshold_h": threshold_h,
        "stale_platforms": stale_platforms,
        "per_platform": per_platform,
        "platforms_observed": sorted(seen_platforms),
    }


def _check_stripe_webhook_freshness() -> Dict[str, Any]:
    """C4: when was the last subscription event recorded? Updates to
    subscriptions.updated_at happen on every webhook (customer.subscription.*).

    If we haven't seen one in 3 days AND we have any active subscriptions,
    that's a possible webhook signature mismatch or DNS issue at the Stripe
    edge. Record-only — we can't auto-heal Stripe.
    """
    from database import get_connection, _fetchall, _fetchone, DATABASE_URL
    try:
        conn = get_connection()
        try:
            active = _fetchone(conn,
                "SELECT COUNT(*) AS n FROM subscriptions WHERE status = %s",
                ("active",))
            if not active or int(active.get("n", 0) or 0) == 0:
                return {"ok": True, "skipped": "no_active_subscriptions"}
            if DATABASE_URL:
                row = _fetchone(conn, """
                    SELECT MAX(updated_at) AS last_evt,
                           EXTRACT(EPOCH FROM (NOW() - MAX(updated_at))) / 3600.0 AS age_h
                    FROM subscriptions
                    WHERE status = 'active'
                """)
            else:
                row = _fetchone(conn, """
                    SELECT MAX(updated_at) AS last_evt,
                           (julianday('now') - julianday(MAX(updated_at))) * 24.0 AS age_h
                    FROM subscriptions
                    WHERE status = 'active'
                """)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        age_h = float((row or {}).get("age_h") or 0)
        ok = age_h <= _STRIPE_WEBHOOK_MAX_AGE_H
        return {
            "ok": ok,
            "age_h": round(age_h, 2),
            "last_evt": str((row or {}).get("last_evt") or ""),
            "threshold_h": _STRIPE_WEBHOOK_MAX_AGE_H,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def _check_scrape_loop_alive() -> Dict[str, Any]:
    """C5: did we attempt at least one scrape (success or failure) in the
    last N minutes? Uses accounts.last_updated OR last_success_at OR
    consecutive_failures bump time as a proxy.

    With the GitHub Actions cron firing every 2-3 hours plus daily Vercel
    crons, the global watermark should always be <30 min stale during
    business hours. If nothing has happened in 60 min, the scrape loop is
    quiet → ping /api/cron/health-monitor as a defibrillator.
    """
    from database import get_connection, _fetchone, DATABASE_URL
    try:
        conn = get_connection()
        try:
            if DATABASE_URL:
                row = _fetchone(conn, """
                    SELECT
                        EXTRACT(EPOCH FROM (NOW() - GREATEST(
                            COALESCE(MAX(last_updated),   '1970-01-01'::timestamp),
                            COALESCE(MAX(last_success_at),'1970-01-01'::timestamp)
                        ))) / 60.0 AS quiet_min
                    FROM accounts
                """)
            else:
                row = _fetchone(conn, """
                    SELECT
                        (julianday('now') - julianday(MAX(COALESCE(last_updated, last_success_at)))) * 1440.0
                            AS quiet_min
                    FROM accounts
                """)
        finally:
            try:
                conn.close()
            except Exception:
                pass
        quiet_min = float((row or {}).get("quiet_min") or 0)
        return {
            "ok": quiet_min <= _SCRAPE_QUIET_MAX_MINUTES,
            "quiet_minutes": round(quiet_min, 1),
            "threshold_minutes": _SCRAPE_QUIET_MAX_MINUTES,
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


# ── Tick orchestrator ──────────────────────────────────────────────────
def _alert_if_persistent(check_name: str, detail: Dict[str, Any],
                        healed: Optional[bool], severity: str = "warning") -> bool:
    """Send admin email iff this check ALSO failed last tick. Returns
    True if an alert was actually fired (used to set alert_sent in
    watchdog_events)."""
    # If we just healed successfully, don't escalate — even if last tick
    # was degraded.
    if healed is True:
        return False
    # First-tick degradation: silent. Only the second consecutive tick
    # earns an email — kills 95% of alert noise.
    if not _previous_tick_degraded(check_name):
        return False
    try:
        from emailer import send_admin_alert
        body = (
            f"Le watchdog a détecté `{check_name}` en dégradation sur DEUX "
            f"ticks consécutifs (10 min), ET l'auto-heal a échoué.\n\n"
            f"Détail technique :\n{json.dumps(detail, indent=2, default=str)[:2400]}\n\n"
            "Action recommandée :\n"
            "  - Vérifier https://trackinglab.online/healthz\n"
            "  - Consulter les logs Vercel runtime des 30 dernières minutes\n"
            "  - Si pool corrompu persistant : redéployer pour rebooter les instances\n"
        )
        sent = send_admin_alert(
            subject=f"watchdog: {check_name} dégradé 2 ticks de suite",
            body_text=body,
            severity=severity,
        )
        return bool(sent)
    except Exception:
        # Email layer failure must not crash the watchdog itself.
        return False


def _run_tick() -> Dict[str, Any]:
    """Execute one watchdog pass. Returns a summary dict for the response."""
    from database import (
        record_watchdog_event, _force_pool_reset, prune_watchdog_events,
    )
    t_started = time.time()
    deadline = t_started + _WATCHDOG_DEADLINE_S

    summary: Dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "biz_hours_paris": _is_paris_business_hours(),
        "checks": {},
        "auto_heals": [],
        "alerts": [],
    }

    def _record(name, *, degraded, attempted, healed, alerted, dur_ms, detail):
        try:
            record_watchdog_event(
                name,
                degradation_detected=degraded,
                auto_heal_attempted=attempted,
                healed_successfully=healed,
                alert_sent=alerted,
                duration_ms=dur_ms,
                detail=detail,
            )
        except Exception:
            # Already swallowed inside record_watchdog_event, but belt-and-braces.
            pass

    # ── C1: /healthz endpoint ─────────────────────────────────────────
    t0 = time.time()
    r = _check_endpoint("/healthz")
    dur = int((time.time() - t0) * 1000)
    degraded = not r["ok"]
    healed = None
    alerted = False
    if degraded:
        # /healthz failing usually means the function instance is dying.
        # We can't restart Vercel — but we CAN nuke our pool so the next
        # caller rebuilds it. That's a no-op if /healthz fails for non-DB
        # reasons (boot, import) but harmless.
        reset = _force_pool_reset()
        summary["auto_heals"].append({"check": "endpoint:/healthz",
                                      "action": "force_pool_reset",
                                      "result": reset})
        # We don't re-probe immediately — leave it for the next tick.
        # Mark healed as unknown (None) — the next tick will confirm.
        alerted = _alert_if_persistent("endpoint:/healthz", r, healed,
                                        severity="critical")
        summary["alerts"].append({"check": "endpoint:/healthz",
                                  "sent": alerted}) if alerted else None
    summary["checks"]["endpoint_healthz"] = {**r, "degraded": degraded}
    _record("endpoint:/healthz", degraded=degraded, attempted=degraded,
            healed=healed, alerted=alerted, dur_ms=dur, detail=r)

    if time.time() > deadline:
        summary["aborted"] = "deadline_exceeded_after_endpoint"
        return summary

    # ── C2: pool health probe ─────────────────────────────────────────
    t0 = time.time()
    r = _check_pool_health()
    dur = int((time.time() - t0) * 1000)
    degraded = not r["ok"]
    healed = None
    alerted = False
    if degraded:
        reset = _force_pool_reset()
        # Re-probe ONCE to confirm the rebuilt pool works. If it does, mark
        # healed=True so the next tick won't alert. If it still fails, leave
        # healed=False so a persistent failure escalates next tick.
        time.sleep(0.5)  # let any in-flight conns settle
        r2 = _check_pool_health()
        healed = r2["ok"]
        summary["auto_heals"].append({
            "check": "pool_health",
            "action": "force_pool_reset",
            "reset_result": reset,
            "reprobe_ok": healed,
            "reprobe_detail": r2,
        })
        alerted = _alert_if_persistent("pool_health", {**r, "reprobe": r2}, healed,
                                        severity="critical")
        if alerted:
            summary["alerts"].append({"check": "pool_health", "sent": True})
    summary["checks"]["pool_health"] = {**r, "degraded": degraded, "healed": healed}
    _record("pool_health", degraded=degraded, attempted=degraded,
            healed=healed, alerted=alerted, dur_ms=dur, detail=r)

    if time.time() > deadline:
        summary["aborted"] = "deadline_exceeded_after_pool"
        return summary

    # ── C3: data freshness per platform ───────────────────────────────
    t0 = time.time()
    r = _check_data_freshness()
    dur = int((time.time() - t0) * 1000)
    degraded = not r.get("ok", True)
    healed = None
    alerted = False
    if degraded:
        # Trigger a scrape for each stale platform. We map platform → cron
        # endpoint. Each is fire-and-forget on a short timeout — we don't
        # block the watchdog waiting 30s for a scrape to finish.
        platform_cron = {
            "tiktok":   "/api/cron/scrape-tiktok-youtube",
            "youtube":  "/api/cron/scrape-tiktok-youtube",
            "instagram": "/api/cron/scrape-instagram",
            "linkedin": "/api/cron/scrape-linkedin",
        }
        triggered = {}
        seen_paths = set()
        for plat in r.get("stale_platforms", []):
            path = platform_cron.get(plat)
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            ok, msg = _internal_trigger(path, timeout_s=15.0)
            triggered[path] = {"ok": ok, "msg": msg[:200]}
        summary["auto_heals"].append({
            "check": "data_freshness",
            "action": "trigger_scrape_endpoints",
            "triggered": triggered,
        })
        # We don't re-check freshness immediately (the scrape takes longer
        # than our deadline). Next tick will confirm.
        all_ok = bool(triggered) and all(v["ok"] for v in triggered.values())
        healed = True if all_ok else False
        alerted = _alert_if_persistent("data_freshness",
                                        {**r, "triggered": triggered}, healed,
                                        severity="warning")
        if alerted:
            summary["alerts"].append({"check": "data_freshness", "sent": True})
    summary["checks"]["data_freshness"] = {**r, "degraded": degraded, "healed": healed}
    _record("data_freshness", degraded=degraded, attempted=degraded,
            healed=healed, alerted=alerted, dur_ms=dur, detail=r)

    if time.time() > deadline:
        summary["aborted"] = "deadline_exceeded_after_freshness"
        return summary

    # ── C4: stripe webhook freshness ──────────────────────────────────
    t0 = time.time()
    r = _check_stripe_webhook_freshness()
    dur = int((time.time() - t0) * 1000)
    degraded = not r.get("ok", True) and "skipped" not in r
    # No auto-heal — Stripe's webhook delivery isn't ours to fix.
    alerted = False
    if degraded:
        alerted = _alert_if_persistent("stripe_webhook", r, healed=None,
                                        severity="warning")
        if alerted:
            summary["alerts"].append({"check": "stripe_webhook", "sent": True})
    summary["checks"]["stripe_webhook"] = {**r, "degraded": degraded}
    _record("stripe_webhook", degraded=degraded, attempted=False,
            healed=None, alerted=alerted, dur_ms=dur, detail=r)

    if time.time() > deadline:
        summary["aborted"] = "deadline_exceeded_after_stripe"
        return summary

    # ── C5: scrape loop alive ─────────────────────────────────────────
    t0 = time.time()
    r = _check_scrape_loop_alive()
    dur = int((time.time() - t0) * 1000)
    degraded = not r.get("ok", True)
    healed = None
    alerted = False
    if degraded:
        ok, msg = _internal_trigger("/api/cron/health-monitor", timeout_s=15.0)
        summary["auto_heals"].append({
            "check": "scrape_loop",
            "action": "trigger_health_monitor",
            "result": {"ok": ok, "msg": msg[:200]},
        })
        healed = ok
        alerted = _alert_if_persistent("scrape_loop",
                                        {**r, "trigger_msg": msg[:200]}, healed,
                                        severity="warning")
        if alerted:
            summary["alerts"].append({"check": "scrape_loop", "sent": True})
    summary["checks"]["scrape_loop"] = {**r, "degraded": degraded, "healed": healed}
    _record("scrape_loop", degraded=degraded, attempted=degraded,
            healed=healed, alerted=alerted, dur_ms=dur, detail=r)

    # ── Cleanup pass: trim watchdog_events to last 30 days (cheap) ────
    # Only on a fraction of ticks so we don't add DELETE overhead to every
    # 5-min run. ts % 12 ≈ once per hour.
    try:
        if datetime.utcnow().minute % 60 < 5:
            prune_watchdog_events(older_than_days=30)
    except Exception:
        pass

    summary["duration_ms"] = int((time.time() - t_started) * 1000)
    summary["ok"] = not any(c.get("degraded") for c in summary["checks"].values())
    return summary


# ── Public routes ──────────────────────────────────────────────────────
@watchdog_bp.route("/api/cron/watchdog", methods=["GET"])
def cron_watchdog():
    """The 5-min auto-heal tick. Protected by CRON_SECRET."""
    if not _cron_auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        summary = _run_tick()
        # If the tick itself crashes anywhere below, the outer except sends
        # a dedicated "watchdog itself failed" alert — fail-loud-on-itself.
        return jsonify(summary), 200
    except Exception as e:
        try:
            from database import _oneline_tb, record_watchdog_event
            _oneline_tb("watchdog_tick_crashed", e)
            record_watchdog_event(
                "watchdog_self",
                degradation_detected=True,
                auto_heal_attempted=False,
                healed_successfully=False,
                alert_sent=True,
                detail={"crash": f"{type(e).__name__}: {str(e)[:240]}"},
            )
        except Exception:
            pass
        # Critical: the watchdog crashing IS the alert. No 2-tick rule.
        try:
            from emailer import send_admin_alert
            send_admin_alert(
                subject="watchdog crashed (self-failure)",
                body_text=(
                    "Le watchdog lui-même a planté pendant un tick. C'est une "
                    "anomalie sérieuse — la couche d'auto-heal n'a pas tourné.\n\n"
                    f"Exception: {type(e).__name__}: {e}\n\n"
                    f"Stack:\n{traceback.format_exc()[:2400]}"
                ),
                severity="critical",
            )
        except Exception:
            pass
        return jsonify({"error": "watchdog_crashed",
                        "error_type": type(e).__name__,
                        "message": str(e)[:240]}), 500


@watchdog_bp.route("/status", methods=["GET"])
def status_page():
    """Public, no-auth status page. Renders templates/status.html. Customer
    trust signal: 'they monitor their own SaaS, in public'.

    Renders even if the underlying DB query fails — degraded view shows
    "Status data unavailable" rather than throwing a 500."""
    try:
        from database import get_watchdog_summary, get_connection, _fetchall, DATABASE_URL
        rollup = get_watchdog_summary(hours=24) or {}
        # Per-platform freshness for the status table.
        per_platform: List[Dict[str, Any]] = []
        try:
            conn = get_connection()
            try:
                if DATABASE_URL:
                    rows = _fetchall(conn, """
                        SELECT a.platform,
                               COUNT(*) AS accounts,
                               MAX(a.last_updated) AS last_success,
                               MAX(EXTRACT(EPOCH FROM (NOW() - a.last_updated)) / 60.0)::float AS max_age_min
                        FROM accounts a
                        JOIN users u ON u.id = a.user_id
                        WHERE a.last_updated IS NOT NULL
                          AND COALESCE(u.blocked, FALSE) = FALSE
                        GROUP BY a.platform
                        ORDER BY a.platform
                    """)
                else:
                    rows = _fetchall(conn, """
                        SELECT a.platform,
                               COUNT(*) AS accounts,
                               MAX(a.last_updated) AS last_success,
                               MAX((julianday('now') - julianday(a.last_updated)) * 1440.0) AS max_age_min
                        FROM accounts a
                        JOIN users u ON u.id = a.user_id
                        WHERE a.last_updated IS NOT NULL
                          AND COALESCE(u.blocked, 0) = 0
                        GROUP BY a.platform
                        ORDER BY a.platform
                    """)
                for r in rows or []:
                    age_min = float(r.get("max_age_min") or 0)
                    if age_min < 60:
                        age_label = f"il y a {int(age_min)} min"
                    elif age_min < 1440:
                        age_label = f"il y a {age_min/60:.1f} h"
                    else:
                        age_label = f"il y a {age_min/1440:.1f} j"
                    # Operational thresholds:
                    #   <2h biz / <8h off = OK (green)
                    #   <6h biz / <12h off = degraded (amber)
                    #   else = down (red)
                    biz = _is_paris_business_hours()
                    if age_min <= (120 if biz else 480):
                        state = "ok"
                    elif age_min <= (360 if biz else 720):
                        state = "degraded"
                    else:
                        state = "down"
                    per_platform.append({
                        "platform": r.get("platform"),
                        "accounts": int(r.get("accounts") or 0),
                        "age_label": age_label,
                        "state": state,
                    })
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception:
            per_platform = []

        # Decide overall status badge
        if any(p["state"] == "down" for p in per_platform):
            overall = "down"
        elif any(p["state"] == "degraded" for p in per_platform):
            overall = "degraded"
        else:
            overall = "operational"

        return render_template(
            "status.html",
            overall=overall,
            per_platform=per_platform,
            rollup=rollup,
            last_tick=rollup.get("last_tick"),
        )
    except Exception:
        # Render a safe minimal HTML rather than 500 — public-facing page.
        html = ("<!doctype html><meta charset=utf-8>"
                "<title>Tracking Lab — Status</title>"
                "<body style='font-family:system-ui;padding:48px;color:#1d1d1f;'>"
                "<h1>Status temporairement indisponible</h1>"
                "<p>Le service principal est opérationnel. La page de statut "
                "est en cours de mise à jour.</p>"
                "<p><a href='/'>Retour à l'accueil</a></p></body>")
        return Response(html, status=200, mimetype="text/html")


# ── Admin JSON endpoints (consumed by the admin dashboard widget) ─────
@watchdog_bp.route("/api/admin/watchdog/summary", methods=["GET"])
def admin_watchdog_summary():
    if not _is_admin_request():
        return jsonify({"error": "Forbidden"}), 403
    try:
        from database import get_watchdog_summary
        hours = int(request.args.get("hours", "24"))
        hours = max(1, min(hours, 168))
        return jsonify({"hours": hours, "summary": get_watchdog_summary(hours=hours)})
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500


@watchdog_bp.route("/api/admin/watchdog/degradations", methods=["GET"])
def admin_watchdog_degradations():
    if not _is_admin_request():
        return jsonify({"error": "Forbidden"}), 403
    try:
        from database import get_watchdog_recent_degradations
        limit = int(request.args.get("limit", "20"))
        limit = max(1, min(limit, 200))
        rows = get_watchdog_recent_degradations(limit=limit)
        # Parse JSON detail string back to dict for the UI.
        out = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("detail"), str):
                try:
                    d["detail"] = json.loads(d["detail"])
                except Exception:
                    pass
            # Normalise dates → ISO string for JSON safety.
            if d.get("ts") is not None and not isinstance(d["ts"], str):
                d["ts"] = d["ts"].isoformat()
            out.append(d)
        return jsonify({"degradations": out})
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 500


@watchdog_bp.route("/admin/watchdog", methods=["GET"])
def admin_watchdog_page():
    """Admin-only widget page. Tiny standalone view at /admin/watchdog —
    intentionally separate from /admin so we don't have to touch admin.html
    or its template/JS while the parallel app.py refactor is in flight.

    Renders zero on un-auth'd access (redirect to dashboard so we don't
    leak "this URL exists" info).
    """
    try:
        from flask_login import current_user
        from flask import redirect, url_for
        if not getattr(current_user, "is_authenticated", False):
            return redirect("/login")
        if not getattr(current_user, "is_admin", False):
            return redirect("/dashboard")
    except Exception:
        # If flask-login isn't wired the way we expect, treat as un-auth'd.
        from flask import redirect
        return redirect("/")
    return render_template("admin_watchdog.html")


def register(app):
    """Idempotent registration helper for api/index.py. Call after `from
    app import app` so the existing routes are already attached.

    Idempotency: blueprints can only be registered once per Flask app; we
    no-op silently on the second call so a re-import (Vercel warm path)
    doesn't crash boot.
    """
    if "watchdog" in app.blueprints:
        return False
    app.register_blueprint(watchdog_bp)
    return True
