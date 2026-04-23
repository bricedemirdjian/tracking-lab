"""
emailer.py — transactional emails via Resend.

Fails silently (prints a warning) when RESEND_API_KEY is not set, so local dev
and the webhook path never break because of email delivery.

Env vars:
  RESEND_API_KEY    (required in prod — without it, emails are no-op)
  RESEND_FROM_EMAIL (default: "onboarding@resend.dev" — Resend sandbox domain)
  RESEND_FROM_NAME  (default: "Tracking Lab")
  APP_BASE_URL      (default: "https://tracking-lab.io") — used in email links
"""
from __future__ import annotations

import os
from typing import Optional


_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
_FROM_NAME = os.environ.get("RESEND_FROM_NAME", "Tracking Lab")
_APP_URL = os.environ.get("APP_BASE_URL", "https://tracking-lab.io").rstrip("/")


def _send(to_email: str, subject: str, html: str, reply_to: Optional[str] = None) -> bool:
    """Low-level sender. Returns True on success, False otherwise."""
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        print(f"[emailer] RESEND_API_KEY not set — skipping email to {to_email}")
        return False
    try:
        import resend  # lazy import so missing package doesn't kill the app
    except ImportError:
        print("[emailer] 'resend' package not installed — run: pip install resend")
        return False

    resend.api_key = api_key
    params = {
        "from": f"{_FROM_NAME} <{_FROM_EMAIL}>",
        "to": [to_email],
        "subject": subject,
        "html": html,
    }
    if reply_to:
        params["reply_to"] = reply_to
    try:
        resend.Emails.send(params)
        print(f"[emailer] sent '{subject}' to {to_email}")
        return True
    except Exception as e:
        print(f"[emailer] send failed to {to_email}: {e}")
        return False


# ── Shared shell ────────────────────────────────────────────────────────
def _shell(title: str, preheader: str, body_html: str) -> str:
    """Wrap a body fragment in a minimal, responsive email shell."""
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#f6f7f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;color:#0b0b0f;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f7f9;padding:32px 16px;">
  <tr><td align="center">
    <table role="presentation" width="560" cellpadding="0" cellspacing="0"
           style="max-width:560px;background:#fff;border-radius:16px;
                  box-shadow:0 1px 2px rgba(15,15,15,0.06);overflow:hidden;">
      <tr><td style="padding:36px 40px 12px 40px;">
        <div style="font-size:18px;font-weight:700;letter-spacing:-0.01em;">Tracking Lab</div>
      </td></tr>
      <tr><td style="padding:8px 40px 40px 40px;font-size:15px;line-height:1.55;color:#0b0b0f;">
        {body_html}
      </td></tr>
      <tr><td style="padding:20px 40px 28px 40px;border-top:1px solid #eee;
                     font-size:12px;line-height:1.5;color:#7a7a86;">
        Tracking Lab · Analytics pour créateurs et agences<br>
        <a href="{_APP_URL}" style="color:#7a7a86;text-decoration:underline;">{_APP_URL}</a>
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


# ── Public senders ──────────────────────────────────────────────────────
def send_welcome_email(to_email: str, user_name: str) -> bool:
    """Sent on first login (new account)."""
    subject = "Bienvenue sur Tracking Lab"
    first = (user_name or to_email.split("@")[0]).split()[0]
    body = f"""
    <h1 style="font-size:22px;font-weight:700;margin:0 0 16px 0;letter-spacing:-0.01em;">
      Salut {first} 👋
    </h1>
    <p style="margin:0 0 16px 0;">
      Content de t'accueillir sur Tracking Lab. Tu peux dès maintenant ajouter
      tes premiers comptes à suivre (TikTok, Instagram, YouTube, LinkedIn).
    </p>
    <p style="margin:0 0 24px 0;">
      Les statistiques se mettent à jour automatiquement chaque jour — tu ne
      touches plus à rien.
    </p>
    <a href="{_APP_URL}/dashboard"
       style="display:inline-block;background:#0b0b0f;color:#fff;text-decoration:none;
              padding:12px 20px;border-radius:10px;font-weight:600;font-size:14px;">
      Aller au tableau de bord →
    </a>
    <p style="margin:32px 0 0 0;color:#5a5a66;font-size:13px;">
      Une question ? Réponds simplement à cet email, on lit tout.
    </p>
    """
    return _send(
        to_email=to_email,
        subject=subject,
        html=_shell(subject, "Ton compte est prêt — ajoute ton premier compte à suivre.", body),
    )


def send_payment_confirmation(
    to_email: str, user_name: str, plan_name: str, period_end_iso: Optional[str] = None
) -> bool:
    """Sent after checkout.session.completed."""
    plan_label = {
        "pro": "Pro (29€/mois)",
        "agency": "Entreprises (79€/mois)",
    }.get(plan_name, plan_name.title())

    first = (user_name or to_email.split("@")[0]).split()[0]
    renew_line = ""
    if period_end_iso:
        date_part = period_end_iso[:10]  # YYYY-MM-DD
        renew_line = (
            f'<p style="margin:0 0 16px 0;color:#5a5a66;">'
            f'Prochain renouvellement : <strong>{date_part}</strong>.</p>'
        )

    subject = f"Ton abonnement {plan_label} est actif"
    body = f"""
    <h1 style="font-size:22px;font-weight:700;margin:0 0 16px 0;letter-spacing:-0.01em;">
      Merci {first} 🚀
    </h1>
    <p style="margin:0 0 16px 0;">
      Ton abonnement <strong>{plan_label}</strong> est activé. Toutes les
      fonctionnalités du plan sont disponibles dès maintenant.
    </p>
    {renew_line}
    <a href="{_APP_URL}/dashboard"
       style="display:inline-block;background:#0b0b0f;color:#fff;text-decoration:none;
              padding:12px 20px;border-radius:10px;font-weight:600;font-size:14px;">
      Ouvrir le dashboard →
    </a>
    <p style="margin:32px 0 0 0;color:#5a5a66;font-size:13px;">
      Tu peux gérer ton abonnement et tes factures à tout moment depuis la
      section <em>Facturation</em> du dashboard.
    </p>
    """
    return _send(
        to_email=to_email,
        subject=subject,
        html=_shell(subject, f"Ton plan {plan_label} est actif.", body),
    )
