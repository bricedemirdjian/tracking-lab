// Multi-metric scoring + persistent history. Used by the orchestrator at the
// end of each cycle to track whether the system is improving or regressing.
const fs = require('fs');
const path = require('path');

const STORE = path.join(__dirname, '..', '..', 'data', 'swarm', 'cycle-history.jsonl');
fs.mkdirSync(path.dirname(STORE), { recursive: true });

function recordCycle(record) {
  fs.appendFileSync(STORE, JSON.stringify({ ts: new Date().toISOString(), ...record }) + '\n');
}

function loadHistory() {
  if (!fs.existsSync(STORE)) return [];
  return fs.readFileSync(STORE, 'utf8').trim().split('\n').filter(Boolean).map(l => {
    try { return JSON.parse(l); } catch { return null; }
  }).filter(Boolean);
}

function computeMetrics(history) {
  if (!history.length) {
    return {
      success_rate: 0, failure_rate: 0,
      data_completeness_score: 0, selector_stability_score: 0,
      adversarial_resilience_score: 0,
      cycles: 0,
    };
  }
  const last = history.slice(-50);
  const passes = last.filter(h => h.verdict === 'pass').length;
  const failures = last.filter(h => h.verdict === 'fail').length;
  const completeness = avg(last.map(h => h.completenessScore || 0));
  const stability = avg(last.map(h => h.stabilityScore || 0));
  // Adversarial resilience = pass rate when chaos was active
  const chaosRuns = last.filter(h => h.chaos);
  const chaosPasses = chaosRuns.filter(h => h.verdict !== 'fail').length;
  const resilience = chaosRuns.length ? Math.round((chaosPasses / chaosRuns.length) * 100) : null;

  return {
    cycles: last.length,
    success_rate: Math.round((passes / last.length) * 100),
    failure_rate: Math.round((failures / last.length) * 100),
    data_completeness_score: Math.round(completeness),
    selector_stability_score: Math.round(stability),
    adversarial_resilience_score: resilience,
  };
}

function avg(arr) {
  if (!arr.length) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

module.exports = { recordCycle, loadHistory, computeMetrics };
