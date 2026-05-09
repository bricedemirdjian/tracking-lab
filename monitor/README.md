# Tracking Lab — UI Monitor

Self-healing Playwright monitor for `app.trackinglab.online/dashboard`.
Runs hourly via GitHub Actions, extracts every KPI + the activity table,
validates against a strict schema, and learns which selectors are reliable
over time.

This is a **QA monitor**, not a data scraper — your real data is in the
Postgres DB and exposed at `/api/stats`. The point here is:

- **Catch UI regressions in production before users do** (KPI shows 0 when
  it shouldn't, columns shift, an entire card disappears, a deploy breaks
  rendering, JS bundle gets cached weird, etc.)
- **Verify auth + session pipeline works** end-to-end every hour.
- **Cross-check** UI-displayed numbers against the JSON API for drift.

## Layout

```
monitor/
├── src/
│   ├── scraper.js           Main entry — orchestrates one full run
│   ├── selectors.js         Field registry (primary + fallbacks + label)
│   ├── extractor.js         Self-healing extraction + partial re-scrape
│   ├── selector-recovery.js AI-like recovery: find by label proximity
│   ├── selector-scores.js   Persistent reliability scoring + learning
│   ├── dom-memory.js        Save/diff HTML snapshots for drift detection
│   ├── validation.js        Pure parsing + type/range/cross-field checks
│   ├── alerting.js          Webhook + console alerts
│   ├── logger.js            Structured JSONL logger
│   ├── save-auth.js         One-time interactive auth helper
│   └── validate.js          Standalone CI validation step
├── data/
│   ├── selector-stats.json  Persistent learning store (committed by CI)
│   ├── auth.json            Playwright storage state (gitignored)
│   ├── dom-snapshots/       Last 30 snapshots
│   ├── results/             One JSON per run
│   └── logs/                Daily JSONL logs
└── .github/workflows/scraper.yml
```

## Usage

```bash
# Setup (once)
npm install
npx playwright install --with-deps chromium

# One-time auth: opens a real browser, you log in via Google
npm run auth:save

# Run the monitor
npm run scrape

# Validate the latest result
npm run validate
```

## CI/CD (GitHub Actions)

Workflow runs hourly. Required secrets:

- `AUTH_STATE_JSON` — full content of `data/auth.json` (base64 not needed,
  it's already JSON). Re-generate if Google session expires (~14 days).
- `ALERT_WEBHOOK_URL` — Slack/Discord incoming webhook for alerts.

## How the self-healing loop works

```
   ┌──────────────────────────────────────────────────────┐
   │ 1. For each field, build candidate list:             │
   │       learned fallbacks + primary + static fallbacks │
   │ 2. Rank by score (success/(success+fail) + Laplace)  │
   │ 3. Try each. First valid wins.                       │
   │ 4. If ALL fail → AI-like recovery:                   │
   │       a. Find label text in DOM                      │
   │       b. Walk to sibling containing a number         │
   │       c. Synthesize stable selector pointing at it   │
   │       d. Promote to learnedFallbacks                 │
   │ 5. If a required field still null → partialRescrape  │
   │       (wait for networkidle, retry with longer       │
   │        timeouts only the missing fields)             │
   │ 6. Validate: types, ranges, cross-field consistency  │
   │ 7. Persist result + commit learning state            │
   └──────────────────────────────────────────────────────┘
```

## Exit codes

- `0` — All fields extracted, all validations passed
- `1` — Fatal: auth expired, page unreachable, browser crash
- `2` — Soft: ran to completion but at least one validation flagged
