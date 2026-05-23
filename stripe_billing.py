import os
import stripe

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# Single offer, two billing cadences (full feature parity):
#   - 'monthly' = 29€ TTC/mois, sans engagement
#   - 'annual'  = 79€ TTC/an  (soit ~6,58€/mois, économie 77%)
# users.plan column values:
#   - 'pending'  → signup terminé mais paiement Stripe pas encore confirmé
#   - 'monthly'  → abonnement mensuel actif
#   - 'annual'   → abonnement annuel actif
# Legacy keys ('starter', 'pro', 'agency') are aliased below for back-compat
# with any pre-existing row, then migrated to the new names.
_FULL_FEATURES = {
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
}

PLANS = {
    'pending': {
        'name': 'Sans abonnement',
        'price': 0,
        'price_annual': 0,
        'price_id': None,
        'price_id_annual': None,
        # Pending users hit the paywall on /dashboard — keep limits at 0 so
        # any rogue feature access without a gate also fails closed.
        'max_accounts': 0,
        'max_videos': 0,
        'max_projects': 0,
        'max_shared_users': 0,
        'platforms': [],
        'instagram': False,
        'linkedin': False,
        'export_csv': False,
        'import_csv': False,
        'competitor_access': False,
        'analytics_full': False,
        'ai_video_analysis': False,
        'scrape_cadence_hours': 24,
    },
    'monthly': {
        'name': 'Mensuel',
        'price': 29,
        'price_annual': 29,
        'price_id': os.environ.get('STRIPE_MONTHLY_PRICE_ID'),
        'price_id_annual': os.environ.get('STRIPE_MONTHLY_PRICE_ID'),
        **_FULL_FEATURES,
    },
    'annual': {
        'name': 'Annuel',
        'price': 79,
        'price_annual': 79,
        'price_id': os.environ.get('STRIPE_ANNUAL_PRICE_ID'),
        'price_id_annual': os.environ.get('STRIPE_ANNUAL_PRICE_ID'),
        **_FULL_FEATURES,
    },
}

# Back-compat aliases for any legacy row still tagged with old names.
# These point to the SAME config dict so feature-flag reads return correct
# values during the transition. Stripe webhook normalises new subs to the
# canonical 'monthly' / 'annual' keys.
PLANS['pro']     = PLANS['monthly']
PLANS['agency']  = PLANS['annual']
PLANS['starter'] = PLANS['monthly']


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
    plan = PLANS.get(plan_name) or PLANS['monthly']
    return plan.get('scrape_cadence_hours', 6)


def get_plan(plan_name):
    return PLANS.get(plan_name, PLANS['monthly'])


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
    # Only consider canonical keys when reverse-looking-up by price_id —
    # the legacy aliases ('pro', 'agency', 'starter') all point to the same
    # config dict, so iterating PLANS.items() would return whichever key
    # came first. Pin to canonical names so new subs always normalise to
    # 'monthly' or 'annual'.
    for plan_name in ('monthly', 'annual'):
        plan = PLANS[plan_name]
        if plan.get('price_id') == price_id or plan.get('price_id_annual') == price_id:
            return plan_name
    return 'pending'
