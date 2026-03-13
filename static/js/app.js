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
        const [accounts, stats, videos, evolution, bestVideos] = await Promise.all([
            fetchAPI("/api/accounts"),
            fetchAPI("/api/stats", params),
            fetchAPI("/api/videos", { ...params, sort_by: state.sortBy, sort_order: state.sortOrder }),
            fetchAPI("/api/evolution", params),
            fetchAPI("/api/best-videos", params),
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

        html += `
            <div class="account-card ${state.selectedAccount === account.username ? 'active' : ''}"
                 onclick="selectAccount('${account.username}')">
                <div class="account-header">
                    <div class="avatar" style="background:${color}">${initial}</div>
                    <div>
                        <div class="account-name">${displayName}</div>
                        <div class="account-handle">@${account.username}</div>
                    </div>
                    <div class="account-eng-badge">${engRate}%</div>
                </div>
                <div class="account-stats-grid">
                    <div class="stat-row">
                        <span class="stat-icon">&#127909;</span>
                        <span class="stat-label-inline">Contenus</span>
                        <span class="stat-value-inline">${formatNumber(s.total_videos || 0)}</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-icon">&#128064;</span>
                        <span class="stat-label-inline">Vues</span>
                        <span class="stat-value-inline">${formatNumber(s.total_views || 0)}</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-icon">&#10084;</span>
                        <span class="stat-label-inline">Likes</span>
                        <span class="stat-value-inline">${formatNumber(s.total_likes || 0)}</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-icon">&#128172;</span>
                        <span class="stat-label-inline">Commentaires</span>
                        <span class="stat-value-inline">${formatNumber(s.total_comments || 0)}</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-icon">&#128257;</span>
                        <span class="stat-label-inline">Partages</span>
                        <span class="stat-value-inline">${formatNumber(s.total_shares || 0)}</span>
                    </div>
                    <div class="stat-row">
                        <span class="stat-icon">&#128200;</span>
                        <span class="stat-label-inline">Moy. vues/video</span>
                        <span class="stat-value-inline">${formatNumber(avgViews)}</span>
                    </div>
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

// Best Videos
function renderBestVideos(videos) {
    const tbody = document.getElementById("bestVideosBody");
    const badge = document.getElementById("bestVideosBadge");
    if (!tbody) return;

    badge.textContent = "Top " + videos.length;

    if (videos.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:30px; color:var(--text-muted)">Aucune video trouvee</td></tr>`;
        return;
    }

    tbody.innerHTML = videos.map((v, i) => {
        const colorIdx = getAccountColorIndex(v.account_username);
        const totalEng = (v.likes || 0) + (v.comments || 0) + (v.shares || 0) + (v.saves || 0);
        const engRate = v.views > 0 ? ((totalEng / v.views) * 100).toFixed(2) : "0.00";
        const desc = (v.description || "").length > 50 ? v.description.substring(0, 50) + "..." : (v.description || "-");
        const link = v.video_url ? `<a href="${v.video_url}" target="_blank" style="color:var(--tiktok-blue);text-decoration:none">&#128279; Voir</a>` : "-";

        return `
            <tr>
                <td><span style="color:${i < 3 ? 'var(--warning)' : 'var(--text-muted)'};font-weight:bold">${i < 3 ? ['&#129351;','&#129352;','&#129353;'][i] : '#' + (i + 1)}</span></td>
                <td><span class="account-tag"><span class="dot color-${colorIdx}"></span>@${v.account_username}</span></td>
                <td>${formatDate(v.create_time)}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text-secondary);font-size:12px" title="${(v.description || '').replace(/"/g, '&quot;')}">${desc}</td>
                <td><span class="metric" style="font-weight:700">${formatNumber(v.views)}</span></td>
                <td><span class="metric">${formatNumber(v.likes)}</span></td>
                <td><span class="metric" style="color:var(--tiktok-blue)">${engRate}%</span></td>
                <td>${link}</td>
            </tr>
        `;
    }).join("");
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

    const dateMap = {};
    const accountsInData = new Set();
    evolution.forEach(d => {
        accountsInData.add(d.account_username);
        if (!dateMap[d.date]) dateMap[d.date] = {};
        dateMap[d.date][d.account_username] = d.views;
    });

    const dates = Object.keys(dateMap).sort();
    const datasets = [];

    accountsInData.forEach(username => {
        datasets.push({
            label: "@" + username,
            data: dates.map(d => dateMap[d][username] || 0),
            borderColor: getAccountColor(username),
            backgroundColor: getAccountColor(username) + "20",
            borderWidth: 2,
            fill: true,
            tension: 0.4,
            pointRadius: 3,
            pointHoverRadius: 6,
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
                legend: { labels: { color: "#8888aa", font: { size: 11 } } },
                tooltip: {
                    backgroundColor: "#1a1a2e",
                    titleColor: "#f0f0f5",
                    bodyColor: "#8888aa",
                    borderColor: "#2a2a40",
                    borderWidth: 1,
                    callbacks: {
                        label: ctx => ctx.dataset.label + ": " + formatNumber(ctx.raw),
                    },
                },
                datalabels: {
                    color: "#f0f0f5",
                    font: { size: 9, weight: "bold" },
                    anchor: "end",
                    align: "top",
                    offset: 2,
                    formatter: v => formatCompact(v),
                    display: ctx => ctx.dataset.data[ctx.dataIndex] > 0,
                },
            },
            scales: {
                x: { grid: { color: "#1a1a2e" }, ticks: { color: "#555570", font: { size: 10 } } },
                y: { grid: { color: "#1a1a2e" }, ticks: { color: "#555570", callback: v => formatNumber(v) } },
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
                y: { stacked: true, grid: { color: "#1a1a2e" }, ticks: { color: "#555570", callback: v => formatNumber(v) } },
            },
        },
    });
}

// Render Table
function renderTable(videos) {
    const tbody = document.getElementById("videosTableBody");
    const countEl = document.getElementById("videoCount");

    countEl.textContent = videos.length + " videos";

    if (videos.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:40px; color:var(--text-muted)">Aucune video trouvee. Lancez un scraping ou importez un CSV.</td></tr>`;
        return;
    }

    tbody.innerHTML = videos.map(v => {
        const colorIdx = getAccountColorIndex(v.account_username);
        const totalEngagement = (v.likes || 0) + (v.comments || 0) + (v.shares || 0) + (v.saves || 0);
        const engRate = v.views > 0 ? ((totalEngagement / v.views) * 100).toFixed(2) : "0.00";

        return `
            <tr>
                <td><span class="account-tag"><span class="dot color-${colorIdx}"></span>@${v.account_username}</span></td>
                <td>${formatDate(v.create_time)}</td>
                <td><span class="metric">${formatNumber(v.views)}</span></td>
                <td><span class="metric">${formatNumber(v.likes)}</span></td>
                <td><span class="metric" style="color:var(--tiktok-blue)">${engRate}%</span></td>
                <td><span class="metric">${formatNumber(v.comments)}</span></td>
                <td><span class="metric">${formatNumber(v.shares)}</span></td>
            </tr>
        `;
    }).join("");
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
});
