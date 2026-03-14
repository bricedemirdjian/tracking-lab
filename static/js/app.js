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
};

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
    };

    try {
        const [accounts, stats, videos, evolution, bestVideos, latestVideos] = await Promise.all([
            fetchAPI("/api/accounts"),
            fetchAPI("/api/stats", params),
            fetchAPI("/api/videos", { ...params, sort_by: state.sortBy, sort_order: state.sortOrder }),
            // Evolution chart: only filter by account, NOT by date (always show full history)
            fetchAPI("/api/evolution", { account: state.selectedAccount }),
            // Best & Latest videos: only filter by account, NOT by date (always show global best/latest)
            fetchAPI("/api/best-videos", { account: state.selectedAccount, limit: state.bestVideosLimit }),
            fetchAPI("/api/latest-videos", { account: state.selectedAccount, limit: state.latestVideosLimit }),
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
        renderTable(videos);
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
    perAccount.forEach(s => { statsMap[s.account_username] = s; });

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
        const s = statsMap[account.username] || {};
        const color = getAccountColor(account.username);
        const initial = account.username.charAt(0).toUpperCase();
        const displayName = account.display_name || account.username;

        const totalEng = (s.total_likes || 0) + (s.total_comments || 0) + (s.total_shares || 0) + (s.total_saves || 0);
        const engRate = (s.total_views || 0) > 0 ? ((totalEng / s.total_views) * 100).toFixed(2) : "0.00";
        const avgViews = (s.total_videos || 0) > 0 ? Math.round((s.total_views || 0) / s.total_videos) : 0;
        const nbVideos = s.total_videos || 0;

        html += `
            <div class="account-card ${state.selectedAccount === account.username ? 'active' : ''}"
                 onclick="selectAccount('${account.username}')">
                <div class="account-header">
                    <div class="avatar" style="background:${color}">${initial}</div>
                    <div class="account-info">
                        <div class="account-name">${displayName}</div>
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
        const url = v.video_url || "#";
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

function setBestVideosLimit(n) {
    state.bestVideosLimit = n;
    document.querySelectorAll("#bestVideosLimit .limit-btn").forEach(b => b.classList.toggle("active", parseInt(b.dataset.limit) === n));
    loadDashboard();
}

function setLatestVideosLimit(n) {
    state.latestVideosLimit = n;
    document.querySelectorAll("#latestVideosLimit .limit-btn").forEach(b => b.classList.toggle("active", parseInt(b.dataset.limit) === n));
    loadDashboard();
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

function renderViewsChart(evolution) {
    const ctx = document.getElementById("viewsChart");
    if (!ctx) return;

    if (state.charts.views) state.charts.views.destroy();

    // Evolution data from daily_snapshots (cumulative totals per scraping day)
    const dateMap = {};
    const accountsInData = new Set();
    evolution.forEach(d => {
        accountsInData.add(d.account_username);
        if (!dateMap[d.date]) dateMap[d.date] = {};
        dateMap[d.date][d.account_username] = d.views;
    });

    const dates = Object.keys(dateMap).sort();
    const datasets = [];
    const fewPoints = dates.length <= 7;

    accountsInData.forEach(username => {
        datasets.push({
            label: "@" + username,
            data: dates.map(d => dateMap[d][username] || 0),
            borderColor: getAccountColor(username),
            backgroundColor: "transparent",
            borderWidth: 2.5,
            fill: false,
            tension: 0.35,
            pointRadius: fewPoints ? 5 : 3,
            pointHoverRadius: 7,
            pointBackgroundColor: getAccountColor(username),
            pointBorderColor: "#12121e",
            pointBorderWidth: 2,
        });
    });

    state.charts.views = new Chart(ctx, {
        type: "line",
        data: { labels: dates.map(d => formatDate(d)), datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: {
                legend: {
                    position: "bottom",
                    labels: { color: "#8888aa", font: { size: 11 }, padding: 16, usePointStyle: true, pointStyle: "circle" },
                },
                tooltip: {
                    backgroundColor: "#1a1a2eee",
                    titleColor: "#f0f0f5",
                    bodyColor: "#c0c0d0",
                    borderColor: "#2a2a40",
                    borderWidth: 1,
                    padding: 10,
                    callbacks: {
                        label: ctx => " " + ctx.dataset.label + ": " + formatNumber(ctx.raw) + " vues",
                    },
                },
                datalabels: {
                    // Only show label on the LAST data point to avoid overlap
                    display: ctx => ctx.dataIndex === ctx.dataset.data.length - 1 && ctx.dataset.data[ctx.dataIndex] > 0,
                    color: ctx => ctx.dataset.borderColor,
                    font: { size: 10, weight: "bold" },
                    anchor: "end",
                    align: "right",
                    offset: 6,
                    formatter: v => formatCompact(v),
                },
            },
            scales: {
                x: { grid: { color: "#1a1a2e" }, ticks: { color: "#555570", font: { size: 10 } } },
                y: {
                    grid: { color: "#1a1a2e" },
                    ticks: { color: "#555570", callback: v => formatCompact(v) },
                },
            },
        },
    });
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
    const usernames = perAccount.map(a => "@" + a.account_username);
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
    const usernames = perAccount.map(a => "@" + a.account_username);
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
    simpleBarChart("likesPerAccountChart", "likesPA", perAccount.map(a => "@" + a.account_username), perAccount.map(a => a.total_likes), perAccount.map(a => getAccountColor(a.account_username)), "Likes", "likes");
}

function renderContentPerAccountChart(perAccount) {
    const ctx = document.getElementById("contentPerAccountChart");
    if (!ctx) return;
    if (state.charts.contentPA) state.charts.contentPA.destroy();
    const usernames = perAccount.map(a => "@" + a.account_username);
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
    simpleBarChart("avgViewsChart", "avgViewsPA", perAccount.map(a => "@" + a.account_username), perAccount.map(a => a.total_videos > 0 ? Math.round(a.total_views / a.total_videos) : 0), perAccount.map(a => getAccountColor(a.account_username)), "Moy. vues/video", "vues/video");
}

function renderSharesPerAccountChart(perAccount) {
    simpleBarChart("sharesPerAccountChart", "sharesPA", perAccount.map(a => "@" + a.account_username), perAccount.map(a => a.total_shares), perAccount.map(a => getAccountColor(a.account_username)), "Partages", "partages");
}

function renderCommentsPerAccountChart(perAccount) {
    simpleBarChart("commentsPerAccountChart", "commentsPA", perAccount.map(a => "@" + a.account_username), perAccount.map(a => a.total_comments), perAccount.map(a => getAccountColor(a.account_username)), "Commentaires", "commentaires");
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
        const url = v.video_url || "#";

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
    list.innerHTML = accounts.map(a => `
        <div class="account-list-item">
            <span class="account-list-name">@${a.username}</span>
            <button class="btn-remove" onclick="removeAccount('${a.username}')">Supprimer</button>
        </div>
    `).join("");
}

async function addAccount() {
    const input = document.getElementById("newAccountInput");
    const username = input.value.trim().replace("@", "");
    if (!username) return;
    try {
        const res = await fetch("/api/accounts/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username })
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

// Auto-refresh system
const AUTO_REFRESH_INTERVAL = 10;
let refreshCountdown = AUTO_REFRESH_INTERVAL;
let refreshTimer = null;
let countdownTimer = null;

function startAutoRefresh() {
    stopAutoRefresh();
    refreshCountdown = AUTO_REFRESH_INTERVAL;
    updateRefreshIndicator();
    countdownTimer = setInterval(() => {
        refreshCountdown--;
        updateRefreshIndicator();
        if (refreshCountdown <= 0) {
            refreshCountdown = AUTO_REFRESH_INTERVAL;
            loadDashboard();
        }
    }, 1000);
}

function stopAutoRefresh() {
    if (countdownTimer) clearInterval(countdownTimer);
    if (refreshTimer) clearInterval(refreshTimer);
}

function updateRefreshIndicator() {
    const el = document.getElementById("refreshCountdown");
    if (el) {
        el.textContent = refreshCountdown + "s";
        const progress = ((AUTO_REFRESH_INTERVAL - refreshCountdown) / AUTO_REFRESH_INTERVAL) * 100;
        const bar = document.getElementById("refreshBar");
        if (bar) bar.style.width = progress + "%";
    }
}

function refreshNow() {
    refreshCountdown = AUTO_REFRESH_INTERVAL;
    loadDashboard();
    showStatus("Donnees actualisees", "success");
}

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
    loadDashboard();
    startAutoRefresh();
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
