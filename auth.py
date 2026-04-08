import os
from flask import Blueprint, redirect, url_for, session, request, render_template
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
from database import create_or_update_user, get_user_by_id, seed_user_data, set_user_role

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
        self.google_id = user_dict['google_id']
        self.email = user_dict['email']
        self.name = user_dict['name']
        self.avatar_url = user_dict['avatar_url']
        self.role = user_dict.get('role', 'user')
        self.blocked = user_dict.get('blocked', False)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_manager(self):
        return self.role == 'manager'

    @property
    def data_user_id(self):
        """Managers see admin's data (user_id=1), others see their own."""
        if self.role == 'manager':
            return 1  # Admin's user_id
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
        user_dict = create_or_update_user(
            google_id='dev-local',
            email='dev@local.test',
            name='Dev Local',
            avatar_url=None
        )
        user = User(user_dict)
        login_user(user, remember=True)
        seed_user_data(user.id)
        return redirect(url_for('dashboard'))

    return render_template('login.html')


@auth_bp.route('/login/google')
def login_google():
    redirect_uri = url_for('auth.auth_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route('/auth/callback')
def auth_callback():
    try:
        token = oauth.google.authorize_access_token()
        userinfo = token.get('userinfo')
        if not userinfo:
            userinfo = oauth.google.get('https://openidconnect.googleapis.com/v1/userinfo').json()

        user_dict = create_or_update_user(
            google_id=userinfo['sub'],
            email=userinfo['email'],
            name=userinfo.get('name', ''),
            avatar_url=userinfo.get('picture', '')
        )

        # Check if user is blocked
        if user_dict.get('blocked'):
            return render_template('blocked.html'), 403

        # Auto-assign admin role if email matches ADMIN_EMAIL
        admin_email = os.environ.get('ADMIN_EMAIL', '')
        if admin_email and userinfo['email'].lower() == admin_email.lower() and user_dict.get('role') != 'admin':
            set_user_role(user_dict['id'], 'admin')
            user_dict['role'] = 'admin'

        # Auto-assign manager role if email matches MANAGER_EMAILS
        manager_emails = [e.strip().lower() for e in os.environ.get('MANAGER_EMAILS', '').split(',') if e.strip()]
        if userinfo['email'].lower() in manager_emails and user_dict.get('role') not in ('admin', 'manager'):
            set_user_role(user_dict['id'], 'manager')
            user_dict['role'] = 'manager'

        user = User(user_dict)
        login_user(user, remember=True)

        # Auto-seed historical data for new users with no accounts
        seed_user_data(user.id)

        next_page = request.args.get('next', url_for('dashboard'))
        return redirect(next_page)
    except Exception as e:
        print(f"[Auth] Error: {e}")
        return redirect(url_for('auth.login'))


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
