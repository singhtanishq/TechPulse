/* =========================================================
   TECHPULSE — APPLICATION
   ========================================================= */

document.addEventListener("DOMContentLoaded", async () => {
    await window.TechPulseData.load();
    updateAll();
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
}

/* =========================================================
   META
   ========================================================= */

function updateMeta() {
    const data = window.TechPulseData.get().meta;

    const dateElement = document.querySelector("[data-today]");
    const observationsElement = document.querySelector("[data-observations]");

    if (dateElement && data.date) {
        dateElement.textContent = formatDate(data.date);
    }

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

    // Update latest vulnerabilities list
    const container = document.querySelector("[data-security-latest]");
    if (container && Array.isArray(security.latest)) {
        renderVulnerabilityList(container, security.latest);
    }
}

/* =========================================================
   RELEASES
   ========================================================= */

function updateReleases() {
    const releases = window.TechPulseData.get().releases;
    const container = document.querySelector("[data-releases-list]");
    if (container && Array.isArray(releases)) {
        renderReleaseList(container, releases);
    }
}

/* =========================================================
   OPEN SOURCE
   ========================================================= */

function updateOpenSource() {
    const projects = window.TechPulseData.get().openSource;
    const container = document.querySelector("[data-opensource-list]");
    if (container && Array.isArray(projects)) {
        renderProjectList(container, projects);
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
    const container = document.querySelector("[data-history-list]");
    if (container && Array.isArray(history)) {
        renderHistoryList(container, history);
    }
}

/* =========================================================
   RENDERERS
   ========================================================= */

function renderVulnerabilityList(container, vulnerabilities) {
    if (!vulnerabilities.length) {
        container.innerHTML = '<div class="empty-state">No vulnerability data available</div>';
        return;
    }

    container.innerHTML = vulnerabilities.map(vuln => `
        <div class="vulnerability-item">
            <div class="vuln-id">
                <span class="vuln-label">CVE</span>
                <strong>${escapeHtml(vuln.id)}</strong>
            </div>
            <div class="vuln-content">
                <h4>${escapeHtml(vuln.title)}</h4>
                <div class="vuln-meta">
                    <span>${escapeHtml(vuln.published || 'Unknown date')}</span>
                    ${vuln.cvss_score ? `<span>CVSS ${vuln.cvss_version}: ${vuln.cvss_score}</span>` : ''}
                    ${vuln.known_exploited ? '<span class="kev-badge">KNOWN EXPLOITED</span>' : ''}
                </div>
            </div>
            <span class="severity ${(vuln.severity || '').toLowerCase()}">${escapeHtml(vuln.severity || 'UNKNOWN')}</span>
        </div>
    `).join('');
}

function renderReleaseList(container, releases) {
    if (!releases.length) {
        container.innerHTML = '<div class="empty-state">No release data available</div>';
        return;
    }

    container.innerHTML = releases.map(rel => `
        <div class="release-row">
            <div class="release-project">
                <strong>${escapeHtml(rel.project)}</strong>
                <span>${escapeHtml(rel.repository)}</span>
            </div>
            <div class="release-version">
                <span class="release-badge">${escapeHtml(rel.version)}</span>
            </div>
            <time>${escapeHtml(rel.date || 'Unknown')}</time>
            ${rel.url ? `<a href="${escapeHtml(rel.url)}" target="_blank" rel="noopener">View</a>` : ''}
        </div>
    `).join('');
}

function renderProjectList(container, projects) {
    if (!projects.length) {
        container.innerHTML = '<div class="empty-state">No open source data available</div>';
        return;
    }

    container.innerHTML = projects.map(proj => `
        <div class="project-card">
            <div class="project-rank">#${String(proj.rank).padStart(2, '0')}</div>
            <div class="project-content">
                <h3>${escapeHtml(proj.name)}</h3>
                <p>${escapeHtml(proj.description || 'No description available')}</p>
                <div class="project-meta">
                    <span>★ ${formatNumber(proj.stars)}</span>
                    ${proj.daily_growth !== null ? `<span class="growth">+${formatNumber(proj.daily_growth)} today</span>` : '<span class="growth-na">Growth: N/A</span>'}
                    <span>${escapeHtml(proj.language || 'Unknown')}</span>
                </div>
            </div>
        </div>
    `).join('');
}

function renderTechList(container, entries) {
    if (!entries.length) {
        container.innerHTML = '<div class="empty-state">No technology updates available</div>';
        return;
    }

    container.innerHTML = entries.map(entry => `
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

function renderHistoryList(container, history) {
    if (!history.length) {
        container.innerHTML = '<div class="empty-state">No historical data available</div>';
        return;
    }

    container.innerHTML = history.map(item => `
        <div class="history-item">
            <div class="history-date">
                <strong>${formatDate(item.date)}</strong>
            </div>
            <div class="history-stats">
                <div><strong>${item.cves || 0}</strong><span>CVEs</span></div>
                <div><strong>${item.knownExploited || 0}</strong><span>Exploited</span></div>
                <div><strong>${item.releases || 0}</strong><span>Releases</span></div>
                <div><strong>${item.projects || 0}</strong><span>Projects</span></div>
                <div><strong>${item.techEntries || 0}</strong><span>Tech</span></div>
            </div>
        </div>
    `).join('');
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
    if (!dateString) return '';
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