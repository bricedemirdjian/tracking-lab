import os
import stripe

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# Pricing collapsed on 2026-05-20 to a single offer with two billing
# cadences (full feature parity, no gated tiers):
#   - 'pro' = formule mensuelle (29,99€ TTC/mois)
#   - 'agency' = formule annuelle (79,99€ TTC/an, soit ~6,67€/mois)
# Plan keys are kept as 'pro'/'agency' to avoid migrating the users.plan
# column; the user-facing names are 'Mensuel' / 'Annuel'. 'starter' is the
# legacy free tier — no longer sold, but kept as a no-op fallback for any
# pre-existing rows (and the auth.py default when a user is created before
# they pick a plan).
PLANS = {
    'starter': {
        'name': 'Starter (legacy)',
        'price': 0,
        'price_annual': 0,
        'price_id': None,
        'price_id_annual': None,
        # Legacy free tier: keep the original limits so existing rows
        # don't suddenly gain unlimited access without paying. Anyone new
        # is routed to 'pro' or 'agency' on signup.
        'max_accounts': 1,
        'max_videos': 999999,
        'max_projects': 1,
        'max_shared_users': 0,
        'platforms': ['tiktok', 'youtube'],
        'instagram': False,
        'linkedin': False,
        'export_csv': False,
        'import_csv': False,
        'competitor_access': False,
        'analytics_full': False,
        'ai_video_analysis': False,
        'scrape_cadence_hours': 6,
    },
    'pro': {
        'name': 'Mensuel',
        'price': 29.99,
        'price_annual': 29.99,  # legacy field, kept = price for back-compat
        'price_id': os.environ.get('STRIPE_MONTHLY_PRICE_ID'),
        'price_id_annual': os.environ.get('STRIPE_MONTHLY_PRICE_ID'),
        # Full feature parity with the annual plan — only difference is
        # the Stripe billing cadence.
        'max_accounts': 9999,
        'max_videos': 999999,
        'max_projects': 9999,
        'max_shared_users': 9999,
        'platforms': ['tiktok', 'youtube', 'instagram', 'linkedin'],
        'instagram': True,
        'linkedin': True,
        'export_csv': True,
        'import_csv': True,
        'competitor_access': True,
        'analytics_full': True,
        'ai_video_analysis': True,
        'scrape_cadence_hours': 1,
    },
    'agency': {
        'name': 'Annuel',
        'price': 79.99,
        'price_annual': 79.99,
        'price_id': os.environ.get('STRIPE_ANNUAL_PRICE_ID'),
        'price_id_annual': os.environ.get('STRIPE_ANNUAL_PRICE_ID'),
        'max_accounts': 9999,
        'max_videos': 999999,
        'max_projects': 9999,
        'max_shared_users': 9999,
        'platforms': ['tiktok', 'youtube', 'instagram', 'linkedin'],
        'instagram': True,
        'linkedin': True,
        'export_csv': True,
        'import_csv': True,
        'competitor_access': True,
        'analytics_full': True,
        'ai_video_analysis': True,
        'scrape_cadence_hours': 1,
    },
}


# Admin role bypasses tier-based scrape throttling. The owner of the SaaS
# (role='admin' in users table) always gets the most aggressive cadence
# regardless of their plan. Solo testers shouldn't be slowed by their own
# starter plan.
ADMIN_SCRAPE_CADENCE_HOURS = 1


def get_scrape_cadence_hours(plan_name, is_admin=False):
    """Return the scrape cadence (in hours) for a given plan.

    Admin role overrides plan and always returns the most aggressive cadence.
    Unknown plans fall back to starter (6h) — safest assumption: don't burn
    compute on accounts with no clear billing relationship.
    """
    if is_admin:
        return ADMIN_SCRAPE_CADENCE_HOURS
    plan = PLANS.get(plan_name) or PLANS['starter']
    return plan.get('scrape_cadence_hours', 6)


def get_plan(plan_name):
    return PLANS.get(plan_name, PLANS['starter'])


def create_checkout_session(user_email, price_id, success_url, cancel_url, customer_id=None):
    params = {
        'payment_method_types': ['card'],
        'line_items': [{'price': price_id, 'quantity': 1}],
        'mode': 'subscription',
        'success_url': success_url + '?session_id={CHECKOUT_SESSION_ID}',
        'cancel_url': cancel_url,
        'customer_email': user_email if not customer_id else None,
        'customer': customer_id if customer_id else None,
        'allow_promotion_codes': True,
        'billing_address_collection': 'auto',
    }
    # Remove None values
    params = {k: v for k, v in params.items() if v is not None}
    session = stripe.checkout.Session.create(**params)
    return session


def create_portal_session(customer_id, return_url):
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session


def get_subscription(subscription_id):
    return stripe.Subscription.retrieve(subscription_id)


def get_price_plan(price_id):
    for plan_name, plan in PLANS.items():
        if plan.get('price_id') == price_id or plan.get('price_id_annual') == price_id:
            return plan_name
    return 'starter'
