// Save HTML snapshots of the dashboard before/after each run + diff against last
// snapshot. Used by alerting (warn on big structure shift) + by selector recovery
// (compare current DOM to last known-good).
const fs = require('fs');
const path = require('path');
const { info } = require('./logger');

const SNAPSHOT_DIR = path.join(__dirname, '..', 'data', 'dom-snapshots');
fs.mkdirSync(SNAPSHOT_DIR, { recursive: true });

const MAX_SNAPSHOTS = 30;

async function saveSnapshot(page, label) {
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  const fp = path.join(SNAPSHOT_DIR, `${label}-${ts}.html`);
  const html = await page.content();
  fs.writeFileSync(fp, html);
  rotate(label);
  info('dom_snapshot_saved', { file: path.basename(fp), bytes: html.length });
  return { path: fp, html };
}

function rotate(prefix) {
  const files = fs.readdirSync(SNAPSHOT_DIR)
    .filter(f => f.startsWith(prefix) && f.endsWith('.html'))
    .map(f => ({ f, t: fs.statSync(path.join(SNAPSHOT_DIR, f)).mtimeMs }))
    .sort((a, b) => b.t - a.t);
  files.slice(MAX_SNAPSHOTS).forEach(x => {
    try { fs.unlinkSync(path.join(SNAPSHOT_DIR, x.f)); } catch {}
  });
}

function loadLatestSnapshot(prefix) {
  const files = fs.readdirSync(SNAPSHOT_DIR)
    .filter(f => f.startsWith(prefix) && f.endsWith('.html'))
    .map(f => ({ f, t: fs.statSync(path.join(SNAPSHOT_DIR, f)).mtimeMs }))
    .sort((a, b) => b.t - a.t);
  if (files.length < 2) return null; // index 0 is what we just saved
  return fs.readFileSync(path.join(SNAPSHOT_DIR, files[1].f), 'utf8');
}

function structuralDiff(prevHtml, currentHtml) {
  if (!prevHtml || !currentHtml) return { changed: true, reason: 'no_baseline' };
  const norm = h => h
    .replace(/\s+/g, ' ')
    .replace(/<!--[\s\S]*?-->/g, '')
    // Strip dynamic attrs that change every render (CSP nonces, request ids, etc.)
    .replace(/data-[\w-]+="[^"]*"/g, '')
    .replace(/nonce="[^"]*"/g, '')
    .toLowerCase();
  const a = norm(prevHtml), b = norm(currentHtml);
  if (a === b) return { changed: false };
  const lenDiff = Math.abs(a.length - b.length);
  const ratio = lenDiff / Math.max(a.length, b.length);
  // Tag set comparison — biggest signal of "structure changed"
  const tagSet = h => new Set(Array.from(h.matchAll(/<([a-z][\w-]*)/g)).map(m => m[1]));
  const ta = tagSet(a), tb = tagSet(b);
  const onlyInPrev = [...ta].filter(t => !tb.has(t));
  const onlyInCur = [...tb].filter(t => !ta.has(t));
  return { changed: true, ratio, lenDiff, onlyInPrev, onlyInCur };
}

module.exports = { saveSnapshot, loadLatestSnapshot, structuralDiff };
