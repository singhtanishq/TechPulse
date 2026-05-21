/* =========================================================
   TECHPULSE — APPLICATION
   ========================================================= */

document.addEventListener("DOMContentLoaded", async () => {
    await window.TechPulseData.load();
    updateAll();
    updatePageSpecific();
});

/* =========================================================
   MAIN UPDATE
   ========================================================= */

function updateAll() {
    updateMeta();
    updateSnapshot();
    updateSecurity();
    updateReleases();
    updateOpenSource();
    updateTechnology();
    updateHistory();
    updateStatus();
}

/* =========================================================
   META
   ========================================================= */

function updateMeta() {
    const data = window.TechPulseData.get().meta;

    const dateElement = document.querySelector("[data-today]");
    const observationsElement = document.querySelector("[data-observations]");
    const pageDateElement = document.querySelector("[data-page-date]");
    const snapshotDateElement = document.querySelector("[data-snapshot-date]");
    const securityDateElement = document.querySelector("[data-security-date]");
    const releasesDateElement = document.querySelector("[data-releases-date]");
    const pageUpdatedElements = document.querySelectorAll("[data-page-updated]");

    const formattedDate = formatDate(data.date);

    if (dateElement) dateElement.textContent = formattedDate;
    if (pageDateElement) pageDateElement.textContent = formattedDate;
    if (snapshotDateElement) snapshotDateElement.textContent = formattedDate;
    if (securityDateElement) securityDateElement.textContent = formattedDate;
    if (releasesDateElement) releasesDateElement.textContent = formattedDate;

    pageUpdatedElements.forEach(el => {
        if (data.generatedAt) {
            const d = new Date(data.generatedAt);
            el.textContent = d.toLocaleDateString("en-GB", {
                day: "2-digit", month: "short", year: "numeric",
                hour: "2-digit", minute: "2-digit", timeZone: "UTC"
            }).toUpperCase() + " UTC";
        }
    });

    if (observationsElement) {
        observationsElement.textContent = String(data.daysObserved || 0).padStart(3, "0");
    }
}

/* =========================================================
   SNAPSHOT
   ========================================================= */

function updateSnapshot() {
    const snapshot = window.TechPulseData.get().snapshot;

    setText("[data-cves]", snapshot.cves);
    setText("[data-known-exploited]", snapshot.knownExploited);
    setText("[data-releases]", snapshot.releases);
    setText("[data-projects]", snapshot.projects);
    setText("[data-tech-entries]", snapshot.techEntries);
}

/* =========================================================
   SECURITY
   ========================================================= */

function updateSecurity() {
    const security = window.TechPulseData.get().security;

    // Update severity counts
    setText("[data-critical]", security.critical);
    setText("[data-high]", security.high);
    setText("[data-medium]", security.medium);
    setText("[data-low]", security.low);
    setText("[data-kev]", security.critical + security.high); // Approximation

    // Update latest vulnerabilities list
    const container = document.querySelector("[data-security-latest]");
    if (container && Array.isArray(security.latest)) {
        renderVulnerabilityList(container, security.latest);
    }

    // Security page specific
    const vulnListContainer = document.querySelector("[data-vulnerability-list]");
    if (vulnListContainer && Array.isArray(security.latest)) {
        renderFullVulnerabilityList(vulnListContainer, security.latest);
    }

    const historyContainer = document.querySelector("[data-security-history]");
    const history = window.TechPulseData.get().history;
    if (historyContainer && Array.isArray(history)) {
        renderSecurityHistory(historyContainer, history);
    }
}

/* =========================================================
   RELEASES
   ========================================================= */

function updateReleases() {
    const releases = window.TechPulseData.get().releases;

    // Update category counts
    const categories = { major: 0, minor: 0, patch: 0 };
    releases.forEach(r => {
        const version = (r.version || "").replace(/^v/, "");
        const parts = version.split(".");
        if (parts.length >= 3) {
            const major = parseInt(parts[0]) || 0;
            const minor = parseInt(parts[1]) || 0;
            const patch = parseInt(parts[2]) || 0;
            if (minor === 0 && patch === 0) categories.major++;
            else if (patch === 0) categories.minor++;
            else categories.patch++;
        }
    });

    setText("[data-releases-count]", releases.length);
    setText("[data-releases-major]", categories.major);
    setText("[data-releases-minor]", categories.minor);
    setText("[data-releases-patch]", categories.patch);

    // Releases list
    const listContainer = document.querySelector("[data-releases-list]");
    if (listContainer && Array.isArray(releases)) {
        renderReleasesTable(listContainer, releases);
    }

    // Tracked projects
    const projectsContainer = document.querySelector("[data-tracked-projects]");
    const opensource = window.TechPulseData.get().openSource;
    if (projectsContainer && Array.isArray(opensource)) {
        renderTrackedProjects(projectsContainer, opensource);
    }
}

/* =========================================================
   OPEN SOURCE
   ========================================================= */

function updateOpenSource() {
    const projects = window.TechPulseData.get().openSource;
    const container = document.querySelector("[data-opensource-list]");
    if (container && Array.isArray(projects)) {
        renderOpenSourceList(container, projects);
    }
}

/* =========================================================
   TECHNOLOGY
   ========================================================= */

function updateTechnology() {
    const entries = window.TechPulseData.get().technology;
    const container = document.querySelector("[data-technology-list]");
    if (container && Array.isArray(entries)) {
        renderTechList(container, entries);
    }
}

/* =========================================================
   HISTORY
   ========================================================= */

function updateHistory() {
    const history = window.TechPulseData.get().history;

    // Index page preview
    const previewContainer = document.querySelector("[data-history-preview]");
    if (previewContainer && Array.isArray(history)) {
        renderHistoryPreview(previewContainer, history.slice(0, 5));
    }

    // History page full list
    const listContainer = document.querySelector("[data-history-list]");
    if (listContainer && Array.isArray(history)) {
        renderHistoryList(listContainer, history);
    }

    // Archive status
    const statusElement = document.querySelector("[data-archive-status]");
    if (statusElement) {
        statusElement.textContent = history.length > 0 ? `${history.length} snapshots` : "No snapshots";
    }
}

/* =========================================================
   STATUS
   ========================================================= */

function updateStatus() {
    const data = window.TechPulseData.get();
    const sources = data.sources || {};

    const dotElements = document.querySelectorAll("[data-status-dot]");
    const textElements = document.querySelectorAll("[data-status-text]");
    const mainStatusElement = document.querySelector("[data-status-main]");

    // Check if any source failed
    let hasFailure = false;
    Object.values(sources).forEach(src => {
        if (src && typeof src === 'object') {
            Object.values(src).forEach(s => {
                if (s && s.status === 'failed') hasFailure = true;
            });
        }
    });

    const isLoaded = window.TechPulseData.isLoaded();

    dotElements.forEach(el => {
        if (!isLoaded) {
            el.style.background = '#f6c85f';
            el.style.boxShadow = '0 0 0 3px rgba(246, 200, 95, 0.08), 0 0 12px rgba(246, 200, 95, 0.45)';
        } else if (hasFailure) {
            el.style.background = '#ff6b6b';
            el.style.boxShadow = '0 0 0 3px rgba(255, 107, 107, 0.08), 0 0 12px rgba(255, 107, 107, 0.45)';
        }
    });

    textElements.forEach(el => {
        if (!isLoaded) el.textContent = 'Loading...';
        else if (hasFailure) el.textContent = 'Degraded';
        else el.textContent = 'Live';
    });

    if (mainStatusElement) {
        if (!isLoaded) {
            mainStatusElement.textContent = '● LOADING';
            mainStatusElement.style.color = '#f6c85f';
        } else if (hasFailure) {
            mainStatusElement.textContent = '● DEGRADED';
            mainStatusElement.style.color = '#ff6b6b';
        } else {
            mainStatusElement.textContent = '● LIVE';
            mainStatusElement.style.color = '#5eead4';
        }
    }
}

/* =========================================================
   PAGE SPECIFIC
   ========================================================= */

function updatePageSpecific() {
    // Security page filters
    initSecurityFilters();

    // Navigation active state
    updateNavActive();
}

/* =========================================================
   RENDERERS
   ========================================================= */

function renderVulnerabilityList(container, vulnerabilities) {
    if (!vulnerabilities.length) {
        container.innerHTML = '<div class="empty-state">No vulnerability data available</div>';
        return;
    }

    container.innerHTML = vulnerabilities.slice(0, 5).map(vuln => `
        <div class="list-item">
            <div>
                <strong>${escapeHtml(vuln.id)}</strong>
                <span>${escapeHtml(vuln.title)}</span>
            </div>
            <span class="severity ${(vuln.severity || '').toLowerCase()}">${escapeHtml(vuln.severity || 'UNKNOWN')}</span>
        </div>
    `).join('');
}

function renderFullVulnerabilityList(container, vulnerabilities) {
    if (!vulnerabilities.length) {
        container.innerHTML = '<div class="empty-state">No vulnerability data available for this period</div>';
        return;
    }

    container.innerHTML = vulnerabilities.map(vuln => `
        <article class="vulnerability-card" data-severity="${(vuln.severity || '').toLowerCase()}">
            <div class="vulnerability-id">
                <span>CVE</span>
                <strong>${escapeHtml(vuln.id)}</strong>
            </div>
            <div class="vulnerability-content">
                <h3>${escapeHtml(vuln.title)}</h3>
                <p>${escapeHtml(vuln.description || 'No description available')}</p>
                <div class="vulnerability-meta">
                    <span>${escapeHtml(vuln.published || 'Unknown date')}</span>
                    ${vuln.cvss_score ? `<span>CVSS ${vuln.cvss_version}: ${vuln.cvss_score}</span>` : ''}
                    ${vuln.known_exploited ? '<span class="kev-badge">KNOWN EXPLOITED</span>' : ''}
                </div>
            </div>
            <span class="severity ${(vuln.severity || '').toLowerCase()}">${escapeHtml(vuln.severity || 'UNKNOWN')}</span>
        </article>
    `).join('');

    // Add filter functionality
    initVulnerabilityFilters(container);
}

function renderSecurityHistory(container, history) {
    if (!history.length) {
        container.innerHTML = '<div class="empty-state">No historical security data available</div>';
        return;
    }

    container.innerHTML = history.map(item => `
        <div class="security-history-row">
            <span class="history-date">${formatDate(item.date)}</span>
            <span>${item.cves || 0} CVEs</span>
            <span>${item.knownExploited || 0} Exploited</span>
            <span>${item.releases || 0} Releases</span>
        </div>
    `).join('');
}

function renderReleasesTable(container, releases) {
    if (!releases.length) {
        container.innerHTML = '<div class="empty-state">No release data available for this period</div>';
        return;
    }

    container.innerHTML = releases.map(rel => {
        const version = rel.version || "";
        let badgeClass = "patch";
        const parts = version.replace(/^v/, "").split(".");
        if (parts.length >= 3) {
            const major = parseInt(parts[0]) || 0;
            const minor = parseInt(parts[1]) || 0;
            const patch = parseInt(parts[2]) || 0;
            if (minor === 0 && patch === 0) badgeClass = "major";
            else if (patch === 0) badgeClass = "minor";
        }
        return `
            <article class="release-row">
                <div class="release-project">
                    <div class="release-icon">${escapeHtml((rel.project || 'X')[0].toUpperCase())}</div>
                    <div>
                        <strong>${escapeHtml(rel.project)}</strong>
                        <span>${escapeHtml(rel.repository)}</span>
                    </div>
                </div>
                <div class="release-version">
                    <span>VERSION</span>
                    <strong>${escapeHtml(version)}</strong>
                </div>
                <div class="release-type">
                    <span class="release-badge ${badgeClass}">${badgeClass.toUpperCase()}</span>
                </div>
                <time>${escapeHtml(rel.date || 'Unknown')}</time>
            </article>
        `;
    }).join('');
}

function renderTrackedProjects(container, projects) {
    if (!projects.length) {
        container.innerHTML = '<div class="empty-state">No project data available</div>';
        return;
    }

    container.innerHTML = projects.map(proj => `
        <div class="tracked-project">
            <strong>${escapeHtml(proj.name)}</strong>
            <span>${escapeHtml(proj.full_name)}</span>
        </div>
    `).join('');
}

function renderOpenSourceList(container, projects) {
    if (!projects.length) {
        container.innerHTML = '<div class="empty-state">No open source data available</div>';
        return;
    }

    container.innerHTML = projects.slice(0, 10).map(proj => `
        <article class="opensource-card">
            <div class="opensource-rank">#${String(proj.rank || 0).padStart(2, '0')}</div>
            <div class="opensource-main">
                <div class="opensource-header">
                    <div>
                        <h3>${escapeHtml(proj.name)}</h3>
                        <span class="opensource-label">${escapeHtml(proj.language || 'Unknown')}</span>
                    </div>
                    <div class="opensource-growth">
                        ${proj.daily_growth !== null ? `+${formatNumber(proj.daily_growth)} <span>today</span>` : '<span class="growth-na">N/A</span>'}
                    </div>
                </div>
                <p>${escapeHtml(proj.description || 'No description available')}</p>
                <div class="opensource-stats">
                    <div><strong>${formatNumber(proj.stars)}</strong><span>Stars</span></div>
                    <div><strong>${proj.daily_growth !== null ? formatNumber(proj.daily_growth) : '—'}</strong><span>Daily growth</span></div>
                    <div><strong>${escapeHtml(proj.language || 'Unknown')}</strong><span>Language</span></div>
                </div>
            </div>
        </article>
    `).join('');
}

function renderTechList(container, entries) {
    if (!entries.length) {
        container.innerHTML = '<div class="empty-state">No technology updates available</div>';
        return;
    }

    container.innerHTML = entries.slice(0, 10).map(entry => `
        <div class="tech-item">
            <h4><a href="${escapeHtml(entry.url)}" target="_blank" rel="noopener">${escapeHtml(entry.title)}</a></h4>
            <div class="tech-meta">
                <span class="tech-source">${escapeHtml(entry.source)}</span>
                <span class="tech-category">${escapeHtml(entry.category)}</span>
                <span class="tech-date">${escapeHtml(entry.date)}</span>
            </div>
            <p>${escapeHtml(entry.summary)}</p>
        </div>
    `).join('');
}

function renderHistoryPreview(container, history) {
    if (!history.length) {
        container.innerHTML = '<div class="empty-state">No history available</div>';
        return;
    }

    container.innerHTML = `
        <div class="timeline-year">${new Date().getUTCFullYear()}</div>
        <div class="timeline">
            ${history.map((item, i) => `
                <div class="timeline-item ${i === 0 ? 'active' : ''}">
                    <span>${new Date(item.date + 'T00:00:00Z').getUTCDate()}</span>
                    <div>
                        <strong>${new Date(item.date + 'T00:00:00Z').toLocaleDateString('en-GB', {month: 'long', timeZone: 'UTC'})}</strong>
                        <small>${item.cves || 0} CVEs · ${item.releases || 0} releases</small>
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

function renderHistoryList(container, history) {
    if (!history.length) {
        container.innerHTML = '<div class="empty-state">No historical snapshots available yet</div>';
        return;
    }

    container.innerHTML = history.map(item => `
        <article class="history-card">
            <div class="history-date">
                <strong>${new Date(item.date + 'T00:00:00Z').getUTCDate()}</strong>
                <span>${new Date(item.date + 'T00:00:00Z').toLocaleDateString('en-GB', {month: 'short', year: 'numeric', timeZone: 'UTC'}).toUpperCase()}</span>
            </div>
            <div class="history-content">
                <div class="history-header">
                    <div>
                        <h3>Daily Technology Snapshot</h3>
                        <span>${new Date(item.date + 'T00:00:00Z').toLocaleDateString('en-GB', {weekday: 'long', timeZone: 'UTC'})}${item.date === window.TechPulseData.get().meta.date ? ' · Today' : ''}</span>
                    </div>
                </div>
                <div class="history-stats">
                    <div><strong>${item.cves || 0}</strong><span>CVEs</span></div>
                    <div><strong>${item.knownExploited || 0}</strong><span>Exploited</span></div>
                    <div><strong>${item.releases || 0}</strong><span>Releases</span></div>
                    <div><strong>${item.projects || 0}</strong><span>Projects</span></div>
                    <div><strong>${item.techEntries || 0}</strong><span>Tech</span></div>
                </div>
            </div>
        </article>
    `).join('');
}

/* =========================================================
   FILTERS
   ========================================================= */

function initSecurityFilters() {
    const filterButtons = document.querySelectorAll("[data-filter]");
    const vulnCards = document.querySelectorAll(".vulnerability-card");

    filterButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            filterButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");

            const filter = btn.dataset.filter;
            vulnCards.forEach(card => {
                if (filter === "all" || card.dataset.severity === filter) {
                    card.style.display = "grid";
                } else {
                    card.style.display = "none";
                }
            });
        });
    });
}

function initVulnerabilityFilters(container) {
    // Filters are initialized once in initSecurityFilters
}

function updateNavActive() {
    const currentPage = window.location.pathname.split('/').pop() || 'index.html';
    const navLinks = document.querySelectorAll(".main-nav a[data-nav]");
    navLinks.forEach(link => {
        const page = link.dataset.nav;
        const href = link.getAttribute('href');
        if ((page === 'today' && (currentPage === 'index.html' || currentPage === '')) ||
            href === currentPage) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
}

/* =========================================================
   HELPERS
   ========================================================= */

function setText(selector, value) {
    const element = document.querySelector(selector);
    if (element) {
        element.textContent = value !== null && value !== undefined ? value : '—';
    }
}

function formatDate(dateString) {
    if (!dateString) return '—';
    const date = new Date(`${dateString}T00:00:00Z`);
    return date.toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        timeZone: "UTC"
    }).toUpperCase();
}

function formatNumber(num) {
    if (num === null || num === undefined) return '—';
    return num.toLocaleString();
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}