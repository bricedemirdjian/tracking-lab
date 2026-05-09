// Main entry. Run with: node src/scraper.js
// Exit codes:
//   0  → success, all fields extracted, validation passed
//   1  → fatal error (auth expired, page unreachable, browser crash)
//   2  → soft failure: ran to completion but validation flagged issues
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
const selectors = require('./selectors');
const { extractWithFallback, extractActivityRows, partialRescrape } = require('./extractor');
const { saveSnapshot, loadLatestSnapshot, structuralDiff } = require('./dom-memory');
const { validatePayload } = require('./validation');
const { sendAlert } = require('./alerting');
const { info, warn, error } = require('./logger');

const TARGET = process.env.TARGET_URL || 'https://app.trackinglab.online/dashboard';
const STORAGE_STATE = process.env.STORAGE_STATE || path.join(__dirname, '..', 'data', 'auth.json');
const RESULTS_DIR = path.join(__dirname, '..', 'data', 'results');
fs.mkdirSync(RESULTS_DIR, { recursive: true });

// Schema drives validation. required:true means the run fails if missing.
const SCHEMA = {
  kpiVideos:         { type: 'number', required: true },
  kpiViews:          { type: 'number', required: true },
  kpiLikes:          { type: 'number', required: true },
  kpiComments:       { type: 'number', required: true },
  kpiShares:         { type: 'number', required: true },
  kpiEngagement:     { type: 'percent', required: true },
  kpiActiveAccounts: { type: 'number', required: true },
  kpiAvgViews:       { type: 'number', required: true },
  kpiFollowers:      { type: 'number', required: true },
  kpiFollowerGain:   { type: 'signedNumber', required: false }, // 0 valid (no period)
};

async function withRetry(fn, { tries = 3, delayMs = 2_000, label = 'op' } = {}) {
  let lastErr;
  for (let i = 0; i < tries; i++) {
    try { return await fn(); }
    catch (e) {
      lastErr = e;
      warn('retry', { label, attempt: i + 1, of: tries, err: String(e).slice(0, 200) });
      await new Promise(r => setTimeout(r, delayMs * Math.pow(2, i)));
    }
  }
  throw lastErr;
}

async function run() {
  const startedAt = Date.now();
  info('run_start', { target: TARGET });

  const browser = await chromium.launch({
    headless: true,
    args: ['--disable-dev-shm-usage', '--no-sandbox'], // CI-friendly
  });
  let context, page;

  try {
    if (fs.existsSync(STORAGE_STATE)) {
      context = await browser.newContext({
        storageState: STORAGE_STATE,
        viewport: { width: 1440, height: 900 },
      });
      info('auth_state_loaded', { from: STORAGE_STATE });
    } else {
      warn('no_storage_state_found', { hint: 'run npm run auth:save first' });
      context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    }
    // Fail fast on broken nav
    context.setDefaultNavigationTimeout(30_000);
    context.setDefaultTimeout(15_000);

    page = await context.newPage();

    // Capture network errors (helps explain why a field is missing)
    page.on('pageerror', (err) => warn('page_error', { err: String(err).slice(0, 200) }));
    page.on('requestfailed', (req) => warn('request_failed', { url: req.url(), failure: req.failure()?.errorText }));

    await withRetry(
      () => page.goto(TARGET, { waitUntil: 'domcontentloaded' }),
      { tries: 3, label: 'goto' }
    );

    // Auth gate detection (Flask redirects to /login)
    if (/\/login(\?|$)/.test(page.url())) {
      await sendAlert('critical', 'Auth expired — landed on /login', { url: page.url() });
      throw Object.assign(new Error('auth_expired'), { code: 'AUTH_EXPIRED' });
    }

    // Wait for at least one KPI to render. The dashboard auto-fetches /api/stats on load.
    await page.waitForSelector('#kpiVideos, .kpi-card-new', { timeout: 20_000 });
    // Wait until the value is no longer the initial "0" placeholder.
    await page.waitForFunction(() => {
      const el = document.querySelector('#kpiViews');
      return el && /[1-9]/.test(el.textContent);
    }, { timeout: 12_000 }).catch(() => {
      warn('kpi_views_did_not_populate', { hint: 'maybe an empty account or stats fetch failed' });
    });

    // DOM memory (before extraction so the snapshot reflects what we read)
    const prevHtml = loadLatestSnapshot('dashboard');
    await saveSnapshot(page, 'dashboard');
    const currentHtml = await page.content();
    const diff = structuralDiff(prevHtml, currentHtml);
    if (diff.changed && (diff.ratio ?? 0) > 0.20) {
      await sendAlert('warning', 'DOM structure shifted significantly', {
        ratio: diff.ratio,
        lenDiff: diff.lenDiff,
        onlyInPrev: diff.onlyInPrev,
        onlyInCur: diff.onlyInCur,
      });
    }

    // Extract every scalar field
    const result = {};
    const meta = {};
    for (const [field, def] of Object.entries(selectors)) {
      if (def.type === 'rowList') continue;
      const out = await extractWithFallback(page, field, def);
      if (out.ok) {
        result[field] = out.value;
        meta[field] = { selector: out.selector, recovered: !!out.recovered, raw: out.raw };
      } else {
        result[field] = null;
        meta[field] = { error: out.error };
      }
    }

    // Self-healing partial re-scrape if any required field is null
    const missingRequired = Object.entries(SCHEMA).filter(([f, def]) => def.required && result[f] == null);
    if (missingRequired.length) {
      info('attempting_partial_rescrape', { fields: missingRequired.map(([f]) => f) });
      const rescraped = await partialRescrape(page, SCHEMA, result);
      Object.assign(result, rescraped.result);
      Object.assign(meta, rescraped.meta || {});
    }

    // Activity table
    const activity = await extractActivityRows(page, selectors.activityRows);
    result.activityRows = activity.ok ? activity.rows : null;
    meta.activityRows = activity.ok
      ? { count: activity.count, sample: activity.rows.slice(0, 3) }
      : { error: activity.error };

    // Validate
    const validation = validatePayload(result, SCHEMA);
    if (!validation.ok) {
      await sendAlert('error', 'Data validation failed', { errors: validation.errors, partial: result });
    }

    // Persist
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
    const outFile = path.join(RESULTS_DIR, `dashboard-${stamp}.json`);
    fs.writeFileSync(outFile, JSON.stringify({
      at: new Date().toISOString(),
      durationMs: Date.now() - startedAt,
      url: page.url(),
      data: result,
      meta,
      validation,
      domDiff: diff,
    }, null, 2));
    info('run_end', { file: outFile, durationMs: Date.now() - startedAt, valid: validation.ok });

    process.exit(validation.ok ? 0 : 2);
  } catch (e) {
    error('run_failed', { err: String(e).slice(0, 400), stack: e.stack?.slice(0, 800) });
    if (e.code !== 'AUTH_EXPIRED') {
      await sendAlert('critical', 'Scraper run failed', { err: String(e).slice(0, 200) });
    }
    // Save a debug snapshot if we have a page
    try { if (page) await page.screenshot({ path: path.join(RESULTS_DIR, `error-${Date.now()}.png`), fullPage: true }); } catch {}
    process.exit(1);
  } finally {
    try { await context?.close(); } catch {}
    try { await browser.close(); } catch {}
  }
}

if (require.main === module) {
  run();
}
module.exports = { run };
