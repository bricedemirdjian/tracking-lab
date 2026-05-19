# Stripe setup runbook — Tracking Lab

**Status:** À configurer (commits `7b3a48b` → `8a434de` ont posé le code, il reste la conf Stripe Dashboard + les env vars Vercel).

**Goal:** Activer le paiement réel des 3 plans (Starter 19€ / 15€, Pro 29€ / 23€, Entreprises 79€ / 63€) sur `trackinglab.online`, avec upsell fluide via le Stripe Customer Portal pour les utilisateurs déjà abonnés.

---

## Architecture résumée

```
Anonymous visitor                    Authenticated subscriber
       │                                       │
       ▼                                       ▼
 /tarifs ou /                            /billing
   Payment Link URLs                       │
   (data-stripe-monthly/annual)            │ click "Passer au Pro"
       │                                   │
       ▼                                   ▼
 Stripe Payment Link               /api/billing/checkout
 → Stripe Checkout (new sub)             │
                                         ├─ has subscription_id? ─yes─▶ Stripe Portal
                                         │                              (subscription_update_confirm)
                                         │                              → modifie la sub existante
                                         │                              → prorata auto
                                         │
                                         └─ no sub? ─▶ Stripe Checkout (new sub)
```

Deux flows distincts, deux jeux d'env vars différents.

---

## 1. Produits & Prix Stripe Dashboard

Dashboard → **Catalog → Products**. Créer 3 produits, chacun avec 2 prices (mensuel et annuel).

**Convention** : le prix annuel affiché est **par mois** (15€/mo, facturé 180€/an). Donc côté Stripe : `recurring.interval = year`, `unit_amount = 12 × (prix annuel affiché)`.

| Produit | Cadence | Stripe interval | Unit amount (centimes) | Env var (Flask) | Env var (Payment Link URL) |
|---|---|---|---|---|---|
| Starter | Mensuel | month | 1900 (19€) | `STRIPE_STARTER_PRICE_ID` | `STRIPE_STARTER_MONTHLY_URL` |
| Starter | Annuel | year | 18000 (180€ = 15€×12) | `STRIPE_STARTER_ANNUAL_PRICE_ID` | `STRIPE_STARTER_ANNUAL_URL` |
| Pro | Mensuel | month | 2900 (29€) | `STRIPE_PRO_PRICE_ID` | `STRIPE_PRO_MONTHLY_URL` |
| Pro | Annuel | year | 27600 (276€ = 23€×12) | `STRIPE_PRO_ANNUAL_PRICE_ID` | `STRIPE_PRO_ANNUAL_URL` |
| Entreprises | Mensuel | month | 7900 (79€) | `STRIPE_AGENCY_PRICE_ID` | `STRIPE_ENTERPRISE_MONTHLY_URL` |
| Entreprises | Annuel | year | 75600 (756€ = 63€×12) | `STRIPE_AGENCY_ANNUAL_PRICE_ID` | `STRIPE_ENTERPRISE_ANNUAL_URL` |

Pour chaque price, copier le `price_xxx` ID et l'URL du Payment Link (si tu en crées un — voir section 4).

---

## 2. Customer Portal (essentiel pour les upsells)

Dashboard → **Settings → Billing → Customer Portal** → Activer.

Sans cette config, le flow `/api/billing/checkout` retombera silencieusement sur un nouveau Checkout (le user créera une 2e subscription parallèle au lieu de modifier l'existante).

**Sections à activer :**

- **Customer information** : laisser cocher "Customers can update email/billing address" (les utilisateurs en B2B en ont besoin pour les factures).
- **Invoice history** : activer (montre les factures passées).
- **Payment methods** : activer (changer de CB).
- **Subscriptions** :
  - ✅ **Customers can switch plans** ← obligatoire
  - **Proration behavior** : `Always invoice` (Stripe facture le prorata immédiatement à l'upgrade ; meilleur UX que `Create prorations`)
  - **Products** : ajouter **les 6 prices** créés en section 1. Sans ça le `flow_data.subscription_update_confirm` retournera 400.
  - **Cancellation** : optionnel — activer "Customers can cancel" pour réduire le support load.
- **Business information** : raison sociale, email support (`brice.demirdjian@gmail.com`), URL ToS, URL Privacy.

Sauvegarder. La conf vit en mode Test ET en mode Live séparément — refaire les deux quand tu passes en prod.

---

## 3. Webhook Stripe → Flask

Dashboard → **Developers → Webhooks → Add endpoint**.

| Champ | Valeur |
|---|---|
| URL | `https://trackinglab.online/webhook/stripe` |
| Events à écouter | `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.payment_succeeded`, `invoice.payment_failed` |

Après création, cliquer **"Reveal signing secret"** → copier le `whsec_xxx` → c'est `STRIPE_WEBHOOK_SECRET`.

Sans ce secret côté serveur, `app.py` REFUSE tous les webhooks (cf. lignes 583-586) — pas de fallback "trust but verify", l'event est jeté.

---

## 4. Payment Links pour la landing (anonymes)

Dashboard → **Payment Links → New**.

Créer **6 Payment Links** (un par price ID de la section 1). Pour chaque :

- **Product** : choisir le price correspondant.
- **After payment** : "Show confirmation page" suffit, ou redirect vers `https://trackinglab.online/login` pour qu'ils créent leur compte après paiement.
- **Tax collection** : Activer **automatic tax** (Stripe Tax) si tu collectes la TVA, sinon laisser off.
- **Save and copy link**.

Les 6 URLs (qui ressemblent à `https://buy.stripe.com/xxx_xxx`) servent côté **Next.js landing** (`tracking-lab-v2` Vercel project) dans les data-attributs des CTAs Pro/Entreprises/Starter. Pas utilisés côté Flask.

---

## 5. Env vars Vercel — TWO projects

### A) `tracking-lab` (Flask) — utilisé par `/api/billing/checkout`, `/webhook/stripe`, `stripe_billing.py`

Vercel Dashboard → projet `tracking-lab` → Settings → Environment Variables. Ajouter pour **Production** :

```
STRIPE_SECRET_KEY=sk_live_...                # Dashboard → Developers → API keys (mode Live)
STRIPE_WEBHOOK_SECRET=whsec_...              # Section 3
STRIPE_STARTER_PRICE_ID=price_...
STRIPE_STARTER_ANNUAL_PRICE_ID=price_...
STRIPE_PRO_PRICE_ID=price_...
STRIPE_PRO_ANNUAL_PRICE_ID=price_...
STRIPE_AGENCY_PRICE_ID=price_...
STRIPE_AGENCY_ANNUAL_PRICE_ID=price_...
```

### B) `tracking-lab-v2` (Next.js landing) — utilisé par `page.tsx` (substitution des `{{STRIPE_X}}` tokens)

Vercel Dashboard → projet `tracking-lab-v2` → Settings → Environment Variables. Ajouter pour **Production** :

```
STRIPE_STARTER_MONTHLY_URL=https://buy.stripe.com/...
STRIPE_STARTER_ANNUAL_URL=https://buy.stripe.com/...
STRIPE_PRO_MONTHLY_URL=https://buy.stripe.com/...
STRIPE_PRO_ANNUAL_URL=https://buy.stripe.com/...
STRIPE_ENTERPRISE_MONTHLY_URL=https://buy.stripe.com/...
STRIPE_ENTERPRISE_ANNUAL_URL=https://buy.stripe.com/...
```

Après chaque ajout : **Redeploy** depuis l'onglet Deployments du projet (les env vars ne sont injectées qu'aux nouveaux deploys).

---

## 6. Vérification end-to-end (Test mode d'abord)

**Toujours faire le run complet en Test mode avant de switcher en Live.**

### Test mode setup
1. Dashboard → toggle "Test mode" (haut à droite) → ON.
2. Refaire sections 1, 2, 3, 4 en mode Test (les configs sont séparées).
3. Sur Vercel, créer un environnement **Preview** ou un projet de test avec les `sk_test_...` / `whsec_test_...` / `price_test_...`.
4. Sur les Payment Links de test, utiliser la carte `4242 4242 4242 4242` / expiry future / CVC quelconque.

### Test cases (à passer un par un)

| # | Scénario | URL de départ | Action | Attendu |
|---|---|---|---|---|
| 1 | Nouveau signup Pro | `/tarifs` (anonyme) | Click "Essai gratuit" sur Pro card | Redirect Stripe Payment Link → checkout → succès → sub Pro créée |
| 2 | Webhook reçu | (idem) | (auto après checkout) | DB `subscriptions.plan = 'pro'`, `stripe_customer_id` + `stripe_subscription_id` peuplés |
| 3 | Upsell Pro → Entreprises | `/billing` (logged-in Pro) | Click "Passer à Entreprises" | Redirect Stripe Portal `subscription_update_confirm` → confirmer → retour `/billing?success=1` → DB plan = 'agency' |
| 4 | Downgrade Pro → Starter | `/billing` (logged-in Pro) | Click "Passer au Starter" | Idem Portal flow, plan = 'starter' |
| 5 | Toggle Mensuel/Annuel | `/billing` | Toggle, click "Passer au Pro" | `/api/billing/checkout` reçoit `period: 'monthly'`, utilise `STRIPE_PRO_PRICE_ID` |
| 6 | Subscription cancelled in Stripe | `/billing` (sub canceled manuellement dans Dashboard) | Click "Passer au Pro" | Portal retourne `InvalidRequestError` → fallback Checkout → nouvelle sub créée |
| 7 | Annulation depuis Portal | `/billing` | Click "Gérer la facturation" → Cancel | Webhook `customer.subscription.deleted` reçu → DB plan retombe à 'starter' |

Si **6** échoue : le Customer Portal n'accepte pas `flow_data.subscription_update_confirm` sans la conf "Customers can switch plans" + prices ajoutés. Re-check section 2.

### Switch en Live mode

Une fois les 7 cas verts en Test :
1. Refaire **toutes** les sections 1-4 en mode **Live** (Dashboard toggle OFF "Test mode").
2. Update les env vars Vercel : `sk_live_...`, `whsec_live...`, `price_live_...`.
3. Redeploy les 2 projets.
4. Refaire les cases 1 et 3 avec **une vraie CB** (montant test minimum, refund après).

---

## 7. Comportement actuel sans config

État au commit `8a434de` (déployé) :

- `/api/billing/checkout` → essaie le Stripe Portal flow, échoue avec `InvalidRequestError` ("No such price"), bascule sur `create_checkout_session`, qui à son tour échoue avec "Prix non configuré" si l'env var price_id n'est pas set → renvoie 500 + message d'erreur au frontend.
- `/tarifs` et `/` Payment Links → fallback sur `https://app.trackinglab.online/login` (cf. `LandingScripts.tsx` `syncStripeHrefs`) — le user atterrit sur le login Flask au lieu d'un checkout.
- `/webhook/stripe` → refuse tout payload puisque `STRIPE_WEBHOOK_SECRET` est missing.

Donc rien ne crash, mais aucun paiement n'est possible tant que les sections 1-5 ne sont pas faites.

---

## 8. Pitfalls connus

- **Mode Test vs Live** : facile de mélanger. Les `price_xxx` ne sont PAS interchangeables. Si tu as une `STRIPE_SECRET_KEY` en `sk_live_...` mais des `STRIPE_PRO_PRICE_ID` en `price_test_...`, Stripe renverra `No such price` au checkout.
- **Customer Portal config oubliée** : c'est la cause #1 de fallback silencieux vers Checkout. Test case #3 le détecte.
- **Annual price `unit_amount`** : c'est le total annuel en centimes, pas le mensuel. 23€/mo annual = 27600 centimes, pas 2300.
- **Webhook secret mode-specific** : Test mode et Live mode ont des `whsec_xxx` différents. Faire 2 webhooks séparés sur le Dashboard.
- **Vercel env vars ne propagent pas automatiquement** : il faut un **Redeploy** après chaque modif. Les anciens deploys gardent les anciennes valeurs.
- **`stripe.Subscription.retrieve` peut renvoyer une sub annulée** : si l'utilisateur a annulé son abonnement mais que la sub est encore en mode `canceled` dans Stripe (pas supprimée), le portal flow retournera l'erreur "Can't modify a canceled subscription". Le fallback Checkout gère ça.
