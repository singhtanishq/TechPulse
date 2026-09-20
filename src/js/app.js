/* =========================================================
   TECHPULSE — APPLICATION
   Renders all pages from generated data (loaded in data.js).

   Design rules:
     - Every list has honest loading, empty and error states.
     - Unscored CVEs render explicitly as UNSCORED, never as zeros
       or LOW severity.
     - External content is escaped and URL-checked (see components.js).
     - All dates follow the TechPulse IST reporting model (dates.js):
       the displayed edition date is universal; relative labels are
       computed live against the current IST calendar date.
   ========================================================= */

document.addEventListener("DOMContentLoaded", async () => {
    initChrome(); // nav, theme toggle, mobile menu — before data arrives
    markSkeletons();
    await window.TechPulseData.load();
    updateAll();
    await updatePageSpecific();
    initRevealAnimations();
});

/* =========================================================
   SITE CHROME — nav state, mobile menu, theme toggle
   ========================================================= */

function initChrome() {
    updateNavActive();
    initMobileNav();
    initThemeToggle();
}

function updateNavActive() {
    const currentPage = (window.location.pathname.split("/").pop() || "index.html").toLowerCase();
    const links = document.querySelectorAll(".main-nav a[data-nav], .mobile-nav a[data-nav]");
    links.forEach((link) => {
        const href = (link.getAttribute("href") || "").toLowerCase();
        const isHome = currentPage === "index.html" || currentPage === "";
        const isActive = href === currentPage || (isHome && link.dataset.nav === "today");
        link.classList.toggle("active", isActive);
        if (isActive) {
            link.setAttribute("aria-current", "page");
        } else {
            link.removeAttribute("aria-current");
        }
    });
}

function initMobileNav() {
    const toggle = document.querySelector("[data-nav-toggle]");
    const menu = document.querySelector("[data-mobile-nav]");
    if (!toggle || !menu) return;

    const setOpen = (open) => {
        document.body.classList.toggle("nav-open", open);
        toggle.setAttribute("aria-expanded", String(open));
    };

    toggle.addEventListener("click", () => {
        setOpen(!document.body.classList.contains("nav-open"));
    });

    menu.addEventListener("click", (event) => {
        if (event.target.closest("a")) setOpen(false);
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setOpen(false);
    });
}

function initThemeToggle() {
    const toggle = document.querySelector("[data-theme-toggle]");
    if (!toggle) return;

    const syncState = () => {
        const theme = document.documentElement.getAttribute("data-theme") === "light"
            ? "light"
            : "dark";
        toggle.setAttribute("aria-pressed", String(theme === "light"));
        toggle.title = theme === "light" ? "Switch to dark theme" : "Switch to light theme";
    };
    syncState();

    toggle.addEventListener("click", () => {
        const root = document.documentElement;
        const next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
        root.classList.add("theme-transition");
        root.setAttribute("data-theme", next);
        try {
            localStorage.setItem("techpulse-theme", next);
        } catch (error) { /* storage unavailable — theme is session-only */ }
        window.setTimeout(() => root.classList.remove("theme-transition"), 400);
        syncState();
    });
}

/* =========================================================
   SKELETONS — swap "Loading…" placeholders for shimmer states
   ========================================================= */

function markSkeletons() {
    document.querySelectorAll("[data-skeleton]").forEach((el) => {
        const variant = el.dataset.skeleton || "rows";
        const count = Number(el.dataset.skeletonCount || 3);
        renderSkeletons(el, count, variant);
    });
}

/* =========================================================
   MAIN UPDATE
   ========================================================= */

function updateAll() {
    const loaded = window.TechPulseData.isLoaded();
    if (!loaded) {
        showDataErrorBanner();
    }
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
}

function showDataErrorBanner() {
    const banner = document.querySelector("[data-error-banner]");
    if (!banner) return;
    const message = window.TechPulseData.getError();
    banner.hidden = false;
    banner.querySelector("[data-error-detail]").textContent =
        message || "The generated data file could not be loaded.";
}

/* =========================================================
   META — edition date, freshness, generated timestamp
   ========================================================= */

function updateMeta() {
    const data = window.TechPulseData.get().meta;
    const dates = window.TechPulseDates;

    const formattedDate = data.date ? dates.display(data.date) : "—";
    setText("[data-today]", formattedDate);
    setText("[data-page-date]", formattedDate);
    setText("[data-snapshot-date]", formattedDate);
    setText("[data-security-date]", formattedDate);
    setText("[data-releases-date]", formattedDate);

    // Honest freshness: how does the displayed edition relate to the
    // current TechPulse (IST) date? Deterministic for every visitor.
    if (data.date) {
        const freshness = dates.freshness(data.date);
        document.querySelectorAll("[data-edition-chip]").forEach((el) => {
            el.textContent = freshness.label;
            el.classList.remove("chip--current", "chip--stale");
            el.classList.add(freshness.state === "current" ? "chip--current" : "chip--stale");
            if (data.coveredDate) {
                el.title = `Edition for ${dates.long(data.date)} — covering the India day of ${dates.long(data.coveredDate)}`;
            }
        });
    }

    document.querySelectorAll("[data-page-updated]").forEach((el) => {
        el.textContent = data.generatedAt
            ? formatTimestampIST(data.generatedAt)
            : "—";
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
    setText("[data-tracked-count]", snapshot.projects);
    setText("[data-releases-total]", snapshot.releases);

    // Dynamic "first observation year" from the archive itself.
    const history = window.TechPulseData.get().history;
    const oldest = history.length ? history[history.length - 1].date : null;
    const year = oldest ? window.TechPulseDates.chip(oldest).year : "—";
    setText("[data-first-year]", year);

    // Live counters for the autonomous section.
    setText("[data-days-observed]", window.TechPulseData.get().meta.daysObserved || 0);
    setText("[data-snapshots-count]", window.TechPulseData.get().meta.snapshots || 0);
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

    updateSeverityBars(security);

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

function updateSeverityBars(security) {
    const bars = document.querySelectorAll("[data-severity-bar]");
    const total = (security.critical || 0) + (security.high || 0) + (security.medium || 0)
        + (security.low || 0) + (security.unscored || 0);
    bars.forEach((bar) => {
        const key = (bar.dataset.severityBar || "").toLowerCase();
        const value = security[key] || 0;
        const fill = bar.querySelector("[data-severity-fill]");
        const label = bar.querySelector("[data-severity-share]");
        if (!fill) return;
        const share = total > 0 ? Math.max((value / total) * 100, value > 0 ? 4 : 0) : 0;
        if (prefersReducedMotion()) {
            fill.style.width = `${share}%`;
        } else {
            requestAnimationFrame(() => { fill.style.width = `${share}%`; });
        }
        if (label) {
            label.textContent = total > 0 ? `${Math.round((value / total) * 100)}%` : "—";
        }
    });
}

function renderHomeVulnerabilityList(container, vulnerabilities) {
    if (!Array.isArray(vulnerabilities) || !vulnerabilities.length) {
        renderEmptyState(container, "No vulnerability data available for this edition.");
        return;
    }
    container.innerHTML = vulnerabilities.slice(0, 5).map((vuln, index) => `
        <div class="list-item reveal-item" style="--stagger:${index}">
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
        renderEmptyState(container, "No vulnerability data available for this edition.");
        return;
    }

    container.innerHTML = vulnerabilities.map((vuln, index) => {
        const link = safeUrl(vuln.url);
        const idHtml = link
            ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(vuln.id)}</a>`
            : escapeHtml(vuln.id);
        const cvss = (vuln.cvss_score !== null && vuln.cvss_score !== undefined)
            ? `<span>CVSS v${escapeHtml(vuln.cvss_version)}: <strong>${escapeHtml(vuln.cvss_score)}</strong></span>`
            : "<span>CVSS: not yet scored</span>";
        const kev = vuln.known_exploited
            ? '<span class="kev-badge" title="Present in the CISA Known Exploited Vulnerabilities catalog">KNOWN EXPLOITED</span>'
            : "";
        return `
        <article class="vulnerability-card reveal-item" data-severity="${severityClass(vuln.severity)}" style="--stagger:${index}">
            <div class="vulnerability-id">
                <span>CVE</span>
                <strong>${idHtml}</strong>
            </div>
            <div class="vulnerability-content">
                <h3>${escapeHtml(vuln.title || "")}</h3>
                <p>${escapeHtml(vuln.description || "")}</p>
                <div class="vulnerability-meta">
                    <span title="${escapeHtml(formatDisplayDate(vuln.publishedAt))}">Published ${escapeHtml(formatRelativeDate(vuln.publishedAt))}</span>
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
    container.innerHTML = history.slice(0, 10).map((item, index) => `
        <div class="security-history-row reveal-item" style="--stagger:${index}">
            <span class="history-date" title="${escapeHtml(formatDisplayDate(item.date))}">${escapeHtml(formatRelativeDate(item.date))}</span>
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
        renderEmptyState(container, "No releases detected in this edition's window.");
        return;
    }

    container.innerHTML = releases.map((rel, index) => {
        const kind = rel.kind || "other";
        const icon = (rel.project || "·").charAt(0).toUpperCase();
        const absolute = formatDisplayDate(rel.publishedAt);
        return `
        <article class="release-row reveal-item" style="--stagger:${index}">
            <div class="release-project">
                <div class="release-icon" aria-hidden="true">${escapeHtml(icon)}</div>
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
                <span class="release-badge ${escapeHtml(kind)}">${escapeHtml(kind.toUpperCase())}</span>
            </div>
            <time title="${escapeHtml(absolute)}">${escapeHtml(formatRelativeDate(rel.publishedAt))}</time>
        </article>`;
    }).join("");
}

function renderTrackedProjects(container, projects) {
    if (!Array.isArray(projects) || !projects.length) {
        renderEmptyState(container, "Repository data unavailable for this edition.");
        return;
    }
    container.innerHTML = projects.map((project, index) => `
        <div class="tracked-project reveal-item" style="--stagger:${index}">
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
            "Open-source data unavailable for this edition. Run the GitHub collector to populate this view."
        );
        return;
    }

    container.innerHTML = projects.map((project, index) => {
        const growth = project.growth_available && project.daily_growth !== null
            ? `+${formatNumber(project.daily_growth)} <span>stars</span>`
            : '<span class="growth-na">growth n/a</span>';
        const link = safeUrl(project.url);
        const nameHtml = link
            ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer">${escapeHtml(project.name || project.full_name || "—")}</a>`
            : escapeHtml(project.name || project.full_name || "—");
        return `
        <article class="opensource-card reveal-item" style="--stagger:${index}">
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
        renderEmptyState(container, "No technology updates collected for this edition.");
        return;
    }

    container.innerHTML = entries.map((entry, index) => `
        <div class="tech-item reveal-item" style="--stagger:${index}">
            <h4>${safeLink(entry.url, entry.title || "(untitled)", "tech-link")}</h4>
            <div class="tech-meta">
                <span class="tech-source">${escapeHtml(entry.source || "Unknown")}</span>
                <span class="tech-category">${escapeHtml(entry.category || "tech")}</span>
                <span class="tech-date" title="${escapeHtml(formatDisplayDate(entry.publishedAt))}">${escapeHtml(formatRelativeDate(entry.publishedAt))}</span>
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
    const year = history[0].date ? window.TechPulseDates.chip(history[0].date).year : "";
    container.innerHTML = `
        <div class="timeline-year">${escapeHtml(year)}</div>
        <div class="timeline">
            ${history.map((item, index) => {
                const chip = window.TechPulseDates.chip(item.date);
                return `
                <div class="timeline-item ${index === 0 ? "active" : ""} reveal-item" style="--stagger:${index}">
                    <span>${escapeHtml(chip.day)}</span>
                    <div>
                        <strong>${escapeHtml(chip.month)}</strong>
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

    container.innerHTML = history.map((item, index) => {
        const chip = window.TechPulseDates.chip(item.date);
        const weekday = window.TechPulseDates.weekday(item.date);
        const isCurrent = item.date === currentDate;
        return `
        <article class="history-card reveal-item" style="--stagger:${index}">
            <div class="history-date">
                <strong>${escapeHtml(chip.day)}</strong>
                <span>${escapeHtml(chip.monthYear.toUpperCase())}</span>
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

    container.innerHTML = archive.map((snap, index) => {
        const counts = snap.snapshot || {};
        const severity = (snap.security || {}).severity || {};
        const releases = (snap.releases || {}).recent || [];
        const projects = (snap.opensource || {}).topProjects || [];
        const tech = (snap.technology || {}).recent || [];
        const chip = window.TechPulseDates.chip(snap.date);

        const releaseItems = releases.length
            ? releases.slice(0, 5).map((r) => `
                <li>${safeLink(r.url, `${r.project} ${r.version}`, "archive-link")}</li>`).join("")
            : '<li class="archive-empty">No releases recorded</li>';

        const projectItems = projects.length
            ? projects.slice(0, 5).map((p) => `
                <li>${escapeHtml(p.full_name || "—")} · ★ ${formatNumber(p.stars)}</li>`).join("")
            : '<li class="archive-empty">No project data recorded</li>';

        const techItems = tech.length
            ? tech.slice(0, 5).map((t) => `
                <li>${safeLink(t.url, t.title || "(untitled)", "archive-link")}</li>`).join("")
            : '<li class="archive-empty">No tech entries recorded</li>';

        return `
        <article class="history-card archive-detail reveal-item" style="--stagger:${index}">
            <div class="history-date">
                <strong>${escapeHtml(chip.day)}</strong>
                <span>${escapeHtml(chip.monthYear.toUpperCase())}</span>
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
        el.classList.remove("is-live", "is-warning", "is-error");
        if (!loaded) {
            el.classList.add("is-error");
        } else if (degraded) {
            el.classList.add("is-warning");
        } else {
            el.classList.add("is-live");
        }
    });

    textElements.forEach((el) => {
        el.textContent = !loaded ? "No data" : degraded ? "Partial" : "Live";
    });

    if (mainStatus) {
        mainStatus.classList.remove("is-live", "is-warning", "is-error");
        if (!loaded) {
            mainStatus.classList.add("is-error");
            mainStatus.textContent = "No data";
            mainStatus.title = error ? `Data unavailable: ${error}` : "Data unavailable";
        } else if (degraded) {
            mainStatus.classList.add("is-warning");
            mainStatus.textContent = "Partial";
            mainStatus.title = "One or more sources were unavailable during collection.";
        } else {
            mainStatus.classList.add("is-live");
            mainStatus.textContent = "Live";
            mainStatus.title = "";
        }
    }
}

/* =========================================================
   FILTERS
   ========================================================= */

function initSecurityFilters() {
    const filterButtons = document.querySelectorAll("[data-filter]");
    const listContainer = document.querySelector("[data-vulnerability-list]");
    if (!filterButtons.length || !listContainer) return;

    const cards = () => listContainer.querySelectorAll(".vulnerability-card");

    // Empty-result feedback when a filter matches nothing.
    let note = listContainer.querySelector("[data-filter-empty]");
    if (!note) {
        note = document.createElement("div");
        note.className = "empty-state";
        note.setAttribute("data-filter-empty", "");
        note.hidden = true;
        note.textContent = "No CVEs with this severity in the current edition.";
        listContainer.appendChild(note);
    }

    const applyFilter = (filter) => {
        let visible = 0;
        cards().forEach((card) => {
            const match = filter === "all" || card.dataset.severity === filter;
            card.classList.toggle("is-hidden", !match);
            if (match) visible += 1;
        });
        note.hidden = visible > 0;
    };

    filterButtons.forEach((button) => {
        button.addEventListener("click", () => {
            filterButtons.forEach((b) => {
                b.classList.remove("active");
                b.removeAttribute("aria-pressed");
            });
            button.classList.add("active");
            button.setAttribute("aria-pressed", "true");
            applyFilter(button.dataset.filter);
        });
    });

    applyFilter("all");
}

/* =========================================================
   MOTION — reveal on scroll, count-ups, reduced motion
   ========================================================= */

function prefersReducedMotion() {
    return window.matchMedia
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function initRevealAnimations() {
    const targets = document.querySelectorAll(".reveal, .reveal-item");
    if (!targets.length) return;

    if (prefersReducedMotion() || !("IntersectionObserver" in window)) {
        targets.forEach((el) => el.classList.add("is-visible"));
        return;
    }

    // Batch stagger: within each visible batch, items get sequential
    // delays so grouped cards cascade smoothly.
    const observer = new IntersectionObserver((entries) => {
        let batchIndex = 0;
        const visible = entries.filter((e) => e.isIntersecting);
        visible.forEach((entry) => {
            const el = entry.target;
            if (!el.style.getPropertyValue("--reveal-delay")) {
                el.style.setProperty("--reveal-delay", `${Math.min(batchIndex * 60, 420)}ms`);
                batchIndex += 1;
            }
            el.classList.add("is-visible");
            observer.unobserve(el);
        });
    }, { threshold: 0.08, rootMargin: "0px 0px -5% 0px" });

    targets.forEach((el) => observer.observe(el));
}
