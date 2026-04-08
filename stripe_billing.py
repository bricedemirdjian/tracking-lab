import os
import stripe

stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

PLANS = {
    'starter': {
        'name': 'Starter',
        'price': 0,
        'max_accounts': 5,
        'max_projects': 1,
        'max_shared_users': 0,
        'platforms': ['tiktok', 'youtube'],
        'instagram': False,
        'export_csv': False,
    },
    'pro': {
        'name': 'Pro',
        'price': 29,
        'price_id': os.environ.get('STRIPE_PRO_PRICE_ID'),
        'max_accounts': 20,
        'max_projects': 5,
        'max_shared_users': 2,
        'platforms': ['tiktok', 'youtube', 'instagram'],
        'instagram': True,
        'export_csv': True,
    },
    'agency': {
        'name': 'Agency',
        'price': 99,
        'price_id': os.environ.get('STRIPE_AGENCY_PRICE_ID'),
        'max_accounts': 9999,
        'max_projects': 9999,
        'max_shared_users': 9999,
        'platforms': ['tiktok', 'youtube', 'instagram'],
        'instagram': True,
        'export_csv': True,
    },
}


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
        if plan.get('price_id') == price_id:
            return plan_name
    return 'starter'
