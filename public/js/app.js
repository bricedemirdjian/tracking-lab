// Register datalabels plugin globally
Chart.register(ChartDataLabels);

// Dynamic color palette (assigned per user's accounts)
const PALETTE = ["#fe2c55", "#25f4ee", "#ffaa00", "#00d68f", "#7b61ff", "#ff6b6b",
                 "#e040fb", "#00bcd4", "#ff9800", "#8bc34a", "#f06292", "#4dd0e1"];

let accountColorMap = {};

function assignColors(accounts) {
    accountColorMap = {};
    accounts.forEach((account, i) => {
        accountColorMap[account.username] = PALETTE[i % PALETTE.length];
    });
}

function getAccountColor(username) {
    return accountColorMap[username] || "#888";
}

function getAccountColorIndex(username) {
    const keys = Object.keys(accountColorMap);
    const idx = keys.indexOf(username);
    return idx >= 0 ? idx + 1 : 1;
}

let state = {
    selectedAccount: "all",
    selectedProject: "all",
    projects: [],
    dateFrom: null,
    dateTo: null,
    sortBy: "create_time",
    sortOrder: "DESC",
    activeTab: "overview",
    charts: {},
    bestVideosLimit: 10,
    latestVideosLimit: 10,
    // Table state
    tableSearch: "",
    tablePage: 1,
    tablePerPage: 25,
    tableVideos: [],
    tableBestLimit: 5,
    tableLatestLimit: 5,
    tableLatestDateFrom: null,
    tableLatestDateTo: null,
    // Best videos date filter
    bestDateFrom: null,
    bestDateTo: null,
    // Latest videos date filter
    latestDateFrom: null,
    latestDateTo: null,
    // Project accounts modal
    editingProjectId: null,
    // Chart date filters (default: last 7 days)
    viewsChartDateFrom: (() => { const d = new Date(); d.setDate(d.getDate() - 7); return d.toLocaleDateString('en-CA'); })(),
    viewsChartDateTo: new Date().toLocaleDateString('en-CA'),
    postsChartDateFrom: (() => { const d = new Date(); d.setDate(d.getDate() - 7); return d.toLocaleDateString('en-CA'); })(),
    postsChartDateTo: new Date().toLocaleDateString('en-CA'),
};

// Platform icon helper
function platformIcon(platform, size = 14) {
    const svgs = {
        tiktok: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" style="vertical-align:middle"><path fill="#fff" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-2.88 2.5 2.89 2.89 0 0 1-2.89-2.89 2.89 2.89 0 0 1 2.89-2.89c.28 0 .54.04.79.1V9.01a6.27 6.27 0 0 0-.79-.05 6.34 6.34 0 0 0-6.34 6.34 6.34 6.34 0 0 0 6.34 6.34 6.34 6.34 0 0 0 6.34-6.34V8.75a8.18 8.18 0 0 0 4.76 1.52V6.84a4.83 4.83 0 0 1-1-.15z"/></svg>`,
        instagram: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" style="vertical-align:middle"><defs><linearGradient id="ig${size}" x1="0%" y1="100%" x2="100%" y2="0%"><stop offset="0%" style="stop-color:#feda75"/><stop offset="25%" style="stop-color:#fa7e1e"/><stop offset="50%" style="stop-color:#d62976"/><stop offset="75%" style="stop-color:#962fbf"/><stop offset="100%" style="stop-color:#4f5bd5"/></linearGradient></defs><rect x="2" y="2" width="20" height="20" rx="5" fill="url(#ig${size})"/><circle cx="12" cy="12" r="5" fill="none" stroke="#fff" stroke-width="1.5"/><circle cx="17.5" cy="6.5" r="1.2" fill="#fff"/></svg>`,
        snapchat: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" style="vertical-align:middle"><path fill="#FFFC00" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 14.19c-.12.27-.47.46-.73.52-.26.06-.54.09-.81.15-.18.04-.37.08-.5.2-.13.12-.2.3-.34.42a1.5 1.5 0 0 1-.87.35c-.38 0-.72-.18-1.08-.33-.5-.21-1.06-.44-1.65-.07a3.8 3.8 0 0 0-1.47 1.34c-.31.46-.67.76-1.13.76-.07 0-.14 0-.21-.02-.73-.15-.88-.93-1.31-1.23-.23-.16-.56-.2-.85-.25-.24-.04-.49-.08-.71-.17-.36-.15-.56-.42-.47-.72.06-.21.23-.36.4-.47.56-.34 1.17-.57 1.63-1.02.38-.37.6-.85.38-1.36-.14-.32-.4-.57-.65-.8-.34-.31-.7-.6-.93-1.01-.32-.55-.27-1.24.21-1.62.29-.23.66-.3 1.02-.27.08.01.16.02.24.04-.02-.46.01-.93.08-1.39.18-1.21.72-2.3 1.63-3.12A4.94 4.94 0 0 1 12 5.5c1.26 0 2.43.47 3.33 1.3.91.82 1.45 1.91 1.63 3.12.07.46.1.93.08 1.39.08-.02.16-.03.24-.04.36-.03.73.04 1.02.27.48.38.53 1.07.21 1.62-.23.41-.59.7-.93 1.01-.25.23-.51.48-.65.8-.22.51 0 .99.38 1.36.46.45 1.07.68 1.63 1.02.17.11.34.26.4.47z"/></svg>`,
        youtube: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" style="vertical-align:middle"><rect width="24" height="24" rx="4" fill="#FF0000"/><polygon points="10,7.5 16,12 10,16.5" fill="#fff"/></svg>`
    };
    const names = { tiktok: 'TikTok', instagram: 'Instagram', snapchat: 'Snapchat', youtube: 'YouTube Shorts' };
    const svg = svgs[platform] || svgs.tiktok;
    const name = names[platform] || 'TikTok';
    return `<span title="${name}" style="display:inline-flex;align-items:center">${svg}</span>`;
}

function platformShort(platform) {
    const shorts = { tiktok: 'TT', instagram: 'IG', snapchat: 'SC', youtube: 'YT' };
    return shorts[platform] || 'TT';
}

function accountLabel(username, platform) {
    return `@${username} (${platformShort(platform)})`;
}

// Utility functions
function formatNumber(num) {
    if (num === null || num === undefined) return "0";
    num = parseInt(num);
    return num.toLocaleString("fr-FR");
}

function formatCompact(num) {
    if (num === null || num === undefined || num === 0) return "";
    num = parseInt(num);
    if (num >= 1000000) return (num / 1000000).toFixed(1).replace(".0", "") + "M";
    if (num >= 1000) return (num / 1000).toFixed(1).replace(".0", "") + "K";
    return num.toString();
}

function formatDate(dateStr) {
    if (!dateStr) return "-";
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" });
}

function showStatus(message, type = "info") {
    const bar = document.getElementById("statusBar");
    bar.textContent = message;
    bar.className = "status-bar visible " + type;
    setTimeout(() => { bar.className = "status-bar"; }, 3000);
}

// API calls with 401 handling
async function fetchAPI(endpoint, params = {}) {
    const url = new URL(endpoint, window.location.origin);
    Object.entries(params).forEach(([k, v]) => {
        if (v !== null && v !== undefined && v !== "") url.searchParams.set(k, v);
    });
    const res = await fetch(url);
    if (res.status === 401) {
        window.location.href = "/login";
        return null;
    }
    return res.json();
}

// Data loading
async function loadDashboard() {
    const params = {
        account: state.selectedAccount,
        date_from: state.dateFrom,
        date_to: state.dateTo,
        project_id: state.selectedProject,
    };

    try {
        const tableBestLimitVal = state.tableBestLimit === 'all' ? 9999 : state.tableBestLimit;
        const tableLatestLimitVal = state.tableLatestLimit === 'all' ? 9999 : state.tableLatestLimit;
        const [accounts, stats, evolution, bestVideos, latestVideos, postsPerDay, tableBest, tableLatest] = await Promise.all([
            fetchAPI("/api/accounts", { project_id: state.selectedProject }),
            fetchAPI("/api/stats", params),
            // Evolution chart: filter by account + optional chart date filter
            fetchAPI("/api/evolution", { account: state.selectedAccount, project_id: state.selectedProject, date_from: state.viewsChartDateFrom, date_to: state.viewsChartDateTo }),
            // Best videos: filter by account + optional dedicated date filter
            fetchAPI("/api/best-videos", {
                account: state.selectedAccount,
                limit: state.bestVideosLimit,
                date_from: state.bestDateFrom,
                date_to: state.bestDateTo,
                project_id: state.selectedProject,
            }),
            // Latest videos: filter by account + optional dedicated date filter
            fetchAPI("/api/latest-videos", {
                account: state.selectedAccount,
                limit: state.latestVideosLimit,
                date_from: state.latestDateFrom,
                date_to: state.latestDateTo,
                project_id: state.selectedProject,
            }),
            fetchAPI("/api/posts-per-day", { account: state.selectedAccount, project_id: state.selectedProject, date_from: state.postsChartDateFrom, date_to: state.postsChartDateTo }),
            // Table tab: best videos (same API)
            fetchAPI("/api/best-videos", {
                account: state.selectedAccount,
                limit: tableBestLimitVal,
                project_id: state.selectedProject,
            }),
            // Table tab: latest videos (same API)
            fetchAPI("/api/latest-videos", {
                account: state.selectedAccount,
                limit: tableLatestLimitVal,
                date_from: state.tableLatestDateFrom,
                date_to: state.tableLatestDateTo,
                project_id: state.selectedProject,
            }),
        ]);

        if (!accounts) return; // Redirected to login

        // Assign dynamic colors
        assignColors(accounts);

        // Populate filter dropdown dynamically
        populateAccountFilter(accounts);

        // Update accounts badge
        const badge = document.getElementById("accountsBadge");
        if (badge) badge.textContent = accounts.length + " comptes";

        renderKPIs(stats.global);
        renderAccountCards(accounts, stats.per_account);
        renderBestVideos(bestVideos);
        renderLatestVideos(latestVideos);
        renderCharts(stats, evolution);
        renderPostsPerDayChart(postsPerDay);
        // Table tab: use same API data
        renderVideoCards(tableBest, "tableBestGrid", "tableBestBadge", "Top ");
        renderVideoCards(tableLatest, "tableLatestGrid", "tableLatestBadge", "");
    } catch (err) {
        console.error("Error loading dashboard:", err);
        showStatus("Erreur de chargement des donnees", "error");
    }
}

function populateAccountFilter(accounts) {
    const filterSelect = document.getElementById("filterAccount");
    const currentValue = filterSelect.value;
    filterSelect.innerHTML = '<option value="all">Tous les comptes</option>';
    accounts.forEach(account => {
        const opt = document.createElement("option");
        opt.value = account.username;
        opt.textContent = "@" + account.username;
        filterSelect.appendChild(opt);
    });
    filterSelect.value = currentValue || "all";
}

// Render KPIs
function renderKPIs(global) {
    document.getElementById("kpiVideos").textContent = formatNumber(global.total_videos);
    document.getElementById("kpiViews").textContent = formatNumber(global.total_views);
    document.getElementById("kpiLikes").textContent = formatNumber(global.total_likes);
    document.getElementById("kpiComments").textContent = formatNumber(global.total_comments);
    document.getElementById("kpiShares").textContent = formatNumber(global.total_shares);
    document.getElementById("kpiEngagement").textContent = global.engagement_rate.toFixed(2) + "%";
}

// Render Account Cards
function renderAccountCards(accounts, perAccount) {
    const container = document.getElementById("accountCards");
    const statsMap = {};
    perAccount.forEach(s => {
        const key = s.account_username + ":" + (s.platform || "tiktok");
        statsMap[key] = s;
    });

    if (accounts.length === 0) {
        container.innerHTML = `
            <div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-muted)">
                <p style="font-size:32px;margin-bottom:12px">&#128269;</p>
                <p>Aucun compte suivi. Cliquez sur <strong>"Gerer les comptes"</strong> pour ajouter des comptes TikTok.</p>
            </div>
        `;
        return;
    }

    let html = "";

    accounts.forEach(account => {
        const s = statsMap[account.username + ":" + (account.platform || "tiktok")] || {};
        const color = getAccountColor(account.username);
        const initial = account.username.charAt(0).toUpperCase();
        const displayName = account.display_name || account.username;

        const totalEng = (s.total_likes || 0) + (s.total_comments || 0) + (s.total_shares || 0) + (s.total_saves || 0);
        const engRate = (s.total_views || 0) > 0 ? ((totalEng / s.total_views) * 100).toFixed(2) : "0.00";
        const avgViews = (s.total_videos || 0) > 0 ? Math.round((s.total_views || 0) / s.total_videos) : 0;
        const nbVideos = s.total_videos || 0;
        const pIcon = platformIcon(account.platform);

        html += `
            <div class="account-card ${state.selectedAccount === account.username ? 'active' : ''}"
                 onclick="selectAccount('${account.username}')">
                <div class="account-header">
                    <div class="avatar" style="background:${color}">${initial}</div>
                    <div class="account-info">
                        <div class="account-name">${pIcon} ${displayName}</div>
                        <div class="account-handle">@${account.username}</div>
                    </div>
                    <div class="account-contenus-badge">${nbVideos} contenu${nbVideos > 1 ? 's' : ''}</div>
                </div>
                <div class="account-metrics">
                    <div class="account-metric metric-views">
                        <div class="metric-value">${formatCompact(s.total_views || 0) || "0"}</div>
                        <div class="metric-label">vues</div>
                    </div>
                    <div class="account-metric metric-likes">
                        <div class="metric-value">${formatCompact(s.total_likes || 0) || "0"}</div>
                        <div class="metric-label">likes</div>
                    </div>
                    <div class="account-metric metric-eng">
                        <div class="metric-value">${engRate}%</div>
                        <div class="metric-label">engage.</div>
                    </div>
                </div>
                <div class="account-secondary">
                    <span>&#128172; <span class="sec-value">${formatNumber(s.total_comments || 0)}</span></span>
                    <span class="sep">&#183;</span>
                    <span>&#128257; <span class="sec-value">${formatNumber(s.total_shares || 0)}</span></span>
                    <span class="sep">&#183;</span>
                    <span>&#128200; <span class="sec-value">${formatCompact(avgViews) || "0"}</span>/vid</span>
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

// Render video cards (shared between best & latest)
function renderVideoCards(videos, containerId, badgeId, badgePrefix) {
    const container = document.getElementById(containerId);
    const badge = document.getElementById(badgeId);
    if (!container) return;

    if (badge) badge.textContent = badgePrefix + videos.length;

    if (videos.length === 0) {
        container.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-muted)">Aucune video trouvee</div>`;
        return;
    }

    container.innerHTML = videos.map((v, i) => {
        const color = getAccountColor(v.account_username);
        const totalEng = (v.likes || 0) + (v.comments || 0) + (v.shares || 0) + (v.saves || 0);
        const engRate = v.views > 0 ? ((totalEng / v.views) * 100).toFixed(2) : "0.00";
        const desc = (v.description || "").length > 60 ? v.description.substring(0, 60) + "..." : (v.description || "");
        const thumb = v.thumbnail_url || "";
        // Build video URL: use stored url, or construct from platform + video_id
        let url = v.video_url || "";
        if (!url && v.video_id && v.platform) {
            if (v.platform === "tiktok") url = `https://www.tiktok.com/@${v.account_username}/video/${v.video_id}`;
            else if (v.platform === "instagram") url = `https://www.instagram.com/reel/${v.video_id}/`;
            else if (v.platform === "youtube") url = `https://www.youtube.com/shorts/${v.video_id}`;
        }
        if (!url) url = "#";
        const rankHtml = badgePrefix === "Top " ? `<div class="vcard-rank" style="${i < 3 ? 'background:var(--warning);color:#000' : ''}">${i < 3 ? ['&#129351;','&#129352;','&#129353;'][i] : '#' + (i + 1)}</div>` : "";

        // Use <img> tag with onerror fallback for reliable thumbnail display
        const thumbHtml = thumb
            ? `<img src="${thumb}" alt="" class="vcard-thumb-img" onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">`
            : "";
        const placeholderStyle = thumb ? 'style="display:none"' : 'style="display:flex"';

        return `
            <div class="video-card">
                <a href="${url}" target="_blank" class="vcard-thumb">
                    ${thumbHtml}
                    <div class="vcard-thumb-placeholder" ${placeholderStyle}>
                        <span>&#127909;</span>
                    </div>
                    ${rankHtml}
                    <div class="vcard-views">&#9654; ${formatCompact(v.views || 0) || "0"}</div>
                </a>
                <div class="vcard-body">
                    <div class="vcard-account" style="color:${color}">@${v.account_username}</div>
                    <div class="vcard-date">${formatDate(v.create_time)}</div>
                    <div class="vcard-desc" title="${(v.description || '').replace(/"/g, '&quot;')}">${desc}</div>
                    <div class="vcard-stats">
                        <span>&#10084; ${formatCompact(v.likes || 0) || "0"}</span>
                        <span>&#128172; ${formatCompact(v.comments || 0) || "0"}</span>
                        <span style="color:var(--tiktok-blue);font-weight:700">${engRate}%</span>
                    </div>
                </div>
            </div>
        `;
    }).join("");
}

function renderBestVideos(videos) {
    renderVideoCards(videos, "bestVideosGrid", "bestVideosBadge", "Top ");
}

function renderLatestVideos(videos) {
    renderVideoCards(videos, "latestVideosGrid", "latestVideosBadge", "");
}

// Table tab: best & latest in grid (not scrollable)
function setTableBestLimit(n) {
    state.tableBestLimit = n;
    document.querySelectorAll("#tableBestLimit .limit-btn").forEach(b => b.classList.toggle("active", b.dataset.limit === String(n)));
    loadDashboard();
}
function setTableLatestLimit(n) {
    state.tableLatestLimit = n;
    document.querySelectorAll("#tableLatestLimit .limit-btn").forEach(b => b.classList.toggle("active", b.dataset.limit === String(n)));
    loadDashboard();
}
function onTableLatestDateFilter() {
    state.tableLatestDateFrom = document.getElementById("tableLatestDateFrom").value || null;
    state.tableLatestDateTo = document.getElementById("tableLatestDateTo").value || null;
    loadDashboard();
}
function clearTableLatestDateFilter() {
    state.tableLatestDateFrom = null;
    state.tableLatestDateTo = null;
    document.getElementById("tableLatestDateFrom").value = "";
    document.getElementById("tableLatestDateTo").value = "";
    loadDashboard();
}
function renderTableBestVideos(videos) {
    const limit = state.tableBestLimit === 'all' ? videos.length : state.tableBestLimit;
    renderVideoCards(videos.slice(0, limit), "tableBestGrid", "tableBestBadge", "Top ");
}
function renderTableLatestVideos(videos) {
    let filtered = videos;
    if (state.tableLatestDateFrom) {
        filtered = filtered.filter(v => String(v.create_time).slice(0, 10) >= state.tableLatestDateFrom);
    }
    if (state.tableLatestDateTo) {
        filtered = filtered.filter(v => String(v.create_time).slice(0, 10) <= state.tableLatestDateTo);
    }
    const limit = state.tableLatestLimit === 'all' ? filtered.length : state.tableLatestLimit;
    renderVideoCards(filtered.slice(0, limit), "tableLatestGrid", "tableLatestBadge", "");
}

function setBestVideosLimit(n) {
    state.bestVideosLimit = n;
    document.querySelectorAll("#bestVideosLimit .limit-btn").forEach(b => b.classList.toggle("active", parseInt(b.dataset.limit) === n));
    loadDashboard();
}

function onBestDateFilter() {
    state.bestDateFrom = document.getElementById("bestDateFrom").value || null;
    state.bestDateTo = document.getElementById("bestDateTo").value || null;
    loadDashboard();
}

function clearBestDateFilter() {
    state.bestDateFrom = null;
    state.bestDateTo = null;
    document.getElementById("bestDateFrom").value = "";
    document.getElementById("bestDateTo").value = "";
    loadDashboard();
}

function setLatestVideosLimit(n) {
    state.latestVideosLimit = n;
    document.querySelectorAll("#latestVideosLimit .limit-btn").forEach(b => b.classList.toggle("active", parseInt(b.dataset.limit) === n));
    loadDashboard();
}

function onLatestDateFilter() {
    state.latestDateFrom = document.getElementById("latestDateFrom").value || null;
    state.latestDateTo = document.getElementById("latestDateTo").value || null;
    loadDashboard();
}

function clearLatestDateFilter() {
    state.latestDateFrom = null;
    state.latestDateTo = null;
    document.getElementById("latestDateFrom").value = "";
    document.getElementById("latestDateTo").value = "";
    loadDashboard();
}

// Chart date filters
function onViewsChartDateFilter() {
    state.viewsChartDateFrom = document.getElementById("viewsChartDateFrom").value || null;
    state.viewsChartDateTo = document.getElementById("viewsChartDateTo").value || null;
    loadDashboard();
}
function clearViewsChartDateFilter() {
    state.viewsChartDateFrom = null;
    state.viewsChartDateTo = null;
    document.getElementById("viewsChartDateFrom").value = "";
    document.getElementById("viewsChartDateTo").value = "";
    loadDashboard();
}
function onPostsChartDateFilter() {
    state.postsChartDateFrom = document.getElementById("postsChartDateFrom").value || null;
    state.postsChartDateTo = document.getElementById("postsChartDateTo").value || null;
    loadDashboard();
}
function clearPostsChartDateFilter() {
    state.postsChartDateFrom = null;
    state.postsChartDateTo = null;
    document.getElementById("postsChartDateFrom").value = "";
    document.getElementById("postsChartDateTo").value = "";
    loadDashboard();
}

// Custom HTML tooltip for charts
function getOrCreateTooltipEl(chart) {
    let el = chart.canvas.parentNode.querySelector('.chart-tooltip');
    if (!el) {
        el = document.createElement('div');
        el.className = 'chart-tooltip';
        chart.canvas.parentNode.style.position = 'relative';
        chart.canvas.parentNode.appendChild(el);
    }
    return el;
}

function customTooltipHandler(context, unit) {
    const { chart, tooltip } = context;
    const el = getOrCreateTooltipEl(chart);

    if (tooltip.opacity === 0) {
        el.style.opacity = '0';
        return;
    }

    // Build content
    const title = tooltip.title[0] || '';
    const items = tooltip.dataPoints || [];
    // Filter items with value > 0 and sort descending
    const filtered = items.filter(i => i.raw > 0).sort((a, b) => b.raw - a.raw);

    let html = `<div class="chart-tooltip-title">${title}</div>`;
    let total = 0;
    filtered.forEach(item => {
        const color = item.dataset.backgroundColor || item.dataset.borderColor || '#888';
        const label = item.dataset.label || '';
        const value = item.raw || 0;
        total += value;
        const formatted = unit === 'vues' ? '+' + formatNumber(value) + ' vues' : value + ' post' + (value > 1 ? 's' : '');
        html += `<div class="chart-tooltip-row">
            <div class="chart-tooltip-color" style="background:${color}"></div>
            <span class="chart-tooltip-label">${label}</span>
            <span class="chart-tooltip-value">${formatted}</span>
        </div>`;
    });
    const totalFormatted = unit === 'vues' ? '+' + formatNumber(total) + ' vues' : total + ' post' + (total > 1 ? 's' : '');
    html += `<div class="chart-tooltip-total">Total: ${totalFormatted}</div>`;

    el.innerHTML = html;
    el.style.opacity = '1';

    // Position
    const pos = chart.canvas.getBoundingClientRect();
    const left = tooltip.caretX;
    const top = tooltip.caretY;
    // Keep tooltip within chart bounds
    const elRect = el.getBoundingClientRect();
    const maxLeft = chart.canvas.offsetWidth - elRect.width - 10;
    el.style.left = Math.min(Math.max(10, left), maxLeft) + 'px';
    el.style.top = Math.max(10, top - elRect.height / 2) + 'px';
}

// Charts
function renderCharts(stats, evolution) {
    renderViewsChart(evolution);
    renderEngagementPieChart(stats.global);
    renderAccountComparisonChart(stats.per_account);
    renderTimelineChart(evolution);
    renderEngagementByAccountChart(stats.per_account);
    renderLikesPerAccountChart(stats.per_account);
    renderContentPerAccountChart(stats.per_account);
    renderAvgViewsChart(stats.per_account);
    renderSharesPerAccountChart(stats.per_account);
    renderCommentsPerAccountChart(stats.per_account);
}

function renderPostsPerDayChart(postsPerDay) {
    const container = document.getElementById("postsPerDayTable");
    if (!container || !postsPerDay) return;

    const dates = Object.keys(postsPerDay).sort();
    if (dates.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted)">Aucune publication</div>';
        return;
    }

    // Collect all account keys
    const accountKeys = new Set();
    dates.forEach(d => Object.keys(postsPerDay[d]).forEach(k => accountKeys.add(k)));
    const accounts = Array.from(accountKeys);

    // Total card
    const totalPerAccount = {};
    dates.forEach(date => {
        accounts.forEach(key => {
            totalPerAccount[key] = (totalPerAccount[key] || 0) + (postsPerDay[date][key] || 0);
        });
    });
    const totalRows = accounts
        .map(key => {
            const [username, platform] = key.split(":");
            return { username, platform: platform || "tiktok", value: totalPerAccount[key] || 0, color: getAccountColor(username) };
        })
        .filter(r => r.value > 0)
        .sort((a, b) => b.value - a.value);
    const grandTotal = totalRows.reduce((s, r) => s + r.value, 0);

    const totalCard = buildDayCard(
        state.postsChartDateFrom && state.postsChartDateTo ? 'Total (' + formatDate(state.postsChartDateFrom) + ' - ' + formatDate(state.postsChartDateTo) + ')' : dates.length > 1 ? 'Total (' + formatDate(dates[0]) + ' - ' + formatDate(dates[dates.length - 1]) + ')' : 'Total',
        totalRows, grandTotal, 'posts', true
    );

    // Generate all days in range (including days with 0 posts)
    let allDates = dates;
    if (state.postsChartDateFrom && state.postsChartDateTo) {
        allDates = [];
        const start = new Date(state.postsChartDateFrom);
        const end = new Date(state.postsChartDateTo);
        for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
            allDates.push(d.toLocaleDateString('en-CA'));
        }
    }

    // Day cards (most recent first)
    const dayCards = allDates.slice().reverse().map(date => {
        const dayData = postsPerDay[date] || {};
        const rows = accounts
            .map(key => {
                const [username, platform] = key.split(":");
                return { username, platform: platform || "tiktok", value: dayData[key] || 0, color: getAccountColor(username) };
            })
            .filter(r => r.value > 0)
            .sort((a, b) => b.value - a.value);
        const total = rows.reduce((s, r) => s + r.value, 0);
        return buildDayCard(formatDate(date), rows, total, 'posts');
    }).join('');

    container.innerHTML = totalCard + dayCards;
}

function renderViewsChart(evolution) {
    const container = document.getElementById("viewsPerDayTable");
    if (!container) return;

    // Build cumulative data per account+platform per date
    const dateMap = {};
    const accountKeys = new Set();
    const accountMeta = {};
    evolution.forEach(d => {
        const key = d.account_username + ":" + (d.platform || "tiktok");
        accountKeys.add(key);
        accountMeta[key] = { username: d.account_username, platform: d.platform || "tiktok" };
        if (!dateMap[d.date]) dateMap[d.date] = {};
        dateMap[d.date][key] = (dateMap[d.date][key] || 0) + (d.views || 0);
    });

    const dates = Object.keys(dateMap).sort();
    const accounts = Array.from(accountKeys);

    // Compute daily DELTAS
    const deltaMap = {};
    dates.forEach((date, i) => {
        deltaMap[date] = {};
        accounts.forEach(key => {
            const current = dateMap[date][key] || 0;
            const prev = i > 0 ? (dateMap[dates[i - 1]][key] || 0) : 0;
            deltaMap[date][key] = Math.max(0, current - prev);
        });
    });

    const showDelta = dates.length > 1;
    const dataSource = showDelta ? deltaMap : dateMap;
    const displayDates = showDelta ? dates.slice(1) : dates;

    if (displayDates.length === 0) {
        container.innerHTML = '<div style="text-align:center;padding:30px;color:var(--text-muted)">Pas assez de donnees</div>';
        return;
    }

    // Build a "Total" card that sums all days
    const totalPerAccount = {};
    displayDates.forEach(date => {
        accounts.forEach(key => {
            totalPerAccount[key] = (totalPerAccount[key] || 0) + (dataSource[date][key] || 0);
        });
    });
    const totalRows = accounts
        .map(key => ({ username: accountMeta[key].username, platform: accountMeta[key].platform, value: totalPerAccount[key] || 0, color: getAccountColor(accountMeta[key].username) }))
        .filter(r => r.value > 0)
        .sort((a, b) => b.value - a.value);
    const grandTotal = totalRows.reduce((s, r) => s + r.value, 0);

    // Generate all days in range (including days with 0 views)
    let allViewDates = displayDates;
    if (state.viewsChartDateFrom && state.viewsChartDateTo) {
        allViewDates = [];
        const start = new Date(state.viewsChartDateFrom);
        const end = new Date(state.viewsChartDateTo);
        for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
            const ds = d.toLocaleDateString('en-CA');
            if (displayDates.includes(ds)) allViewDates.push(ds);
            else allViewDates.push(ds); // include even if no data
        }
    }

    // Build per-day cards (most recent first)
    const dayCards = allViewDates.slice().reverse().map(date => {
        const rows = accounts
            .map(key => ({ username: accountMeta[key].username, platform: accountMeta[key].platform, value: (dataSource[date] && dataSource[date][key]) || 0, color: getAccountColor(accountMeta[key].username) }))
            .filter(r => r.value > 0)
            .sort((a, b) => b.value - a.value);
        const total = rows.reduce((s, r) => s + r.value, 0);
        return buildDayCard(formatDate(date), rows, total, 'vues');
    }).join('');

    // Total card first, then day cards
    const totalCard = buildDayCard(
        state.viewsChartDateFrom && state.viewsChartDateTo ? 'Total (' + formatDate(state.viewsChartDateFrom) + ' - ' + formatDate(state.viewsChartDateTo) + ')' : displayDates.length > 1 ? 'Total (' + formatDate(displayDates[0]) + ' - ' + formatDate(displayDates[displayDates.length - 1]) + ')' : 'Total',
        totalRows, grandTotal, 'vues', true
    );

    container.innerHTML = totalCard + dayCards;
}

function buildDayCard(title, rows, total, unit = 'vues', isTotal = false) {
    const rowsHtml = rows.map(r => {
        const platformLabel = r.platform === 'tiktok' ? 'TT' : r.platform === 'instagram' ? 'IG' : r.platform === 'youtube' ? 'YT' : r.platform.toUpperCase();
        const valueText = unit === 'vues' ? '+' + formatNumber(r.value) + ' vues' : r.value + ' post' + (r.value > 1 ? 's' : '');
        return `<div class="posts-day-row">
            <div class="posts-day-color" style="background:${r.color}"></div>
            <span class="posts-day-label">@${r.username} (${platformLabel})</span>
            <span class="posts-day-value">${valueText}</span>
        </div>`;
    }).join('');

    const totalText = unit === 'vues' ? 'Total: +' + formatNumber(total) + ' vues' : 'Total: ' + total + ' post' + (total > 1 ? 's' : '');
    const style = isTotal ? 'border: 2px solid var(--accent); background: var(--bg-card);' : '';
    return `<div class="posts-day-card" style="${style}">
        <div class="posts-day-date">${title}</div>
        ${rowsHtml}
        <div class="posts-day-total">${totalText}</div>
    </div>`;
}

function renderEngagementPieChart(global) {
    const ctx = document.getElementById("engagementChart");
    if (!ctx) return;
    if (state.charts.engagement) state.charts.engagement.destroy();
    state.charts.engagement = new Chart(ctx, {
        type: "doughnut",
        data: {
            labels: ["Likes", "Commentaires", "Partages"],
            datasets: [{ data: [global.total_likes, global.total_comments, global.total_shares], backgroundColor: ["#fe2c55", "#25f4ee", "#ffaa00"], borderColor: "#1a1a2e", borderWidth: 3 }],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { position: "bottom", labels: { color: "#8888aa", font: { size: 11 }, padding: 16 } },
                tooltip: { backgroundColor: "#1a1a2e", titleColor: "#f0f0f5", bodyColor: "#8888aa", borderColor: "#2a2a40", borderWidth: 1, callbacks: { label: ctx => ctx.label + ": " + formatNumber(ctx.raw) } },
                datalabels: { color: "#fff", font: { size: 12, weight: "bold" }, formatter: v => formatCompact(v), display: ctx => ctx.dataset.data[ctx.dataIndex] > 0 },
            },
            cutout: "65%",
        },
    });
}

function renderAccountComparisonChart(perAccount) {
    const ctx = document.getElementById("comparisonChart");
    if (!ctx) return;
    if (state.charts.comparison) state.charts.comparison.destroy();
    const usernames = perAccount.map(a => accountLabel(a.account_username, a.platform));
    state.charts.comparison = new Chart(ctx, {
        type: "bar",
        data: {
            labels: usernames,
            datasets: [
                { label: "Vues", data: perAccount.map(a => a.total_views), backgroundColor: "#fe2c55cc", borderRadius: 6, barPercentage: 0.6 },
                { label: "Likes", data: perAccount.map(a => a.total_likes), backgroundColor: "#25f4eecc", borderRadius: 6, barPercentage: 0.6 },
                { label: "Partages", data: perAccount.map(a => a.total_shares), backgroundColor: "#ffaa00cc", borderRadius: 6, barPercentage: 0.6 },
            ],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: "#8888aa", font: { size: 11 } } },
                tooltip: { backgroundColor: "#1a1a2e", titleColor: "#f0f0f5", bodyColor: "#8888aa", borderColor: "#2a2a40", borderWidth: 1, callbacks: { label: ctx => ctx.dataset.label + ": " + formatNumber(ctx.raw) } },
                datalabels: { color: "#f0f0f5", font: { size: 10, weight: "bold" }, anchor: "end", align: "top", offset: 2, formatter: v => formatCompact(v), display: ctx => ctx.dataset.data[ctx.dataIndex] > 0 },
            },
            scales: {
                x: { grid: { display: false }, ticks: { color: "#8888aa", font: { size: 11 } } },
                y: { grid: { color: "#1a1a2e" }, ticks: { color: "#555570", callback: v => formatNumber(v) } },
            },
        },
    });
}

function renderEngagementByAccountChart(perAccount) {
    const ctx = document.getElementById("engagementByAccountChart");
    if (!ctx) return;
    if (state.charts.engByAccount) state.charts.engByAccount.destroy();
    const usernames = perAccount.map(a => accountLabel(a.account_username, a.platform));
    const colors = perAccount.map(a => getAccountColor(a.account_username));
    const engRates = perAccount.map(a => {
        const total = (a.total_likes || 0) + (a.total_comments || 0) + (a.total_shares || 0) + (a.total_saves || 0);
        return a.total_views > 0 ? ((total / a.total_views) * 100) : 0;
    });
    state.charts.engByAccount = new Chart(ctx, {
        type: "bar",
        data: { labels: usernames, datasets: [{ label: "Taux d'engagement (%)", data: engRates, backgroundColor: colors.map(c => c + "cc"), borderColor: colors, borderWidth: 2, borderRadius: 8, barPercentage: 0.6 }] },
        options: {
            responsive: true, maintainAspectRatio: false, indexAxis: "y",
            plugins: {
                legend: { display: false },
                tooltip: { backgroundColor: "#1a1a2e", titleColor: "#f0f0f5", bodyColor: "#8888aa", borderColor: "#2a2a40", borderWidth: 1, callbacks: { label: ctx => ctx.raw.toFixed(2) + "% engagement" } },
                datalabels: { color: "#fff", font: { size: 11, weight: "bold" }, anchor: "end", align: "right", offset: 4, formatter: v => v.toFixed(2) + "%", display: ctx => ctx.dataset.data[ctx.dataIndex] > 0 },
            },
            scales: {
                x: { grid: { color: "#1a1a2e" }, ticks: { color: "#555570", callback: v => v + "%" } },
                y: { grid: { display: false }, ticks: { color: "#8888aa", font: { size: 12, weight: "bold" } } },
            },
        },
    });
}

function simpleBarChart(canvasId, chartKey, labels, data, colors, label, tooltipSuffix) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    if (state.charts[chartKey]) state.charts[chartKey].destroy();
    state.charts[chartKey] = new Chart(ctx, {
        type: "bar",
        data: { labels, datasets: [{ label, data, backgroundColor: colors.map(c => c + "cc"), borderColor: colors, borderWidth: 2, borderRadius: 8, barPercentage: 0.6 }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { backgroundColor: "#1a1a2e", titleColor: "#f0f0f5", bodyColor: "#8888aa", borderColor: "#2a2a40", borderWidth: 1, callbacks: { label: ctx => formatNumber(ctx.raw) + " " + tooltipSuffix } },
                datalabels: { color: "#f0f0f5", font: { size: 11, weight: "bold" }, anchor: "end", align: "top", offset: 2, formatter: v => formatCompact(v), display: ctx => ctx.dataset.data[ctx.dataIndex] > 0 },
            },
            scales: {
                x: { grid: { display: false }, ticks: { color: "#8888aa", font: { size: 11 } } },
                y: { grid: { color: "#1a1a2e" }, ticks: { color: "#555570", callback: v => formatNumber(v) } },
            },
        },
    });
}

function renderLikesPerAccountChart(perAccount) {
    simpleBarChart("likesPerAccountChart", "likesPA", perAccount.map(a => accountLabel(a.account_username, a.platform)), perAccount.map(a => a.total_likes), perAccount.map(a => getAccountColor(a.account_username)), "Likes", "likes");
}

function renderContentPerAccountChart(perAccount) {
    const ctx = document.getElementById("contentPerAccountChart");
    if (!ctx) return;
    if (state.charts.contentPA) state.charts.contentPA.destroy();
    const usernames = perAccount.map(a => accountLabel(a.account_username, a.platform));
    const colors = perAccount.map(a => getAccountColor(a.account_username));
    state.charts.contentPA = new Chart(ctx, {
        type: "doughnut",
        data: { labels: usernames, datasets: [{ data: perAccount.map(a => a.total_videos), backgroundColor: colors.map(c => c + "cc"), borderColor: "#1a1a2e", borderWidth: 3 }] },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { position: "bottom", labels: { color: "#8888aa", font: { size: 11 }, padding: 12 } },
                tooltip: { backgroundColor: "#1a1a2e", titleColor: "#f0f0f5", bodyColor: "#8888aa", borderColor: "#2a2a40", borderWidth: 1, callbacks: { label: ctx => ctx.label + ": " + ctx.raw + " videos" } },
                datalabels: { color: "#fff", font: { size: 13, weight: "bold" }, formatter: v => v > 0 ? v : "", display: ctx => ctx.dataset.data[ctx.dataIndex] > 0 },
            },
            cutout: "55%",
        },
    });
}

function renderAvgViewsChart(perAccount) {
    simpleBarChart("avgViewsChart", "avgViewsPA", perAccount.map(a => accountLabel(a.account_username, a.platform)), perAccount.map(a => a.total_videos > 0 ? Math.round(a.total_views / a.total_videos) : 0), perAccount.map(a => getAccountColor(a.account_username)), "Moy. vues/video", "vues/video");
}

function renderSharesPerAccountChart(perAccount) {
    simpleBarChart("sharesPerAccountChart", "sharesPA", perAccount.map(a => accountLabel(a.account_username, a.platform)), perAccount.map(a => a.total_shares), perAccount.map(a => getAccountColor(a.account_username)), "Partages", "partages");
}

function renderCommentsPerAccountChart(perAccount) {
    simpleBarChart("commentsPerAccountChart", "commentsPA", perAccount.map(a => accountLabel(a.account_username, a.platform)), perAccount.map(a => a.total_comments), perAccount.map(a => getAccountColor(a.account_username)), "Commentaires", "commentaires");
}

function renderTimelineChart(evolution) {
    const ctx = document.getElementById("timelineChart");
    if (!ctx) return;
    if (state.charts.timeline) state.charts.timeline.destroy();

    // Aggregate snapshot data per date (sum across accounts)
    const dateMap = {};
    evolution.forEach(d => {
        if (!dateMap[d.date]) dateMap[d.date] = { likes: 0, comments: 0, shares: 0 };
        dateMap[d.date].likes += d.likes;
        dateMap[d.date].comments += d.comments;
        dateMap[d.date].shares += d.shares;
    });
    const dates = Object.keys(dateMap).sort();

    state.charts.timeline = new Chart(ctx, {
        type: "bar",
        data: {
            labels: dates.map(d => formatDate(d)),
            datasets: [
                { label: "Likes", data: dates.map(d => dateMap[d].likes), backgroundColor: "#fe2c55cc", borderRadius: 4 },
                { label: "Commentaires", data: dates.map(d => dateMap[d].comments), backgroundColor: "#25f4eecc", borderRadius: 4 },
                { label: "Partages", data: dates.map(d => dateMap[d].shares), backgroundColor: "#ffaa00cc", borderRadius: 4 },
            ],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: { labels: { color: "#8888aa", font: { size: 11 } } },
                tooltip: { backgroundColor: "#1a1a2e", titleColor: "#f0f0f5", bodyColor: "#8888aa", borderColor: "#2a2a40", borderWidth: 1, callbacks: { label: ctx => ctx.dataset.label + ": " + formatNumber(ctx.raw) } },
                datalabels: { color: "#fff", font: { size: 9, weight: "bold" }, anchor: "center", align: "center", formatter: v => formatCompact(v), display: ctx => ctx.dataset.data[ctx.dataIndex] > 500 },
            },
            scales: {
                x: { stacked: true, grid: { display: false }, ticks: { color: "#555570", font: { size: 10 } } },
                y: { stacked: true, grid: { color: "#1a1a2e" }, ticks: { color: "#555570", callback: v => formatCompact(v) } },
            },
        },
    });
}

// Render Table with search, pagination and engagement bars
function renderTable(videos) {
    state.tableVideos = videos;
    state.tablePage = 1;
    renderTablePage();
}

function getFilteredTableVideos() {
    const q = state.tableSearch.toLowerCase().trim();
    if (!q) return state.tableVideos;
    return state.tableVideos.filter(v =>
        (v.account_username || "").toLowerCase().includes(q) ||
        (v.description || "").toLowerCase().includes(q) ||
        (v.video_id || "").toLowerCase().includes(q)
    );
}

function renderTablePage() {
    const tbody = document.getElementById("videosTableBody");
    const countEl = document.getElementById("videoCount");
    const paginationEl = document.getElementById("tablePagination");

    const filtered = getFilteredTableVideos();
    const total = filtered.length;
    const perPage = state.tablePerPage;
    const totalPages = Math.max(1, Math.ceil(total / perPage));

    // Clamp current page
    if (state.tablePage > totalPages) state.tablePage = totalPages;
    if (state.tablePage < 1) state.tablePage = 1;

    const startIdx = (state.tablePage - 1) * perPage;
    const pageVideos = filtered.slice(startIdx, startIdx + perPage);

    // Update count badge
    if (state.tableSearch) {
        countEl.textContent = total + " / " + state.tableVideos.length + " videos";
    } else {
        countEl.textContent = total + " videos";
    }

    // Find max engagement rate for bar scaling
    const maxEng = Math.max(1, ...filtered.map(v => {
        const eng = (v.likes || 0) + (v.comments || 0) + (v.shares || 0) + (v.saves || 0);
        return v.views > 0 ? (eng / v.views) * 100 : 0;
    }));

    if (total === 0) {
        if (state.tableSearch) {
            tbody.innerHTML = `<tr><td colspan="9"><div class="table-empty-search"><div class="empty-icon">&#128269;</div><p>Aucun resultat pour "${state.tableSearch}"</p></div></td></tr>`;
        } else {
            tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:40px; color:var(--text-muted)">Aucune video trouvee. Lancez un scraping ou importez un CSV.</td></tr>`;
        }
        renderTablePagination(totalPages);
        return;
    }

    tbody.innerHTML = pageVideos.map((v, idx) => {
        const rowNum = startIdx + idx + 1;
        const color = getAccountColor(v.account_username);
        const totalEngagement = (v.likes || 0) + (v.comments || 0) + (v.shares || 0) + (v.saves || 0);
        const engRate = v.views > 0 ? ((totalEngagement / v.views) * 100) : 0;
        const engRateStr = engRate.toFixed(2);
        const desc = (v.description || "").length > 60 ? v.description.substring(0, 60) + "..." : (v.description || "Sans description");
        const thumb = v.thumbnail_url || "";
        // Build video URL: use stored url, or construct from platform + video_id
        let url = v.video_url || "";
        if (!url && v.video_id && v.platform) {
            if (v.platform === "tiktok") url = `https://www.tiktok.com/@${v.account_username}/video/${v.video_id}`;
            else if (v.platform === "instagram") url = `https://www.instagram.com/reel/${v.video_id}/`;
            else if (v.platform === "youtube") url = `https://www.youtube.com/shorts/${v.video_id}`;
        }
        if (!url) url = "#";

        // Engagement color class
        const engClass = engRate >= 5 ? "eng-high" : engRate >= 2 ? "eng-mid" : "eng-low";
        const engBarColor = engRate >= 5 ? "var(--success)" : engRate >= 2 ? "var(--warning)" : "var(--tiktok-pink)";
        const engBarWidth = Math.min(100, (engRate / Math.min(maxEng, 15)) * 100);

        return `
            <tr>
                <td><span class="table-row-num">${rowNum}</span></td>
                <td>
                    <div class="table-video-cell">
                        <a href="${url}" target="_blank" class="table-thumb">
                            ${thumb ? `<img src="${thumb}" alt="" onerror="this.style.display='none'">` : ""}
                            <span class="table-thumb-ph">&#127909;</span>
                        </a>
                        <div class="table-video-meta">
                            <div class="table-account" style="color:${color}">@${v.account_username}</div>
                            <div class="table-desc" title="${(v.description || '').replace(/"/g, '&quot;')}">${desc}</div>
                        </div>
                    </div>
                </td>
                <td>${formatDate(v.create_time)}</td>
                <td class="text-right"><span class="metric">${formatNumber(v.views)}</span></td>
                <td class="text-right"><span class="metric">${formatNumber(v.likes)}</span></td>
                <td class="text-right">
                    <div class="table-eng-cell">
                        <span class="table-eng-value ${engClass}">${engRateStr}%</span>
                        <div class="table-eng-bar">
                            <div class="table-eng-bar-fill" style="width:${engBarWidth}%;background:${engBarColor}"></div>
                        </div>
                    </div>
                </td>
                <td class="text-right"><span class="metric">${formatNumber(v.comments)}</span></td>
                <td class="text-right"><span class="metric">${formatNumber(v.shares)}</span></td>
                <td class="text-right"><span class="metric">${formatNumber(v.saves || 0)}</span></td>
                <td><a href="${url}" target="_blank" class="table-link" title="Voir sur TikTok">&#x2197;</a></td>
            </tr>
        `;
    }).join("");

    renderTablePagination(totalPages);
}

function renderTablePagination(totalPages) {
    const el = document.getElementById("tablePagination");
    if (!el) return;

    const filtered = getFilteredTableVideos();
    const total = filtered.length;
    const startIdx = (state.tablePage - 1) * state.tablePerPage;
    const endIdx = Math.min(startIdx + state.tablePerPage, total);

    let pagesHtml = "";
    // Show max 5 page buttons
    let startPage = Math.max(1, state.tablePage - 2);
    let endPage = Math.min(totalPages, startPage + 4);
    if (endPage - startPage < 4) startPage = Math.max(1, endPage - 4);

    for (let i = startPage; i <= endPage; i++) {
        pagesHtml += `<button class="table-page-btn ${i === state.tablePage ? 'active' : ''}" onclick="goToTablePage(${i})">${i}</button>`;
    }

    el.innerHTML = `
        <span class="table-pagination-info">${total > 0 ? (startIdx + 1) + '-' + endIdx + ' sur ' + total : '0 videos'}</span>
        <button class="table-page-btn" onclick="goToTablePage(${state.tablePage - 1})" ${state.tablePage <= 1 ? 'disabled' : ''}>&#8249;</button>
        ${pagesHtml}
        <button class="table-page-btn" onclick="goToTablePage(${state.tablePage + 1})" ${state.tablePage >= totalPages ? 'disabled' : ''}>&#8250;</button>
    `;
}

function goToTablePage(page) {
    const filtered = getFilteredTableVideos();
    const totalPages = Math.max(1, Math.ceil(filtered.length / state.tablePerPage));
    if (page < 1 || page > totalPages) return;
    state.tablePage = page;
    renderTablePage();
    // Scroll to top of table
    const tableEl = document.querySelector(".table-container");
    if (tableEl) tableEl.scrollIntoView({ behavior: "smooth", block: "start" });
}

function onTableSearch(value) {
    state.tableSearch = value;
    state.tablePage = 1;
    renderTablePage();
}

function onTablePerPageChange(value) {
    state.tablePerPage = parseInt(value);
    state.tablePage = 1;
    renderTablePage();
}

// Event handlers
function selectAccount(username) {
    state.selectedAccount = username;
    document.getElementById("filterAccount").value = username;
    loadDashboard();
}

function switchTab(tabName) {
    state.activeTab = tabName;
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.tab === tabName);
    });
    document.querySelectorAll(".tab-content").forEach(el => {
        el.classList.toggle("active", el.id === "tab-" + tabName);
    });
    if (tabName === "overview" || tabName === "charts") {
        setTimeout(() => {
            Object.values(state.charts).forEach(c => c && c.resize && c.resize());
        }, 100);
    }
}

function sortTable(column) {
    if (state.sortBy === column) {
        state.sortOrder = state.sortOrder === "DESC" ? "ASC" : "DESC";
    } else {
        state.sortBy = column;
        state.sortOrder = "DESC";
    }
    document.querySelectorAll("thead th").forEach(th => {
        th.classList.remove("sorted");
        const arrow = th.querySelector(".sort-arrow");
        if (arrow) arrow.textContent = "";
    });
    const activeHeader = document.querySelector(`th[data-sort="${column}"]`);
    if (activeHeader) {
        activeHeader.classList.add("sorted");
        const arrow = activeHeader.querySelector(".sort-arrow");
        if (arrow) arrow.textContent = state.sortOrder === "DESC" ? " \u25BC" : " \u25B2";
    }
    loadDashboard();
}

let scrapePollingTimer = null;
let lastCompletedCount = 0;

async function startScraping() {
    const btn = document.getElementById("scrapeBtn");
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;display:inline-block"></span> Scraping...';
    showStatus("Scraping en cours... Les donnees s'actualisent en temps reel.", "info");
    try {
        const res = await fetch("/api/scrape", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
        const data = await res.json();
        if (data.status === "already_running") {
            showStatus("Scraping deja en cours...", "info");
        }
        lastCompletedCount = 0;
        startScrapePolling();
    } catch (err) {
        showStatus("Erreur lors du lancement du scraping", "error");
        btn.disabled = false;
        btn.innerHTML = 'Scraper les donnees';
    }
}

function startScrapePolling() {
    stopScrapePolling();
    scrapePollingTimer = setInterval(async () => {
        try {
            const status = await fetchAPI("/api/scrape-status");
            if (!status) return;

            const btn = document.getElementById("scrapeBtn");

            // Update button with progress
            if (status.active) {
                const progress = status.completed + "/" + status.total;
                const current = status.current_account ? " (@" + status.current_account + ")" : "";
                btn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;display:inline-block"></span> ' + progress + current;
            }

            // New account completed -> refresh dashboard
            if (status.completed > lastCompletedCount) {
                lastCompletedCount = status.completed;
                const lastDone = status.done_accounts[status.done_accounts.length - 1];
                if (lastDone) {
                    showStatus("@" + lastDone.username + " : " + lastDone.videos + " videos scrapees", "success");
                }
                loadDashboard();
            }

            // Scraping finished
            if (!status.active && status.total > 0) {
                stopScrapePolling();
                btn.disabled = false;
                btn.innerHTML = 'Scraper les donnees';
                loadDashboard();
                const errors = status.errors ? status.errors.length : 0;
                if (errors > 0) {
                    showStatus("Scraping termine ! " + status.completed + "/" + status.total + " comptes (" + errors + " erreurs)", "error");
                } else {
                    showStatus("Scraping termine ! " + status.completed + "/" + status.total + " comptes scrapes", "success");
                }
            }
        } catch (e) {
            console.error("Scrape polling error:", e);
        }
    }, 2000);
}

function stopScrapePolling() {
    if (scrapePollingTimer) {
        clearInterval(scrapePollingTimer);
        scrapePollingTimer = null;
    }
}

function openImportModal() {
    document.getElementById("importModal").classList.remove("hidden");
}

function closeImportModal() {
    document.getElementById("importModal").classList.add("hidden");
}

async function handleImport() {
    const input = document.getElementById("csvFileInput");
    if (!input.files.length) {
        showStatus("Selectionnez un fichier CSV", "error");
        return;
    }
    const formData = new FormData();
    formData.append("file", input.files[0]);
    try {
        const res = await fetch("/api/import-csv", { method: "POST", body: formData });
        const data = await res.json();
        if (data.error) {
            showStatus("Erreur: " + data.error, "error");
        } else {
            showStatus(`${data.imported} videos importees avec succes !`, "success");
            closeImportModal();
            loadDashboard();
        }
    } catch (err) {
        showStatus("Erreur d'importation", "error");
    }
}

function exportCSV() {
    const params = new URLSearchParams();
    if (state.selectedAccount !== "all") params.set("account", state.selectedAccount);
    if (state.dateFrom) params.set("date_from", state.dateFrom);
    if (state.dateTo) params.set("date_to", state.dateTo);
    if (state.selectedProject !== "all") params.set("project_id", state.selectedProject);
    window.location.href = "/api/export-csv?" + params.toString();
}

// Account management
function openAccountsModal() {
    document.getElementById("accountsModal").classList.remove("hidden");
    loadAccountsList();
}

function closeAccountsModal() {
    document.getElementById("accountsModal").classList.add("hidden");
}

async function loadAccountsList() {
    const accounts = await fetchAPI("/api/accounts");
    if (!accounts) return;
    const list = document.getElementById("accountsList");
    if (accounts.length === 0) {
        list.innerHTML = '<p style="text-align:center;color:var(--text-muted);padding:16px">Aucun compte suivi</p>';
        return;
    }
    list.innerHTML = accounts.map(a => {
        const pIcon = platformIcon(a.platform);
        return `
        <div class="account-list-item">
            <span class="account-list-name">${pIcon} @${a.username}</span>
            <button class="btn-remove" onclick="removeAccount('${a.username}')">Supprimer</button>
        </div>
    `}).join("");
}

async function addAccount() {
    const input = document.getElementById("newAccountInput");
    const platformSelect = document.getElementById("newAccountPlatform");
    const username = input.value.trim().replace("@", "");
    const platform = platformSelect ? platformSelect.value : "tiktok";
    if (!username) return;
    try {
        const res = await fetch("/api/accounts/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, platform })
        });
        if (res.status === 401) { window.location.href = "/login"; return; }
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            showStatus(data.error || "Erreur lors de l'ajout", "error");
            return;
        }
        input.value = "";
        loadAccountsList();
        loadDashboard();
        showStatus(`Compte @${username} ajoute ! Scraping en cours...`, "success");
        // Poll for new data every 5s until account has videos
        let pollCount = 0;
        const addPoll = setInterval(async () => {
            pollCount++;
            loadDashboard();
            loadAccountsList();
            if (pollCount >= 24) clearInterval(addPoll); // stop after 2 min
        }, 5000);
    } catch (err) {
        showStatus("Erreur lors de l'ajout", "error");
    }
}

async function removeAccount(username) {
    if (!confirm(`Supprimer @${username} et toutes ses donnees ?`)) return;
    try {
        const res = await fetch("/api/accounts/remove", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username })
        });
        if (res.status === 401) { window.location.href = "/login"; return; }
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            showStatus(data.error || "Erreur lors de la suppression", "error");
            return;
        }
        loadAccountsList();
        loadDashboard();
        showStatus(`Compte @${username} supprime`, "success");
    } catch (err) {
        showStatus("Erreur lors de la suppression", "error");
    }
}

// ==================== Project management ====================

function onProjectFilter(value) {
    state.selectedProject = value;
    state.selectedAccount = "all";
    document.getElementById("filterAccount").value = "all";
    loadDashboard();
}

async function loadProjects() {
    const projects = await fetchAPI("/api/projects");
    if (!projects) return;
    state.projects = projects;
    const select = document.getElementById("filterProject");
    if (!select) return;
    const current = select.value;
    select.innerHTML = '<option value="all">Tous les projets</option>';
    projects.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = p.name;
        select.appendChild(opt);
    });
    select.value = current || "all";
}

function openProjectsModal() {
    document.getElementById("projectsModal").classList.remove("hidden");
    loadProjectsList();
}

function closeProjectsModal() {
    document.getElementById("projectsModal").classList.add("hidden");
}

async function loadProjectsList() {
    const projects = await fetchAPI("/api/projects");
    if (!projects) return;
    const list = document.getElementById("projectsList");
    if (projects.length === 0) {
        list.innerHTML = '<p style="text-align:center;color:var(--text-muted);padding:16px">Aucun projet</p>';
        return;
    }
    list.innerHTML = projects.map(p => `
        <div class="account-list-item" style="gap:8px">
            <span class="account-list-name" style="flex:1">${p.name}</span>
            <button class="btn btn-secondary btn-sm" onclick="openProjectAccountsEditor(${p.id}, '${p.name.replace(/'/g, "\\'")}')">Comptes</button>
            <button class="btn btn-secondary btn-sm" onclick="promptRenameProject(${p.id}, '${p.name.replace(/'/g, "\\'")}')">Renommer</button>
            <button class="btn-remove" onclick="deleteProjectConfirm(${p.id}, '${p.name.replace(/'/g, "\\'")}')">Supprimer</button>
        </div>
    `).join("");
}

async function createNewProject() {
    const input = document.getElementById("newProjectInput");
    const name = input.value.trim();
    if (!name) return;
    try {
        const res = await fetch("/api/projects", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name })
        });
        if (res.status === 401) { window.location.href = "/login"; return; }
        const data = await res.json();
        if (data.error) { showStatus(data.error, "error"); return; }
        input.value = "";
        loadProjectsList();
        loadProjects();
        showStatus(`Projet "${name}" cree !`, "success");
    } catch (err) {
        showStatus("Erreur lors de la creation du projet", "error");
    }
}

async function promptRenameProject(projectId, currentName) {
    const newName = prompt("Nouveau nom du projet :", currentName);
    if (!newName || newName.trim() === "" || newName === currentName) return;
    try {
        await fetch(`/api/projects/${projectId}/rename`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: newName.trim() })
        });
        loadProjectsList();
        loadProjects();
        showStatus(`Projet renomme en "${newName.trim()}"`, "success");
    } catch (err) {
        showStatus("Erreur lors du renommage", "error");
    }
}

async function deleteProjectConfirm(projectId, name) {
    if (!confirm(`Supprimer le projet "${name}" ? Les comptes ne seront pas supprimes.`)) return;
    try {
        await fetch(`/api/projects/${projectId}/delete`, {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });
        loadProjectsList();
        loadProjects();
        if (state.selectedProject == projectId) {
            state.selectedProject = "all";
            document.getElementById("filterProject").value = "all";
            loadDashboard();
        }
        showStatus(`Projet "${name}" supprime`, "success");
    } catch (err) {
        showStatus("Erreur lors de la suppression", "error");
    }
}

async function openProjectAccountsEditor(projectId, projectName) {
    state.editingProjectId = projectId;
    document.getElementById("projectAccountsTitle").textContent = `Comptes du projet : ${projectName}`;
    document.getElementById("projectAccountsModal").classList.remove("hidden");

    // Fetch all accounts and project's accounts
    const [allAccounts, projectAccounts] = await Promise.all([
        fetchAPI("/api/accounts"),
        fetchAPI(`/api/projects/${projectId}/accounts`)
    ]);
    if (!allAccounts) return;

    const projectAccountIds = new Set((projectAccounts || []).map(a => a.id));
    const list = document.getElementById("projectAccountsList");

    list.innerHTML = allAccounts.map(a => {
        const checked = projectAccountIds.has(a.id) ? "checked" : "";
        const pIcon = platformIcon(a.platform);
        return `
        <div class="account-list-item" style="cursor:pointer" onclick="this.querySelector('input').click()">
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;flex:1" onclick="event.stopPropagation()">
                <input type="checkbox" value="${a.id}" ${checked} style="width:18px;height:18px">
                <span>${pIcon} @${a.username}</span>
            </label>
        </div>
    `}).join("");
}

function closeProjectAccountsModal() {
    document.getElementById("projectAccountsModal").classList.add("hidden");
}

async function saveCurrentProjectAccounts() {
    const checkboxes = document.querySelectorAll("#projectAccountsList input[type=checkbox]:checked");
    const accountIds = Array.from(checkboxes).map(cb => parseInt(cb.value));
    try {
        await fetch(`/api/projects/${state.editingProjectId}/accounts`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ account_ids: accountIds })
        });
        closeProjectAccountsModal();
        showStatus("Comptes du projet mis a jour !", "success");
        loadDashboard();
    } catch (err) {
        showStatus("Erreur lors de la sauvegarde", "error");
    }
}

// Auto-refresh removed — scraping is manual or on page load

// Init
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("filterAccount").addEventListener("change", (e) => {
        state.selectedAccount = e.target.value;
        loadDashboard();
    });
    document.getElementById("filterDateFrom").addEventListener("change", (e) => {
        state.dateFrom = e.target.value || null;
        loadDashboard();
    });
    document.getElementById("filterDateTo").addEventListener("change", (e) => {
        state.dateTo = e.target.value || null;
        loadDashboard();
    });
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });
    document.querySelectorAll("th[data-sort]").forEach(th => {
        th.addEventListener("click", () => sortTable(th.dataset.sort));
    });
    // Pre-fill chart date filters with default values
    if (state.viewsChartDateFrom) document.getElementById("viewsChartDateFrom").value = state.viewsChartDateFrom;
    if (state.viewsChartDateTo) document.getElementById("viewsChartDateTo").value = state.viewsChartDateTo;
    if (state.postsChartDateFrom) document.getElementById("postsChartDateFrom").value = state.postsChartDateFrom;
    if (state.postsChartDateTo) document.getElementById("postsChartDateTo").value = state.postsChartDateTo;
    loadProjects();
    loadDashboard();
    // Auto-scrape au chargement de la page
    autoScrapeOnLoad();
});

async function autoScrapeOnLoad() {
    try {
        // Verifier si un scraping est deja en cours
        const status = await fetchAPI("/api/scrape-status");
        if (status && status.active) {
            // Scraping deja en cours, juste suivre la progression
            const btn = document.getElementById("scrapeBtn");
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;display:inline-block"></span> Scraping...';
            lastCompletedCount = status.completed || 0;
            startScrapePolling();
            return;
        }
        // Lancer le scraping automatiquement
        startScraping();
    } catch (e) {
        console.error("Auto-scrape error:", e);
    }
}
