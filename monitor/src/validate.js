// Standalone validation step. Used by CI to fail the build if the latest result
// is incomplete. Read-only — pure file system.
const fs = require('fs');
const path = require('path');

const RESULTS_DIR = path.join(__dirname, '..', 'data', 'results');

if (!fs.existsSync(RESULTS_DIR)) {
  console.error('No results directory found:', RESULTS_DIR);
  process.exit(1);
}
const files = fs.readdirSync(RESULTS_DIR)
  .filter(f => f.startsWith('dashboard-') && f.endsWith('.json'))
  .sort();
if (!files.length) {
  console.error('No dashboard result files found');
  process.exit(1);
}
const latestPath = path.join(RESULTS_DIR, files[files.length - 1]);
const latest = JSON.parse(fs.readFileSync(latestPath, 'utf8'));

if (!latest.validation?.ok) {
  console.error('Validation FAILED:', JSON.stringify(latest.validation.errors, null, 2));
  console.error('From:', files[files.length - 1]);
  process.exit(2);
}

// Additional defense: warn loudly if the run took too long
if ((latest.durationMs || 0) > 60_000) {
  console.warn(`Run took ${latest.durationMs}ms — slow path, investigate.`);
}

console.log('OK', { file: files[files.length - 1], durationMs: latest.durationMs });
