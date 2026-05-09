// ADVERSARY AGENT — chaos engine.
// Implemented entirely via Playwright route interception. We never bypass any
// security mechanism — we SIMULATE failure conditions so the system can prove
// it survives them.
//
// Modes (selected at random when chaos is active):
//   1. dom_mutation        — mutate KPI value cells to random text
//   2. selector_breakage   — strip #id attributes from KPI cells
//   3. timeout_spike       — delay XHR responses by 8–15s (most operations time out)
//   4. partial_render      — drop CSS so layout reflows + waitFor functions fail
//   5. captcha_simulation  — replace HTML with a fake "verify you are human" page
//   6. cf_challenge_sim    — replace HTML with a fake Cloudflare-style challenge
//                            (visual mimicry only — NO bypass logic anywhere)
//   7. partial_data        — return /api/stats with several fields removed
//
// IMPORTANT: modes 5 & 6 only INJECT a fake page. The Scraper Agent must
// DETECT them and abort the run with a 'captcha_detected' verdict. There is
// no code to "solve" them.
const { info, warn } = require('../logger');

const MODES = [
  'dom_mutation',
  'selector_breakage',
  'timeout_spike',
  'partial_render',
  'captcha_simulation',
  'cf_challenge_sim',
  'partial_data',
];

function pickMode(rng = Math.random) {
  return MODES[Math.floor(rng() * MODES.length)];
}

const FAKE_CAPTCHA_HTML = `<!doctype html><html><head><title>Verify you are human</title></head>
<body style="font-family:sans-serif;text-align:center;padding:80px">
  <h1>Verify you are human</h1>
  <p>Please complete the challenge to continue.</p>
  <div data-captcha="simulation" id="captcha-widget" style="border:1px solid #ccc;padding:20px;display:inline-block">
    [ I am human checkbox simulation ]
  </div>
</body></html>`;

const FAKE_CF_HTML = `<!doctype html><html><head><title>Just a moment...</title></head>
<body style="background:#f7f7f7;text-align:center;padding:120px;font-family:sans-serif">
  <h1>Checking your browser</h1>
  <div data-cf-challenge="simulation">Please wait while we verify your connection.</div>
  <noscript>This is a SIMULATION — not a real challenge.</noscript>
</body></html>`;

function attach(page, { mode, intensity = 1 }) {
  const log = (event, ctx = {}) => warn('adversary_event', { mode, ...ctx, event });

  // Hook for downstream visibility
  page._adversary = { mode, intensity };

  switch (mode) {
    case 'dom_mutation':
      // After load, randomly replace KPI values with junk text via init script
      page.addInitScript(() => {
        window.__chaos_dom_mutation = true;
        document.addEventListener('DOMContentLoaded', () => {
          setTimeout(() => {
            const els = document.querySelectorAll('.kpi-value-new, [id^="kpi"]');
            els.forEach((el, i) => {
              if (i % 2 === 0) el.textContent = '???' + Math.random().toString(36).slice(2, 5);
            });
          }, 1500);
        });
      });
      log('attached');
      return;

    case 'selector_breakage':
      page.addInitScript(() => {
        window.__chaos_selector_breakage = true;
        document.addEventListener('DOMContentLoaded', () => {
          setTimeout(() => {
            // Strip #id attributes — forces fallback selectors to engage
            document.querySelectorAll('[id^="kpi"]').forEach(el => el.removeAttribute('id'));
          }, 800);
        });
      });
      log('attached');
      return;

    case 'timeout_spike':
      page.route('**/api/**', async (route) => {
        const delay = 8000 + Math.floor(Math.random() * 7000);
        log('delayed', { url: route.request().url(), delayMs: delay });
        await new Promise(r => setTimeout(r, delay * intensity));
        try { await route.continue(); } catch {}
      });
      log('attached');
      return;

    case 'partial_render':
      // Drop all CSS — layout breaks. waitFor on visual cues will fail.
      page.route(/\.css(\?.*)?$/, route => {
        log('css_blocked', { url: route.request().url() });
        return route.fulfill({ status: 200, body: '/* dropped by chaos */', contentType: 'text/css' });
      });
      log('attached');
      return;

    case 'captcha_simulation':
      // Replace the dashboard HTML with a fake captcha page. The scraper MUST
      // detect this and abort. We do not provide any code to bypass it.
      page.route(/\/dashboard(\?.*)?$/, route => {
        log('served_captcha_simulation');
        return route.fulfill({ status: 200, contentType: 'text/html', body: FAKE_CAPTCHA_HTML });
      });
      return;

    case 'cf_challenge_sim':
      page.route(/\/dashboard(\?.*)?$/, route => {
        log('served_cf_challenge_simulation');
        return route.fulfill({ status: 200, contentType: 'text/html', body: FAKE_CF_HTML });
      });
      return;

    case 'partial_data':
      page.route('**/api/stats**', async (route) => {
        const resp = await route.fetch();
        let body;
        try { body = await resp.json(); } catch { return route.continue(); }
        if (body && body.global) {
          // Strip 3 random KPIs to simulate degraded backend
          const keys = ['total_likes', 'total_comments', 'total_shares', 'total_followers'];
          const drop = keys.sort(() => Math.random() - 0.5).slice(0, 3);
          for (const k of drop) delete body.global[k];
          log('stripped_fields', { drop });
        }
        return route.fulfill({ status: resp.status(), contentType: 'application/json', body: JSON.stringify(body) });
      });
      return;
  }
}

// Detector: a captcha/CF page is a hard gate. The scraper calls this before extraction.
async function detectGate(page) {
  return await page.evaluate(() => {
    if (document.querySelector('[data-captcha], [data-cf-challenge]')) {
      return { gated: true, kind: 'simulated_challenge' };
    }
    const t = (document.title || '').toLowerCase();
    if (/just a moment|verify you are human|attention required/.test(t)) {
      return { gated: true, kind: 'title_match', title: document.title };
    }
    return { gated: false };
  });
}

module.exports = { attach, detectGate, MODES, pickMode };
