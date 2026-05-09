# Swarm — Autonomous Multi-Agent Self-Evolving Scraper

Built on top of `monitor/` (Playwright self-healing). Adds 4 agents that run
in a loop and continuously stress + improve the scraper.

## Run

```bash
cd monitor
npm install
npx playwright install --with-deps chromium
node src/swarm/orchestrator.js 10        # 10 cycles
```

Set `CHAOS_PROBABILITY=0.0` for clean baseline runs, or `=1.0` to test under
permanent adversarial conditions.

## Agents

| Agent | Module | Role |
|---|---|---|
| Scraper | `scraper-agent.js` | Wraps `monitor/src/extractor.js` — emits a proposal |
| Reviewer | `reviewer-agent.js` | Validates proposal — emits score 0–100 + issues |
| Adversary | `adversary-agent.js` | Injects 7 chaos modes via Playwright route interception |
| Evolution | `evolution-agent.js` | Generates new selector candidates, persists winners |

## Cycle loop

```
[Adversary attaches chaos mode to fresh page]
         │
         ▼
[Scraper.scrape(page)] ──→ proposal
         │
         ▼
[Reviewer.review(proposal)] ──→ verdict (score + issues)
         │
         ▼ (only if verdict != pass)
[Evolution.evolve(page, verdict, proposal)] ──→ mutations applied to learnedFallbacks
         │
         ▼
[Scoring.recordCycle(...)] ──→ data/swarm/cycle-history.jsonl
         │
         ▼
[Next cycle reads ranked selectors — improvements stick]
```

## Chaos modes (SIMULATION ONLY)

| Mode | Mechanism | Detection |
|---|---|---|
| `dom_mutation` | Init script replaces KPI text with random junk | Reviewer cross-field check + `parseNumberFR` returns NaN |
| `selector_breakage` | Init script strips `#id` attributes | `extractWithFallback` falls through to fallbacks |
| `timeout_spike` | XHR responses delayed 8–15s | `waitForFunction` times out → null fields |
| `partial_render` | All CSS responses dropped | Visual `waitFor` may fail |
| `captcha_simulation` | `/dashboard` HTML replaced with fake captcha page | `detectGate()` returns `{gated:true}` → cycle aborts cleanly |
| `cf_challenge_sim` | `/dashboard` HTML replaced with fake CF challenge | Same — explicit abort, no bypass logic anywhere |
| `partial_data` | `/api/stats` response mutated to drop random fields | Reviewer flags missing required fields |

We never solve, bypass, or work around the captcha/CF simulation pages.
The Scraper detects them via `[data-captcha]` / `[data-cf-challenge]` markers
or page title patterns and aborts the cycle with `verdict: fail`.

## Persistent state

```
data/swarm/
├── cycle-history.jsonl    # one line per cycle (audit trail)
├── evolution-log.jsonl    # one line per applied mutation
└── ../selector-stats.json # learned fallbacks (shared with monitor)
```

## Metrics emitted at swarm end

```json
{
  "cycles": 50,
  "success_rate": 78,
  "failure_rate": 14,
  "data_completeness_score": 91,
  "selector_stability_score": 94,
  "adversarial_resilience_score": 62
}
```

`adversarial_resilience_score` is the pass rate **only on cycles where chaos
was active**. This is the hardest metric to improve — that's the point.
