import os
from flask import Blueprint, redirect, url_for, session, request, render_template, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
from werkzeug.security import generate_password_hash
from database import (
    create_or_update_user, get_user_by_id, seed_user_data, set_user_role,
    get_admin_user_id, create_password_user, get_user_by_email, verify_password,
)

auth_bp = Blueprint('auth', __name__)

# Flask-Login setup
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Veuillez vous connecter pour acceder au tableau de bord.'

# OAuth setup
oauth = OAuth()


class User(UserMixin):
    def __init__(self, user_dict):
        self.id = user_dict['id']
        # google_id is nullable now (password-only users have it as None).
        self.google_id = user_dict.get('google_id')
        self.email = user_dict['email']
        self.name = user_dict.get('name')
        self.avatar_url = user_dict.get('avatar_url')
        self.role = user_dict.get('role', 'user')
        self.blocked = user_dict.get('blocked', False)
        self.created_at = user_dict.get('created_at')
        # Plan is read in templates (e.g. agency-only feature gates like the
        # AI video analysis modal). Default to 'pending' if unset so the
        # paywall fires for any uninitialised row (safer than defaulting to
        # 'monthly' which would silently grant free access).
        self.plan = user_dict.get('plan', 'pending') or 'pending'

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_manager(self):
        return self.role == 'manager'

    @property
    def data_user_id(self):
        """Managers see the admin's data; everyone else sees their own.

        The admin's user_id is looked up dynamically (role='admin' in DB)
        rather than hard-coded, so it adapts when the admin user_id changes.
        Falls back to self.id if no admin is set.
        """
        if self.role == 'manager':
            admin_id = get_admin_user_id()
            if admin_id:
                return admin_id
        return self.id


@login_manager.user_loader
def load_user(user_id):
    user_dict = get_user_by_id(int(user_id))
    if user_dict:
        return User(user_dict)
    return None


def init_auth(app):
    """Initialize authentication on the Flask app."""
    login_manager.init_app(app)
    oauth.init_app(app)

    # Authlib reads GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET from Flask app.config
    oauth.register(
        name='google',
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile'
        }
    )


@auth_bp.route('/login')
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    # Dev mode: auto-login when Google OAuth is not configured
    if not os.environ.get('GOOGLE_CLIENT_ID'):
        user_dict, is_new = create_or_update_user(
            google_id='dev-local',
            email='dev@local.test',
            name='Dev Local',
            avatar_url=None
        )
        user = User(user_dict)
        login_user(user, remember=True)
        # NOTE: seed_user_data() removed here too (see auth_callback comment).
        # Dev-mode users start with an empty dashboard — add accounts via UI.
        if is_new:
            _maybe_send_welcome(user_dict)
        return redirect(url_for('dashboard'))

    return render_template('login.html')


@auth_bp.route('/login/google')
def login_google():
    redirect_uri = url_for('auth.auth_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route('/signup/google')
def signup_google():
    redirect_uri = url_for('auth.auth_callback', _external=True)
    resp = oauth.google.authorize_redirect(redirect_uri)
    # signup intent in a SEPARATE cookie (not Flask session) so it survives
    # even if authlib's session-stored OAuth state has issues with the proxy
    # chain. Short-lived (10 min) and scoped to /auth/callback path.
    resp.set_cookie(
        'tl_signup_intent', '1',
        max_age=600, httponly=True, secure=True, samesite='Lax', path='/'
    )
    return resp


@auth_bp.route('/auth/callback')
def auth_callback():
    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get('userinfo')
        if not userinfo:
            userinfo = oauth.google.get('https://openidconnect.googleapis.com/v1/userinfo').json()

        user_email = userinfo['email'].strip().lower()

        # Allowlist gate — opt-in via ENFORCE_ALLOWLIST=1. Public signup is
        # open by default so the SaaS is commercializable. To re-arm the
        # gate (e.g. private beta), set ENFORCE_ALLOWLIST=1 and populate
        # ADMIN_EMAIL / MANAGER_EMAILS / ALLOWED_EMAILS.
        admin_email = os.environ.get('ADMIN_EMAIL', '').strip().lower()
        manager_emails = [e.strip().lower() for e in os.environ.get('MANAGER_EMAILS', '').split(',') if e.strip()]
        allowed_extra = [e.strip().lower() for e in os.environ.get('ALLOWED_EMAILS', '').split(',') if e.strip()]
        allowlist = {admin_email, *manager_emails, *allowed_extra} - {''}

        if os.environ.get('ENFORCE_ALLOWLIST') == '1' and allowlist and user_email not in allowlist:
            print(f"[Auth] Rejected sign-in: {user_email} not on allowlist")
            return render_template('blocked.html'), 403

        user_dict, is_new = create_or_update_user(
            google_id=userinfo['sub'],
            email=userinfo['email'],
            name=userinfo.get('name', ''),
            avatar_url=userinfo.get('picture', '')
        )

        # Check if user is blocked
        if user_dict.get('blocked'):
            return render_template('blocked.html'), 403

        # Auto-assign admin role if email matches ADMIN_EMAIL
        if admin_email and user_email == admin_email and user_dict.get('role') != 'admin':
            set_user_role(user_dict['id'], 'admin')
            user_dict['role'] = 'admin'

        # Auto-assign manager role if email matches MANAGER_EMAILS
        if user_email in manager_emails and user_dict.get('role') not in ('admin', 'manager'):
            set_user_role(user_dict['id'], 'manager')
            user_dict['role'] = 'manager'

        user = User(user_dict)
        login_user(user, remember=True)

        # NOTE: seed_user_data() was previously called here. It cloned the
        # contents of seed_data.json (6 demo TikTok accounts + their videos
        # + snapshots) into EVERY new user's user_id, which (a) leaked the
        # admin's actual tracked usernames to anyone who signed up, and (b)
        # populated a fake dashboard for users who hadn't added accounts
        # themselves. Removed 2026-05-12. The admin already has the seed
        # applied from initial setup; new users should add their own
        # accounts via the UI.

        # Welcome email on first login only (non-blocking, best-effort)
        if is_new:
            _maybe_send_welcome(user_dict)

        # Google signups from /signup land on /billing to pick a paid plan
        # (consistency with email/password signup flow). Returning users from
        # /login go straight to the dashboard. Intent is read from a separate
        # short-lived cookie so we don't rely on Flask session for it (the
        # session may be lost across the OAuth roundtrip in some proxy setups).
        signup_intent = request.cookies.get('tl_signup_intent') == '1'
        print(f"[Auth] callback ok email={user_email} is_new={is_new} signup_intent={signup_intent} plan={user_dict.get('plan')}")

        if signup_intent and is_new:
            # Brand new Google signup: force plan='pending' so /dashboard
            # redirects to /billing until they pay. Direct UPDATE because
            # set_user_plan() only accepts paid tiers.
            try:
                from database import get_connection, _execute
                conn = get_connection()
                _execute(conn, "UPDATE users SET plan = %s WHERE id = %s", ('pending', user_dict['id']))
                conn.commit()
                conn.close()
                user.plan = 'pending'
            except Exception as e:
                print(f"[Auth] failed to mark new Google signup as pending: {e}")

        if signup_intent and (is_new or user_dict.get('plan') in (None, 'pending', 'starter')):
            resp = redirect(url_for('billing'))
            resp.delete_cookie('tl_signup_intent', path='/')
            return resp

        next_page = request.args.get('next', url_for('dashboard'))
        resp = redirect(next_page)
        # Best-effort cleanup if the intent cookie lingers (e.g. existing user
        # came in through /signup/google but already has a paid plan).
        if request.cookies.get('tl_signup_intent'):
            resp.delete_cookie('tl_signup_intent', path='/')
        return resp
    except Exception as e:
        # Detailed logging so we can diagnose OAuth state mismatches (common
        # cause: session cookie lost across the proxy chain or SameSite issues).
        has_intent = request.cookies.get('tl_signup_intent') == '1'
        session_keys = list(session.keys()) if session else []
        url_state = request.args.get('state', '<none>')[:12]
        print(f"[Auth] Error type={type(e).__name__} msg={e} url_state={url_state} session_keys={session_keys} signup_intent_cookie={has_intent}")
        # If this was a signup attempt, send them back to /signup not /login
        # so they can retry without losing context.
        if has_intent:
            resp = redirect(url_for('auth.signup_page'))
            resp.delete_cookie('tl_signup_intent', path='/')
            return resp
        return redirect(url_for('auth.login'))


def _maybe_send_welcome(user_dict):
    """Fire the welcome email if Resend is configured. Never raises."""
    try:
        from emailer import send_welcome_email
        send_welcome_email(
            to_email=user_dict['email'],
            user_name=user_dict.get('name') or user_dict['email'].split('@')[0],
        )
    except Exception as e:
        print(f"[Auth] welcome email failed (non-fatal): {e}")


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@login_manager.unauthorized_handler
def unauthorized():
    """Handle unauthorized access - return 401 for API, redirect for pages."""
    if request.path.startswith('/api/'):
        from flask import jsonify
        return jsonify({"error": "Non autorise"}), 401
    return redirect(url_for('auth.login', next=request.url))


# ============================================================
# Email + password auth — coexists with Google OAuth.
# Users who sign up via the /signup form get a password_hash and
# plan='pending' until Stripe Checkout completes. Users who signed
# up via Google never have a password_hash. A single email can be
# linked to BOTH methods (create_or_update_user handles linking
# Google to an existing password-only row).
# ============================================================

@auth_bp.route('/signup')
def signup_page():
    """Render the signup form. Already-logged-in users skip to dashboard."""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return render_template(
        'signup.html',
        # .strip() defends against trailing whitespace / newline in the Vercel
        # env var which would break the JS string literal client-side.
        stripe_pub_key=(os.environ.get('STRIPE_PUBLISHABLE_KEY') or '').strip(),
    )


@auth_bp.route('/api/signup', methods=['POST'])
def api_signup():
    """Create an email/password user, log them in, return success.

    Frontend follows up immediately with POST /api/billing/checkout to start
    Stripe Checkout. We log the user in BEFORE redirecting to Stripe so the
    @login_required-protected checkout endpoint accepts the request, and so
    the user can land on /billing on Stripe's return.
    """
    body = request.json or {}
    first_name = (body.get('first_name') or '').strip()
    last_name = (body.get('last_name') or '').strip()
    email = (body.get('email') or '').strip().lower()
    company = (body.get('company') or '').strip() or None
    password = body.get('password') or ''

    # Basic validation (frontend also validates; defense in depth here).
    if not first_name or not last_name:
        return jsonify({"error": "Prénom et nom obligatoires."}), 400
    if '@' not in email or '.' not in email.split('@')[-1]:
        return jsonify({"error": "Email invalide."}), 400
    if len(password) < 8:
        return jsonify({"error": "Le mot de passe doit faire au moins 8 caractères."}), 400

    try:
        user_dict = create_password_user(
            email=email,
            password_hash=generate_password_hash(password),
            first_name=first_name,
            last_name=last_name,
            company=company,
            plan='pending',
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        print(f"[Auth] signup failed: {e}")
        return jsonify({"error": "Erreur lors de la création du compte."}), 500

    user = User(user_dict)
    login_user(user, remember=True)
    return jsonify({"ok": True})


@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    """Email + password login. Returns redirect target on success."""
    body = request.json or {}
    email = (body.get('email') or '').strip().lower()
    password = body.get('password') or ''
    if not email or not password:
        return jsonify({"error": "Email et mot de passe requis."}), 400

    user_dict = verify_password(email, password)
    if not user_dict:
        return jsonify({"error": "Email ou mot de passe incorrect."}), 401

    if user_dict.get('blocked'):
        return jsonify({"error": "Compte suspendu."}), 403

    user = User(user_dict)
    login_user(user, remember=True)

    # Pending payment? Send them back to billing to finish checkout.
    if user_dict.get('plan') == 'pending':
        return jsonify({"ok": True, "redirect": "/billing?resume=1"})
    return jsonify({"ok": True, "redirect": "/dashboard"})
