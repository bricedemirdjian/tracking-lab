// Structured JSONL logger — one line per event, machine-parseable.
// Writes to console (for CI capture) + a daily file.
const fs = require('fs');
const path = require('path');

const LOG_DIR = path.join(__dirname, '..', 'data', 'logs');
fs.mkdirSync(LOG_DIR, { recursive: true });
const LOG_FILE = path.join(LOG_DIR, `run-${new Date().toISOString().slice(0, 10)}.jsonl`);

function log(entry) {
  const record = {
    ...entry,
    timestamp: new Date().toISOString(),
    runId: process.env.RUN_ID || 'local',
  };
  const line = JSON.stringify(record);
  try { process.stdout.write(line + '\n'); } catch {}
  try { fs.appendFileSync(LOG_FILE, line + '\n'); } catch {}
}

const info = (msg, ctx = {}) => log({ level: 'info', msg, ...ctx });
const warn = (msg, ctx = {}) => log({ level: 'warn', msg, ...ctx });
const error = (msg, ctx = {}) => log({ level: 'error', msg, ...ctx });
const debug = (msg, ctx = {}) => process.env.DEBUG && log({ level: 'debug', msg, ...ctx });

module.exports = { log, info, warn, error, debug };
