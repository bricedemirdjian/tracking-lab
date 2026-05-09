// SCRAPER AGENT — extracts data using the registry + extractor from monitor/.
// In the swarm loop it produces a `proposal` that the Reviewer validates.
const { extractWithFallback, extractActivityRows } = require('../extractor');
const selectors = require('../selectors');
const { saveSnapshot, loadLatestSnapshot, structuralDiff } = require('../dom-memory');
const { info, warn } = require('../logger');

const FIELDS_SCALAR = Object.entries(selectors).filter(([, def]) => def.type !== 'rowList');

async function scrape(page, { ackChaos } = {}) {
  const startedAt = Date.now();
  // Wait for at least one KPI rendered
  await page.waitForSelector('#kpiVideos, .kpi-card-new', { timeout: 20_000 }).catch(() => {});
  await page.waitForFunction(() => {
    const el = document.querySelector('#kpiViews');
    return el && /[1-9]/.test(el.textContent);
  }, { timeout: 12_000 }).catch(() => {});

  // DOM memory
  const prev = loadLatestSnapshot('dashboard-swarm');
  await saveSnapshot(page, 'dashboard-swarm');
  const html = await page.content();
  const drift = structuralDiff(prev, html);

  const data = {};
  const meta = {};
  const failures = [];

  for (const [field, def] of FIELDS_SCALAR) {
    const r = await extractWithFallback(page, field, def);
    if (r.ok) {
      data[field] = r.value;
      meta[field] = { selector: r.selector, recovered: !!r.recovered };
    } else {
      data[field] = null;
      meta[field] = { error: r.error };
      failures.push({ field, error: r.error });
    }
  }

  const activity = await extractActivityRows(page, selectors.activityRows);
  data.activityRows = activity.ok ? activity.rows : null;
  if (!activity.ok) failures.push({ field: 'activityRows', error: activity.error });

  return {
    agent: 'scraper',
    durationMs: Date.now() - startedAt,
    data,
    meta,
    failures,
    drift,
    chaosAcknowledged: !!ackChaos,
  };
}

module.exports = { scrape };
