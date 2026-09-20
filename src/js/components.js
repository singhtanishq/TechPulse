/* =========================================================
   TECHPULSE — COMPONENTS
   Shared, security-conscious UI helpers.

   Security rules:
     - All external/source-derived text passes through escapeHtml()
       before insertion (escapes &, <, >, ", ').
     - All URLs pass through safeUrl(); only http/https links are
       rendered, everything else renders as inert text.
     - No raw external HTML is ever injected.

   Date rules (see dates.js):
     - TechPulse calendar dates are India days (Asia/Kolkata).
     - Relative labels are computed live in the browser from ISO
       timestamps — never frozen into the data.
   ========================================================= */

/**
 * Escape a value for safe interpolation into HTML text or attributes.
 * Escapes &, <, >, ", and ' — attribute-safe.
 */
function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

/**
 * Return a safe http(s) URL, or null when the value is missing or
 * uses a dangerous scheme (javascript:, data:, vbscript:, etc.).
 */
function safeUrl(value) {
    if (typeof value !== "string") return null;
    const trimmed = value.trim();
    if (!trimmed) return null;
    try {
        const parsed = new URL(trimmed, "https://techpulse.invalid");
        if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
            return null;
        }
        return trimmed;
    } catch (error) {
        return null;
    }
}

/** Render an anchor safely, or plain text when the URL is unsafe. */
function safeLink(href, text, cssClass) {
    const label = escapeHtml(text || href || "Link");
    const url = safeUrl(href);
    if (!url) {
        return `<span class="${escapeHtml(cssClass || "link-dead")}">${label}</span>`;
    }
    return (
        `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer"` +
        `${cssClass ? ` class="${escapeHtml(cssClass)}"` : ""}>${label}</a>`
    );
}

/** Never render undefined / null / NaN — show an honest dash instead. */
function displayValue(value, fallback) {
    if (value === null || value === undefined) return fallback || "—";
    if (typeof value === "number" && !Number.isFinite(value)) return fallback || "—";
    return value;
}

function setText(selector, value) {
    const element = document.querySelector(selector);
    if (element) {
        element.textContent = displayValue(value);
    }
}

/* ---------------------------------------------------------
   Dates — thin delegates to the IST-aware dates.js module.
   --------------------------------------------------------- */

function formatDisplayDate(dateString) {
    if (window.TechPulseDates) return window.TechPulseDates.display(dateString);
    return "—";
}

/** Live relative label vs the current IST calendar date. */
function formatRelativeDate(dateString) {
    if (window.TechPulseDates) return window.TechPulseDates.relative(dateString);
    return "—";
}

/** ISO timestamp formatted explicitly in IST. */
function formatTimestampIST(value) {
    if (window.TechPulseDates) return window.TechPulseDates.timestampIST(value);
    return "—";
}

function formatNumber(value) {
    const num = Number(value);
    if (value === null || value === undefined || Number.isNaN(num)) return "—";
    return num.toLocaleString("en-US");
}

function truncateText(text, maxLength) {
    if (typeof text !== "string") return "";
    if (text.length <= maxLength) return text;
    return text.slice(0, maxLength).trimEnd() + "…";
}

/** CSS severity class for a possibly-null severity (unscored CVEs). */
function severityClass(severity) {
    const normalized = (severity || "").toLowerCase();
    if (["critical", "high", "medium", "low", "none"].includes(normalized)) {
        return normalized;
    }
    return "unscored";
}

function severityLabel(severity) {
    return severity ? String(severity).toUpperCase() : "UNSCORED";
}

/* ---------------------------------------------------------
   States — loading / empty / error
   --------------------------------------------------------- */

function renderEmptyState(container, message) {
    if (container) {
        container.innerHTML =
            `<div class="empty-state">${escapeHtml(message || "No data available")}</div>`;
    }
}

function renderErrorState(container, message) {
    if (container) {
        container.innerHTML =
            `<div class="empty-state empty-state--error" role="status">` +
            `<strong>Unable to load data</strong>` +
            `<span>${escapeHtml(message || "Something went wrong while loading this view.")}</span>` +
            `</div>`;
    }
}

function renderSkeletons(container, count, variant) {
    if (!container) return;
    const skeletons = [];
    for (let i = 0; i < (count || 3); i++) {
        skeletons.push(
            `<div class="skeleton ${variant ? `skeleton--${escapeHtml(variant)}` : ""}" aria-hidden="true">` +
            `<span class="skeleton-line"></span>` +
            `<span class="skeleton-line skeleton-line--short"></span>` +
            `</div>`
        );
    }
    container.innerHTML = skeletons.join("");
}
