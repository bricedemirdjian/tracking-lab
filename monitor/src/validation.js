// Pure parsing + validation. No I/O. Used by extractor + standalone validate.js.

// Tracking Lab uses non-breaking spaces as thousand separators (FR locale)
// and prefixes like "+", "-", "·". Numbers can also be K/M shortened.
function parseNumberFR(text) {
  if (text == null) return null;
  let s = String(text).trim();
  // Strip whitespace (incl. non-breaking) and currency-ish chars
  s = s.replace(/[\s  ]/g, '').replace(/[^\d.,kKmMbB+-]/g, '');
  if (!s) return null;
  // Compact form: 1.5K, 2,8M
  const compactMatch = s.match(/^(-?[\d.,]+)([kKmMbB])$/);
  if (compactMatch) {
    const base = Number(compactMatch[1].replace(',', '.'));
    const unit = { k: 1e3, m: 1e6, b: 1e9 }[compactMatch[2].toLowerCase()];
    return Number.isFinite(base) ? Math.round(base * unit) : null;
  }
  // Pure number — strip , (FR thousand sep)
  const n = Number(s.replace(/,/g, ''));
  return Number.isFinite(n) ? n : null;
}

function parsePercent(text) {
  if (text == null) return null;
  const m = String(text).match(/(-?\d+([.,]\d+)?)\s*%/);
  if (!m) return null;
  const v = Number(m[1].replace(',', '.'));
  return Number.isFinite(v) ? v : null;
}

function parseSignedNumber(text) {
  if (text == null) return null;
  const t = String(text).trim();
  const sign = t.startsWith('-') ? -1 : 1;
  const num = parseNumberFR(t.replace(/^[+\-]/, ''));
  return num == null ? null : sign * num;
}

function parseByType(type, text) {
  switch (type) {
    case 'number': return parseNumberFR(text);
    case 'percent': return parsePercent(text);
    case 'signedNumber': return parseSignedNumber(text);
    default: return text;
  }
}

const validators = {
  number: v => typeof v === 'number' && Number.isFinite(v) && v >= 0,
  percent: v => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= 100,
  signedNumber: v => typeof v === 'number' && Number.isFinite(v),
};

function isValid(type, value) {
  const fn = validators[type];
  return fn ? fn(value) : value !== null && value !== undefined;
}

function validatePayload(payload, schema) {
  const errors = [];
  for (const [field, def] of Object.entries(schema)) {
    if (def.required && (payload[field] == null)) {
      errors.push({ field, error: 'missing' });
      continue;
    }
    if (payload[field] != null && def.type) {
      if (!isValid(def.type, payload[field])) {
        errors.push({ field, error: 'invalid', value: payload[field], expected: def.type });
      }
    }
  }
  // Cross-field sanity: avg_views must roughly match views/videos when both present
  if (payload.kpiViews != null && payload.kpiVideos != null && payload.kpiAvgViews != null && payload.kpiVideos > 0) {
    const expected = payload.kpiViews / payload.kpiVideos;
    const actual = payload.kpiAvgViews;
    const ratio = Math.abs(expected - actual) / Math.max(1, expected);
    if (ratio > 0.05) { // tolerate 5% rounding (UI uses formatCompact)
      errors.push({ field: 'kpiAvgViews', error: 'inconsistent', expected: Math.round(expected), actual });
    }
  }
  return { ok: errors.length === 0, errors };
}

module.exports = {
  parseByType, parseNumberFR, parsePercent, parseSignedNumber,
  isValid, validatePayload,
};
