// Alert sink. Console always; webhook (Slack/Discord) if configured.
// Severity: info | warning | error | critical (used for routing later if you add PagerDuty)
const { info, error } = require('./logger');

const WEBHOOK = process.env.ALERT_WEBHOOK_URL;
const ALERT_MIN_SEVERITY = process.env.ALERT_MIN_SEVERITY || 'warning'; // info|warning|error|critical
const SEVERITY_RANK = { info: 0, warning: 1, error: 2, critical: 3 };

function shouldRoute(severity) {
  return (SEVERITY_RANK[severity] ?? 1) >= (SEVERITY_RANK[ALERT_MIN_SEVERITY] ?? 1);
}

async function sendAlert(severity, msg, ctx = {}) {
  const payload = { severity, msg, ctx, ts: new Date().toISOString() };
  // Always log
  if (severity === 'critical' || severity === 'error') error('alert', payload);
  else info('alert', payload);

  if (!WEBHOOK || !shouldRoute(severity)) return;

  const body = {
    text: `[${severity.toUpperCase()}] ${msg}`,
    blocks: [
      { type: 'section', text: { type: 'mrkdwn', text: `*[${severity.toUpperCase()}] ${msg}*` } },
      { type: 'section', text: { type: 'mrkdwn', text: '```' + JSON.stringify(ctx, null, 2).slice(0, 2500) + '```' } },
    ],
  };
  try {
    const res = await fetch(WEBHOOK, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    info('alert_delivered', { status: res.status });
  } catch (e) {
    error('alert_delivery_failed', { err: String(e).slice(0, 200) });
  }
}

module.exports = { sendAlert };
