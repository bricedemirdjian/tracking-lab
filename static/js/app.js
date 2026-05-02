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
    bestVideosSort: "views",  // "views" | "engagement"
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
    // Activity table sort
    activitySortBy: "views",
    activitySortOrder: "DESC",
    activityAccounts: [],
    activityPerAccount: [],
    // Platform filter
    platformFilter: "all",
    allAccounts: [],
    allPerAccount: [],
    // Project accounts modal
    editingProjectId: null,
    // Competitor state
    competitorDataLoaded: false,
    competitorAccounts: [],
    competitorPerAccount: [],
    competitorActivitySortBy: "views",
    competitorActivitySortOrder: "DESC",
    competitorPlatformFilter: "all",
    competitorAllAccounts: [],
    competitorAllPerAccount: [],
    competitorBestLimit: 10,
    competitorLatestLimit: 10,
    // Competitor overview filters
    cOverviewAccount: "all",
    cOverviewDateFrom: null,
    cOverviewDateTo: null,
    // Competitor charts/table
    competitorChartsLoaded: false,
    competitorTableLoaded: false,
    cTableBestLimit: 5,
    cTableLatestLimit: 5,
    cTableLatestDateFrom: null,
    cTableLatestDateTo: null,
    // Analytics overview
    analyticsLoaded: false,
    aLabProject: "all",
    aLabDateFrom: null,
    aLabDateTo: null,
    aCompAccount: "all",
    aCompDateFrom: null,
    aCompDateTo: null,
    // Chart date filters (default: last 7 days)
    viewsChartDateFrom: (() => { const d = new Date(); d.setDate(d.getDate() - 7); return d.toLocaleDateString('en-CA'); })(),
    viewsChartDateTo: new Date().toLocaleDateString('en-CA'),
    postsChartDateFrom: (() => { const d = new Date(); d.setDate(d.getDate() - 7); return d.toLocaleDateString('en-CA'); })(),
    postsChartDateTo: new Date().toLocaleDateString('en-CA'),
};

// Platform icon helper
function platformIcon(platform, size = 14) {
    const uid = Math.random().toString(36).substr(2, 6);
    const svgs = {
        tiktok: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" style="vertical-align:middle"><path fill="#010101" d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-2.88 2.5 2.89 2.89 0 0 1-2.89-2.89 2.89 2.89 0 0 1 2.89-2.89c.28 0 .54.04.79.1V9.01a6.27 6.27 0 0 0-.79-.05 6.34 6.34 0 0 0-6.34 6.34 6.34 6.34 0 0 0 6.34 6.34 6.34 6.34 0 0 0 6.34-6.34V8.75a8.18 8.18 0 0 0 4.76 1.52V6.84a4.83 4.83 0 0 1-1-.15z"/></svg>`,
        instagram: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" style="vertical-align:middle"><defs><linearGradient id="ig${uid}" x1="0%" y1="100%" x2="100%" y2="0%"><stop offset="0%" style="stop-color:#feda75"/><stop offset="25%" style="stop-color:#fa7e1e"/><stop offset="50%" style="stop-color:#d62976"/><stop offset="75%" style="stop-color:#962fbf"/><stop offset="100%" style="stop-color:#4f5bd5"/></linearGradient></defs><rect x="2" y="2" width="20" height="20" rx="5" fill="url(#ig${uid})"/><circle cx="12" cy="12" r="5" fill="none" stroke="#fff" stroke-width="1.5"/><circle cx="17.5" cy="6.5" r="1.2" fill="#fff"/></svg>`,
        snapchat: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" style="vertical-align:middle"><path fill="#FFFC00" d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 14.19c-.12.27-.47.46-.73.52-.26.06-.54.09-.81.15-.18.04-.37.08-.5.2-.13.12-.2.3-.34.42a1.5 1.5 0 0 1-.87.35c-.38 0-.72-.18-1.08-.33-.5-.21-1.06-.44-1.65-.07a3.8 3.8 0 0 0-1.47 1.34c-.31.46-.67.76-1.13.76-.07 0-.14 0-.21-.02-.73-.15-.88-.93-1.31-1.23-.23-.16-.56-.2-.85-.25-.24-.04-.49-.08-.71-.17-.36-.15-.56-.42-.47-.72.06-.21.23-.36.4-.47.56-.34 1.17-.57 1.63-1.02.38-.37.6-.85.38-1.36-.14-.32-.4-.57-.65-.8-.34-.31-.7-.6-.93-1.01-.32-.55-.27-1.24.21-1.62.29-.23.66-.3 1.02-.27.08.01.16.02.24.04-.02-.46.01-.93.08-1.39.18-1.21.72-2.3 1.63-3.12A4.94 4.94 0 0 1 12 5.5c1.26 0 2.43.47 3.33 1.3.91.82 1.45 1.91 1.63 3.12.07.46.1.93.08 1.39.08-.02.16-.03.24-.04.36-.03.73.04 1.02.27.48.38.53 1.07.21 1.62-.23.41-.59.7-.93 1.01-.25.23-.51.48-.65.8-.22.51 0 .99.38 1.36.46.45 1.07.68 1.63 1.02.17.11.34.26.4.47z"/></svg>`,
        youtube: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" style="vertical-align:middle"><rect width="24" height="24" rx="4" fill="#FF0000"/><polygon points="10,7.5 16,12 10,16.5" fill="#fff"/></svg>`,
        linkedin: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" style="vertical-align:middle"><rect width="24" height="24" rx="4" fill="#0A66C2"/><path fill="#fff" d="M7.5 9.5h-2v7h2v-7zm-1-3.2a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4zm10 3.2h-1.9c0 0 0 0 0 0h-.1v7h2v-3.9c0-1.1.4-1.8 1.3-1.8.8 0 1.2.6 1.2 1.8v3.9h2v-4.3c0-2.1-1.1-3.2-2.7-3.2-1.2 0-1.8.6-2.1 1.1V9.5h-.7z"/></svg>`
    };
    const names = { tiktok: 'TikTok', instagram: 'Instagram', snapchat: 'Snapchat', youtube: 'YouTube Shorts', linkedin: 'LinkedIn' };
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
        const competitorFlag = state.selectedProject === "all" ? "false" : undefined;
        const [accounts, stats, evolution, bestVideos, latestVideos, postsPerDay, tableBest, tableLatest] = await Promise.all([
            fetchAPI("/api/accounts", { project_id: state.selectedProject, competitor: competitorFlag }),
            fetchAPI("/api/stats", { ...params, competitor: competitorFlag }),
            // Evolution chart: filter by account + optional chart date filter
            fetchAPI("/api/evolution", { account: state.selectedAccount, project_id: state.selectedProject, date_from: state.viewsChartDateFrom, date_to: state.viewsChartDateTo, competitor: competitorFlag }),
            // Best videos: filter by account + optional dedicated date filter.
            // `sort` toggles between pure-reach (views) and weighted-engagement
            // — the latter surfaces high-engagement IG carousels alongside videos.
            fetchAPI("/api/best-videos", {
                account: state.selectedAccount,
                limit: state.bestVideosLimit,
                sort: state.bestVideosSort,
                date_from: state.bestDateFrom,
                date_to: state.bestDateTo,
                project_id: state.selectedProject,
                competitor: competitorFlag,
            }),
            // Latest videos: filter by account + optional dedicated date filter
            fetchAPI("/api/latest-videos", {
                account: state.selectedAccount,
                limit: state.latestVideosLimit,
                date_from: state.latestDateFrom,
                date_to: state.latestDateTo,
                project_id: state.selectedProject,
                competitor: competitorFlag,
            }),
            fetchAPI("/api/posts-per-day", { account: state.selectedAccount, project_id: state.selectedProject, date_from: state.postsChartDateFrom, date_to: state.postsChartDateTo, competitor: competitorFlag }),
            // Table tab: best videos (same API)
            fetchAPI("/api/best-videos", {
                account: state.selectedAccount,
                limit: tableBestLimitVal,
                project_id: state.selectedProject,
                competitor: competitorFlag,
            }),
            // Table tab: latest videos (same API)
            fetchAPI("/api/latest-videos", {
                account: state.selectedAccount,
                limit: tableLatestLimitVal,
                date_from: state.tableLatestDateFrom,
                date_to: state.tableLatestDateTo,
                project_id: state.selectedProject,
                competitor: competitorFlag,
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

        renderKPIs(stats.global, accounts);
        renderAccountActivity(accounts, stats.per_account);
        renderAccountCards(accounts, stats.per_account);
        renderBestVideos(bestVideos);
        renderLatestVideos(latestVideos);
        renderCharts(stats, evolution);
        renderPostsPerDayChart(postsPerDay);
        // Table tab: use same API data
        renderVideoCards(tableBest, "tableBestGrid", "tableBestBadge", "Top ");
        renderVideoCards(tableLatest, "tableLatestGrid", "tableLatestBadge", "");

        // Update sidebar badge
        const sidebarBadge = document.getElementById("sidebarAccountsBadge");
        if (sidebarBadge) sidebarBadge.textContent = accounts.length;
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

// Render KPIs (10 cards)
function renderKPIs(global, accounts) {
    document.getElementById("kpiVideos").textContent = formatNumber(global.total_videos);
    document.getElementById("kpiViews").textContent = formatNumber(global.total_views);
    document.getElementById("kpiLikes").textContent = formatNumber(global.total_likes);
    document.getElementById("kpiComments").textContent = formatNumber(global.total_comments);
    document.getElementById("kpiShares").textContent = formatNumber(global.total_shares);
    document.getElementById("kpiEngagement").textContent = global.engagement_rate.toFixed(2) + "%";
    const activeAccounts = accounts ? accounts.length : 0;
    document.getElementById("kpiActiveAccounts").textContent = activeAccounts;
    const avgViews = global.total_videos > 0 ? Math.round(global.total_views / global.total_videos) : 0;
    document.getElementById("kpiAvgViews").textContent = formatNumber(avgViews);
    // Followers KPIs
    const elFollowers = document.getElementById("kpiFollowers");
    if (elFollowers) elFollowers.textContent = formatNumber(global.total_followers || 0);
    const elGain = document.getElementById("kpiFollowerGain");
    if (elGain) {
        const g = global.follower_gain || 0;
        const sign = g > 0 ? "+" : (g < 0 ? "-" : "");
        elGain.textContent = sign + formatNumber(Math.abs(g));
        elGain.style.color = g > 0 ? "#34c759" : (g < 0 ? "#ff3b30" : "");
    }
}

// Render Account Activity Table
function renderAccountActivity(accounts, perAccount) {
    // Store for re-sorting without re-fetch
    state.activityAccounts = accounts;
    state.activityPerAccount = perAccount;
    renderActivityTableSorted();
}

function renderActivityTableSorted() {
    const accounts = state.activityAccounts;
    const perAccount = state.activityPerAccount;
    const tbody = document.getElementById("accountActivityBody");
    const badge = document.getElementById("activityBadge");
    if (!tbody) return;

    if (badge) badge.textContent = accounts.length + " comptes";

    const statsMap = {};
    perAccount.forEach(s => {
        const key = s.account_username + ":" + (s.platform || "tiktok");
        statsMap[key] = s;
    });

    if (accounts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:40px;color:#86868b">Aucun compte suivi. Ajoutez des comptes pour commencer.</td></tr>';
        return;
    }

    // Build enriched rows for sorting
    const rows = accounts.map(account => {
        const s = statsMap[account.username + ":" + (account.platform || "tiktok")] || {};
        const totalEng = (s.total_likes||0) + (s.total_comments||0) + (s.total_shares||0) + (s.total_saves||0);
        const engRate = (s.total_views||0) > 0 ? ((totalEng / s.total_views) * 100) : 0;
        const avgViews = (s.total_videos||0) > 0 ? Math.round((s.total_views||0) / s.total_videos) : 0;
        return {
            account,
            stats: s,
            name: (account.display_name || account.username).toLowerCase(),
            videos: s.total_videos || 0,
            views: s.total_views || 0,
            likes: s.total_likes || 0,
            engagement: engRate,
            avg_views: avgViews,
            followers: s.followers || account.followers || 0,
            follower_gain: s.follower_gain || 0,
        };
    });

    // Sort
    const sortKey = state.activitySortBy;
    const sortDir = state.activitySortOrder === "ASC" ? 1 : -1;
    rows.sort((a, b) => {
        if (sortKey === "name") {
            return a.name < b.name ? -1 * sortDir : a.name > b.name ? 1 * sortDir : 0;
        }
        return (a[sortKey] - b[sortKey]) * sortDir;
    });

    // Update header indicators
    document.querySelectorAll(".activity-table thead th.sortable").forEach(th => {
        const col = th.dataset.sort;
        const indicator = th.querySelector(".sort-indicator");
        const arrows = th.querySelector(".sort-arrows");
        if (col === sortKey) {
            th.classList.add("sorted");
            indicator.textContent = state.activitySortOrder === "DESC" ? " \u25BC" : " \u25B2";
            if (arrows) arrows.style.display = "none";
        } else {
            th.classList.remove("sorted");
            indicator.textContent = "";
            if (arrows) arrows.style.display = "";
        }
    });

    // Max engagement for bar scaling
    const maxEng = Math.max(1, ...rows.map(r => r.engagement));

    // Today as midnight UTC for "days since last post" math — keeps the badge
    // stable through the day rather than ticking up by hours.
    const nowMs = Date.now();

    tbody.innerHTML = rows.map(row => {
        const account = row.account;
        const s = row.stats;
        const color = getAccountColor(account.username);
        const initial = account.username.charAt(0).toUpperCase();
        const displayName = account.display_name || account.username;
        const pIcon = platformIcon(account.platform, 14);

        const engRate = row.engagement;
        const engClass = engRate >= 5 ? "eng-high" : engRate >= 2 ? "eng-mid" : "eng-low";
        const engBarColor = engRate >= 5 ? "var(--success)" : engRate >= 2 ? "var(--warning)" : "var(--accent)";
        const engBarWidth = Math.min(100, (engRate / Math.min(maxEng, 15)) * 100);

        // Inactivity badge: shown only when the account has 0 videos *in the
        // current date window* but exists in the videos table with an older
        // last_post_at. Three flavors so users can act on the right signal:
        //   - >0 in range          → no badge (account is healthy)
        //   - 0 in range, never posted → "Aucune publication" (could be a typo
        //                                  in handle, scrape failure, or empty
        //                                  account — worth investigating)
        //   - 0 in range, posted before → "Inactif depuis Xj" (account is real
        //                                  but dormant in the chosen window)
        let inactivityBadge = "";
        if (row.videos === 0) {
            const lastPost = account.last_post_at;
            if (lastPost) {
                const lastMs = new Date(lastPost).getTime();
                const days = Math.max(1, Math.floor((nowMs - lastMs) / 86400000));
                inactivityBadge = `<span class="activity-inactive-badge" title="Dernier post: ${new Date(lastPost).toLocaleDateString('fr-FR')}">⊘ Inactif depuis ${days}j</span>`;
            } else {
                inactivityBadge = `<span class="activity-inactive-badge activity-inactive-badge--unknown" title="Aucune vidéo récupérée par le scraping">⊘ Aucune publication</span>`;
            }
        }

        return `<tr onclick="selectAccount('${account.username}')">
            <td>
                <div class="activity-account">
                    <div class="activity-avatar" style="background:${color}">${initial}</div>
                    <div class="activity-account-info">
                        <div class="activity-account-name">${pIcon} ${displayName}</div>
                        <div class="activity-account-handle">@${account.username}${inactivityBadge}</div>
                    </div>
                </div>
            </td>
            <td class="text-center"><span class="activity-videos-count">${row.videos}</span></td>
            <td class="text-right"><span class="activity-metric">${formatCompact(row.views) || "0"}</span></td>
            <td class="text-right"><span class="activity-metric">${formatCompact(row.likes) || "0"}</span></td>
            <td class="text-right">
                <div class="activity-eng">
                    <span class="activity-eng-value ${engClass}">${engRate.toFixed(2)}%</span>
                    <div class="activity-eng-bar"><div class="activity-eng-bar-fill" style="width:${engBarWidth}%;background:${engBarColor}"></div></div>
                </div>
            </td>
            <td class="text-right"><span class="activity-metric">${formatCompact(row.followers) || "0"}</span></td>
            <td class="text-right"><span class="activity-metric" style="color:${row.follower_gain > 0 ? '#34c759' : (row.follower_gain < 0 ? '#ff3b30' : '#86868b')}">${row.follower_gain > 0 ? '+' : ''}${formatCompact(row.follower_gain) || "0"}</span></td>
            <td class="text-right"><span class="activity-metric">${formatCompact(row.avg_views) || "0"}</span></td>
        </tr>`;
    }).join("");
}

function sortActivityTable(column) {
    if (state.activitySortBy === column) {
        state.activitySortOrder = state.activitySortOrder === "DESC" ? "ASC" : "DESC";
    } else {
        state.activitySortBy = column;
        state.activitySortOrder = "DESC";
    }
    renderActivityTableSorted();
}

// Render Account Cards
function renderAccountCards(accounts, perAccount) {
    // Store for platform filtering
    state.allAccounts = accounts;
    state.allPerAccount = perAccount;
    updatePlatformCounts(accounts);
    renderAccountCardsFiltered();
}

function updatePlatformCounts(accounts) {
    const counts = { tiktok: 0, instagram: 0, youtube: 0 };
    accounts.forEach(a => {
        const p = a.platform || "tiktok";
        if (counts[p] !== undefined) counts[p]++;
    });
    const elTT = document.getElementById("countTiktok");
    const elIG = document.getElementById("countInstagram");
    const elYT = document.getElementById("countYoutube");
    if (elTT) elTT.textContent = counts.tiktok;
    if (elIG) elIG.textContent = counts.instagram;
    if (elYT) elYT.textContent = counts.youtube;
}

function filterByPlatform(platform) {
    state.platformFilter = platform;
    document.querySelectorAll(".platform-pill").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.platform === platform);
    });
    renderAccountCardsFiltered();
}

function renderAccountCardsFiltered() {
    const accounts = state.platformFilter === "all"
        ? state.allAccounts
        : state.allAccounts.filter(a => (a.platform || "tiktok") === state.platformFilter);
    const perAccount = state.allPerAccount;

    const container = document.getElementById("accountCards");
    if (!container) return;
    const statsMap = {};
    perAccount.forEach(s => {
        const key = s.account_username + ":" + (s.platform || "tiktok");
        statsMap[key] = s;
    });

    // Update badge
    const badge = document.getElementById("accountsBadge");
    if (badge) {
        if (state.platformFilter === "all") {
            badge.textContent = state.allAccounts.length + " comptes";
        } else {
            badge.textContent = accounts.length + " / " + state.allAccounts.length + " comptes";
        }
    }

    if (accounts.length === 0) {
        container.innerHTML = `
            <div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-3)">
                <p style="font-size:32px;margin-bottom:12px">&#128269;</p>
                <p>Aucun compte${state.platformFilter !== 'all' ? ' sur cette plateforme' : ' suivi'}.</p>
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

// Toggle ranking mode for "Meilleures vidéos". Updates the active button,
// stores in state, and triggers a full dashboard reload — the API returns
// already-sorted data, so we don't need a client-side re-sort.
function setBestVideosSort(sort) {
    if (sort !== "views" && sort !== "engagement") return;
    state.bestVideosSort = sort;
    document.querySelectorAll("#bestVideosSort .sort-btn").forEach(b => b.classList.toggle("active", b.dataset.sort === sort));
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

// Sidebar page navigation
function switchPage(pageName) {
    state.activeTab = pageName;
    // Update sidebar nav
    document.querySelectorAll(".nav-item").forEach(item => {
        item.classList.toggle("active", item.dataset.page === pageName);
    });
    // Update page visibility
    document.querySelectorAll(".page").forEach(el => {
        el.classList.toggle("active", el.id === "page-" + pageName);
    });
    // Resize charts when switching to a page with charts
    if (pageName === "overview" || pageName === "table" || pageName === "c-table") {
        setTimeout(() => {
            Object.values(state.charts).forEach(c => c && c.resize && c.resize());
        }, 100);
    }
    // Load analytics overview on first visit
    if (pageName === "analytics" && !state.analyticsLoaded) {
        loadAnalyticsOverview();
    }
    // Load competitor data on first visit to any competitor page
    if (pageName.startsWith("c-") && !state.competitorDataLoaded) {
        loadCompetitorDashboard();
    }
    // Load competitor charts + table on first visit
    if (pageName === "c-table") {
        if (!state.competitorChartsLoaded) loadCompetitorChartsData();
        if (!state.competitorTableLoaded) loadCompetitorTableData();
    }
    // Close sidebar on mobile
    closeSidebar();
}

// Legacy support
function switchTab(tabName) {
    switchPage(tabName);
}

// Sidebar toggle (mobile)
function toggleSidebar() {
    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("sidebarOverlay");
    sidebar.classList.toggle("open");
    if (overlay) overlay.classList.toggle("active");
}

function closeSidebar() {
    if (window.innerWidth <= 768) {
        const sidebar = document.getElementById("sidebar");
        const overlay = document.getElementById("sidebarOverlay");
        sidebar.classList.remove("open");
        if (overlay) overlay.classList.remove("active");
    }
}

// Reset all filters
function resetAllFilters() {
    state.dateFrom = null;
    state.dateTo = null;
    state.selectedAccount = "all";
    state.selectedProject = "all";
    document.getElementById("filterDateFrom").value = "";
    document.getElementById("filterDateTo").value = "";
    document.getElementById("filterAccount").value = "all";
    document.getElementById("filterProject").value = "all";
    loadDashboard();
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

function formatDuration(seconds) {
    if (!seconds || seconds < 0) return "0s";
    if (seconds < 60) return Math.round(seconds) + "s";
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds - m * 60);
    return m + "m" + String(s).padStart(2, "0");
}

function formatRelativeTime(timestampSec) {
    if (!timestampSec) return "";
    const ageSec = Date.now() / 1000 - timestampSec;
    if (ageSec < 0) return "à l'instant";
    if (ageSec < 60) return "il y a " + Math.round(ageSec) + "s";
    if (ageSec < 3600) return "il y a " + Math.round(ageSec / 60) + " min";
    if (ageSec < 86400) return "il y a " + Math.round(ageSec / 3600) + "h";
    return "il y a " + Math.round(ageSec / 86400) + "j";
}

function updateLastSyncLabel(finishedAt, durationSec) {
    const el = document.getElementById("lastSyncLabel");
    if (!el || !finishedAt) return;
    const dur = durationSec ? " · " + formatDuration(durationSec) : "";
    el.textContent = "Sync " + formatRelativeTime(finishedAt) + dur;
    el.style.display = "";
}

function startScrapePolling() {
    stopScrapePolling();
    scrapePollingTimer = setInterval(async () => {
        try {
            const status = await fetchAPI("/api/scrape-status");
            if (!status) return;

            const btn = document.getElementById("scrapeBtn");

            // Compute elapsed time (server-side started_at in seconds since epoch)
            const nowSec = Date.now() / 1000;
            const startedAt = status.started_at || nowSec;
            const elapsed = Math.max(0, nowSec - startedAt);

            // Update button with progress: X/Y · NN% · 12s (@account)
            if (status.active) {
                const total = status.total || 0;
                const done = status.completed || 0;
                const pct = total > 0 ? Math.round((done / total) * 100) : 0;
                const progress = done + "/" + total + " · " + pct + "% · " + formatDuration(elapsed);
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
                // Total duration: from started_at to finished_at (server-side, accurate)
                const durationSec = status.finished_at && status.started_at
                    ? (status.finished_at - status.started_at)
                    : elapsed;
                const totalDuration = formatDuration(durationSec);
                updateLastSyncLabel(status.finished_at || (Date.now() / 1000), durationSec);
                const errors = status.errors ? status.errors.length : 0;
                if (errors > 0) {
                    showStatus("Scraping termine en " + totalDuration + " ! " + status.completed + "/" + status.total + " comptes (" + errors + " erreurs)", "error");
                } else {
                    showStatus("Scraping termine en " + totalDuration + " ! " + status.completed + "/" + status.total + " comptes scrapes", "success");
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
        showStatus(`Compte @${username} ajouté ! Scraping en cours...`, "success");
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
        showStatus(`Compte @${username} supprimé`, "success");
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
        showStatus(`Projet "${name}" créé !`, "success");
    } catch (err) {
        showStatus("Erreur lors de la création du projet", "error");
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
    if (!confirm(`Supprimer le projet "${name}" ? Les comptes ne seront pas supprimés.`)) return;
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
        showStatus(`Projet "${name}" supprimé`, "success");
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
        showStatus("Comptes du projet mis à jour !", "success");
        loadDashboard();
    } catch (err) {
        showStatus("Erreur lors de la sauvegarde", "error");
    }
}

// ==================== Analytics Overview (Lab + Concurrents) ====================

async function loadAnalyticsOverview() {
    await Promise.all([loadAnalyticsLab(), loadAnalyticsComp()]);
    state.analyticsLoaded = true;
}

async function loadAnalyticsLab() {
    try {
        const projectParam = state.aLabProject !== "all" ? state.aLabProject : undefined;
        const [accounts, stats, projects] = await Promise.all([
            fetchAPI("/api/accounts", { competitor: "false", project_id: projectParam }),
            fetchAPI("/api/stats", {
                competitor: "false",
                project_id: projectParam,
                date_from: state.aLabDateFrom,
                date_to: state.aLabDateTo,
            }),
            fetchAPI("/api/projects"),
        ]);
        if (!accounts) return;

        // Populate project filter dropdown
        const sel = document.getElementById("a-labProject");
        if (sel) {
            const cur = sel.value;
            sel.innerHTML = '<option value="all">Tous les projets</option>';
            if (projects) {
                projects.forEach(p => {
                    const opt = document.createElement("option");
                    opt.value = p.id;
                    opt.textContent = p.name;
                    sel.appendChild(opt);
                });
            }
            sel.value = cur || "all";
        }

        const g = stats.global;
        document.getElementById("a-labCount").textContent = accounts.length + " comptes";
        document.getElementById("a-labVideos").textContent = formatNumber(g.total_videos);
        document.getElementById("a-labViews").textContent = formatNumber(g.total_views);
        document.getElementById("a-labLikes").textContent = formatNumber(g.total_likes);
        document.getElementById("a-labEngagement").textContent = g.engagement_rate.toFixed(2) + "%";
        document.getElementById("a-labComments").textContent = formatNumber(g.total_comments);
        document.getElementById("a-labShares").textContent = formatNumber(g.total_shares);
        const avg = g.total_videos > 0 ? Math.round(g.total_views / g.total_videos) : 0;
        document.getElementById("a-labAvgViews").textContent = formatNumber(avg);
        document.getElementById("a-labAccounts").textContent = accounts.length;

        assignColors(accounts);
        renderAnalyticsActivityTable(accounts, stats.per_account, "a-labActivityBody");
    } catch (err) {
        console.error("Error loading analytics lab:", err);
    }
}

async function loadAnalyticsComp() {
    try {
        const [accounts, stats] = await Promise.all([
            fetchAPI("/api/accounts", { competitor: "true" }),
            fetchAPI("/api/stats", {
                competitor: "true",
                account: state.aCompAccount,
                date_from: state.aCompDateFrom,
                date_to: state.aCompDateTo,
            }),
        ]);
        if (!accounts) return;

        // Populate account filter dropdown
        const sel = document.getElementById("a-compAccount");
        if (sel) {
            const cur = sel.value;
            sel.innerHTML = '<option value="all">Tous les comptes</option>';
            accounts.forEach(a => {
                const opt = document.createElement("option");
                opt.value = a.username;
                opt.textContent = "@" + a.username;
                sel.appendChild(opt);
            });
            sel.value = cur || "all";
        }

        const g = stats.global;
        document.getElementById("a-compCount").textContent = accounts.length + " comptes";
        document.getElementById("a-compVideos").textContent = formatNumber(g.total_videos);
        document.getElementById("a-compViews").textContent = formatNumber(g.total_views);
        document.getElementById("a-compLikes").textContent = formatNumber(g.total_likes);
        document.getElementById("a-compEngagement").textContent = g.engagement_rate.toFixed(2) + "%";
        document.getElementById("a-compComments").textContent = formatNumber(g.total_comments);
        document.getElementById("a-compShares").textContent = formatNumber(g.total_shares);
        const avg = g.total_videos > 0 ? Math.round(g.total_views / g.total_videos) : 0;
        document.getElementById("a-compAvgViews").textContent = formatNumber(avg);
        document.getElementById("a-compAccounts").textContent = accounts.length;

        assignColors(accounts);
        renderAnalyticsActivityTable(accounts, stats.per_account, "a-compActivityBody");
    } catch (err) {
        console.error("Error loading analytics comp:", err);
    }
}

function onAnalyticsLabFilter() {
    state.aLabProject = document.getElementById("a-labProject").value;
    state.aLabDateFrom = document.getElementById("a-labDateFrom").value || null;
    state.aLabDateTo = document.getElementById("a-labDateTo").value || null;
    loadAnalyticsLab();
}

function resetAnalyticsLabFilter() {
    state.aLabProject = "all";
    state.aLabDateFrom = null;
    state.aLabDateTo = null;
    document.getElementById("a-labProject").value = "all";
    document.getElementById("a-labDateFrom").value = "";
    document.getElementById("a-labDateTo").value = "";
    loadAnalyticsLab();
}

function onAnalyticsCompFilter() {
    state.aCompAccount = document.getElementById("a-compAccount").value;
    state.aCompDateFrom = document.getElementById("a-compDateFrom").value || null;
    state.aCompDateTo = document.getElementById("a-compDateTo").value || null;
    loadAnalyticsComp();
}

function resetAnalyticsCompFilter() {
    state.aCompAccount = "all";
    state.aCompDateFrom = null;
    state.aCompDateTo = null;
    document.getElementById("a-compAccount").value = "all";
    document.getElementById("a-compDateFrom").value = "";
    document.getElementById("a-compDateTo").value = "";
    loadAnalyticsComp();
}

function renderAnalyticsActivityTable(accounts, perAccount, tbodyId) {
    const tbody = document.getElementById(tbodyId);
    if (!tbody) return;

    const statsMap = {};
    perAccount.forEach(s => {
        const key = s.account_username + ":" + (s.platform || "tiktok");
        statsMap[key] = s;
    });

    if (accounts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" class="a-table-empty">Aucun compte</td></tr>';
        return;
    }

    // Build rows sorted by views DESC, show top 5
    const rows = accounts.map(account => {
        const s = statsMap[account.username + ":" + (account.platform || "tiktok")] || {};
        const totalEng = (s.total_likes||0) + (s.total_comments||0) + (s.total_shares||0) + (s.total_saves||0);
        const engRate = (s.total_views||0) > 0 ? ((totalEng / s.total_views) * 100) : 0;
        return { account, views: s.total_views || 0, likes: s.total_likes || 0, engagement: engRate };
    }).sort((a, b) => b.views - a.views).slice(0, 5);

    assignColors(accounts);

    tbody.innerHTML = rows.map(row => {
        const a = row.account;
        const color = getAccountColor(a.username);
        const initial = a.username.charAt(0).toUpperCase();
        const displayName = a.display_name || a.username;
        const pIcon = platformIcon(a.platform, 12);
        const engClass = row.engagement >= 5 ? "eng-high" : row.engagement >= 2 ? "eng-mid" : "eng-low";

        return `<tr>
            <td>
                <div class="activity-account">
                    <div class="activity-avatar" style="background:${color}">${initial}</div>
                    <div class="activity-account-info">
                        <div class="activity-account-name">${pIcon} ${displayName}</div>
                        <div class="activity-account-handle">@${a.username}</div>
                    </div>
                </div>
            </td>
            <td class="text-right">${formatCompact(row.views) || "0"}</td>
            <td class="text-right">${formatCompact(row.likes) || "0"}</td>
            <td class="text-right"><span class="${engClass}">${row.engagement.toFixed(2)}%</span></td>
        </tr>`;
    }).join("");
}

// ==================== Competitor Dashboard ====================

async function loadCompetitorDashboard() {
    try {
        const filterParams = {
            competitor: "true",
            account: state.cOverviewAccount !== "all" ? state.cOverviewAccount : undefined,
            date_from: state.cOverviewDateFrom,
            date_to: state.cOverviewDateTo,
        };
        const [accounts, stats, bestVideos, latestVideos] = await Promise.all([
            fetchAPI("/api/accounts", { competitor: "true" }),
            fetchAPI("/api/stats", filterParams),
            fetchAPI("/api/best-videos", { ...filterParams, limit: state.competitorBestLimit }),
            fetchAPI("/api/latest-videos", { ...filterParams, limit: state.competitorLatestLimit }),
        ]);
        if (!accounts) return;

        // Assign colors for competitor accounts
        assignColors(accounts);

        // Store competitor data
        state.competitorAccounts = accounts;

        // Populate competitor overview account filter
        populateCompOverviewAccountFilter(accounts);

        // Update sidebar badge
        const badge = document.getElementById("sidebarCompetitorsBadge");
        if (badge) badge.textContent = accounts.length;

        // Render KPIs
        renderCompetitorKPIs(stats.global, accounts);

        // Render activity table
        state.competitorAccounts = accounts;
        state.competitorPerAccount = stats.per_account;
        renderCompetitorActivitySorted();

        // Render account cards
        state.competitorAllAccounts = accounts;
        state.competitorAllPerAccount = stats.per_account;
        updateCompetitorPlatformCounts(accounts);
        renderCompetitorAccountCardsFiltered();

        // Render videos
        renderVideoCards(bestVideos, "c-bestVideosGrid", "c-bestVideosBadge", "Top ");
        renderVideoCards(latestVideos, "c-latestVideosGrid", "c-latestVideosBadge", "");

        state.competitorDataLoaded = true;
    } catch (err) {
        console.error("Error loading competitor dashboard:", err);
    }
}

function renderCompetitorKPIs(global, accounts) {
    const el = id => document.getElementById(id);
    if (!el("c-kpiVideos")) return;
    el("c-kpiVideos").textContent = formatNumber(global.total_videos);
    el("c-kpiViews").textContent = formatNumber(global.total_views);
    el("c-kpiLikes").textContent = formatNumber(global.total_likes);
    el("c-kpiComments").textContent = formatNumber(global.total_comments);
    el("c-kpiShares").textContent = formatNumber(global.total_shares);
    el("c-kpiEngagement").textContent = global.engagement_rate.toFixed(2) + "%";
    el("c-kpiActiveAccounts").textContent = accounts ? accounts.length : 0;
    const avgViews = global.total_videos > 0 ? Math.round(global.total_views / global.total_videos) : 0;
    el("c-kpiAvgViews").textContent = formatNumber(avgViews);
}

function renderCompetitorActivitySorted() {
    const accounts = state.competitorAccounts;
    const perAccount = state.competitorPerAccount;
    const tbody = document.getElementById("c-accountActivityBody");
    const badge = document.getElementById("c-activityBadge");
    if (!tbody) return;

    if (badge) badge.textContent = accounts.length + " comptes";

    const statsMap = {};
    perAccount.forEach(s => {
        const key = s.account_username + ":" + (s.platform || "tiktok");
        statsMap[key] = s;
    });

    if (accounts.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:40px;color:#86868b">Aucun concurrent suivi. Ajoutez des comptes concurrents pour commencer.</td></tr>';
        return;
    }

    const rows = accounts.map(account => {
        const s = statsMap[account.username + ":" + (account.platform || "tiktok")] || {};
        const totalEng = (s.total_likes||0) + (s.total_comments||0) + (s.total_shares||0) + (s.total_saves||0);
        const engRate = (s.total_views||0) > 0 ? ((totalEng / s.total_views) * 100) : 0;
        const avgViews = (s.total_videos||0) > 0 ? Math.round((s.total_views||0) / s.total_videos) : 0;
        return {
            account, stats: s,
            name: (account.display_name || account.username).toLowerCase(),
            videos: s.total_videos || 0,
            views: s.total_views || 0,
            likes: s.total_likes || 0,
            engagement: engRate,
            avg_views: avgViews,
        };
    });

    const sortKey = state.competitorActivitySortBy;
    const sortDir = state.competitorActivitySortOrder === "ASC" ? 1 : -1;
    rows.sort((a, b) => {
        if (sortKey === "name") return a.name < b.name ? -1 * sortDir : a.name > b.name ? 1 * sortDir : 0;
        return (a[sortKey] - b[sortKey]) * sortDir;
    });

    // Update header indicators for competitor table
    const table = tbody.closest(".activity-table");
    if (table) {
        table.querySelectorAll("thead th.sortable").forEach(th => {
            const col = th.dataset.sort;
            const indicator = th.querySelector(".sort-indicator");
            const arrows = th.querySelector(".sort-arrows");
            if (col === sortKey) {
                th.classList.add("sorted");
                indicator.textContent = state.competitorActivitySortOrder === "DESC" ? " \u25BC" : " \u25B2";
                if (arrows) arrows.style.display = "none";
            } else {
                th.classList.remove("sorted");
                indicator.textContent = "";
                if (arrows) arrows.style.display = "";
            }
        });
    }

    const maxEng = Math.max(1, ...rows.map(r => r.engagement));

    tbody.innerHTML = rows.map(row => {
        const account = row.account;
        const color = getAccountColor(account.username);
        const initial = account.username.charAt(0).toUpperCase();
        const displayName = account.display_name || account.username;
        const pIcon = platformIcon(account.platform, 14);
        const engRate = row.engagement;
        const engClass = engRate >= 5 ? "eng-high" : engRate >= 2 ? "eng-mid" : "eng-low";
        const engBarColor = engRate >= 5 ? "var(--success)" : engRate >= 2 ? "var(--warning)" : "var(--accent)";
        const engBarWidth = Math.min(100, (engRate / Math.min(maxEng, 15)) * 100);

        return `<tr>
            <td>
                <div class="activity-account">
                    <div class="activity-avatar" style="background:${color}">${initial}</div>
                    <div class="activity-account-info">
                        <div class="activity-account-name">${pIcon} ${displayName}</div>
                        <div class="activity-account-handle">@${account.username}</div>
                    </div>
                </div>
            </td>
            <td class="text-center"><span class="activity-videos-count">${row.videos}</span></td>
            <td class="text-right"><span class="activity-metric">${formatCompact(row.views) || "0"}</span></td>
            <td class="text-right"><span class="activity-metric">${formatCompact(row.likes) || "0"}</span></td>
            <td class="text-right">
                <div class="activity-eng">
                    <span class="activity-eng-value ${engClass}">${engRate.toFixed(2)}%</span>
                    <div class="activity-eng-bar"><div class="activity-eng-bar-fill" style="width:${engBarWidth}%;background:${engBarColor}"></div></div>
                </div>
            </td>
            <td class="text-right"><span class="activity-metric">${formatCompact(row.avg_views) || "0"}</span></td>
        </tr>`;
    }).join("");
}

function sortCompetitorActivityTable(column) {
    if (state.competitorActivitySortBy === column) {
        state.competitorActivitySortOrder = state.competitorActivitySortOrder === "DESC" ? "ASC" : "DESC";
    } else {
        state.competitorActivitySortBy = column;
        state.competitorActivitySortOrder = "DESC";
    }
    renderCompetitorActivitySorted();
}

// Competitor overview filter functions
function populateCompOverviewAccountFilter(accounts) {
    const select = document.getElementById("c-overviewAccount");
    if (!select) return;
    const current = select.value;
    select.innerHTML = '<option value="all">Tous les comptes</option>';
    accounts.forEach(a => {
        const opt = document.createElement("option");
        opt.value = a.username;
        opt.textContent = "@" + a.username;
        select.appendChild(opt);
    });
    select.value = current || "all";
}

function onCompOverviewFilter() {
    const account = document.getElementById("c-overviewAccount");
    const dateFrom = document.getElementById("c-overviewDateFrom");
    const dateTo = document.getElementById("c-overviewDateTo");
    if (account) state.cOverviewAccount = account.value;
    if (dateFrom) state.cOverviewDateFrom = dateFrom.value || null;
    if (dateTo) state.cOverviewDateTo = dateTo.value || null;
    loadCompetitorDashboard();
}

function resetCompOverviewFilter() {
    state.cOverviewAccount = "all";
    state.cOverviewDateFrom = null;
    state.cOverviewDateTo = null;
    const account = document.getElementById("c-overviewAccount");
    const dateFrom = document.getElementById("c-overviewDateFrom");
    const dateTo = document.getElementById("c-overviewDateTo");
    if (account) account.value = "all";
    if (dateFrom) dateFrom.value = "";
    if (dateTo) dateTo.value = "";
    loadCompetitorDashboard();
}

// ==================== Competitor Charts ====================

async function loadCompetitorChartsData() {
    try {
        const [stats, evolution] = await Promise.all([
            fetchAPI("/api/stats", { competitor: "true" }),
            fetchAPI("/api/evolution", { competitor: "true" }),
        ]);
        if (!stats) return;
        renderCompetitorCharts(stats, evolution);
        state.competitorChartsLoaded = true;
    } catch (err) {
        console.error("Error loading competitor charts:", err);
    }
}

function renderCompetitorCharts(stats, evolution) {
    const perAccount = stats.per_account || [];
    const global = stats.global || {};

    // Timeline chart
    renderGenericTimelineChart(evolution, "c-timelineChart", "cTimeline");

    // Likes per account
    simpleBarChart("c-likesPerAccountChart", "cLikesPA",
        perAccount.map(a => accountLabel(a.account_username, a.platform)),
        perAccount.map(a => a.total_likes),
        perAccount.map(a => getAccountColor(a.account_username)),
        "Likes", "likes"
    );

    // Content per account (doughnut)
    renderGenericContentDoughnut(perAccount, "c-contentPerAccountChart", "cContentPA");

    // Avg views per account
    simpleBarChart("c-avgViewsChart", "cAvgViewsPA",
        perAccount.map(a => accountLabel(a.account_username, a.platform)),
        perAccount.map(a => a.total_videos > 0 ? Math.round(a.total_views / a.total_videos) : 0),
        perAccount.map(a => getAccountColor(a.account_username)),
        "Moy. vues/video", "vues/video"
    );

    // Shares per account
    simpleBarChart("c-sharesPerAccountChart", "cSharesPA",
        perAccount.map(a => accountLabel(a.account_username, a.platform)),
        perAccount.map(a => a.total_shares),
        perAccount.map(a => getAccountColor(a.account_username)),
        "Partages", "partages"
    );

    // Comments per account
    simpleBarChart("c-commentsPerAccountChart", "cCommentsPA",
        perAccount.map(a => accountLabel(a.account_username, a.platform)),
        perAccount.map(a => a.total_comments),
        perAccount.map(a => getAccountColor(a.account_username)),
        "Commentaires", "commentaires"
    );
}

function renderGenericTimelineChart(evolution, canvasId, chartKey) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    if (state.charts[chartKey]) state.charts[chartKey].destroy();

    const dateMap = {};
    evolution.forEach(d => {
        if (!dateMap[d.date]) dateMap[d.date] = { likes: 0, comments: 0, shares: 0 };
        dateMap[d.date].likes += d.likes || 0;
        dateMap[d.date].comments += d.comments || 0;
        dateMap[d.date].shares += d.shares || 0;
    });

    const dates = Object.keys(dateMap).sort();
    state.charts[chartKey] = new Chart(ctx, {
        type: "line",
        data: {
            labels: dates.map(d => { const dt = new Date(d); return dt.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' }); }),
            datasets: [
                { label: "Likes", data: dates.map(d => dateMap[d].likes), borderColor: "#fe2c55", backgroundColor: "rgba(254,44,85,0.1)", tension: 0.3, fill: true },
                { label: "Commentaires", data: dates.map(d => dateMap[d].comments), borderColor: "#25f4ee", backgroundColor: "rgba(37,244,238,0.1)", tension: 0.3, fill: true },
                { label: "Partages", data: dates.map(d => dateMap[d].shares), borderColor: "#ffaa00", backgroundColor: "rgba(255,170,0,0.1)", tension: 0.3, fill: true },
            ],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { labels: { color: "#8888aa", font: { size: 11 } } },
                tooltip: { backgroundColor: "#1a1a2e", titleColor: "#f0f0f5", bodyColor: "#8888aa", borderColor: "#2a2a40", borderWidth: 1, callbacks: { label: ctx => ctx.dataset.label + ": " + formatNumber(ctx.raw) } },
                datalabels: { display: false },
            },
            scales: {
                x: { grid: { display: false }, ticks: { color: "#8888aa", font: { size: 10 }, maxTicksLimit: 10 } },
                y: { grid: { color: "#1a1a2e" }, ticks: { color: "#555570", callback: v => formatNumber(v) } },
            },
        },
    });
}

function renderGenericContentDoughnut(perAccount, canvasId, chartKey) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    if (state.charts[chartKey]) state.charts[chartKey].destroy();
    const usernames = perAccount.map(a => accountLabel(a.account_username, a.platform));
    const colors = perAccount.map(a => getAccountColor(a.account_username));
    state.charts[chartKey] = new Chart(ctx, {
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

// ==================== Competitor Table ====================

async function loadCompetitorTableData() {
    try {
        const bestLimitVal = state.cTableBestLimit === 'all' ? 9999 : state.cTableBestLimit;
        const latestLimitVal = state.cTableLatestLimit === 'all' ? 9999 : state.cTableLatestLimit;
        const [best, latest] = await Promise.all([
            fetchAPI("/api/best-videos", { competitor: "true", limit: bestLimitVal }),
            fetchAPI("/api/latest-videos", {
                competitor: "true",
                limit: latestLimitVal,
                date_from: state.cTableLatestDateFrom,
                date_to: state.cTableLatestDateTo,
            }),
        ]);
        if (!best) return;
        renderVideoCards(best, "c-tableBestGrid", "c-tableBestBadge", "Top ");
        renderVideoCards(latest, "c-tableLatestGrid", "c-tableLatestBadge", "");
        state.competitorTableLoaded = true;
    } catch (err) {
        console.error("Error loading competitor table:", err);
    }
}

function setCTableBestLimit(n) {
    state.cTableBestLimit = n;
    document.querySelectorAll("#c-tableBestLimit .limit-btn").forEach(b => b.classList.toggle("active", b.dataset.limit === String(n)));
    state.competitorTableLoaded = false;
    loadCompetitorTableData();
}

function setCTableLatestLimit(n) {
    state.cTableLatestLimit = n;
    document.querySelectorAll("#c-tableLatestLimit .limit-btn").forEach(b => b.classList.toggle("active", b.dataset.limit === String(n)));
    state.competitorTableLoaded = false;
    loadCompetitorTableData();
}

function onCTableLatestDateFilter() {
    state.cTableLatestDateFrom = document.getElementById("c-tableLatestDateFrom").value || null;
    state.cTableLatestDateTo = document.getElementById("c-tableLatestDateTo").value || null;
    state.competitorTableLoaded = false;
    loadCompetitorTableData();
}

function clearCTableLatestDateFilter() {
    state.cTableLatestDateFrom = null;
    state.cTableLatestDateTo = null;
    document.getElementById("c-tableLatestDateFrom").value = "";
    document.getElementById("c-tableLatestDateTo").value = "";
    state.competitorTableLoaded = false;
    loadCompetitorTableData();
}

function updateCompetitorPlatformCounts(accounts) {
    const counts = { tiktok: 0, instagram: 0, youtube: 0 };
    accounts.forEach(a => {
        const p = a.platform || "tiktok";
        if (counts[p] !== undefined) counts[p]++;
    });
    const el = id => document.getElementById(id);
    if (el("c-countTiktok")) el("c-countTiktok").textContent = counts.tiktok;
    if (el("c-countInstagram")) el("c-countInstagram").textContent = counts.instagram;
    if (el("c-countYoutube")) el("c-countYoutube").textContent = counts.youtube;
}

function filterCompetitorByPlatform(platform) {
    state.competitorPlatformFilter = platform;
    const container = document.getElementById("c-platformFilters");
    if (container) {
        container.querySelectorAll(".platform-pill").forEach(btn => {
            btn.classList.toggle("active", btn.dataset.platform === platform);
        });
    }
    renderCompetitorAccountCardsFiltered();
}

function renderCompetitorAccountCardsFiltered() {
    const accounts = state.competitorPlatformFilter === "all"
        ? state.competitorAllAccounts
        : state.competitorAllAccounts.filter(a => (a.platform || "tiktok") === state.competitorPlatformFilter);
    const perAccount = state.competitorAllPerAccount;

    const container = document.getElementById("c-accountCards");
    if (!container) return;
    const statsMap = {};
    perAccount.forEach(s => {
        const key = s.account_username + ":" + (s.platform || "tiktok");
        statsMap[key] = s;
    });

    const badge = document.getElementById("c-accountsBadge");
    if (badge) {
        if (state.competitorPlatformFilter === "all") {
            badge.textContent = state.competitorAllAccounts.length + " comptes";
        } else {
            badge.textContent = accounts.length + " / " + state.competitorAllAccounts.length + " comptes";
        }
    }

    if (accounts.length === 0) {
        container.innerHTML = `
            <div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-3)">
                <p style="font-size:32px;margin-bottom:12px">&#128269;</p>
                <p>Aucun concurrent${state.competitorPlatformFilter !== 'all' ? ' sur cette plateforme' : ' suivi'}.</p>
                <button class="btn btn-primary" style="margin-top:16px" onclick="openCompetitorModal()">Ajouter un concurrent</button>
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
            <div class="account-card">
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

function setCompetitorBestLimit(n) {
    state.competitorBestLimit = n;
    document.querySelectorAll("#c-bestVideosLimit .limit-btn").forEach(b => b.classList.toggle("active", parseInt(b.dataset.limit) === n));
    loadCompetitorDashboard();
}

function setCompetitorLatestLimit(n) {
    state.competitorLatestLimit = n;
    document.querySelectorAll("#c-latestVideosLimit .limit-btn").forEach(b => b.classList.toggle("active", parseInt(b.dataset.limit) === n));
    loadCompetitorDashboard();
}

// Competitor account management modal
function openCompetitorModal() {
    document.getElementById("competitorModal").classList.remove("hidden");
    loadCompetitorList();
}

function closeCompetitorModal() {
    document.getElementById("competitorModal").classList.add("hidden");
}

async function loadCompetitorList() {
    const accounts = await fetchAPI("/api/accounts", { competitor: "true" });
    if (!accounts) return;
    const list = document.getElementById("competitorList");
    if (accounts.length === 0) {
        list.innerHTML = '<p style="text-align:center;color:var(--text-muted);padding:16px">Aucun concurrent suivi</p>';
        return;
    }
    list.innerHTML = accounts.map(a => {
        const pIcon = platformIcon(a.platform);
        return `
        <div class="account-list-item">
            <span class="account-list-name">${pIcon} @${a.username}</span>
            <button class="btn-remove" onclick="removeCompetitor('${a.username}')">Supprimer</button>
        </div>
    `}).join("");
}

async function addCompetitor() {
    const input = document.getElementById("competitorInput");
    const platformSelect = document.getElementById("competitorPlatform");
    const username = input.value.trim().replace("@", "");
    const platform = platformSelect ? platformSelect.value : "tiktok";
    if (!username) return;
    try {
        const res = await fetch("/api/accounts/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, platform, is_competitor: true })
        });
        if (res.status === 401) { window.location.href = "/login"; return; }
        if (!res.ok) {
            const data = await res.json().catch(() => ({}));
            showStatus(data.error || "Erreur lors de l'ajout", "error");
            return;
        }
        input.value = "";
        loadCompetitorList();
        state.competitorDataLoaded = false;
        loadCompetitorDashboard();
        showStatus(`Concurrent @${username} ajouté ! Lancez un scraping pour récupérer les données.`, "success");
    } catch (err) {
        showStatus("Erreur lors de l'ajout", "error");
    }
}

async function removeCompetitor(username) {
    if (!confirm(`Supprimer le concurrent @${username} et toutes ses données ?`)) return;
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
        loadCompetitorList();
        state.competitorDataLoaded = false;
        loadCompetitorDashboard();
        showStatus(`Concurrent @${username} supprimé`, "success");
    } catch (err) {
        showStatus("Erreur lors de la suppression", "error");
    }
}

// Auto-refresh removed — scraping is manual or on page load

// Init
document.addEventListener("DOMContentLoaded", () => {
    // Add sidebar overlay for mobile
    const overlay = document.createElement("div");
    overlay.className = "sidebar-overlay";
    overlay.id = "sidebarOverlay";
    overlay.onclick = closeSidebar;
    document.body.appendChild(overlay);

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
    // Load analytics overview (default page)
    loadAnalyticsOverview();
    // Load competitor count for sidebar badge
    fetchAPI("/api/accounts", { competitor: "true" }).then(accounts => {
        if (accounts) {
            const badge = document.getElementById("sidebarCompetitorsBadge");
            if (badge) badge.textContent = accounts.length;
        }
    });
    // Initialiser le toggle auto-scrape depuis localStorage
    initAutoScrapeToggle();
    // Auto-scrape au chargement (seulement si activé)
    autoScrapeOnLoad();
});

function initAutoScrapeToggle() {
    const toggle = document.getElementById("autoScrapeToggle");
    if (!toggle) return;
    const saved = localStorage.getItem("autoScrapeEnabled");
    // Activé par défaut (toutes plateformes scrapées au chargement)
    toggle.checked = saved !== "false";
}

function toggleAutoScrape(enabled) {
    localStorage.setItem("autoScrapeEnabled", enabled ? "true" : "false");
}

async function autoScrapeOnLoad() {
    try {
        // Vérifier si un scraping est déjà en cours
        const status = await fetchAPI("/api/scrape-status");
        if (status && status.active) {
            // Scraping déjà en cours, juste suivre la progression
            const btn = document.getElementById("scrapeBtn");
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner" style="width:14px;height:14px;border-width:2px;display:inline-block"></span> Scraping...';
            lastCompletedCount = status.completed || 0;
            startScrapePolling();
            return;
        }
        // Display last sync info if we have a previous scrape on record
        if (status && status.finished_at) {
            const dur = status.started_at ? (status.finished_at - status.started_at) : 0;
            updateLastSyncLabel(status.finished_at, dur);
        }
        // Lancer le scraping automatiquement (activé par défaut, toutes plateformes)
        const autoEnabled = localStorage.getItem("autoScrapeEnabled") !== "false";
        if (autoEnabled) {
            startScraping();
        }
    } catch (e) {
        console.error("Auto-scrape error:", e);
    }
}
