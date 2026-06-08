/* =========================================================
   TECHPULSE — APPLICATION
   Renders all pages from generated data (loaded in data.js).

   Design rules:
     - Every list has an honest empty state; no fabricated values.
     - Unscored CVEs render explicitly as UNSCORED, never as zeros
       or LOW severity.
     - External content is escaped and URL-checked (see components.js).
   ========================================================= */

document.addEventListener("DOMContentLoaded", async () => {
    await window.TechPulseData.load();
    updateAll();
    await updatePageSpecific();
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

async function updatePageSpecific() {
    if (document.querySelector("[data-archive-list]")) {
        await window.TechPulseData.loadArchive();
        renderArchivePage();
    }
    updateNavActive();
}

/* =========================================================
   META
   ========================================================= */

function updateMeta() {
    const data = window.TechPulseData.get().meta;

    const formattedDate = data.date ? formatDisplayDate(data.date) : "—";

    setText("[data-today]", formattedDate);
    setText("[data-page-date]", formattedDate);
    setText("[data-snapshot-date]", formattedDate);
    setText("[data-security-date]", formattedDate);
    setText("[data-releases-date]", formattedDate);

    document.querySelectorAll("[data-page-updated]").forEach((el) => {
        if (data.generatedAt) {
            const d = new Date(data.generatedAt);
            if (!Number.isNaN(d.getTime())) {
                el.textContent = d.toLocaleString("en-GB", {
                    day: "2-digit", month: "short", year: "numeric",
                    hour: "2-digit", minute: "2-digit", timeZone: "UTC",
                }).toUpperCase() + " UTC";
                return;
            }
        }
        el.textContent = "—";
    });

    const observations = document.querySelector("[data-observations]");
    if (observations) {
        observations.textContent = String(data.daysObserved || 0).padStart(3, "0");
    }
}

/* =========================================================
   SNAPSHOT METRICS
   ========================================================= */

function updateSnapshot() {
    const snapshot = window.TechPulseData.get().snapshot;
    setText("[data-cves]", snapshot.cves);
    setText("[data-known-exploited]", snapshot.knownExploited);
    setText("[data-kev]", snapshot.knownExploited);
    setText("[data-releases]", snapshot.releases);
    setText("[data-projects]", snapshot.projects);
    setText("[data-tech-entries]", snapshot.techEntries);
}

/* =========================================================
   SECURITY
   ========================================================= */

function updateSecurity() {
    const security = window.TechPulseData.get().security;

    setText("[data-critical]", security.critical);
    setText("[data-high]", security.high);
    setText("[data-medium]", security.medium);
    setText("[data-low]", security.low);
    setText("[data-unscored]", security.unscored);

    const homeList = document.querySelector("[data-security-latest]");
    if (homeList) {
        renderHomeVulnerabilityList(homeList, security.latest);
    }

    const fullList = document.querySelector("[data-vulnerability-list]");
    if (fullList) {
        renderVulnerabilityCards(fullList, security.latest);
        initSecurityFilters();
    }

    const historyBlock = document.querySelector("[data-security-history]");
    if (historyBlock) {
        renderSecurityHistory(historyBlock, window.TechPulseData.get().history);
    }
}

function renderHomeVulnerabilityList(container, vulnerabilities) {
    if (!Array.isArray(vulnerabilities) || !vulnerabilities.length) {
        renderEmptyState(container, "No vulnerability data available for this snapshot.");
        return;
    }
    container.innerHTML = vulnerabilities.slice(0, 5).map((vuln) => `
        <div class="list-item">
            <div>
                <strong>${escapeHtml(vuln.id)}</strong>
                <span>${escapeHtml(vuln.title || "")}</span>
            </div>
            <span class="severity ${severityClass(vuln.severity)}">${escapeHtml(severityLabel(vuln.severity))}</span>
        </div>
    `).join("");
}

function renderVulnerabilityCards(container, vulnerabilities) {
    if (!Array.isArray(vulnerabilities) || !vulnerabilities.length) {
        renderEmptyState(container, "No vulnerability data available for this snapshot.");
        return;
    }

    container.innerHTML = vulnerabilities.map((vuln) => {
        const link = safeUrl(vuln.url);
        const idHtml = link
            ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(vuln.id)}</a>`
            : escapeHtml(vuln.id);
        const cvss = (vuln.cvss_score !== null && vuln.cvss_score !== undefined)
            ? `<span>CVSS v${escapeHtml(vuln.cvss_version)}: ${escapeHtml(vuln.cvss_score)}</span>`
            : "<span>CVSS: not yet scored</span>";
        const kev = vuln.known_exploited
            ? '<span class="kev-badge">KNOWN EXPLOITED</span>'
            : "";
        return `
        <article class="vulnerability-card" data-severity="${severityClass(vuln.severity)}">
            <div class="vulnerability-id">
                <span>CVE</span>
                <strong>${idHtml}</strong>
            </div>
            <div class="vulnerability-content">
                <h3>${escapeHtml(vuln.title || "")}</h3>
                <p>${escapeHtml(vuln.description || "")}</p>
                <div class="vulnerability-meta">
                    <span>Published ${escapeHtml(vuln.published || "—")}</span>
                    ${cvss}
                    ${kev}
                </div>
            </div>
            <span class="severity ${severityClass(vuln.severity)}">${escapeHtml(severityLabel(vuln.severity))}</span>
        </article>`;
    }).join("");
}

function renderSecurityHistory(container, history) {
    if (!Array.isArray(history) || !history.length) {
        renderEmptyState(container, "No historical security data available yet.");
        return;
    }
    container.innerHTML = history.slice(0, 10).map((item) => `
        <div class="security-history-row">
            <span class="history-date">${formatDisplayDate(item.date)}</span>
            <span>${formatNumber(item.cves)} CVEs</span>
            <span>${formatNumber(item.knownExploited)} exploited</span>
            <span>${formatNumber(item.releases)} releases</span>
        </div>
    `).join("");
}

/* =========================================================
   RELEASES
   ========================================================= */

function updateReleases() {
    const releases = window.TechPulseData.get().releases;

    const categories = { major: 0, minor: 0, patch: 0, other: 0 };
    releases.forEach((rel) => {
        const kind = rel.kind || "other";
        if (kind in categories) categories[kind] += 1;
    });

    setText("[data-releases-count]", releases.length);
    setText("[data-releases-major]", categories.major);
    setText("[data-releases-minor]", categories.minor);
    setText("[data-releases-patch]", categories.patch);

    const listContainer = document.querySelector("[data-releases-list]");
    if (listContainer) {
        renderReleasesTable(listContainer, releases);
    }

    const trackedContainer = document.querySelector("[data-tracked-projects]");
    if (trackedContainer) {
        renderTrackedProjects(trackedContainer, window.TechPulseData.get().openSource);
    }
}

function renderReleasesTable(container, releases) {
    if (!Array.isArray(releases) || !releases.length) {
        renderEmptyState(container, "No releases detected in this snapshot window.");
        return;
    }

    container.innerHTML = releases.map((rel) => {
        const kind = severityClass(rel.kind) === "unscored" ? "patch" : (rel.kind || "patch");
        const icon = (rel.project || "·").charAt(0).toUpperCase();
        return `
        <article class="release-row">
            <div class="release-project">
                <div class="release-icon">${escapeHtml(icon)}</div>
                <div>
                    <strong>${escapeHtml(rel.project || "—")}</strong>
                    <span>${escapeHtml(rel.repository || "—")}</span>
                </div>
            </div>
            <div class="release-version">
                <span>VERSION</span>
                <strong>${escapeHtml(rel.version || "—")}</strong>
            </div>
            <div class="release-type">
                <span class="release-badge ${escapeHtml(kind)}">${escapeHtml((rel.kind || "other").toUpperCase())}</span>
            </div>
            <time>${escapeHtml(rel.date || "—")}</time>
        </article>`;
    }).join("");
}

function renderTrackedProjects(container, projects) {
    if (!Array.isArray(projects) || !projects.length) {
        renderEmptyState(container, "Repository data unavailable for this snapshot.");
        return;
    }
    container.innerHTML = projects.map((project) => `
        <div class="tracked-project">
            <strong>${escapeHtml(project.name || "—")}</strong>
            <span>${escapeHtml(project.full_name || "—")}</span>
        </div>
    `).join("");
}

/* =========================================================
   OPEN SOURCE
   ========================================================= */

function updateOpenSource() {
    const projects = window.TechPulseData.get().openSource;
    const container = document.querySelector("[data-opensource-list]");
    if (container) {
        renderOpenSourceList(container, projects);
    }
}

function renderOpenSourceList(container, projects) {
    if (!Array.isArray(projects) || !projects.length) {
        renderEmptyState(
            container,
            "Open-source data unavailable for this snapshot. Run the GitHub collector to populate this view."
        );
        return;
    }

    container.innerHTML = projects.map((project) => {
        const growth = project.growth_available && project.daily_growth !== null
            ? `+${formatNumber(project.daily_growth)} <span>stars</span>`
            : '<span class="growth-na">growth n/a</span>';
        const link = safeUrl(project.url);
        const nameHtml = link
            ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(project.name || project.full_name || "—")}</a>`
            : escapeHtml(project.name || project.full_name || "—");
        return `
        <article class="opensource-card">
            <div class="opensource-rank">#${String(displayValue(project.rank, 0)).padStart(2, "0")}</div>
            <div class="opensource-main">
                <div class="opensource-header">
                    <div>
                        <h3>${nameHtml}</h3>
                        <span class="opensource-label">${escapeHtml(project.language || "Unknown language")}</span>
                    </div>
                    <div class="opensource-growth">${growth}</div>
                </div>
                <p>${escapeHtml(project.description || "No description available.")}</p>
                <div class="opensource-stats">
                    <div><strong>${formatNumber(project.stars)}</strong><span>Stars</span></div>
                    <div><strong>${project.growth_available ? formatNumber(project.daily_growth) : "n/a"}</strong><span>Daily growth</span></div>
                    <div><strong>${escapeHtml(project.language || "—")}</strong><span>Language</span></div>
                </div>
            </div>
        </article>`;
    }).join("");
}

/* =========================================================
   TECHNOLOGY
   ========================================================= */

function updateTechnology() {
    const entries = window.TechPulseData.get().technology;
    const container = document.querySelector("[data-technology-list]");
    if (container) {
        renderTechList(container, entries);
    }
}

function renderTechList(container, entries) {
    if (!Array.isArray(entries) || !entries.length) {
        renderEmptyState(container, "No technology updates collected for this snapshot.");
        return;
    }

    container.innerHTML = entries.map((entry) => `
        <div class="tech-item">
            <h4>${safeLink(entry.url, entry.title || "(untitled)", "tech-link")}</h4>
            <div class="tech-meta">
                <span class="tech-source">${escapeHtml(entry.source || "Unknown")}</span>
                <span class="tech-category">${escapeHtml(entry.category || "tech")}</span>
                <span class="tech-date">${escapeHtml(entry.date || "—")}</span>
            </div>
            <p>${escapeHtml(entry.summary || "")}</p>
        </div>
    `).join("");
}

/* =========================================================
   HISTORY
   ========================================================= */

function updateHistory() {
    const history = window.TechPulseData.get().history;

    const preview = document.querySelector("[data-history-preview]");
    if (preview) {
        renderHistoryPreview(preview, history.slice(0, 5));
    }

    const listContainer = document.querySelector("[data-history-list]");
    if (listContainer) {
        renderHistoryCards(listContainer, history);
    }

    const status = document.querySelector("[data-archive-status]");
    if (status) {
        status.textContent = history.length
            ? `${history.length} snapshot${history.length === 1 ? "" : "s"}`
            : "No snapshots yet";
    }
}

function renderHistoryPreview(container, history) {
    if (!Array.isArray(history) || !history.length) {
        renderEmptyState(container, "The archive begins with the first daily run.");
        return;
    }
    const year = history[0].date ? history[0].date.slice(0, 4) : "";
    container.innerHTML = `
        <div class="timeline-year">${escapeHtml(year)}</div>
        <div class="timeline">
            ${history.map((item, index) => {
                const d = new Date(`${item.date}T00:00:00Z`);
                const day = Number.isNaN(d.getTime()) ? "·" : d.getUTCDate();
                const month = Number.isNaN(d.getTime())
                    ? "—"
                    : d.toLocaleDateString("en-GB", { month: "long", timeZone: "UTC" });
                return `
                <div class="timeline-item ${index === 0 ? "active" : ""}">
                    <span>${day}</span>
                    <div>
                        <strong>${escapeHtml(month)}</strong>
                        <small>${formatNumber(item.cves)} CVEs · ${formatNumber(item.releases)} releases</small>
                    </div>
                </div>`;
            }).join("")}
        </div>`;
}

function renderHistoryCards(container, history) {
    if (!Array.isArray(history) || !history.length) {
        renderEmptyState(container, "No historical snapshots yet. The archive grows daily.");
        return;
    }

    const currentDate = window.TechPulseData.get().meta.date;

    container.innerHTML = history.map((item) => {
        const d = new Date(`${item.date}T00:00:00Z`);
        const valid = !Number.isNaN(d.getTime());
        const day = valid ? d.getUTCDate() : "·";
        const monthYear = valid
            ? d.toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" }).toUpperCase()
            : "—";
        const weekday = valid
            ? d.toLocaleDateString("en-GB", { weekday: "long", timeZone: "UTC" })
            : "";
        const isCurrent = item.date === currentDate;
        return `
        <article class="history-card">
            <div class="history-date">
                <strong>${day}</strong>
                <span>${escapeHtml(monthYear)}</span>
            </div>
            <div class="history-content">
                <div class="history-header">
                    <div>
                        <h3>Daily Technology Snapshot</h3>
                        <span>${escapeHtml(weekday)}${isCurrent ? " · Most recent" : ""}</span>
                    </div>
                    ${isCurrent ? '<span class="history-status">CURRENT</span>' : ""}
                </div>
                <div class="history-stats">
                    <div><strong>${formatNumber(item.cves)}</strong><span>CVEs</span></div>
                    <div><strong>${formatNumber(item.knownExploited)}</strong><span>Exploited</span></div>
                    <div><strong>${formatNumber(item.releases)}</strong><span>Releases</span></div>
                    <div><strong>${formatNumber(item.projects)}</strong><span>Projects</span></div>
                    <div><strong>${formatNumber(item.techEntries)}</strong><span>Tech</span></div>
                </div>
            </div>
        </article>`;
    }).join("");
}

/* Archive page (history.html) — deep snapshot data from archive.json */
async function renderArchivePage() {
    const container = document.querySelector("[data-archive-list]");
    if (!container) return;

    const archive = window.TechPulseData.getArchive().archive;

    if (!Array.isArray(archive) || !archive.length) {
        renderEmptyState(container, "No archived snapshots available yet.");
        return;
    }

    container.innerHTML = archive.map((snap) => {
        const counts = snap.snapshot || {};
        const severity = (snap.security || {}).severity || {};
        const releases = (snap.releases || {}).recent || [];
        const projects = (snap.opensource || {}).topProjects || [];
        const tech = (snap.technology || {}).recent || [];

        const releaseItems = releases.length
            ? releases.slice(0, 5).map((r) => `
                <li>${safeLink(r.url, `${r.project} ${r.version}`, "archive-link")}</li>`).join("")
            : "<li class=\"archive-empty\">No releases recorded</li>";

        const projectItems = projects.length
            ? projects.slice(0, 5).map((p) => `
                <li>${escapeHtml(p.full_name || "—")} · ★ ${formatNumber(p.stars)}</li>`).join("")
            : "<li class=\"archive-empty\">No project data recorded</li>";

        const techItems = tech.length
            ? tech.slice(0, 5).map((t) => `
                <li>${safeLink(t.url, t.title || "(untitled)", "archive-link")}</li>`).join("")
            : "<li class=\"archive-empty\">No tech entries recorded</li>";

        return `
        <article class="history-card archive-detail">
            <div class="history-date">
                <strong>${escapeHtml((snap.date || "").slice(8, 10) || "·")}</strong>
                <span>${escapeHtml((snap.date || "").slice(0, 7).replace("-", " / ").toUpperCase())}</span>
            </div>
            <div class="history-content">
                <div class="history-header">
                    <div>
                        <h3>Daily Technology Snapshot</h3>
                        <span>${formatNumber(counts.cves)} CVEs · ${formatNumber(counts.knownExploited)} exploited · ${formatNumber(counts.releases)} releases</span>
                    </div>
                </div>
                <div class="history-stats">
                    <div><strong>${formatNumber(severity.CRITICAL)}</strong><span>Critical</span></div>
                    <div><strong>${formatNumber(severity.HIGH)}</strong><span>High</span></div>
                    <div><strong>${formatNumber(severity.MEDIUM)}</strong><span>Medium</span></div>
                    <div><strong>${formatNumber(counts.techEntries)}</strong><span>Tech</span></div>
                </div>
                <div class="archive-columns">
                    <div>
                        <h4>Releases</h4>
                        <ul>${releaseItems}</ul>
                    </div>
                    <div>
                        <h4>Projects</h4>
                        <ul>${projectItems}</ul>
                    </div>
                    <div>
                        <h4>Technology</h4>
                        <ul>${techItems}</ul>
                    </div>
                </div>
            </div>
        </article>`;
    }).join("");
}

/* =========================================================
   STATUS
   ========================================================= */

function updateStatus() {
    const loaded = window.TechPulseData.isLoaded();
    const error = window.TechPulseData.getError();
    const degraded = loaded && window.TechPulseData.hasSourceFailures();

    const dotElements = document.querySelectorAll("[data-status-dot]");
    const textElements = document.querySelectorAll("[data-status-text]");
    const mainStatus = document.querySelector("[data-status-main]");

    dotElements.forEach((el) => {
        if (!loaded) {
            el.style.background = "var(--warning)";
            el.style.boxShadow = "0 0 0 3px rgba(246, 200, 95, 0.08), 0 0 12px rgba(246, 200, 95, 0.45)";
        } else if (degraded) {
            el.style.background = "var(--warning)";
            el.style.boxShadow = "0 0 0 3px rgba(246, 200, 95, 0.08), 0 0 12px rgba(246, 200, 95, 0.45)";
        } else {
            el.style.background = "var(--accent)";
            el.style.boxShadow = "";
        }
    });

    textElements.forEach((el) => {
        el.textContent = !loaded ? "No data" : degraded ? "Partial" : "Live";
    });

    if (mainStatus) {
        if (!loaded) {
            mainStatus.textContent = "● NO DATA";
            mainStatus.style.color = "var(--warning)";
            mainStatus.title = error ? `Data unavailable: ${error}` : "Data unavailable";
        } else if (degraded) {
            mainStatus.textContent = "● PARTIAL";
            mainStatus.style.color = "var(--warning)";
            mainStatus.title = "One or more sources were unavailable during collection.";
        } else {
            mainStatus.textContent = "● LIVE";
            mainStatus.style.color = "var(--accent)";
            mainStatus.title = "";
        }
    }
}

/* =========================================================
   FILTERS + NAV
   ========================================================= */

function initSecurityFilters() {
    const filterButtons = document.querySelectorAll("[data-filter]");
    const cards = document.querySelectorAll("[data-vulnerability-list] .vulnerability-card");
    if (!filterButtons.length || !cards.length) return;

    filterButtons.forEach((button) => {
        button.addEventListener("click", () => {
            filterButtons.forEach((b) => b.classList.remove("active"));
            button.classList.add("active");

            const filter = button.dataset.filter;
            cards.forEach((card) => {
                const match = filter === "all" || card.dataset.severity === filter;
                card.style.display = match ? "grid" : "none";
            });
        });
    });
}

function updateNavActive() {
    const currentPage = (window.location.pathname.split("/").pop() || "index.html").toLowerCase();
    document.querySelectorAll(".main-nav a[data-nav]").forEach((link) => {
        const href = (link.getAttribute("href") || "").toLowerCase();
        const isHome = currentPage === "index.html" || currentPage === "";
        const isActive = href === currentPage || (isHome && link.dataset.nav === "today");
        link.classList.toggle("active", isActive);
    });
}

/* =========================================================
   HELPERS (formatDate alias for previews)
   ========================================================= */

function formatDate(dateString) {
    return formatDisplayDate(dateString);
}
