// EVOLUTION AGENT — proposes and applies code changes to selectors.js based on
// failures observed by the Reviewer. Operates in two modes:
//
//   1. mutate  — generate candidate selectors using DOM proximity + structure.
//                Verify each candidate on the live page, score them, persist
//                the winner via the existing learnedFallbacks store.
//
//   2. retire  — remove static selectors that have failed N consecutive runs
//                (handled by selector-scores.pruneWeakSelectors + persisted).
//
// We never write JS source files at runtime — that would blow away git history.
// Instead, the learnedFallbacks store is the "evolved" layer; selectors.js is
// the immutable seed.
const fs = require('fs');
const path = require('path');
const { info, warn } = require('../logger');
const scores = require('../selector-scores');
const recovery = require('../selector-recovery');

const HISTORY_FILE = path.join(__dirname, '..', '..', 'data', 'swarm', 'evolution-log.jsonl');
fs.mkdirSync(path.dirname(HISTORY_FILE), { recursive: true });

function logEvolution(record) {
  fs.appendFileSync(HISTORY_FILE, JSON.stringify({ ts: new Date().toISOString(), ...record }) + '\n');
}

// Generate ranked candidates by walking the DOM near the field's known label.
async function mutateSelector(page, field, def, observedFailureSelector) {
  const candidates = [];

  // Strategy A: label proximity (existing recovery)
  const recovered = await recovery.findByLabelProximity(page, def.label);
  if (recovered?.selector) candidates.push({ selector: recovered.selector, source: 'label_proximity' });

  // Strategy B: try parent-of-failed + sibling-numeric search
  if (observedFailureSelector) {
    const synth = await page.evaluate((failedSel, type) => {
      const el = document.querySelector(failedSel);
      if (!el) return null;
      const parent = el.parentElement;
      if (!parent) return null;
      // find the first numeric sibling
      for (const sib of parent.children) {
        if (sib === el) continue;
        const t = (sib.textContent || '').trim();
        if (/^[+\-]?\d/.test(t) && t.length < 24) {
          if (sib.id) return `#${sib.id}`;
          return null;
        }
      }
      return null;
    }, observedFailureSelector, def.type);
    if (synth) candidates.push({ selector: synth, source: 'sibling_numeric' });
  }

  // Strategy C: data-attribute fallback (works if app exposes data-kpi="…")
  const dataAttrCandidate = await page.evaluate((label) => {
    const el = document.querySelector(`[data-label="${label}"], [aria-label="${label}"]`);
    return el ? (el.id ? `#${el.id}` : null) : null;
  }, def.label);
  if (dataAttrCandidate) candidates.push({ selector: dataAttrCandidate, source: 'data_attr' });

  if (!candidates.length) {
    logEvolution({ event: 'no_candidate_generated', field });
    return null;
  }

  // Rank: try each on the live page, keep the one with valid extraction.
  for (const c of candidates) {
    try {
      const handle = await page.locator(c.selector).first();
      const count = await handle.count();
      if (count === 0) continue;
      const text = (await handle.textContent({ timeout: 3000 })) || '';
      if (text.trim().length === 0) continue;
      // Promote into learnedFallbacks → next run prefers it
      scores.learnFallback(field, c.selector);
      logEvolution({
        event: 'selector_evolved',
        field,
        from: observedFailureSelector,
        to: c.selector,
        source: c.source,
        rawValue: text.trim().slice(0, 40),
      });
      info('evolution_applied', { field, to: c.selector, source: c.source });
      return c.selector;
    } catch {
      // skip and try next candidate
    }
  }
  logEvolution({ event: 'all_candidates_invalid', field, candidates });
  return null;
}

// Tune retry strategy based on observed failure patterns.
function suggestRetryConfig(history) {
  const last = history.slice(-20);
  if (!last.length) return { tries: 3, baseDelayMs: 2000 };
  const failures = last.filter(h => h.verdict === 'fail').length;
  const failRatio = failures / last.length;
  if (failRatio > 0.5) return { tries: 5, baseDelayMs: 4000 }; // hostile env
  if (failRatio > 0.2) return { tries: 4, baseDelayMs: 2500 };
  return { tries: 3, baseDelayMs: 2000 }; // healthy
}

async function evolve(page, reviewerVerdict, scraperProposal) {
  if (reviewerVerdict.verdict === 'pass') return { applied: 0, mutations: [] };
  const mutations = [];
  for (const issue of reviewerVerdict.issues) {
    if (issue.severity !== 'error') continue;
    if (!issue.field || issue.field.startsWith('_')) continue;
    const def = require('../selectors')[issue.field];
    if (!def) continue;
    const failedSelector = scraperProposal.meta?.[issue.field]?.selector || def.primary;
    const newSel = await mutateSelector(page, issue.field, def, failedSelector);
    if (newSel) mutations.push({ field: issue.field, from: failedSelector, to: newSel });
  }

  // Prune weak selectors after enough samples
  const pruned = scores.pruneWeakSelectors({ minSamples: 10, scoreThreshold: 0.2 });
  if (pruned > 0) logEvolution({ event: 'pruned_weak_selectors', count: pruned });

  return { agent: 'evolution', applied: mutations.length, mutations, pruned };
}

module.exports = { evolve, mutateSelector, suggestRetryConfig };
