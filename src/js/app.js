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
     - A failed primary data load must never be converted into
       misleading "empty" states.
     - Rendering helpers must tolerate partial/malformed runtime data
       without crashing the entire page.
   ========================================================= */

document.addEventListener("DOMContentLoaded", async () => {
    initChrome();
    markSkeletons();

    const dataApi = window.TechPulseData;

    if (
        !dataApi ||
        typeof dataApi.load !== "function" ||
        typeof dataApi.get !== "function"
    ) {
        showDataErrorBanner(
            "The TechPulse data module is unavailable."
        );
        renderLoadErrorStates(
            "The generated data module could not be initialized."
        );
        updateStatus();
        await updatePageSpecific();
        initRevealAnimations();
        return;
    }

    let loadSucceeded = false;

    try {
        await dataApi.load();
        loadSucceeded = isPrimaryDataLoaded();
    } catch (error) {
        loadSucceeded = false;
        showDataErrorBanner(
            getErrorMessage(
                error,
                "The generated data file could not be loaded."
            )
        );
    }

    if (!loadSucceeded) {
        renderLoadErrorStates(
            getPrimaryDataError()
        );
        updateStatus();
        await updatePageSpecific();
        initRevealAnimations();
        return;
    }

    updateAll();
    await updatePageSpecific();
    initRevealAnimations();
});


/* =========================================================
   SAFE DATA ACCESS
   ========================================================= */

function getDataApi() {
    return window.TechPulseData || null;
}

function getDatesApi() {
    return window.TechPulseDates || null;
}

function isPrimaryDataLoaded() {
    const api = getDataApi();

    if (
        !api ||
        typeof api.isLoaded !== "function"
    ) {
        return false;
    }

    try {
        return api.isLoaded() === true;
    } catch (error) {
        return false;
    }
}

function getPrimaryData() {
    const api = getDataApi();

    if (
        !api ||
        typeof api.get !== "function"
    ) {
        return null;
    }

    try {
        const data = api.get();
        return data && typeof data === "object"
            ? data
            : null;
    } catch (error) {
        return null;
    }
}

function getPrimaryDataError() {
    const api = getDataApi();

    if (
        !api ||
        typeof api.getError !== "function"
    ) {
        return "The generated data file could not be loaded.";
    }

    try {
        return api.getError() ||
            "The generated data file could not be loaded.";
    } catch (error) {
        return "The generated data file could not be loaded.";
    }
}

function getArchiveData() {
    const api = getDataApi();

    if (
        !api ||
        typeof api.getArchive !== "function"
    ) {
        return null;
    }

    try {
        const data = api.getArchive();
        return data && typeof data === "object"
            ? data
            : null;
    } catch (error) {
        return null;
    }
}

function getArchiveLoadedState() {
    const api = getDataApi();

    if (
        !api ||
        typeof api.isArchiveLoaded !== "function"
    ) {
        return true;
    }

    try {
        return api.isArchiveLoaded() === true;
    } catch (error) {
        return false;
    }
}

function getArchiveError() {
    const api = getDataApi();

    if (
        !api ||
        typeof api.getArchiveError !== "function"
    ) {
        return "The archive data could not be loaded.";
    }

    try {
        return api.getArchiveError() ||
            "The archive data could not be loaded.";
    } catch (error) {
        return "The archive data could not be loaded.";
    }
}

function getErrorMessage(error, fallback) {
    if (
        error &&
        typeof error.message === "string" &&
        error.message.trim()
    ) {
        return error.message.trim();
    }

    return fallback;
}

function safeNonNegativeNumber(value) {
    if (
        typeof value !== "number" ||
        !Number.isFinite(value) ||
        value < 0
    ) {
        return 0;
    }

    return value;
}

function safeCount(value) {
    return Math.max(
        0,
        Math.floor(
            safeNonNegativeNumber(value)
        )
    );
}


/* =========================================================
   SITE CHROME — nav state, mobile menu, theme toggle
   ========================================================= */

function initChrome() {
    updateNavActive();
    initMobileNav();
    initThemeToggle();
    initNavScroll();
    initCursorSpotlight();
    initSearchPalette();
}

function updateNavActive() {
    const pathname =
        window.location.pathname || "";

    const currentPage =
        pathname
            .split("/")
            .pop()
            .split("?")[0]
            .split("#")[0]
            .toLowerCase() ||
        "index.html";

    const links = document.querySelectorAll(
        ".main-nav a[data-nav], .mobile-nav a[data-nav]"
    );

    links.forEach((link) => {
        const href =
            (link.getAttribute("href") || "")
                .split("#")[0]
                .split("?")[0]
                .toLowerCase();

        const normalizedHref =
            href
                .replace(/^\.\/+/, "")
                .replace(/^\/+/, "");

        const isHome =
            currentPage === "index.html" ||
            currentPage === "";

        const isActive =
            normalizedHref === currentPage ||
            (
                isHome &&
                link.dataset.nav === "today"
            );

        link.classList.toggle(
            "active",
            isActive
        );

        if (isActive) {
            link.setAttribute(
                "aria-current",
                "page"
            );
        } else {
            link.removeAttribute(
                "aria-current"
            );
        }
    });
}

function initMobileNav() {
    const toggle =
        document.querySelector(
            "[data-nav-toggle]"
        );

    const menu =
        document.querySelector(
            "[data-mobile-nav]"
        );

    if (
        !toggle ||
        !menu
    ) {
        return;
    }

    if (!menu.id) {
        menu.id = "techpulse-mobile-nav";
    }

    toggle.setAttribute(
        "aria-controls",
        menu.id
    );

    const setOpen = (open) => {
        const isOpen = Boolean(open);

        document.body.classList.toggle(
            "nav-open",
            isOpen
        );

        toggle.setAttribute(
            "aria-expanded",
            String(isOpen)
        );

        menu.setAttribute(
            "aria-hidden",
            String(!isOpen)
        );
    };

    setOpen(
        document.body.classList.contains(
            "nav-open"
        )
    );

    toggle.addEventListener(
        "click",
        () => {
            setOpen(
                !document.body.classList.contains(
                    "nav-open"
                )
            );
        }
    );

    menu.addEventListener(
        "click",
        (event) => {
            if (
                event.target.closest("a")
            ) {
                setOpen(false);
            }
        }
    );

    document.addEventListener(
        "click",
        (event) => {
            if (
                !document.body.classList.contains(
                    "nav-open"
                )
            ) {
                return;
            }

            if (
                event.target.closest(
                    "[data-nav-toggle], [data-mobile-nav]"
                )
            ) {
                return;
            }

            setOpen(false);
        }
    );

    document.addEventListener(
        "keydown",
        (event) => {
            if (
                event.key === "Escape" &&
                document.body.classList.contains(
                    "nav-open"
                )
            ) {
                setOpen(false);
                toggle.focus();
            }
        }
    );

    window.addEventListener(
        "resize",
        () => {
            if (
                window.innerWidth > 900 &&
                document.body.classList.contains(
                    "nav-open"
                )
            ) {
                setOpen(false);
            }
        }
    );
}

function initThemeToggle() {
    const toggle =
        document.querySelector(
            "[data-theme-toggle]"
        );

    if (!toggle) {
        return;
    }

    const syncState = () => {
        const theme =
            document.documentElement.getAttribute(
                "data-theme"
            ) === "light"
                ? "light"
                : "dark";

        toggle.setAttribute(
            "aria-pressed",
            String(theme === "light")
        );

        toggle.setAttribute(
            "aria-label",
            theme === "light"
                ? "Switch to dark theme"
                : "Switch to light theme"
        );

        toggle.title =
            theme === "light"
                ? "Switch to dark theme"
                : "Switch to light theme";
    };

    syncState();

    toggle.addEventListener(
        "click",
        () => {
            const root =
                document.documentElement;

            const next =
                root.getAttribute(
                    "data-theme"
                ) === "light"
                    ? "dark"
                    : "light";

            root.classList.add(
                "theme-transition"
            );

            root.setAttribute(
                "data-theme",
                next
            );

            try {
                localStorage.setItem(
                    "techpulse-theme",
                    next
                );
            } catch (error) {
                // Storage may be blocked. Theme still applies for this session.
            }

            window.setTimeout(
                () => {
                    root.classList.remove(
                        "theme-transition"
                    );
                },
                400
            );

            syncState();
        }
    );
}


/* =========================================================
   SKELETONS — swap loading placeholders for shimmer states
   ========================================================= */

function markSkeletons() {
    document
        .querySelectorAll("[data-skeleton]")
        .forEach((el) => {
            const variant =
                el.dataset.skeleton ||
                "rows";

            const count =
                Number(
                    el.dataset.skeletonCount || 3
                );

            renderSkeletons(
                el,
                count,
                variant
            );

            el.setAttribute(
                "aria-busy",
                "true"
            );
        });
}

function clearSkeletonState(container) {
    if (!container) {
        return;
    }

    container.removeAttribute(
        "aria-busy"
    );
}


/* =========================================================
   MAIN UPDATE
   ========================================================= */

function updateAll() {
    const loaded =
        isPrimaryDataLoaded();

    if (!loaded) {
        showDataErrorBanner();
        renderLoadErrorStates();
        updateStatus();
        return;
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


/**
 * When generated data itself cannot be fetched, every dependent
 * list shows an honest error state instead of a misleading empty state.
 */
function renderLoadErrorStates(
    detail
) {
    const message =
        detail ||
        getPrimaryDataError();

    document
        .querySelectorAll(
            "[data-security-latest], [data-vulnerability-list], " +
            "[data-releases-list], [data-tracked-projects], " +
            "[data-opensource-list], [data-technology-list], " +
            "[data-history-preview], [data-history-list], " +
            "[data-security-history]"
        )
        .forEach((container) => {
            renderErrorState(
                container,
                message
            );
        });
}

async function updatePageSpecific() {
    const archiveContainer =
        document.querySelector(
            "[data-archive-list]"
        );

    if (!archiveContainer) {
        return;
    }

    const api = getDataApi();

    if (
        !api ||
        typeof api.loadArchive !== "function"
    ) {
        renderErrorState(
            archiveContainer,
            "The archive data module is unavailable."
        );
        return;
    }

    try {
        await api.loadArchive();
    } catch (error) {
        renderErrorState(
            archiveContainer,
            getErrorMessage(
                error,
                "The archive data could not be loaded."
            )
        );
        return;
    }

    if (
        !getArchiveLoadedState()
    ) {
        renderErrorState(
            archiveContainer,
            getArchiveError()
        );
        return;
    }

    renderArchivePage();
}

function showDataErrorBanner(
    overrideMessage
) {
    const banner =
        document.querySelector(
            "[data-error-banner]"
        );

    if (!banner) {
        return;
    }

    const detailElement =
        banner.querySelector(
            "[data-error-detail]"
        );

    const message =
        overrideMessage ||
        getPrimaryDataError() ||
        "The generated data file could not be loaded.";

    banner.hidden = false;

    if (detailElement) {
        detailElement.textContent =
            String(message);
    }
}


/* =========================================================
   META — edition date, freshness, generated timestamp
   ========================================================= */

function updateMeta() {
    const data =
        getPrimaryData();

    const meta =
        data && data.meta &&
        typeof data.meta === "object"
            ? data.meta
            : {};

    const dates =
        getDatesApi();

    const formattedDate =
        meta.date &&
        dates &&
        typeof dates.display === "function"
            ? dates.display(meta.date)
            : "—";

    setText(
        "[data-today]",
        formattedDate
    );

    setText(
        "[data-page-date]",
        formattedDate
    );

    setText(
        "[data-snapshot-date]",
        formattedDate
    );

    setText(
        "[data-security-date]",
        formattedDate
    );

    setText(
        "[data-releases-date]",
        formattedDate
    );

    /*
     * Honest freshness: the displayed edition relates to the current
     * IST calendar date. Future backfill editions remain distinguishable
     * without being incorrectly labeled as current.
     */
    if (
        meta.date &&
        dates &&
        typeof dates.freshness === "function"
    ) {
        const freshness =
            dates.freshness(
                meta.date
            );

        document
            .querySelectorAll(
                "[data-edition-chip]"
            )
            .forEach((el) => {
                el.textContent =
                    freshness.label;

                el.classList.remove(
                    "chip--current",
                    "chip--stale",
                    "chip--future"
                );

                if (
                    freshness.state ===
                    "current"
                ) {
                    el.classList.add(
                        "chip--current"
                    );
                } else if (
                    freshness.state ===
                    "future"
                ) {
                    el.classList.add(
                        "chip--future"
                    );
                } else {
                    el.classList.add(
                        "chip--stale"
                    );
                }

                if (
                    meta.coveredDate &&
                    typeof dates.long === "function"
                ) {
                    el.title =
                        `Edition for ${dates.long(meta.date)} — covering the India day of ${dates.long(meta.coveredDate)}`;
                } else {
                    el.removeAttribute(
                        "title"
                    );
                }
            });
    }

    document
        .querySelectorAll(
            "[data-page-updated]"
        )
        .forEach((el) => {
            el.textContent =
                meta.generatedAt
                    ? formatTimestampIST(
                        meta.generatedAt
                    )
                    : "—";
        });

    const observations =
        document.querySelector(
            "[data-observations]"
        );

    if (observations) {
        observations.textContent =
            String(
                safeCount(
                    meta.daysObserved
                )
            ).padStart(
                3,
                "0"
            );
    }
}


/* =========================================================
   SNAPSHOT METRICS
   ========================================================= */

function updateSnapshot() {
    const data =
        getPrimaryData() || {};

    const snapshot =
        data.snapshot &&
        typeof data.snapshot === "object"
            ? data.snapshot
            : {};

    setText(
        "[data-cves]",
        snapshot.cves
    );

    setText(
        "[data-known-exploited]",
        snapshot.knownExploited
    );

    setText(
        "[data-kev]",
        snapshot.knownExploited
    );

    setText(
        "[data-releases]",
        snapshot.releases
    );

    setText(
        "[data-projects]",
        snapshot.projects
    );

    setText(
        "[data-tech-entries]",
        snapshot.techEntries
    );

    setText(
        "[data-tracked-count]",
        snapshot.projects
    );

    setText(
        "[data-releases-total]",
        snapshot.releases
    );

    /*
     * Dynamic "first observation year" from the normalized history.
     */
    const history =
        Array.isArray(data.history)
            ? data.history
            : [];

    const oldest =
        history.length
            ? history[history.length - 1]
            : null;

    const dates =
        getDatesApi();

    let year = "—";

    if (
        oldest &&
        oldest.date &&
        dates &&
        typeof dates.chip === "function"
    ) {
        const chip =
            dates.chip(
                oldest.date
            );

        if (
            chip &&
            chip.year !== undefined &&
            chip.year !== null
        ) {
            year = chip.year;
        }
    }

    setText(
        "[data-first-year]",
        year
    );

    const meta =
        data.meta &&
        typeof data.meta === "object"
            ? data.meta
            : {};

    setText(
        "[data-days-observed]",
        meta.daysObserved
    );

    setText(
        "[data-snapshots-count]",
        meta.snapshots
    );
}


/* =========================================================
   SECURITY
   ========================================================= */

function updateSecurity() {
    const data =
        getPrimaryData() || {};

    const security =
        data.security &&
        typeof data.security === "object"
            ? data.security
            : {};

    setText(
        "[data-critical]",
        security.critical
    );

    setText(
        "[data-high]",
        security.high
    );

    setText(
        "[data-medium]",
        security.medium
    );

    setText(
        "[data-low]",
        security.low
    );

    setText(
        "[data-unscored]",
        security.unscored
    );

    updateSeverityBars(
        security
    );

    const homeList =
        document.querySelector(
            "[data-security-latest]"
        );

    if (homeList) {
        renderHomeVulnerabilityList(
            homeList,
            security.latest
        );
    }

    const fullList =
        document.querySelector(
            "[data-vulnerability-list]"
        );

    if (fullList) {
        renderVulnerabilityCards(
            fullList,
            security.latest
        );

        initSecurityFilters();
    }

    const historyBlock =
        document.querySelector(
            "[data-security-history]"
        );

    if (historyBlock) {
        const history =
            Array.isArray(data.history)
                ? data.history
                : [];

        renderSecurityHistory(
            historyBlock,
            history
        );
    }
}

function updateSeverityBars(
    security
) {
    const bars =
        document.querySelectorAll(
            "[data-severity-bar]"
        );

    const total =
        safeNonNegativeNumber(
            security.critical
        ) +
        safeNonNegativeNumber(
            security.high
        ) +
        safeNonNegativeNumber(
            security.medium
        ) +
        safeNonNegativeNumber(
            security.low
        ) +
        safeNonNegativeNumber(
            security.unscored
        );

    bars.forEach((bar) => {
        const key =
            (
                bar.dataset.severityBar ||
                ""
            ).toLowerCase();

        const value =
            safeNonNegativeNumber(
                security[key]
            );

        const fill =
            bar.querySelector(
                "[data-severity-fill]"
            );

        const label =
            bar.querySelector(
                "[data-severity-share]"
            );

        if (!fill) {
            return;
        }

        const share =
            total > 0
                ? Math.max(
                    (value / total) * 100,
                    value > 0 ? 4 : 0
                )
                : 0;

        if (
            prefersReducedMotion()
        ) {
            fill.style.width =
                `${share}%`;
        } else {
            requestAnimationFrame(
                () => {
                    fill.style.width =
                        `${share}%`;
                }
            );
        }

        if (label) {
            label.textContent =
                total > 0
                    ? `${Math.round((value / total) * 100)}%`
                    : "—";
        }
    });
}

function renderHomeVulnerabilityList(
    container,
    vulnerabilities
) {
    clearSkeletonState(
        container
    );

    if (
        !Array.isArray(vulnerabilities) ||
        !vulnerabilities.length
    ) {
        renderEmptyState(
            container,
            "No vulnerability data available for this edition."
        );
        return;
    }

    container.innerHTML =
        vulnerabilities
            .slice(0, 5)
            .map(
                (vuln, index) => `
        <div class="list-item reveal-item" style="--stagger:${index}">
            <div>
                <strong>${escapeHtml(vuln.id || "—")}</strong>
                <span>${escapeHtml(vuln.title || "Untitled vulnerability")}</span>
            </div>
            <span class="severity ${severityClass(vuln.severity)}">${escapeHtml(severityLabel(vuln.severity))}</span>
        </div>
    `
            )
            .join("");

    container
        .querySelectorAll(
            ".reveal-item"
        )
        .forEach((el) => {
            el.classList.add(
                "is-visible"
            );
        });
}

function renderVulnerabilityCards(
    container,
    vulnerabilities
) {
    clearSkeletonState(
        container
    );

    if (
        !Array.isArray(vulnerabilities) ||
        !vulnerabilities.length
    ) {
        renderEmptyState(
            container,
            "No vulnerability data available for this edition."
        );
        return;
    }

    container.innerHTML =
        vulnerabilities
            .map(
                (vuln, index) => {
                    const link =
                        safeUrl(
                            vuln.url
                        );

                    const id =
                        vuln.id ||
                        "—";

                    const idHtml =
                        link
                            ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">${escapeHtml(id)}</a>`
                            : escapeHtml(id);

                    const hasCvssScore =
                        vuln.cvss_score !== null &&
                        vuln.cvss_score !== undefined &&
                        Number.isFinite(
                            Number(
                                vuln.cvss_score
                            )
                        );

                    let cvss = "";

                    if (hasCvssScore) {
                        const score =
                            Number(
                                vuln.cvss_score
                            );

                        const version =
                            vuln.cvss_version !== null &&
                            vuln.cvss_version !== undefined &&
                            String(
                                vuln.cvss_version
                            ).trim()
                                ? ` v${escapeHtml(vuln.cvss_version)}`
                                : "";

                        cvss =
                            `<span>CVSS${version}: <strong>${escapeHtml(score)}</strong></span>`;
                    } else {
                        cvss =
                            "<span>CVSS: not yet scored</span>";
                    }

                    const kev =
                        vuln.known_exploited
                            ? '<span class="kev-badge" title="Present in the CISA Known Exploited Vulnerabilities catalog">KNOWN EXPLOITED</span>'
                            : "";

                    return `
        <article class="vulnerability-card reveal-item" data-severity="${severityClass(vuln.severity)}" style="--stagger:${index}">
            <div class="vulnerability-id">
                <span>CVE</span>
                <strong>${idHtml}</strong>
            </div>
            <div class="vulnerability-content">
                <h3>${escapeHtml(vuln.title || "Untitled vulnerability")}</h3>
                <p>${escapeHtml(vuln.description || "No description available.")}</p>
                <div class="vulnerability-meta">
                    <span title="${escapeHtml(formatDisplayDate(vuln.publishedAt))}">
                        Published ${escapeHtml(formatRelativeDate(vuln.publishedAt))}
                    </span>
                    ${cvss}
                    ${kev}
                </div>
            </div>
            <span class="severity ${severityClass(vuln.severity)}">
                ${escapeHtml(severityLabel(vuln.severity))}
            </span>
        </article>`;
                }
            )
            .join("");
}

function renderSecurityHistory(
    container,
    history
) {
    clearSkeletonState(
        container
    );

    if (
        !Array.isArray(history) ||
        !history.length
    ) {
        renderEmptyState(
            container,
            "No historical security data available yet."
        );
        return;
    }

    container.innerHTML =
        history
            .slice(0, 10)
            .map(
                (item, index) => `
        <div class="security-history-row reveal-item" style="--stagger:${index}">
            <span class="history-date" title="${escapeHtml(formatDisplayDate(item.date))}">
                ${escapeHtml(formatRelativeDate(item.date))}
            </span>
            <span>${formatNumber(item.cves)} CVEs</span>
            <span>${formatNumber(item.knownExploited)} exploited</span>
            <span>${formatNumber(item.releases)} releases</span>
        </div>
    `
            )
            .join("");
}


/* =========================================================
   RELEASES
   ========================================================= */

function updateReleases() {
    const data =
        getPrimaryData() || {};

    const releases =
        Array.isArray(data.releases)
            ? data.releases
            : [];

    const categories = {
        major: 0,
        minor: 0,
        patch: 0,
        other: 0
    };

    releases.forEach((rel) => {
        const kind =
            typeof rel.kind === "string"
                ? rel.kind
                : "other";

        if (
            Object.prototype.hasOwnProperty.call(
                categories,
                kind
            )
        ) {
            categories[kind] += 1;
        } else {
            categories.other += 1;
        }
    });

    setText(
        "[data-releases-count]",
        releases.length
    );

    setText(
        "[data-releases-major]",
        categories.major
    );

    setText(
        "[data-releases-minor]",
        categories.minor
    );

    setText(
        "[data-releases-patch]",
        categories.patch
    );

    const listContainer =
        document.querySelector(
            "[data-releases-list]"
        );

    if (listContainer) {
        renderReleasesTable(
            listContainer,
            releases
        );
    }

    const trackedContainer =
        document.querySelector(
            "[data-tracked-projects]"
        );

    if (trackedContainer) {
        renderTrackedProjects(
            trackedContainer,
            data.openSource
        );
    }
}

function renderReleasesTable(
    container,
    releases
) {
    clearSkeletonState(
        container
    );

    if (
        !Array.isArray(releases) ||
        !releases.length
    ) {
        renderEmptyState(
            container,
            "No releases detected in this edition's window."
        );
        return;
    }

    container.innerHTML =
        releases
            .map(
                (rel, index) => {
                    const kind =
                        typeof rel.kind === "string" &&
                        rel.kind.trim()
                            ? rel.kind.trim().toLowerCase()
                            : "other";

                    const project =
                        rel.project ||
                        "—";

                    const icon =
                        String(project)
                            .charAt(0)
                            .toUpperCase() ||
                        "·";

                    const absolute =
                        formatDisplayDate(
                            rel.publishedAt
                        );

                    return `
        <article class="release-row reveal-item" style="--stagger:${index}">
            <div class="release-project">
                <div class="release-icon" aria-hidden="true">${escapeHtml(icon)}</div>
                <div>
                    <strong>${escapeHtml(project)}</strong>
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
            <time datetime="${escapeHtml(rel.publishedAt || "")}" title="${escapeHtml(absolute)}">
                ${escapeHtml(formatRelativeDate(rel.publishedAt))}
            </time>
        </article>`;
                }
            )
            .join("");
}

function renderTrackedProjects(
    container,
    projects
) {
    clearSkeletonState(
        container
    );

    if (
        !Array.isArray(projects) ||
        !projects.length
    ) {
        renderEmptyState(
            container,
            "Repository data unavailable for this edition."
        );
        return;
    }

    container.innerHTML =
        projects
            .map(
                (project, index) => `
        <div class="tracked-project reveal-item" style="--stagger:${index}">
            <strong>${escapeHtml(project.name || "—")}</strong>
            <span>${escapeHtml(project.full_name || "—")}</span>
        </div>
    `
            )
            .join("");
}


/* =========================================================
   OPEN SOURCE
   ========================================================= */

function updateOpenSource() {
    const data =
        getPrimaryData() || {};

    const projects =
        Array.isArray(data.openSource)
            ? data.openSource
            : [];

    const container =
        document.querySelector(
            "[data-opensource-list]"
        );

    if (container) {
        renderOpenSourceList(
            container,
            projects
        );
    }
}

function renderOpenSourceList(
    container,
    projects
) {
    clearSkeletonState(
        container
    );

    if (
        !Array.isArray(projects) ||
        !projects.length
    ) {
        renderEmptyState(
            container,
            "Open-source data unavailable for this edition. Run the GitHub collector to populate this view."
        );
        return;
    }

    container.innerHTML =
        projects
            .map(
                (project, index) => {
                    const growthAvailable =
                        project.growth_available === true &&
                        project.daily_growth !== null &&
                        project.daily_growth !== undefined &&
                        Number.isFinite(
                            Number(
                                project.daily_growth
                            )
                        );

                    const growth =
                        growthAvailable
                            ? `${Number(project.daily_growth) >= 0 ? "+" : ""}${formatNumber(project.daily_growth)} <span>stars</span>`
                            : '<span class="growth-na">growth n/a</span>';

                    const link =
                        safeUrl(
                            project.url
                        );

                    const projectName =
                        project.name ||
                        project.full_name ||
                        "—";

                    const nameHtml =
                        link
                            ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">${escapeHtml(projectName)}</a>`
                            : escapeHtml(projectName);

                    const rank =
                        Number.isFinite(
                            Number(
                                project.rank
                            )
                        ) &&
                        Number(project.rank) > 0
                            ? Math.floor(
                                Number(
                                    project.rank
                                )
                            )
                            : 0;

                    return `
        <article class="opensource-card reveal-item" style="--stagger:${index}">
            <div class="opensource-rank">#${String(rank).padStart(2, "0")}</div>
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
                    <div>
                        <strong>${formatNumber(project.stars)}</strong>
                        <span>Stars</span>
                    </div>
                    <div>
                        <strong>${growthAvailable ? formatNumber(project.daily_growth) : "n/a"}</strong>
                        <span>Daily growth</span>
                    </div>
                    <div>
                        <strong>${escapeHtml(project.language || "—")}</strong>
                        <span>Language</span>
                    </div>
                </div>
            </div>
        </article>`;
                }
            )
            .join("");
}


/* =========================================================
   TECHNOLOGY
   ========================================================= */

function updateTechnology() {
    const data =
        getPrimaryData() || {};

    const entries =
        Array.isArray(data.technology)
            ? data.technology
            : [];

    const container =
        document.querySelector(
            "[data-technology-list]"
        );

    if (container) {
        renderTechList(
            container,
            entries
        );
    }
}

function renderTechList(
    container,
    entries
) {
    clearSkeletonState(
        container
    );

    if (
        !Array.isArray(entries) ||
        !entries.length
    ) {
        renderEmptyState(
            container,
            "No technology updates collected for this edition."
        );
        return;
    }

    container.innerHTML =
        entries
            .map(
                (entry, index) => `
        <div class="tech-item reveal-item" style="--stagger:${index}">
            <h4>
                ${safeLink(
                    entry.url,
                    entry.title || "(untitled)",
                    "tech-link"
                )}
            </h4>
            <div class="tech-meta">
                <span class="tech-source">${escapeHtml(entry.source || "Unknown")}</span>
                <span class="tech-category">${escapeHtml(entry.category || "tech")}</span>
                <span class="tech-date" title="${escapeHtml(formatDisplayDate(entry.publishedAt))}">
                    ${escapeHtml(formatRelativeDate(entry.publishedAt))}
                </span>
            </div>
            <p>${escapeHtml(entry.summary || "")}</p>
        </div>
    `
            )
            .join("");
}


/* =========================================================
   HISTORY
   ========================================================= */

function updateHistory() {
    const data =
        getPrimaryData() || {};

    const history =
        Array.isArray(data.history)
            ? data.history
            : [];

    const preview =
        document.querySelector(
            "[data-history-preview]"
        );

    if (preview) {
        renderHistoryPreview(
            preview,
            history.slice(0, 5)
        );
    }

    const listContainer =
        document.querySelector(
            "[data-history-list]"
        );

    if (listContainer) {
        renderHistoryCards(
            listContainer,
            history
        );
    }

    const status =
        document.querySelector(
            "[data-archive-status]"
        );

    if (status) {
        status.textContent =
            history.length
                ? `${history.length} snapshot${history.length === 1 ? "" : "s"}`
                : "No snapshots yet";
    }
}

function renderHistoryPreview(
    container,
    history
) {
    clearSkeletonState(
        container
    );

    if (
        !Array.isArray(history) ||
        !history.length
    ) {
        renderEmptyState(
            container,
            "The archive begins with the first daily run."
        );
        return;
    }

    const dates =
        getDatesApi();

    const year =
        history[0].date &&
        dates &&
        typeof dates.chip === "function"
            ? dates.chip(
                history[0].date
            ).year
            : "";

    container.innerHTML = `
        <div class="timeline-year">${escapeHtml(year)}</div>
        <div class="timeline">
            ${history
                .map(
                    (item, index) => {
                        const chip =
                            dates &&
                            typeof dates.chip === "function"
                                ? dates.chip(
                                    item.date
                                )
                                : {
                                    day: "—",
                                    month: "—"
                                };

                        return `
                <div class="timeline-item ${index === 0 ? "active" : ""} reveal-item" style="--stagger:${index}">
                    <span>${escapeHtml(chip.day)}</span>
                    <div>
                        <strong>${escapeHtml(chip.month)}</strong>
                        <small>${formatNumber(item.cves)} CVEs · ${formatNumber(item.releases)} releases</small>
                    </div>
                </div>`;
                    }
                )
                .join("")}
        </div>`;
}

function renderHistoryCards(
    container,
    history
) {
    clearSkeletonState(
        container
    );

    if (
        !Array.isArray(history) ||
        !history.length
    ) {
        renderEmptyState(
            container,
            "No historical snapshots yet. The archive grows daily."
        );
        return;
    }

    const data =
        getPrimaryData() || {};

    const meta =
        data.meta &&
        typeof data.meta === "object"
            ? data.meta
            : {};

    const currentDate =
        meta.date;

    const dates =
        getDatesApi();

    container.innerHTML =
        history
            .map(
                (item, index) => {
                    const chip =
                        dates &&
                        typeof dates.chip === "function"
                            ? dates.chip(
                                item.date
                            )
                            : {
                                day: "—",
                                monthYear: "—"
                            };

                    const weekday =
                        dates &&
                        typeof dates.weekday === "function"
                            ? dates.weekday(
                                item.date
                            )
                            : "—";

                    const isCurrent =
                        item.date === currentDate;

                    return `
        <article class="history-card reveal-item" style="--stagger:${index}">
            <div class="history-date">
                <strong>${escapeHtml(chip.day)}</strong>
                <span>${escapeHtml(String(chip.monthYear || "").toUpperCase())}</span>
            </div>
            <div class="history-content">
                <div class="history-header">
                    <div>
                        <h3>Daily Technology Snapshot</h3>
                        <span>
                            ${escapeHtml(weekday)}
                            ${isCurrent ? " · Most recent" : ""}
                        </span>
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
                }
            )
            .join("");
}


/* =========================================================
   ARCHIVE PAGE — history.html
   Deep snapshot data from archive.json
   ========================================================= */

async function renderArchivePage() {
    const container =
        document.querySelector(
            "[data-archive-list]"
        );

    if (!container) {
        return;
    }

    const archiveData =
        getArchiveData();

    if (!archiveData) {
        renderErrorState(
            container,
            getArchiveError()
        );
        return;
    }

    const archive =
        Array.isArray(
            archiveData.archive
        )
            ? archiveData.archive
            : [];

    clearSkeletonState(
        container
    );

    if (!archive.length) {
        renderEmptyState(
            container,
            "No archived snapshots available yet."
        );
        return;
    }

    const dates =
        getDatesApi();

    container.innerHTML =
        archive
            .map(
                (snap, index) => {
                    const counts =
                        snap.snapshot &&
                        typeof snap.snapshot === "object"
                            ? snap.snapshot
                            : {};

                    const severity =
                        snap.security &&
                        snap.security.severity &&
                        typeof snap.security.severity === "object"
                            ? snap.security.severity
                            : {};

                    const releases =
                        snap.releases &&
                        Array.isArray(
                            snap.releases.recent
                        )
                            ? snap.releases.recent
                            : [];

                    const projects =
                        snap.opensource &&
                        Array.isArray(
                            snap.opensource.topProjects
                        )
                            ? snap.opensource.topProjects
                            : [];

                    const tech =
                        snap.technology &&
                        Array.isArray(
                            snap.technology.recent
                        )
                            ? snap.technology.recent
                            : [];

                    const chip =
                        dates &&
                        typeof dates.chip === "function"
                            ? dates.chip(
                                snap.date
                            )
                            : {
                                day: "—",
                                monthYear: "—"
                            };

                    const releaseItems =
                        releases.length
                            ? releases
                                .slice(0, 5)
                                .map(
                                    (r) => `
                <li>
                    ${safeLink(
                        r.url,
                        `${r.project || "—"} ${r.version || ""}`.trim(),
                        "archive-link"
                    )}
                </li>`
                                )
                                .join("")
                            : '<li class="archive-empty">No releases recorded</li>';

                    const projectItems =
                        projects.length
                            ? projects
                                .slice(0, 5)
                                .map(
                                    (p) => `
                <li>
                    ${escapeHtml(p.full_name || "—")}
                    · ★ ${formatNumber(p.stars)}
                </li>`
                                )
                                .join("")
                            : '<li class="archive-empty">No project data recorded</li>';

                    const techItems =
                        tech.length
                            ? tech
                                .slice(0, 5)
                                .map(
                                    (t) => `
                <li>
                    ${safeLink(
                        t.url,
                        t.title || "(untitled)",
                        "archive-link"
                    )}
                </li>`
                                )
                                .join("")
                            : '<li class="archive-empty">No tech entries recorded</li>';

                    return `
        <article class="history-card archive-detail reveal-item" style="--stagger:${index}">
            <div class="history-date">
                <strong>${escapeHtml(chip.day)}</strong>
                <span>${escapeHtml(String(chip.monthYear || "").toUpperCase())}</span>
            </div>
            <div class="history-content">
                <div class="history-header">
                    <div>
                        <h3>Daily Technology Snapshot</h3>
                        <span>
                            ${formatNumber(counts.cves)} CVEs ·
                            ${formatNumber(counts.knownExploited)} exploited ·
                            ${formatNumber(counts.releases)} releases
                        </span>
                    </div>
                </div>

                <div class="history-stats">
                    <div>
                        <strong>${formatNumber(severity.CRITICAL)}</strong>
                        <span>Critical</span>
                    </div>
                    <div>
                        <strong>${formatNumber(severity.HIGH)}</strong>
                        <span>High</span>
                    </div>
                    <div>
                        <strong>${formatNumber(severity.MEDIUM)}</strong>
                        <span>Medium</span>
                    </div>
                    <div>
                        <strong>${formatNumber(counts.techEntries)}</strong>
                        <span>Tech</span>
                    </div>
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
                }
            )
            .join("");
}


/* =========================================================
   STATUS
   ========================================================= */

function updateStatus() {
    const loaded =
        isPrimaryDataLoaded();

    const error =
        getPrimaryDataError();

    const api =
        getDataApi();

    let hasSourceFailures = false;

    if (
        loaded &&
        api &&
        typeof api.hasSourceFailures === "function"
    ) {
        try {
            hasSourceFailures =
                api.hasSourceFailures() === true;
        } catch (sourceError) {
            hasSourceFailures = true;
        }
    }

    const degraded =
        loaded &&
        hasSourceFailures;

    const dotElements =
        document.querySelectorAll(
            "[data-status-dot]"
        );

    const textElements =
        document.querySelectorAll(
            "[data-status-text]"
        );

    const mainStatus =
        document.querySelector(
            "[data-status-main]"
        );

    dotElements.forEach((el) => {
        el.classList.remove(
            "is-live",
            "is-warning",
            "is-error"
        );

        if (!loaded) {
            el.classList.add(
                "is-error"
            );
        } else if (degraded) {
            el.classList.add(
                "is-warning"
            );
        } else {
            el.classList.add(
                "is-live"
            );
        }
    });

    textElements.forEach((el) => {
        el.textContent =
            !loaded
                ? "No data"
                : degraded
                    ? "Partial"
                    : "Live";
    });

    if (mainStatus) {
        mainStatus.classList.remove(
            "is-live",
            "is-warning",
            "is-error"
        );

        if (!loaded) {
            mainStatus.classList.add(
                "is-error"
            );

            mainStatus.textContent =
                "No data";

            mainStatus.title =
                error
                    ? `Data unavailable: ${error}`
                    : "Data unavailable";
        } else if (degraded) {
            mainStatus.classList.add(
                "is-warning"
            );

            mainStatus.textContent =
                "Partial";

            mainStatus.title =
                "One or more sources were unavailable during collection.";
        } else {
            mainStatus.classList.add(
                "is-live"
            );

            mainStatus.textContent =
                "Live";

            mainStatus.title = "";
        }
    }
}


/* =========================================================
   FILTERS
   ========================================================= */

function initSecurityFilters() {
    const filterButtons =
        document.querySelectorAll(
            "[data-filter]"
        );

    const listContainer =
        document.querySelector(
            "[data-vulnerability-list]"
        );

    if (
        !filterButtons.length ||
        !listContainer
    ) {
        return;
    }

    /*
     * Prevent duplicate event listeners if updateAll() is ever
     * invoked again during the same page lifetime.
     */
    if (
        listContainer.dataset.filtersInitialized === "true"
    ) {
        return;
    }

    listContainer.dataset.filtersInitialized =
        "true";

    const cards = () =>
        listContainer.querySelectorAll(
            ".vulnerability-card"
        );

    let note =
        listContainer.querySelector(
            "[data-filter-empty]"
        );

    if (!note) {
        note =
            document.createElement(
                "div"
            );

        note.className =
            "empty-state";

        note.setAttribute(
            "data-filter-empty",
            ""
        );

        note.hidden = true;

        note.textContent =
            "No CVEs with this severity in the displayed list.";

        listContainer.appendChild(
            note
        );
    }

    const applyFilter = (
        filter
    ) => {
        const normalizedFilter =
            typeof filter === "string" &&
            filter.trim()
                ? filter
                    .trim()
                    .toLowerCase()
                : "all";

        let visible = 0;

        cards().forEach((card) => {
            const match =
                normalizedFilter === "all" ||
                card.dataset.severity ===
                    normalizedFilter;

            card.classList.toggle(
                "is-hidden",
                !match
            );

            if (match) {
                visible += 1;
            }
        });

        note.hidden =
            visible > 0 ||
            normalizedFilter === "all";
    };

    filterButtons.forEach(
        (button) => {
            if (
                !button.hasAttribute(
                    "aria-pressed"
                )
            ) {
                button.setAttribute(
                    "aria-pressed",
                    button.classList.contains(
                        "active"
                    )
                        ? "true"
                        : "false"
                );
            }

            button.addEventListener(
                "click",
                () => {
                    filterButtons.forEach(
                        (otherButton) => {
                            otherButton.classList.remove(
                                "active"
                            );

                            otherButton.setAttribute(
                                "aria-pressed",
                                "false"
                            );
                        }
                    );

                    button.classList.add(
                        "active"
                    );

                    button.setAttribute(
                        "aria-pressed",
                        "true"
                    );

                    applyFilter(
                        button.dataset.filter
                    );
                }
            );
        }
    );

    applyFilter(
        "all"
    );
}


/* =========================================================
   MOTION — reveal on scroll, reduced motion
   ========================================================= */

function prefersReducedMotion() {
    return (
        typeof window.matchMedia === "function" &&
        window.matchMedia(
            "(prefers-reduced-motion: reduce)"
        ).matches
    );
}

function initRevealAnimations() {
    const targets =
        document.querySelectorAll(
            ".reveal, .reveal-item"
        );

    if (!targets.length) {
        return;
    }

    if (
        prefersReducedMotion() ||
        !("IntersectionObserver" in window)
    ) {
        targets.forEach(
            (el) => {
                el.classList.add(
                    "is-visible"
                );
            }
        );

        return;
    }

    const observer =
        new IntersectionObserver(
            (entries) => {
                let batchIndex = 0;

                const visible =
                    entries.filter(
                        (entry) =>
                            entry.isIntersecting
                    );

                visible.forEach(
                    (entry) => {
                        const el =
                            entry.target;

                        if (
                            !el.style.getPropertyValue(
                                "--reveal-delay"
                            )
                        ) {
                            el.style.setProperty(
                                "--reveal-delay",
                                `${Math.min(
                                    batchIndex * 60,
                                    420
                                )}ms`
                            );

                            batchIndex += 1;
                        }

                        el.classList.add(
                            "is-visible"
                        );

                        observer.unobserve(
                            el
                        );
                    }
                );
            },
            {
                threshold: 0.08,
                rootMargin: "0px 0px -5% 0px"
            }
        );

    targets.forEach(
        (el) => observer.observe(el)
    );
}
