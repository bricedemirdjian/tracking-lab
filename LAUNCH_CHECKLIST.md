# Tracking Lab — Pre-Launch Checklist

Tu as ~2h de setup manuel à faire avant la campagne d'acquisition. Tout est à 0€. Ordre exact ci-dessous.

---

## A. Setup deliverability email — 30 min

### A1. Ajouter trackinglab.online dans Resend
1. Va sur https://resend.com/domains
2. Click **Add Domain** → `trackinglab.online`
3. Resend te montre 3-4 DNS records (SPF, DKIM, MX optionnels, DMARC)
4. Note-les, tu les ajoutes au step suivant.

### A2. Ajouter les DNS records chez ton registrar
Où est hébergé trackinglab.online ? Probablement OVH, Namecheap, Cloudflare, ou Vercel DNS.

**Si Cloudflare** : https://dash.cloudflare.com → domain → DNS → Add record
**Si Vercel DNS** : https://vercel.com/bricedemirdjian-1387s-projects/~/domains/trackinglab.online → DNS Records
**Si OVH** : https://www.ovh.com/manager → Web Cloud → Domaines → trackinglab.online → Zone DNS
**Si Namecheap** : https://ap.www.namecheap.com → Domain List → Manage → Advanced DNS

Ajoute les 3 records donnés par Resend (TXT pour SPF + DKIM + DMARC).

### A3. Vérifier sur Resend
Retour sur https://resend.com/domains → cliquer **Verify**. Ça peut prendre 2-5 min.

### A4. Update Vercel env var
https://vercel.com/bricedemirdjian-1387s-projects/tracking-lab/settings/environment-variables

Add/Update :
- `RESEND_FROM_EMAIL = hello@trackinglab.online`
- `RESEND_FROM_NAME = Tracking Lab`

Sans ça, les emails partent depuis `onboarding@resend.dev` → spam folder garanti.

---

## B. Setup email support — 15 min

Tu vas avoir des clients qui veulent te contacter. Crée `support@trackinglab.online` qui forward vers `brice.demirdjian@gmail.com`.

### Option 1 (recommandée) — Cloudflare Email Routing (gratuit illimité)
Si ton domaine est sur Cloudflare :
1. https://dash.cloudflare.com → trackinglab.online → Email → Email Routing
2. Enable Email Routing
3. Add routing rule : `support@trackinglab.online` → `brice.demirdjian@gmail.com`
4. Save

### Option 2 — Vercel/OVH/Namecheap intégré
Suivre la doc du registrar. Tous offrent du forward gratuit basique.

### Option 3 — ImprovMX (gratuit 25 aliases)
https://improvmx.com → Add Domain → ajouter les DNS MX records → créer alias `support@trackinglab.online` → `brice.demirdjian@gmail.com`

### Update le footer du site
Le footer landing affiche déjà `contact@` ou `support@`. Vérifie sur https://trackinglab.online/contact que l'email affiché est `support@trackinglab.online`. Si autre chose, dis-moi et je le change.

---

## C. Test du flow complet payment — 15 min

**Critique** : faire ça AVANT de lancer la campagne. Si le webhook plante, le 1er client paye mais reste bloqué sur 'pending'.

1. Ouvre navigateur privé : https://trackinglab.online/signup
2. Click **S'inscrire avec Google** → utilise un compte Google **différent** de brice.demirdjian@gmail.com et briique30@gmail.com
3. Tu dois atterrir sur `/billing` avec l'écran d'onboarding (BIENVENUE / Une dernière étape)
4. Click **Annuel 79€**
5. Le Stripe Checkout doit s'ouvrir
6. **Utilise ta vraie CB** (paye 79€ réels — tu te rembourseras après comme hier)
7. Après paiement → tu dois être redirigé sur `/dashboard`
8. Vérifie : tu vois bien le dashboard avec l'interface complète
9. Vérifie en DB que `users.plan = 'annual'` pour ce nouvel user
10. Rembourse-toi via Stripe Dashboard comme hier

Si TOUT ça marche → flow validé pour la campagne. Si quelque chose foire, copie l'erreur exacte et envoie-la moi.

---

## D. Setup analytics campagne — 20 min (optionnel mais critique)

Pour mesurer le ROI de ta campagne d'acquisition. Tout à 0€ :

### D1. Plausible Analytics (gratuit auto-hébergé) ou Vercel Analytics (gratuit 10k events/mois Hobby)
Plus simple : Vercel Web Analytics
- https://vercel.com/bricedemirdjian-1387s-projects/tracking-lab-v2/analytics → click **Enable Analytics**
- C'est inclus gratos dans le Hobby plan jusqu'à 10k events/mois.

### D2. UTM tracking en place
Tes liens campagne doivent inclure `?utm_source=X&utm_medium=Y&utm_campaign=Z`. Exemples :
- LinkedIn ad : `https://trackinglab.online?utm_source=linkedin&utm_medium=cpc&utm_campaign=launch-may-2026`
- Instagram story : `https://trackinglab.online?utm_source=instagram&utm_medium=story&utm_campaign=launch-may-2026`

### D3. Conversion tracking
Vercel Analytics te montre déjà /signup → /dashboard conversion. Si tu veux plus précis, ajoute Plausible Goals (gratuit 30 jours puis 9$/mois). Pas obligatoire pour le lancement.

---

## E. Final go/no-go checks — 10 min

Avant d'appuyer sur "publier la campagne", vérifie en navigation privée :

- ☐ `trackinglab.online` charge en <2s
- ☐ Bouton signup visible et fonctionnel
- ☐ Bouton "S'inscrire avec Google" fonctionnel
- ☐ `/cgv`, `/confidentialite`, `/mentions-legales` accessibles
- ☐ `/contact` affiche `support@trackinglab.online`
- ☐ Footer landing affiche le bon email
- ☐ Sur mobile : pas de débordement, scroll smooth, CTAs cliquables
- ☐ Test payment full flow (étape C) passé
- ☐ Email de bienvenue reçu dans la boîte (pas dans spams)

Si tout est ✓ → tu peux lancer.

---

## F. Post-launch monitoring (déjà setup, juste à observer)

Tu as déjà :
- ⏱️ Health monitor toutes les 15 min (auto-fix transient errors, alerte si stuck)
- ⏱️ Data accuracy check toutes les 6h (auto-reconcile drifts)
- ⏱️ Scrape toutes les 15 min 24/7 (après deploy de l'agent en cours)
- 📧 Alerts Resend → brice.demirdjian@gmail.com sur incidents critiques

À monitorer manuellement les premiers jours :
1. https://github.com/bricedemirdjian/tracking-lab/actions → tous les runs verts ?
2. https://vercel.com/bricedemirdjian-1387s-projects/tracking-lab/logs → erreurs 5xx ?
3. https://dashboard.stripe.com → nouveaux abonnements ?
4. https://supabase.com/dashboard/project/vpirlefqxnvmxbmndhmn → DB size + connections ?

---

## Risques restants connus (accepted)

- **Vercel Hobby = ToS non-commercial** : risque de suspension. Si Vercel détecte trafic commercial → migration urgente vers Pro 20€/mois ou autre host.
- **Resend free 100 emails/jour** : si signup explose >100/jour, welcome emails s'arrêtent silencieusement. Migration Brevo (300/jour) ou Resend Pro (50€/mois pour 50k) si besoin.
- **Pas de backup off-site** : Supabase Pro a daily backups intégrés (7 jours retention). Ça suffit pour le launch.

Tout le reste est sous contrôle automatique.
