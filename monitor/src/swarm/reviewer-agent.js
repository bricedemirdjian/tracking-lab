// REVIEWER AGENT — judges a proposal from the Scraper.
// Outputs a quality score 0–100 and itemized issues. Stateless.
const { validatePayload } = require('../validation');

const SCHEMA = {
  kpiVideos:         { type: 'number',       required: true,  weight: 10 },
  kpiViews:          { type: 'number',       required: true,  weight: 15 },
  kpiLikes:          { type: 'number',       required: true,  weight: 10 },
  kpiComments:       { type: 'number',       required: true,  weight: 8  },
  kpiShares:         { type: 'number',       required: true,  weight: 8  },
  kpiEngagement:     { type: 'percent',      required: true,  weight: 10 },
  kpiActiveAccounts: { type: 'number',       required: true,  weight: 8  },
  kpiAvgViews:       { type: 'number',       required: true,  weight: 10 },
  kpiFollowers:      { type: 'number',       required: true,  weight: 11 },
  kpiFollowerGain:   { type: 'signedNumber', required: false, weight: 5  },
  // 95 total — leave 5 for activityRows presence
};

function review(proposal) {
  const issues = [];
  const data = proposal.data || {};
  const validation = validatePayload(data, SCHEMA);
  for (const e of validation.errors) issues.push({ severity: 'error', ...e });

  // Cross-field consistency: avg ≈ views/videos within 5%
  if (data.kpiViews != null && data.kpiVideos > 0 && data.kpiAvgViews != null) {
    const expected = data.kpiViews / data.kpiVideos;
    const ratio = Math.abs(expected - data.kpiAvgViews) / Math.max(1, expected);
    if (ratio > 0.05) {
      issues.push({
        severity: 'error',
        field: 'kpiAvgViews',
        error: 'inconsistent',
        expected: Math.round(expected),
        actual: data.kpiAvgViews,
        ratio: ratio.toFixed(3),
      });
    }
  }

  // Activity rows must be a non-empty list when active accounts > 0
  if ((data.kpiActiveAccounts || 0) > 0 && !(data.activityRows || []).length) {
    issues.push({ severity: 'error', field: 'activityRows', error: 'empty_table_with_active_accounts' });
  }

  // DOM drift > 20% is a soft warning — not an error
  if (proposal.drift?.changed && (proposal.drift.ratio ?? 0) > 0.20) {
    issues.push({ severity: 'warning', field: '_dom', error: 'structural_drift', ratio: proposal.drift.ratio });
  }

  // Score: 100 - (Σ weights of failed required fields)
  let lostPoints = 0;
  for (const issue of issues) {
    if (issue.severity !== 'error') continue;
    const w = SCHEMA[issue.field]?.weight ?? 5;
    lostPoints += w;
  }
  const completenessScore = Math.max(0, 100 - lostPoints);

  // Recovery bonus — lose 1 point per recovered field (means primary failed)
  const recoveredCount = Object.values(proposal.meta || {}).filter(m => m?.recovered).length;
  const stabilityScore = Math.max(0, 100 - recoveredCount * 5);

  const overall = Math.round(0.7 * completenessScore + 0.3 * stabilityScore);

  return {
    agent: 'reviewer',
    score: overall,
    completenessScore,
    stabilityScore,
    issues,
    verdict: overall >= 90 ? 'pass' : overall >= 70 ? 'pass_with_warnings' : 'fail',
  };
}

module.exports = { review, SCHEMA };
