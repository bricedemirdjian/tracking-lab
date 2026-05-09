// SWARM ORCHESTRATOR — runs the 4-agent loop for N cycles.
//
//   Scraper  ─→  Reviewer  ─→  Adversary (next cycle)
//        ↑                              │
//        └──────  Evolution  ───────────┘
//
// One cycle = one fresh page session. Adversary mode is sampled per cycle.
// Evolution applies between cycles (so improvements stick for next run).
const path = require('path');
const fs = require('fs');
const { chromium } = require('playwright');
const scraperAgent = require('./scraper-agent');
const reviewerAgent = require('./reviewer-agent');
const adversaryAgent = require('./adversary-agent');
const evolutionAgent = require('./evolution-agent');
const scoring = require('./scoring');
const { info, warn, error } = require('../logger');

const TARGET = process.env.TARGET_URL || 'https://app.trackinglab.online/dashboard';
const STORAGE_STATE = process.env.STORAGE_STATE || path.join(__dirname, '..', '..', 'data', 'auth.json');
const CHAOS_PROBABILITY = Number(process.env.CHAOS_PROBABILITY ?? '0.7');

async function runCycle(browser, cycleIndex) {
  const cycleStart = Date.now();
  const ctxOpts = { viewport: { width: 1440, height: 900 } };
  if (fs.existsSync(STORAGE_STATE)) ctxOpts.storageState = STORAGE_STATE;
  const context = await browser.newContext(ctxOpts);
  const page = await context.newPage();
  page.setDefaultTimeout(20_000);
  page.on('pageerror', e => warn('page_error', { cycle: cycleIndex, err: String(e).slice(0, 200) }));

  // ── Adversary attaches first — chaos rules apply for the whole session ──
  const chaos = Math.random() < CHAOS_PROBABILITY ? adversaryAgent.pickMode() : null;
  if (chaos) {
    adversaryAgent.attach(page, { mode: chaos, intensity: 1 });
    info('adversary_active', { cycle: cycleIndex, mode: chaos });
  }

  let proposal, verdict, evolution = null, gateDetected = null;
  try {
    await page.goto(TARGET, { waitUntil: 'domcontentloaded', timeout: 30_000 });

    // Captcha / Cloudflare gate detection — abort cleanly, do not bypass.
    gateDetected = await adversaryAgent.detectGate(page);
    if (gateDetected.gated) {
      warn('gate_detected_aborting', { cycle: cycleIndex, ...gateDetected });
      proposal = { agent: 'scraper', data: {}, meta: {}, failures: [{ field: '_page', error: 'gate_detected' }] };
      verdict = { agent: 'reviewer', score: 0, completenessScore: 0, stabilityScore: 0,
                  issues: [{ severity: 'error', field: '_page', error: 'gate_detected', kind: gateDetected.kind }],
                  verdict: 'fail' };
    } else {
      proposal = await scraperAgent.scrape(page, { ackChaos: !!chaos });
      verdict = reviewerAgent.review(proposal);
      evolution = await evolutionAgent.evolve(page, verdict, proposal);
    }
  } catch (e) {
    error('cycle_crash', { cycle: cycleIndex, err: String(e).slice(0, 200) });
    proposal = { agent: 'scraper', data: {}, failures: [{ field: '_run', error: String(e).slice(0, 200) }] };
    verdict = { agent: 'reviewer', score: 0, completenessScore: 0, stabilityScore: 0,
                issues: [{ severity: 'error', field: '_run', error: 'cycle_crash' }], verdict: 'fail' };
  } finally {
    await context.close().catch(() => {});
  }

  scoring.recordCycle({
    cycle: cycleIndex,
    durationMs: Date.now() - cycleStart,
    chaos,
    gateDetected: gateDetected?.gated ? gateDetected.kind : null,
    score: verdict.score,
    completenessScore: verdict.completenessScore,
    stabilityScore: verdict.stabilityScore,
    verdict: verdict.verdict,
    issues: verdict.issues?.length || 0,
    mutations: evolution?.mutations?.length || 0,
  });

  return { cycle: cycleIndex, chaos, gateDetected, proposal, verdict, evolution };
}

async function runSwarm({ cycles = 5 } = {}) {
  info('swarm_start', { cycles, target: TARGET, chaosProbability: CHAOS_PROBABILITY });
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const results = [];
  try {
    for (let i = 0; i < cycles; i++) {
      info('cycle_start', { cycle: i });
      const r = await runCycle(browser, i);
      results.push({
        cycle: i,
        chaos: r.chaos,
        gate: r.gateDetected?.gated ? r.gateDetected.kind : null,
        score: r.verdict.score,
        verdict: r.verdict.verdict,
        mutations: r.evolution?.mutations?.length || 0,
      });
      info('cycle_end', results[i]);
    }
  } finally {
    await browser.close().catch(() => {});
  }

  const history = scoring.loadHistory();
  const metrics = scoring.computeMetrics(history);
  info('swarm_end', { metrics, cycles: results.length });
  return { results, metrics };
}

if (require.main === module) {
  const cycles = Number(process.argv[2] || process.env.CYCLES || 5);
  runSwarm({ cycles })
    .then(({ results, metrics }) => {
      console.log('\n=== SWARM SUMMARY ===');
      console.table(results);
      console.log('\n=== AGGREGATE METRICS ===');
      console.log(JSON.stringify(metrics, null, 2));
      process.exit(metrics.success_rate >= 60 ? 0 : 2);
    })
    .catch(e => { console.error(e); process.exit(1); });
}

module.exports = { runSwarm, runCycle };
