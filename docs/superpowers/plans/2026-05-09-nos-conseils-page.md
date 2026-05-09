# "Nos conseils" Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (this repo has no test framework; tasks use inline verification instead of TDD steps).

**Goal:** Add a new "Nos conseils" view in the dashboard that surfaces 7 actionable charts grouped into 3 insight sections (when to post / quality / content distribution).

**Architecture:** Single-page Flask app already serves dashboard via Jinja template + inline JS. The new view follows the exact same pattern as the existing `viewTable` charts: a `viewAdvice` `<section hidden>`, sidebar entry, dispatch in `load()`, and a `renderAdviceView()` async function fetching data and rendering Chart.js charts. The hourly heatmap (chart A) is implemented as a CSS grid (no extra plugin) to avoid net-new infra cost.

**Tech Stack:**
- Chart.js v4.4.1 (already loaded via CDN)
- Plain CSS grid for the heatmap (7×24 cells)
- Existing endpoints: `/api/stats`, `/api/evolution`, `/api/videos`, `/api/posts-per-day`

**Hard rules respected:**
- No new dependencies (CLAUDE.md: zero infra cost)
- No test suite (CLAUDE.md: don't fabricate one)
- Filter bar visible on advice view so charts respect dates
- All work in `templates/dashboard.html` + bump build version in `app.py`

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `templates/dashboard.html` | Modify | Sidebar entry, `viewAdvice` section, CSS for heatmap, JS render function, dispatch wiring, eyebrow label, build version |
| `app.py` | Modify | Bump `X-Build-Version` header to `2026-05-09-advice` |

No backend changes. No new API endpoints. The existing `/api/videos`, `/api/stats`, `/api/posts-per-day`, `/api/evolution` cover all chart needs.

---

## Task 1: View skeleton + sidebar wiring

**Files:**
- Modify: `templates/dashboard.html` — add sidebar entry under Analytics section, add empty `viewAdvice` section in main, wire dispatch in `load()`, add `'Advice'` to `views` array, update eyebrow label map, include `'advice'` in `showFilterBar` whitelist
- Modify: `app.py` — bump `X-Build-Version` to `2026-05-09-advice`

- [ ] **Step 1.1: Sidebar entry** (after `data-nav="table"` link, ~line 1226)

```html
<a class="sb-item" href="/dashboard?view=advice" data-nav="advice">
  <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7c.6.5.9 1.2.9 2V17h6.2v-.3c0-.8.3-1.5.9-2A7 7 0 0 0 12 2z"/></svg>
  Nos conseils
</a>
```

- [ ] **Step 1.2: View section skeleton** (after `<section id="viewTable">…</section>` close tag)

```html
<section id="viewAdvice" class="view" hidden>
  <h2 class="section-h2">Nos conseils</h2>
  <p class="section-sub" id="adviceSub">—</p>
  <!-- 3 groups of cards added in Tasks 2/3/4 -->
  <div id="adviceGroupWhen"></div>
  <div id="adviceGroupQuality"></div>
  <div id="adviceGroupContent"></div>
</section>
```

- [ ] **Step 1.3: Update `views` array + eyebrow** (search for `views = ['Dashboard', 'Accounts', 'Videos', 'Table']`)

```js
const views = ['Dashboard', 'Accounts', 'Videos', 'Table', 'Advice'];
```

And update the label map:

```js
const viewLbl = { accounts: 'Comptes', videos: 'Vidéos', table: 'Tableau détaillé', advice: 'Nos conseils' }[navView] || 'Tableau de bord';
```

- [ ] **Step 1.4: Filter bar visibility**

```js
const showFilterBar = !navView || navView === 'accounts' || navView === 'table' || navView === 'advice';
```

- [ ] **Step 1.5: Dispatch in `load()`** (search for `else if (navView === 'table')`)

```js
else if (navView === 'table') { renderTableView(accounts, stats); renderTableCharts(accounts, stats); }
else if (navView === 'advice') { renderAdviceView(accounts, stats); }
```

- [ ] **Step 1.6: Stub `renderAdviceView`** (after `renderTableCharts` function)

```js
async function renderAdviceView(accs, stats) {
  const sub = document.getElementById('adviceSub');
  if (sub) sub.textContent = 'Période : ' + (state.range != null
    ? (state.range === 1 ? 'Dernière 24 h' : `Derniers ${state.range} jours`)
    : `${state.date_from || ''} → ${state.date_to || ''}`);
  // Section bodies filled in Tasks 2/3/4
}
```

- [ ] **Step 1.7: Bump build version** in `app.py` and console log

In `app.py`: `response.headers.setdefault("X-Build-Version", "2026-05-09-advice")`
In `dashboard.html`: `console.log('%c[TL] dashboard build v=2026-05-09-advice', ...)`

- [ ] **Step 1.8: Verify** — Jinja template parses + JS syntax OK

```bash
.venv/bin/python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('templates')).get_template('dashboard.html'); print('OK')"
.venv/bin/python -c "import re; src=open('templates/dashboard.html').read(); m=re.search(r'<script>\s*(// .. Self-contained.*?)</script>', src, re.DOTALL); open('/tmp/_d.js','w').write(m.group(1))" && node --check /tmp/_d.js
```

- [ ] **Step 1.9: Commit**

```bash
git add app.py templates/dashboard.html
git commit -m "feat(advice): scaffold Nos conseils view + sidebar entry"
```

---

## Task 2: Section "Quand poster ?" (charts A + B)

**Files:** Modify `templates/dashboard.html` — fill `#adviceGroupWhen`, add CSS for heatmap, expand `renderAdviceView()` to render the 2 charts.

- [ ] **Step 2.1: HTML for the section** (replace `<div id="adviceGroupWhen"></div>`)

```html
<div id="adviceGroupWhen" class="advice-group">
  <div class="advice-group-head">
    <h3 class="advice-group-title">Quand poster ?</h3>
    <p class="advice-group-sub">Quels créneaux performent le mieux dans ton historique de publication.</p>
  </div>
  <div class="charts-grid">

    <div class="chart-card">
      <div class="chart-card-head">
        <div>
          <h3 class="chart-card-title">Heatmap des créneaux de publication</h3>
          <p class="chart-card-sub">Vues moyennes par vidéo · jour de la semaine × heure</p>
        </div>
        <span class="chart-card-badge" id="adviceHeatmapBadge">—</span>
      </div>
      <div class="chart-card-body">
        <div id="adviceHeatmap" class="heatmap"></div>
        <div class="chart-card-empty" id="adviceHeatmapEmpty" hidden>Pas assez de vidéos pour ce filtre.</div>
      </div>
    </div>

    <div class="chart-card">
      <div class="chart-card-head">
        <div>
          <h3 class="chart-card-title">Cadence de publication</h3>
          <p class="chart-card-sub">Nombre de vidéos publiées par jour</p>
        </div>
        <span class="chart-card-badge" id="adviceCadenceBadge">—</span>
      </div>
      <div class="chart-card-body">
        <canvas id="adviceCadence"></canvas>
        <div class="chart-card-empty" id="adviceCadenceEmpty" hidden>Pas de publications sur cette période.</div>
      </div>
    </div>

  </div>
</div>
```

- [ ] **Step 2.2: CSS for heatmap + group** (in main `<style>` block, after `.chart-card-empty[hidden]` rule)

```css
/* Advice page groups */
.advice-group { margin: 0 0 32px; }
.advice-group-head { margin: 0 0 14px; }
.advice-group-title { font-size: 16px; font-weight: 700; color: var(--text-1); margin: 0 0 4px; letter-spacing: -0.2px; }
.advice-group-sub   { font-size: 13px; color: var(--text-3); margin: 0; }

/* Day×Hour heatmap (CSS grid, no plugin) */
.heatmap {
  display: grid;
  grid-template-columns: 38px repeat(24, 1fr);
  grid-auto-rows: 22px;
  gap: 3px;
  align-content: center;
  font-size: 10px;
  color: var(--text-3);
}
.heatmap-corner, .heatmap-day-label, .heatmap-hour-label { display: flex; align-items: center; justify-content: center; }
.heatmap-day-label  { justify-content: flex-end; padding-right: 8px; font-weight: 600; color: var(--text-2); }
.heatmap-hour-label { font-size: 9px; }
.heatmap-cell {
  border-radius: 4px;
  background: #f5f5f7;
  position: relative;
  cursor: default;
}
.heatmap-cell[data-v="0"]  { background: #f5f5f7; }
.heatmap-cell[data-v="1"]  { background: #ffd6e7; }
.heatmap-cell[data-v="2"]  { background: #ffadce; }
.heatmap-cell[data-v="3"]  { background: #ff85b6; }
.heatmap-cell[data-v="4"]  { background: #FF69B4; }
.heatmap-cell[data-v="5"]  { background: #e54f9e; }
.heatmap-cell[title]:hover { outline: 2px solid var(--text-1); outline-offset: 1px; z-index: 1; }
.heatmap-legend {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: var(--text-3);
}
.heatmap-legend-scale { display: flex; gap: 2px; }
.heatmap-legend-scale span { width: 14px; height: 10px; border-radius: 2px; }
```

- [ ] **Step 2.3: Expand `renderAdviceView()` to fetch + render** (replace the stub)

```js
async function renderAdviceView(accs, stats) {
  const sub = document.getElementById('adviceSub');
  if (sub) sub.textContent = 'Période : ' + (state.range != null
    ? (state.range === 1 ? 'Dernière 24 h' : `Derniers ${state.range} jours`)
    : `${state.date_from || ''} → ${state.date_to || ''}`);
  if (typeof Chart === 'undefined') { console.warn('[TL] Chart.js missing'); return; }

  // Fetch the slow stuff in parallel.
  const [videos, ppd, evolution] = await Promise.all([
    fetch(buildVideosURL()).then(r => r.ok ? r.json() : []).catch(() => []),
    fetch(buildPostsPerDayURL()).then(r => r.ok ? r.json() : {}).catch(() => ({})),
    fetch(buildEvolutionURL()).then(r => r.ok ? r.json() : []).catch(() => []),
  ]);

  renderAdviceWhen(videos, ppd);
  renderAdviceQuality(stats, evolution);
  renderAdviceContent(videos, evolution);
}

function buildPostsPerDayURL() {
  const p = new URLSearchParams();
  if (state.project_id && state.project_id !== 'all') p.set('project_id', state.project_id);
  if (state.account && state.account !== 'all') p.set('account', state.account);
  if (state.date_from) p.set('date_from', state.date_from);
  if (state.date_to) p.set('date_to', state.date_to);
  p.set('competitor', isCompetitorScope ? 'true' : 'false');
  return '/api/posts-per-day?' + p.toString();
}
```

- [ ] **Step 2.4: Heatmap render function**

```js
const DAY_LABELS = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];

function renderAdviceWhen(videos, ppd) {
  // ── Heatmap (chart A): avg views per (day_of_week, hour) bucket ──
  const buckets = {};   // key "d|h" → { sum, count }
  (videos || []).forEach(v => {
    if (!v.create_time) return;
    const dt = new Date(v.create_time);
    if (isNaN(dt)) return;
    // JS getDay() returns 0=Sun..6=Sat. Convert to 0=Mon..6=Sun for FR week.
    const d = (dt.getDay() + 6) % 7;
    const h = dt.getHours();
    const k = `${d}|${h}`;
    if (!buckets[k]) buckets[k] = { sum: 0, count: 0 };
    buckets[k].sum   += v.views || 0;
    buckets[k].count += 1;
  });
  const cellAvg = {};
  let maxAvg = 0;
  Object.entries(buckets).forEach(([k, b]) => {
    const avg = b.count > 0 ? b.sum / b.count : 0;
    cellAvg[k] = avg;
    if (avg > maxAvg) maxAvg = avg;
  });
  const totalPosts = (videos || []).filter(v => v.create_time).length;

  const root = document.getElementById('adviceHeatmap');
  const empty = document.getElementById('adviceHeatmapEmpty');
  const badge = document.getElementById('adviceHeatmapBadge');
  if (totalPosts === 0 || maxAvg === 0) {
    root.innerHTML = '';
    empty.hidden = false;
    if (badge) badge.textContent = '—';
    return;
  }
  empty.hidden = true;
  if (badge) badge.textContent = `${totalPosts} vidéo${totalPosts > 1 ? 's' : ''}`;

  // Build the grid: header row (corner + 24 hour labels) + 7 day rows.
  const cells = [];
  cells.push('<div class="heatmap-corner"></div>');
  for (let h = 0; h < 24; h++) {
    cells.push(`<div class="heatmap-hour-label">${h % 3 === 0 ? h + 'h' : ''}</div>`);
  }
  for (let d = 0; d < 7; d++) {
    cells.push(`<div class="heatmap-day-label">${DAY_LABELS[d]}</div>`);
    for (let h = 0; h < 24; h++) {
      const a = cellAvg[`${d}|${h}`] || 0;
      // Bin into 0..5 by maxAvg so colors scale to actual data.
      const v = a === 0 ? 0 : Math.min(5, 1 + Math.floor((a / maxAvg) * 4.99));
      const count = buckets[`${d}|${h}`]?.count || 0;
      const tip = count > 0
        ? `${DAY_LABELS[d]} ${h}h — ${count} post${count > 1 ? 's' : ''} · ${fmtCompact(Math.round(a))} vues moyennes`
        : `${DAY_LABELS[d]} ${h}h — pas de post`;
      cells.push(`<div class="heatmap-cell" data-v="${v}" title="${tip}"></div>`);
    }
  }
  root.innerHTML = cells.join('') +
    `<div class="heatmap-legend" style="grid-column: 1 / -1; margin-top: 10px;">
       <span>Moins</span>
       <div class="heatmap-legend-scale">
         <span style="background:#f5f5f7"></span>
         <span style="background:#ffd6e7"></span>
         <span style="background:#ffadce"></span>
         <span style="background:#ff85b6"></span>
         <span style="background:#FF69B4"></span>
         <span style="background:#e54f9e"></span>
       </div>
       <span>Plus</span>
     </div>`;
}
```

- [ ] **Step 2.5: Cadence render function** (chart B, append to `renderAdviceWhen` or call after)

```js
function renderAdviceCadence(ppd) {
  // /api/posts-per-day returns { "YYYY-MM-DD": count, ... }
  const dates = Object.keys(ppd || {}).sort();
  const data = dates.map(d => ppd[d]);
  const total = data.reduce((s, v) => s + v, 0);
  const isEmpty = dates.length === 0 || total === 0;
  const badge = document.getElementById('adviceCadenceBadge');
  if (badge) badge.textContent = isEmpty ? '—' : `${total} post${total > 1 ? 's' : ''}`;
  setEmpty('adviceCadence', 'adviceCadenceEmpty', isEmpty);
  destroyChart('adviceCadence');
  if (isEmpty) return;
  chartInstances.adviceCadence = new Chart(document.getElementById('adviceCadence'), {
    type: 'bar',
    data: {
      labels: dates,
      datasets: [{
        label: 'Posts', data,
        backgroundColor: '#FF69B4',
        borderRadius: 4, borderSkipped: false, barPercentage: 0.9, categoryPercentage: 0.8,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { backgroundColor: '#111', titleColor: '#fff', bodyColor: '#fff', padding: 10, cornerRadius: 8,
          callbacks: { label: ctx => `${ctx.parsed.y} post${ctx.parsed.y > 1 ? 's' : ''}` } }
      },
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 }, color: '#9aa0a6', maxRotation: 0, autoSkipPadding: 14 } },
        y: { beginAtZero: true, grid: { color: '#f0f0f2' }, border: { display: false }, ticks: { stepSize: 1, font: { size: 10 }, color: '#9aa0a6' } }
      }
    }
  });
}
```

Then: extend `chartInstances` object init to include the new keys (do this once, in the existing init):

```js
const chartInstances = {
  followers: null, views: null, donut: null, top: null,
  adviceCadence: null, adviceRadar: null, adviceEngEvo: null, adviceComp: null, adviceDist: null, adviceAvg: null,
};
```

And update `renderAdviceWhen` signature to also call cadence:

```js
function renderAdviceWhen(videos, ppd) {
  // ... heatmap as above ...
  renderAdviceCadence(ppd);
}
```

- [ ] **Step 2.6: Verify + commit**

```bash
.venv/bin/python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('templates')).get_template('dashboard.html'); print('OK')"
.venv/bin/python -c "import re; src=open('templates/dashboard.html').read(); m=re.search(r'<script>\s*(// .. Self-contained.*?)</script>', src, re.DOTALL); open('/tmp/_d.js','w').write(m.group(1))" && node --check /tmp/_d.js
git add templates/dashboard.html
git commit -m "feat(advice): section Quand poster — heatmap horaire + cadence de publication"
```

---

## Task 3: Section "Quelle qualité ?" (charts C + D + E)

**Files:** Modify `templates/dashboard.html` — fill `#adviceGroupQuality`, add `renderAdviceQuality()`.

- [ ] **Step 3.1: HTML for the section** (replace `<div id="adviceGroupQuality"></div>`)

```html
<div id="adviceGroupQuality" class="advice-group">
  <div class="advice-group-head">
    <h3 class="advice-group-title">Quelle qualité d'audience ?</h3>
    <p class="advice-group-sub">Pas juste la portée — l'engagement réel que tu génères.</p>
  </div>
  <div class="charts-grid">

    <div class="chart-card">
      <div class="chart-card-head">
        <div>
          <h3 class="chart-card-title">Taux d'engagement par plateforme</h3>
          <p class="chart-card-sub">(likes + commentaires + partages) / vues, en %</p>
        </div>
        <span class="chart-card-badge" id="adviceRadarBadge">—</span>
      </div>
      <div class="chart-card-body">
        <canvas id="adviceRadar"></canvas>
        <div class="chart-card-empty" id="adviceRadarEmpty" hidden>Pas encore de vues sur cette période.</div>
      </div>
    </div>

    <div class="chart-card">
      <div class="chart-card-head">
        <div>
          <h3 class="chart-card-title">Évolution du taux d'engagement</h3>
          <p class="chart-card-sub">Engagement quotidien rapporté aux vues du jour</p>
        </div>
        <span class="chart-card-badge" id="adviceEngEvoBadge">—</span>
      </div>
      <div class="chart-card-body">
        <canvas id="adviceEngEvo"></canvas>
        <div class="chart-card-empty" id="adviceEngEvoEmpty" hidden>Pas encore d'historique pour cette période.</div>
      </div>
    </div>

    <div class="chart-card" style="grid-column: 1 / -1;">
      <div class="chart-card-head">
        <div>
          <h3 class="chart-card-title">Composition de l'engagement</h3>
          <p class="chart-card-sub">Likes vs commentaires vs partages vs sauvegardes, par plateforme</p>
        </div>
        <span class="chart-card-badge" id="adviceCompBadge">—</span>
      </div>
      <div class="chart-card-body">
        <canvas id="adviceComp"></canvas>
        <div class="chart-card-empty" id="adviceCompEmpty" hidden>Pas d'engagement à décomposer.</div>
      </div>
    </div>

  </div>
</div>
```

- [ ] **Step 3.2: `renderAdviceQuality()` function**

```js
function renderAdviceQuality(stats, evolution) {
  const perAccount = stats?.per_account || [];

  // ── Aggregate per platform: views, likes, comments, shares, saves ──
  const perPlat = {};
  perAccount.forEach(r => {
    const p = r.platform || 'tiktok';
    if (!perPlat[p]) perPlat[p] = { views: 0, likes: 0, comments: 0, shares: 0, saves: 0 };
    perPlat[p].views    += r.total_views    || 0;
    perPlat[p].likes    += r.total_likes    || 0;
    perPlat[p].comments += r.total_comments || 0;
    perPlat[p].shares   += r.total_shares   || 0;
    perPlat[p].saves    += r.total_saves    || 0;
  });
  const platforms = ['tiktok', 'instagram', 'youtube', 'linkedin'];
  const activePlatforms = platforms.filter(p => perPlat[p] && perPlat[p].views > 0);

  // ── Chart C: radar — engagement rate per platform ──
  {
    const labels = activePlatforms.map(p => PLATFORM_LABEL[p]);
    const data = activePlatforms.map(p => {
      const x = perPlat[p];
      const eng = x.likes + x.comments + x.shares;
      return x.views > 0 ? +(eng / x.views * 100).toFixed(2) : 0;
    });
    const isEmpty = activePlatforms.length === 0;
    const badge = document.getElementById('adviceRadarBadge');
    if (badge) badge.textContent = isEmpty ? '—'
      : `Moy ${(data.reduce((s,v)=>s+v,0)/data.length).toFixed(2).replace('.',',')} %`;
    setEmpty('adviceRadar', 'adviceRadarEmpty', isEmpty);
    destroyChart('adviceRadar');
    if (!isEmpty) {
      chartInstances.adviceRadar = new Chart(document.getElementById('adviceRadar'), {
        type: 'radar',
        data: {
          labels,
          datasets: [{
            label: 'Engagement (%)',
            data,
            backgroundColor: 'rgba(255,105,180,0.20)',
            borderColor: '#FF69B4',
            borderWidth: 2,
            pointBackgroundColor: activePlatforms.map(p => PLATFORM_COLOR[p]),
            pointRadius: 4,
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { backgroundColor: '#111', titleColor: '#fff', bodyColor: '#fff', padding: 10, cornerRadius: 8,
              callbacks: { label: ctx => `${ctx.parsed.r.toFixed(2).replace('.', ',')} %` } }
          },
          scales: {
            r: {
              beginAtZero: true,
              grid:        { color: '#eceef1' },
              angleLines:  { color: '#eceef1' },
              pointLabels: { font: { size: 11, weight: '600' }, color: '#33373d' },
              ticks:       { display: false, stepSize: undefined }
            }
          }
        }
      });
    }
  }

  // ── Chart D: line — engagement rate evolution ──
  // Compute per-date: sum delta_eng / sum delta_views across accounts.
  {
    const byAccount = {};
    (evolution || []).forEach(row => {
      if (!row.date) return;
      const k = `${row.account_username}|${row.platform || 'tiktok'}`;
      (byAccount[k] = byAccount[k] || []).push({
        date: row.date,
        views: row.views || 0,
        eng: (row.likes || 0) + (row.comments || 0) + (row.shares || 0),
      });
    });
    const sumByDate = {}; // date → { dv, de }
    Object.values(byAccount).forEach(series => {
      series.sort((a,b)=>a.date.localeCompare(b.date));
      for (let i = 1; i < series.length; i++) {
        const d = series[i].date;
        const dv = Math.max(0, series[i].views - series[i-1].views);
        const de = Math.max(0, series[i].eng   - series[i-1].eng);
        if (!sumByDate[d]) sumByDate[d] = { dv: 0, de: 0 };
        sumByDate[d].dv += dv;
        sumByDate[d].de += de;
      }
    });
    const dates = Object.keys(sumByDate).sort();
    const data = dates.map(d => sumByDate[d].dv > 0 ? +(sumByDate[d].de / sumByDate[d].dv * 100).toFixed(2) : 0);
    const isEmpty = dates.length === 0;
    const badge = document.getElementById('adviceEngEvoBadge');
    if (badge) {
      const valid = data.filter(v => v > 0);
      badge.textContent = valid.length === 0 ? '—'
        : `Moy ${(valid.reduce((s,v)=>s+v,0)/valid.length).toFixed(2).replace('.',',')} %`;
    }
    setEmpty('adviceEngEvo', 'adviceEngEvoEmpty', isEmpty);
    destroyChart('adviceEngEvo');
    if (!isEmpty) {
      chartInstances.adviceEngEvo = new Chart(document.getElementById('adviceEngEvo'), {
        type: 'line',
        data: { labels: dates, datasets: [{
          label: 'Engagement %', data,
          borderColor: '#FF69B4',
          backgroundColor: 'rgba(255,105,180,0.10)',
          fill: true, borderWidth: 2, tension: 0.35, pointRadius: 0, pointHoverRadius: 4,
        }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { backgroundColor: '#111', titleColor: '#fff', bodyColor: '#fff', padding: 10, cornerRadius: 8,
              callbacks: { label: ctx => `${ctx.parsed.y.toFixed(2).replace('.', ',')} %` } }
          },
          scales: {
            x: { grid: { display: false }, ticks: { font: { size: 10 }, color: '#9aa0a6', maxRotation: 0, autoSkipPadding: 18 } },
            y: { beginAtZero: true, grid: { color: '#f0f0f2' }, border: { display: false }, ticks: { font: { size: 10 }, color: '#9aa0a6', callback: v => v + '%' } }
          }
        }
      });
    }
  }

  // ── Chart E: stacked bar — engagement composition per platform ──
  {
    const isEmpty = activePlatforms.length === 0;
    const badge = document.getElementById('adviceCompBadge');
    if (badge) badge.textContent = isEmpty ? '—' : `${activePlatforms.length} plateforme${activePlatforms.length > 1 ? 's' : ''}`;
    setEmpty('adviceComp', 'adviceCompEmpty', isEmpty);
    destroyChart('adviceComp');
    if (!isEmpty) {
      const labels = activePlatforms.map(p => PLATFORM_LABEL[p]);
      const datasets = [
        { label: 'Likes',         key: 'likes',    color: '#FF69B4' },
        { label: 'Commentaires',  key: 'comments', color: '#7C3AED' },
        { label: 'Partages',      key: 'shares',   color: '#0A66C2' },
        { label: 'Sauvegardes',   key: 'saves',    color: '#10B981' },
      ].map(d => ({
        label: d.label,
        data: activePlatforms.map(p => perPlat[p][d.key] || 0),
        backgroundColor: d.color,
        stack: 'eng',
        borderRadius: 4,
        borderSkipped: false,
      }));
      chartInstances.adviceComp = new Chart(document.getElementById('adviceComp'), {
        type: 'bar',
        data: { labels, datasets },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, font: { size: 11 }, padding: 14, usePointStyle: true } },
            tooltip: { backgroundColor: '#111', titleColor: '#fff', bodyColor: '#fff', padding: 10, cornerRadius: 8,
              callbacks: { label: ctx => `${ctx.dataset.label}: ${fmtCompact(ctx.parsed.y)}` } }
          },
          scales: {
            x: { stacked: true, grid: { display: false }, ticks: { font: { size: 11 }, color: '#33373d' } },
            y: { stacked: true, beginAtZero: true, grid: { color: '#f0f0f2' }, border: { display: false }, ticks: { font: { size: 10 }, color: '#9aa0a6', callback: v => fmtCompact(v) } }
          }
        }
      });
    }
  }
}
```

- [ ] **Step 3.3: Verify + commit**

```bash
.venv/bin/python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('templates')).get_template('dashboard.html'); print('OK')"
.venv/bin/python -c "import re; src=open('templates/dashboard.html').read(); m=re.search(r'<script>\s*(// .. Self-contained.*?)</script>', src, re.DOTALL); open('/tmp/_d.js','w').write(m.group(1))" && node --check /tmp/_d.js
git add templates/dashboard.html
git commit -m "feat(advice): section Quelle qualite — radar engagement + evolution + composition"
```

---

## Task 4: Section "Quelles vidéos performent ?" (charts F + G)

**Files:** Modify `templates/dashboard.html` — fill `#adviceGroupContent`, add `renderAdviceContent()`.

- [ ] **Step 4.1: HTML for the section**

```html
<div id="adviceGroupContent" class="advice-group">
  <div class="advice-group-head">
    <h3 class="advice-group-title">Quelles vidéos performent ?</h3>
    <p class="advice-group-sub">La forme de tes performances — outliers viraux et moyenne réelle.</p>
  </div>
  <div class="charts-grid">

    <div class="chart-card">
      <div class="chart-card-head">
        <div>
          <h3 class="chart-card-title">Distribution des vues par vidéo</h3>
          <p class="chart-card-sub">Combien de vidéos atteignent chaque palier de vues</p>
        </div>
        <span class="chart-card-badge" id="adviceDistBadge">—</span>
      </div>
      <div class="chart-card-body">
        <canvas id="adviceDist"></canvas>
        <div class="chart-card-empty" id="adviceDistEmpty" hidden>Pas de vidéos pour ce filtre.</div>
      </div>
    </div>

    <div class="chart-card">
      <div class="chart-card-head">
        <div>
          <h3 class="chart-card-title">Vues moyennes par vidéo postée</h3>
          <p class="chart-card-sub">Tendance quotidienne · vues moyennes des nouvelles vidéos</p>
        </div>
        <span class="chart-card-badge" id="adviceAvgBadge">—</span>
      </div>
      <div class="chart-card-body">
        <canvas id="adviceAvg"></canvas>
        <div class="chart-card-empty" id="adviceAvgEmpty" hidden>Pas assez d'historique pour calculer la moyenne.</div>
      </div>
    </div>

  </div>
</div>
```

- [ ] **Step 4.2: `renderAdviceContent()` function**

```js
function renderAdviceContent(videos, evolution) {

  // ── Chart F: histogram — distribution of views per video ──
  // Log-spaced buckets: <1k, 1k–10k, 10k–100k, 100k–1M, 1M–10M, >10M.
  {
    const BUCKETS = [
      { label: '< 1k',       min: 0,        max: 1000 },
      { label: '1k – 10k',   min: 1000,     max: 10000 },
      { label: '10k – 100k', min: 10000,    max: 100000 },
      { label: '100k – 1M',  min: 100000,   max: 1000000 },
      { label: '1M – 10M',   min: 1000000,  max: 10000000 },
      { label: '> 10M',      min: 10000000, max: Infinity },
    ];
    const counts = BUCKETS.map(() => 0);
    let total = 0;
    (videos || []).forEach(v => {
      const x = v.views || 0;
      if (x === 0) return; // exclude IG photos with no view count exposed
      total += 1;
      for (let i = 0; i < BUCKETS.length; i++) {
        if (x >= BUCKETS[i].min && x < BUCKETS[i].max) { counts[i] += 1; break; }
      }
    });
    const isEmpty = total === 0;
    const badge = document.getElementById('adviceDistBadge');
    if (badge) badge.textContent = isEmpty ? '—' : `${total} vidéo${total > 1 ? 's' : ''}`;
    setEmpty('adviceDist', 'adviceDistEmpty', isEmpty);
    destroyChart('adviceDist');
    if (!isEmpty) {
      chartInstances.adviceDist = new Chart(document.getElementById('adviceDist'), {
        type: 'bar',
        data: {
          labels: BUCKETS.map(b => b.label),
          datasets: [{
            label: 'Vidéos', data: counts,
            backgroundColor: '#FF69B4',
            borderRadius: 6, borderSkipped: false,
          }]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { backgroundColor: '#111', titleColor: '#fff', bodyColor: '#fff', padding: 10, cornerRadius: 8,
              callbacks: {
                label: ctx => {
                  const n = ctx.parsed.y;
                  const pct = total > 0 ? (n / total * 100).toFixed(1).replace('.', ',') : '0';
                  return `${n} vidéo${n > 1 ? 's' : ''} (${pct}%)`;
                }
              } }
          },
          scales: {
            x: { grid: { display: false }, ticks: { font: { size: 10 }, color: '#9aa0a6' } },
            y: { beginAtZero: true, grid: { color: '#f0f0f2' }, border: { display: false }, ticks: { stepSize: 1, font: { size: 10 }, color: '#9aa0a6' } }
          }
        }
      });
    }
  }

  // ── Chart G: line — average views per video posted, by post date ──
  // Group videos by their publication day, take AVG(views).
  {
    const byDay = {}; // YYYY-MM-DD → { sum, count }
    (videos || []).forEach(v => {
      if (!v.create_time || !v.views) return;
      const d = new Date(v.create_time);
      if (isNaN(d)) return;
      const key = d.toISOString().slice(0, 10);
      if (!byDay[key]) byDay[key] = { sum: 0, count: 0 };
      byDay[key].sum   += v.views;
      byDay[key].count += 1;
    });
    const days = Object.keys(byDay).sort();
    const data = days.map(d => Math.round(byDay[d].sum / byDay[d].count));
    const isEmpty = days.length === 0;
    const badge = document.getElementById('adviceAvgBadge');
    if (badge) {
      const overall = data.length > 0 ? Math.round(data.reduce((s,v)=>s+v,0) / data.length) : 0;
      badge.textContent = isEmpty ? '—' : `Moy ${fmtCompact(overall)}`;
    }
    setEmpty('adviceAvg', 'adviceAvgEmpty', isEmpty);
    destroyChart('adviceAvg');
    if (!isEmpty) {
      chartInstances.adviceAvg = new Chart(document.getElementById('adviceAvg'), {
        type: 'line',
        data: { labels: days, datasets: [{
          label: 'Vues moyennes', data,
          borderColor: '#FF69B4',
          backgroundColor: 'rgba(255,105,180,0.10)',
          fill: true, borderWidth: 2, tension: 0.35, pointRadius: 0, pointHoverRadius: 4,
        }] },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: { backgroundColor: '#111', titleColor: '#fff', bodyColor: '#fff', padding: 10, cornerRadius: 8,
              callbacks: { label: ctx => `${fmtCompact(ctx.parsed.y)} vues moyennes` } }
          },
          scales: {
            x: { grid: { display: false }, ticks: { font: { size: 10 }, color: '#9aa0a6', maxRotation: 0, autoSkipPadding: 18 } },
            y: { beginAtZero: true, grid: { color: '#f0f0f2' }, border: { display: false }, ticks: { font: { size: 10 }, color: '#9aa0a6', callback: v => fmtCompact(v) } }
          }
        }
      });
    }
  }
}
```

- [ ] **Step 4.3: Final verify + commit + push**

```bash
.venv/bin/python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('templates')).get_template('dashboard.html'); print('OK')"
.venv/bin/python -c "import re; src=open('templates/dashboard.html').read(); m=re.search(r'<script>\s*(// .. Self-contained.*?)</script>', src, re.DOTALL); open('/tmp/_d.js','w').write(m.group(1))" && node --check /tmp/_d.js
git add templates/dashboard.html
git commit -m "feat(advice): section Quelles videos performent — distribution + vues moyennes"
git push origin main
```

---

## Spec Coverage Self-Review

| Spec item | Implemented in |
|---|---|
| New page "Nos conseils" with sidebar entry | Task 1 |
| Section "Quand poster ?" — chart A heatmap | Task 2.4 |
| Section "Quand poster ?" — chart B cadence | Task 2.5 |
| Section "Qualité" — chart C radar engagement % per platform | Task 3.2 |
| Section "Qualité" — chart D engagement % evolution | Task 3.2 |
| Section "Qualité" — chart E composition stacked | Task 3.2 |
| Section "Distribution" — chart F views histogram | Task 4.2 |
| Section "Distribution" — chart G avg views per posted video | Task 4.2 |
| Filter bar respected | Task 1.4 |
| No new infra (Chart.js already loaded, no plugin for heatmap) | All tasks |
| Build version bump | Task 1.7 |
| No test framework introduced | All tasks |
