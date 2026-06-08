/* =========================================================
   TECHPULSE — COMPONENTS
   Shared, security-conscious UI helpers.

   Security rules:
     - All external/source-derived text passes through escapeHtml()
       before insertion (escapes &, <, >, ", ').
     - All URLs pass through safeUrl(); only http/https links are
       rendered, everything else renders as inert text.
     - No raw external HTML is ever injected.
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

function formatDisplayDate(dateString) {
    if (!dateString || typeof dateString !== "string") return "—";
    const date = new Date(`${dateString}T00:00:00Z`);
    if (Number.isNaN(date.getTime())) return "—";
    return date
        .toLocaleDateString("en-GB", {
            day: "2-digit",
            month: "short",
            year: "numeric",
            timeZone: "UTC"
        })
        .toUpperCase();
}

function formatRelativeDate(dateString) {
    if (!dateString || typeof dateString !== "string") return "—";
    const date = new Date(dateString);
    if (Number.isNaN(date.getTime())) return "—";
    const now = new Date();
    const diffDays = Math.floor(
        (Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) -
         Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate())) / 86400000
    );
    if (diffDays <= 0) return "Today";
    if (diffDays === 1) return "Yesterday";
    if (diffDays < 7) return `${diffDays} days ago`;
    return formatDisplayDate(dateString.slice(0, 10));
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

function renderEmptyState(container, message) {
    if (container) {
        container.innerHTML =
            `<div class="empty-state">${escapeHtml(message || "No data available")}</div>`;
    }
}
