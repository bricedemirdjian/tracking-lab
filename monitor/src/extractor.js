// Self-healing extractor.
// For each field:
//   1. Build candidate list = learned fallbacks + primary + static fallbacks
//   2. Rank candidates by historical reliability score
//   3. Try each in order, validating type & value
//   4. If all candidates fail, invoke AI-like recovery (label proximity)
//   5. Record success/failure for the score store (auto-training)
const { info, warn, error } = require('./logger');
const scores = require('./selector-scores');
const { parseByType, isValid } = require('./validation');
const { tryRecover } = require('./selector-recovery');

const FIELD_TIMEOUT_MS = 5_000;

async function extractWithFallback(page, field, def) {
  const learned = scores.getLearnedFallbacks(field);
  const candidates = [...learned, def.primary, ...(def.fallbacks || [])];
  const ranked = scores.rankSelectors(field, candidates);

  for (const sel of ranked) {
    const result = await tryOne(page, field, def, sel);
    if (result.ok) return result;
  }

  // All known selectors failed → AI-like recovery (find by label proximity)
  warn('all_static_failed_attempting_recovery', { field });
  const recovered = await tryRecover(page, field, def);
  if (recovered) {
    const result = await tryOne(page, field, def, recovered);
    if (result.ok) return { ...result, recovered: true };
  }
  return { ok: false, field, error: 'all_selectors_failed' };
}

async function tryOne(page, field, def, sel) {
  try {
    const locator = page.locator(sel).first();
    const count = await locator.count();
    if (count === 0) {
      scores.recordFailure(field, sel);
      return { ok: false, reason: 'not_found' };
    }
    const text = (await locator.textContent({ timeout: FIELD_TIMEOUT_MS }) || '').trim();

    // For lists, success = element list non-empty
    if (def.type === 'rowList') {
      const allCount = await page.locator(sel).count();
      if (allCount > 0) {
        scores.recordSuccess(field, sel);
        info('extract_ok', { field, selector: sel, count: allCount });
        return { ok: true, selector: sel, value: allCount, raw: text };
      }
      scores.recordFailure(field, sel);
      return { ok: false, reason: 'empty_list' };
    }

    const value = parseByType(def.type, text);
    if (isValid(def.type, value)) {
      scores.recordSuccess(field, sel);
      info('extract_ok', { field, selector: sel, value });
      return { ok: true, selector: sel, value, raw: text };
    }
    // Special case: signedNumber 0 from kpiFollowerGain is valid (no period set)
    if (def.type === 'signedNumber' && value === 0) {
      scores.recordSuccess(field, sel);
      return { ok: true, selector: sel, value: 0, raw: text };
    }
    scores.recordFailure(field, sel);
    warn('extract_invalid_value', { field, selector: sel, raw: text, parsed: value });
    return { ok: false, reason: 'invalid_value' };
  } catch (e) {
    scores.recordFailure(field, sel);
    warn('extract_error', { field, selector: sel, err: String(e).slice(0, 200) });
    return { ok: false, reason: 'error', err: String(e).slice(0, 200) };
  }
}

// Activity table: extract row count + each row's account handle + per-cell text.
async function extractActivityRows(page, def) {
  const rowResult = await extractWithFallback(page, 'activityRows', def);
  if (!rowResult.ok) return { ok: false, error: 'activity_rows_missing' };
  const rows = await page.evaluate((sel) => {
    const trs = Array.from(document.querySelectorAll(sel));
    return trs.map(tr => {
      const cells = Array.from(tr.querySelectorAll('td')).map(c => (c.textContent || '').trim());
      const handleEl = tr.querySelector('.activity-account-handle, [class*="handle"]');
      const handle = handleEl ? (handleEl.textContent || '').trim().replace(/^@/, '') : null;
      return { handle, cells };
    });
  }, rowResult.selector);
  return { ok: true, rows, count: rowResult.value };
}

// Self-healing partial re-scrape: only retry the fields that failed in main pass.
// Bumps timeouts + waits for any pending network before retrying.
async function partialRescrape(page, schema, previousResult) {
  const toRetry = Object.keys(schema).filter(f => previousResult[f] == null);
  if (!toRetry.length) return previousResult;
  info('partial_rescrape_start', { fields: toRetry });
  await page.waitForLoadState('networkidle', { timeout: 10_000 }).catch(() => {});
  await page.waitForTimeout(1_500); // settle async re-renders
  const merged = { ...previousResult };
  const meta = {};
  for (const field of toRetry) {
    const def = require('./selectors')[field];
    if (!def) continue;
    const out = await extractWithFallback(page, field, def);
    if (out.ok) {
      merged[field] = out.value;
      meta[field] = { selector: out.selector, recovered: !!out.recovered, viaPartialRescrape: true };
    }
  }
  info('partial_rescrape_done', { recovered: Object.keys(meta).length, of: toRetry.length });
  return { result: merged, meta };
}

module.exports = { extractWithFallback, extractActivityRows, partialRescrape };
