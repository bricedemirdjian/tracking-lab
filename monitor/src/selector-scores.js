// Persistent reliability scoring for selectors.
// Stored in data/selector-stats.json — committed by CI so learning carries over runs.
const fs = require('fs');
const path = require('path');

const STORE = path.join(__dirname, '..', 'data', 'selector-stats.json');
fs.mkdirSync(path.dirname(STORE), { recursive: true });

function load() {
  if (!fs.existsSync(STORE)) return { fields: {}, learnedFallbacks: {}, version: 1 };
  try { return JSON.parse(fs.readFileSync(STORE, 'utf8')); }
  catch { return { fields: {}, learnedFallbacks: {}, version: 1 }; }
}

function save(state) {
  fs.writeFileSync(STORE, JSON.stringify(state, null, 2));
}

function _ensure(state, field, selector) {
  state.fields[field] ??= {};
  state.fields[field][selector] ??= { success: 0, fail: 0, lastSuccess: null, lastFail: null };
  return state.fields[field][selector];
}

function recordSuccess(field, selector) {
  const state = load();
  const stat = _ensure(state, field, selector);
  stat.success++;
  stat.lastSuccess = new Date().toISOString();
  save(state);
}

function recordFailure(field, selector) {
  const state = load();
  const stat = _ensure(state, field, selector);
  stat.fail++;
  stat.lastFail = new Date().toISOString();
  save(state);
}

// Smoothed Wilson-ish score so a single failure doesn't crater an unknown selector.
function score(field, selector) {
  const state = load();
  const stat = state.fields[field]?.[selector];
  if (!stat) return 0.5; // unknown → neutral
  const total = stat.success + stat.fail;
  if (total === 0) return 0.5;
  // +1 prior success and +1 prior failure (Laplace smoothing)
  return (stat.success + 1) / (total + 2);
}

function rankSelectors(field, candidates) {
  return [...new Set(candidates)]
    .map(s => ({ s, score: score(field, s) }))
    .sort((a, b) => b.score - a.score)
    .map(x => x.s);
}

// Promote a selector found via AI-like recovery to the top of the learned list.
function learnFallback(field, selector) {
  const state = load();
  state.learnedFallbacks[field] ??= [];
  state.learnedFallbacks[field] = [selector, ...state.learnedFallbacks[field].filter(s => s !== selector)].slice(0, 5);
  save(state);
}

function getLearnedFallbacks(field) {
  return load().learnedFallbacks[field] || [];
}

// CI step can call this to retire selectors with abysmal scores after enough samples.
function pruneWeakSelectors({ minSamples = 10, scoreThreshold = 0.2 } = {}) {
  const state = load();
  let pruned = 0;
  for (const [field, selectors] of Object.entries(state.fields)) {
    for (const [sel, stat] of Object.entries(selectors)) {
      const total = stat.success + stat.fail;
      if (total >= minSamples && score(field, sel) < scoreThreshold) {
        delete state.fields[field][sel];
        if (state.learnedFallbacks[field]) {
          state.learnedFallbacks[field] = state.learnedFallbacks[field].filter(s => s !== sel);
        }
        pruned++;
      }
    }
  }
  save(state);
  return pruned;
}

module.exports = {
  load, save,
  recordSuccess, recordFailure, score, rankSelectors,
  learnFallback, getLearnedFallbacks,
  pruneWeakSelectors,
};
