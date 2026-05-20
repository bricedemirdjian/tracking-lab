# Stripe setup runbook — Tracking Lab

**Status:** À configurer. Pricing simplifié au commit `17787a5` (2026-05-20) : un seul produit "Tracking Lab", deux prix (mensuel + annuel), zéro essai gratuit, plus de tiers gated.

**Goal:** Activer le paiement réel sur `trackinglab.online` pour les 2 cadences :

| Formule | Prix affiché | Stripe `unit_amount` | Stripe `recurring.interval` |
|---|---|---|---|
| Mensuel | 29 € TTC/mois | 2900 (centimes) | `month` |
| Annuel | 79 € TTC/an (≈ 6,58 €/mois) | 7900 | `year` |

Les deux formules **débloquent les mêmes fonctionnalités** — aucun gating entre mensuel et annuel.

---

## Architecture résumée

```
Anonymous visitor                    Authenticated subscriber
       │                                       │
       ▼                                       ▼
 / ou /tarifs                            /billing
   2 Payment Link URLs                     │
   (data-stripe-monthly/annual)            │ click "Commencer en mensuel"
       │                                   │              ou "...annuel"
       ▼                                   ▼
 Stripe Payment Link               /api/billing/checkout
 → Stripe Checkout (new sub)             │
                                         ├─ has subscription_id? ─yes─▶ Stripe Portal
                                         │                              (subscription_update_confirm)
                                         │                              → bascule mensuel ↔ annuel
                                         │                              → prorata auto
                                         │
                                         └─ no sub? ─▶ Stripe Checkout (new sub)
```

Deux flows distincts, deux jeux d'env vars différents (cf. section 5).

---

## 1. Produit & Prix Stripe Dashboard

Dashboard → **Catalog → Products** → créer **un seul produit** "Tracking Lab" (ou "Tracking Lab Pro").

Ajouter **2 prices** à ce produit :

| Cadence | `unit_amount` (centimes) | `recurring.interval` | Devise | Tax behavior |
|---|---|---|---|---|
| Mensuel | `2900` | `month` | EUR | `inclusive` (TTC) |
| Annuel | `7900` | `year` | EUR | `inclusive` (TTC) |

Pour chaque price créé, copier le `price_xxx` ID. Tu en auras besoin section 5.

Le `tax_behavior: inclusive` indique à Stripe que le prix affiché inclut déjà la TVA. C'est important — les prix landing sont **TTC**, donc on dit à Stripe la même chose pour qu'il ne rajoute pas 20% au moment du paiement.

---

## 2. Customer Portal (essentiel pour switcher mensuel ↔ annuel)

Dashboard → **Settings → Billing → Customer Portal** → Activer.

Sans cette config, `/api/billing/checkout` retombera silencieusement sur un nouveau Checkout (le user créera une 2e subscription parallèle au lieu de basculer entre mensuel et annuel).

**Sections à activer :**

- **Customer information** : laisser cocher "Customers can update email/billing address".
- **Invoice history** : activer.
- **Payment methods** : activer.
- **Subscriptions** :
  - ✅ **Customers can switch plans** ← obligatoire
  - **Proration behavior** : `Always invoice`
  - **Products** : ajouter **les 2 prices** créés section 1. Sans ça le `flow_data.subscription_update_confirm` retournera 400.
  - **Cancellation** : optionnel — activer "Customers can cancel" pour réduire le support load.
- **Business information** : raison sociale, email support (`brice.demirdjian@gmail.com`), URL ToS (`https://trackinglab.online/cgv`), URL Privacy.

Sauvegarder. La conf vit en mode Test ET en mode Live séparément — refaire les deux quand tu passes en prod.

---

## 3. Webhook Stripe → Flask

Dashboard → **Developers → Webhooks → Add endpoint**.

| Champ | Valeur |
|---|---|
| URL | `https://trackinglab.online/webhook/stripe` |
| Events | `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_succeeded`, `invoice.payment_failed` |

Après création, cliquer **"Reveal signing secret"** → copier le `whsec_xxx` → c'est `STRIPE_WEBHOOK_SECRET`.

Sans ce secret côté serveur, `app.py` REFUSE tous les webhooks (lignes 583-586) — pas de fallback, l'event est jeté.

---

## 4. Payment Links pour la landing (anonymes)

Dashboard → **Payment Links → New** → créer **2 Payment Links** :

1. **Mensuel** : sélectionner le price Mensuel (2900 centimes / month)
2. **Annuel** : sélectionner le price Annuel (7900 centimes / year)

Pour chaque :
- **After payment** : "Show confirmation page" suffit, ou redirect vers `https://trackinglab.online/login`
- **Tax collection** : si tu collectes la TVA via Stripe Tax, activer **automatic tax**. Sinon laisser off (le prix est déjà TTC).
- **Save and copy link** → URL `https://buy.stripe.com/xxx_xxx`

Ces 2 URLs servent côté Next.js landing (`tracking-lab-v2` Vercel project).

---

## 5. Env vars Vercel — TWO projects

### A) `tracking-lab` (Flask) — `/api/billing/checkout`, `/webhook/stripe`

Vercel Dashboard → projet `tracking-lab` → Settings → Environment Variables → **Production** :

```
STRIPE_SECRET_KEY=sk_live_...                # Dashboard → Developers → API keys (mode Live)
STRIPE_WEBHOOK_SECRET=whsec_...              # Section 3
STRIPE_MONTHLY_PRICE_ID=price_...            # Section 1, mensuel
STRIPE_ANNUAL_PRICE_ID=price_...             # Section 1, annuel
```

**Note :** les anciennes vars (`STRIPE_STARTER_PRICE_ID`, `STRIPE_PRO_PRICE_ID`, `STRIPE_AGENCY_PRICE_ID`, `*_ANNUAL_PRICE_ID`) sont obsolètes — `stripe_billing.PLANS` ne les lit plus. Tu peux les supprimer du Dashboard Vercel pour ne pas confusionner.

### B) `tracking-lab-v2` (Next.js landing) — `page.tsx` (substitution des `{{STRIPE_X}}` tokens)

Vercel Dashboard → projet `tracking-lab-v2` → Settings → Environment Variables → **Production** :

```
STRIPE_MONTHLY_URL=https://buy.stripe.com/...    # Payment Link mensuel
STRIPE_ANNUAL_URL=https://buy.stripe.com/...     # Payment Link annuel
```

**Note :** les anciennes vars `STRIPE_STARTER_MONTHLY_URL`, `STRIPE_PRO_MONTHLY_URL`, `STRIPE_PRO_ANNUAL_URL`, `STRIPE_ENTERPRISE_MONTHLY_URL`, `STRIPE_ENTERPRISE_ANNUAL_URL`, `STRIPE_STARTER_ANNUAL_URL` sont obsolètes — `page.tsx` ne les lit plus. Tu peux les supprimer.

Après chaque ajout : **Redeploy** depuis l'onglet Deployments du projet (les env vars ne sont injectées qu'aux nouveaux deploys).

---

## 6. Vérification end-to-end (Test mode d'abord)

**Toujours faire le run complet en Test mode avant de switcher en Live.**

### Test mode setup
1. Dashboard → toggle "Test mode" (haut à droite) → ON.
2. Refaire sections 1, 2, 3, 4 en mode Test (les configs sont séparées).
3. Sur Vercel, créer un environnement **Preview** ou utiliser temporairement les `sk_test_...` / `whsec_test_...` / `price_test_...` sur Production.
4. Sur les Payment Links de test, utiliser la carte `4242 4242 4242 4242` / expiry future / CVC quelconque.

### Test cases

| # | Scénario | URL de départ | Action | Attendu |
|---|---|---|---|---|
| 1 | Signup en mensuel | `/tarifs` (anonyme) | Click "Commencer en mensuel" | Redirect Payment Link mensuel → checkout → sub Mensuel créée |
| 2 | Signup en annuel | `/tarifs` (anonyme) | Click "Commencer en annuel" | Redirect Payment Link annuel → checkout → sub Annuel créée |
| 3 | Webhook reçu | (idem) | (auto après checkout) | DB `subscriptions.plan = 'pro'` (mensuel) ou `'agency'` (annuel), `stripe_customer_id` + `stripe_subscription_id` peuplés |
| 4 | Bascule Mensuel → Annuel | `/billing` (logged-in Mensuel) | Click "Commencer en annuel" | Redirect Portal `subscription_update_confirm` → confirm → retour `/billing?success=1` → DB plan = 'agency' |
| 5 | Bascule Annuel → Mensuel | `/billing` (logged-in Annuel) | Click "Commencer en mensuel" | Idem Portal flow, plan = 'pro' |
| 6 | Subscription cancelled in Stripe | `/billing` (sub canceled manuellement) | Click "Commencer en annuel" | Portal retourne `InvalidRequestError` → fallback Checkout → nouvelle sub |
| 7 | Annulation depuis Portal | `/billing` | Click "Gérer la facturation" → Cancel | Webhook `customer.subscription.deleted` → DB plan retombe à 'starter' (legacy fallback) |

Si **6** échoue : le Customer Portal n'accepte pas `flow_data.subscription_update_confirm` sans la conf "Customers can switch plans" + prices ajoutés. Re-check section 2.

### Switch en Live mode

Une fois les 7 cas verts en Test :
1. Refaire **toutes** les sections 1-4 en mode **Live** (Dashboard toggle OFF "Test mode").
2. Update les env vars Vercel : `sk_live_...`, `whsec_live...`, `price_live_...`, et les 2 nouvelles `STRIPE_*_URL`.
3. Redeploy les 2 projets.
4. Refaire les cases 1, 2, 4 avec une vraie CB (montant minimum, refund après).

---

## 7. Comportement actuel sans config

État au commit `17787a5` (déployé) :

- `/api/billing/checkout` → essaie le Stripe Portal flow, échoue avec `InvalidRequestError` ("No such price"), bascule sur `create_checkout_session`, qui à son tour échoue avec "Prix non configuré" si les env vars price_id ne sont pas set → renvoie 500 + message d'erreur au frontend.
- `/tarifs` et `/` Payment Links → fallback sur `https://app.trackinglab.online/login` (cf. `LandingScripts.tsx` `syncStripeHrefs`) — le user atterrit sur le login Flask au lieu d'un checkout.
- `/webhook/stripe` → refuse tout payload puisque `STRIPE_WEBHOOK_SECRET` est missing.

Donc rien ne crash, mais aucun paiement n'est possible tant que les sections 1-5 ne sont pas faites.

---

## 8. Pitfalls connus

- **Mode Test vs Live** : facile de mélanger. Les `price_xxx` ne sont PAS interchangeables. Si tu as `STRIPE_SECRET_KEY=sk_live_...` mais `STRIPE_MONTHLY_PRICE_ID=price_test_...`, Stripe renverra `No such price` au checkout.
- **Customer Portal config oubliée** : cause #1 de fallback silencieux vers Checkout. Test case #4 le détecte.
- **TTC vs HT** : les prix annoncés sur la landing (29 € et 79 €) sont **TTC**. Le Stripe price doit avoir `tax_behavior: inclusive` sinon Stripe rajoute 20% au paiement et l'utilisateur paie ~36 €/mois au lieu de 29.
- **Webhook secret mode-specific** : Test mode et Live mode ont des `whsec_xxx` différents. Faire 2 webhooks séparés sur le Dashboard.
- **Vercel env vars ne propagent pas automatiquement** : il faut un **Redeploy** après chaque modif.
- **`stripe.Subscription.retrieve` peut renvoyer une sub annulée** : si l'utilisateur a annulé son abonnement mais que la sub est en mode `canceled` dans Stripe (pas supprimée), le portal flow retourne "Can't modify a canceled subscription". Le fallback Checkout gère ça.
- **Anciennes env vars (3 tiers)** : si tu en avais déjà set (`STRIPE_PRO_PRICE_ID`, etc.), elles sont maintenant ignorées par le code. Supprime-les du Dashboard Vercel pour éviter la confusion future.
