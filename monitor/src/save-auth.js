// One-time helper: opens a real browser, you log in via Google,
// then we save the cookie/storage state to data/auth.json so headless
// CI runs can reuse it.
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const TARGET = process.env.TARGET_URL || 'https://app.trackinglab.online/login';
const OUT = process.env.STORAGE_STATE || path.join(__dirname, '..', 'data', 'auth.json');

(async () => {
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  console.log(`Opening ${TARGET}. Log in via Google, wait until /dashboard loads, then come back here and press ENTER.`);
  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  await page.goto(TARGET);

  await new Promise(resolve => process.stdin.once('data', resolve));

  await context.storageState({ path: OUT });
  console.log(`✓ Saved auth state to ${OUT}`);
  console.log('You can now run `node src/scraper.js` headlessly.');
  console.log('In CI, paste the JSON content into the AUTH_STATE_JSON secret.');
  await browser.close();
  process.exit(0);
})();
