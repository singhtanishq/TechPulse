/* =========================================================
   TECHPULSE — COMPONENTS

   Shared, security-conscious UI helpers.

   Security rules:
     - All external/source-derived text passes through escapeHtml()
       before insertion.
     - All URLs pass through safeUrl(); only http/https links are
       rendered.
     - No raw external HTML is ever injected.
     - CSS class values inserted into HTML are escaped.

   Date rules:
     - TechPulse calendar dates are India days (Asia/Kolkata).
     - Relative labels are computed live in the browser from ISO
       timestamps — never frozen into generated data.

   Data rules:
     - Missing/null/invalid numeric values remain "—".
     - Helpers do not silently convert malformed data into valid-looking
       values.
   ========================================================= */


/**
 * Escape a value for safe interpolation into HTML text or attributes.
 *
 * Escapes:
 *   &
 *   <
 *   >
 *   "
 *   '
 */
function escapeHtml(value) {
    if (value === null || value === undefined) {
        return "";
    }

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}


/**
 * Return a safe http(s) URL, or null when the value is missing,
 * malformed, or uses a dangerous scheme.
 *
 * Relative URLs are intentionally allowed because some TechPulse
 * internal links use relative paths.
 */
function safeUrl(value) {
    if (typeof value !== "string") {
        return null;
    }

    const trimmed = value.trim();

    if (!trimmed) {
        return null;
    }

    try {
        const parsed = new URL(
            trimmed,
            window.location.href
        );

        if (
            parsed.protocol !== "http:" &&
            parsed.protocol !== "https:"
        ) {
            return null;
        }

        /*
         * Reject URLs containing credentials. A source URL with embedded
         * credentials is not appropriate for the public TechPulse UI.
         */
        if (parsed.username || parsed.password) {
            return null;
        }

        return trimmed;
    } catch (error) {
        return null;
    }
}


/**
 * Render an anchor safely, or plain text when the URL is unsafe.
 */
function safeLink(href, text, cssClass) {
    const fallbackLabel =
        href ||
        "Link";

    const label = escapeHtml(
        text ||
        fallbackLabel
    );

    const url = safeUrl(
        href
    );

    if (!url) {
        const className = escapeHtml(
            cssClass ||
            "link-dead"
        );

        return (
            `<span class="${className}">` +
            `${label}` +
            `</span>`
        );
    }

    const classAttribute = cssClass
        ? ` class="${escapeHtml(cssClass)}"`
        : "";

    return (
        `<a href="${escapeHtml(url)}"` +
        ` target="_blank"` +
        ` rel="noopener noreferrer"` +
        ` referrerpolicy="no-referrer"` +
        `${classAttribute}>` +
        `${label}` +
        `</a>`
    );
}


/**
 * Never render undefined / null / invalid numeric values.
 * Fallback defaults to an honest dash.
 */
function displayValue(value, fallback) {
    const safeFallback =
        fallback ||
        "—";

    if (
        value === null ||
        value === undefined
    ) {
        return safeFallback;
    }

    if (
        typeof value === "number" &&
        !Number.isFinite(value)
    ) {
        return safeFallback;
    }

    return value;
}


/**
 * Set text content without interpreting the value as HTML.
 */
function setText(selector, value) {
    const element =
        document.querySelector(
            selector
        );

    if (!element) {
        return;
    }

    element.textContent =
        String(
            displayValue(value)
        );
}


/* ---------------------------------------------------------
   Dates — thin delegates to the IST-aware dates.js module.
   --------------------------------------------------------- */


/** Deterministic TechPulse date display. */
function formatDisplayDate(dateString) {
    if (
        window.TechPulseDates &&
        typeof window.TechPulseDates.display === "function"
    ) {
        return window.TechPulseDates.display(
            dateString
        );
    }

    return "—";
}


/** Live relative label versus the current IST calendar date. */
function formatRelativeDate(dateString) {
    if (
        window.TechPulseDates &&
        typeof window.TechPulseDates.relative === "function"
    ) {
        return window.TechPulseDates.relative(
            dateString
        );
    }

    return "—";
}


/** ISO timestamp formatted explicitly in IST. */
function formatTimestampIST(value) {
    if (
        window.TechPulseDates &&
        typeof window.TechPulseDates.timestampIST === "function"
    ) {
        return window.TechPulseDates.timestampIST(
            value
        );
    }

    return "—";
}


/**
 * Format a numeric value for display.
 *
 * Empty strings, whitespace, booleans, objects and invalid numeric
 * values remain "—" rather than being coerced into misleading numbers.
 */
function formatNumber(value) {
    if (
        value === null ||
        value === undefined ||
        value === ""
    ) {
        return "—";
    }

    if (
        typeof value === "string" &&
        !value.trim()
    ) {
        return "—";
    }

    if (
        typeof value === "boolean" ||
        typeof value === "object"
    ) {
        return "—";
    }

    const num =
        typeof value === "number"
            ? value
            : Number(
                String(value).trim()
            );

    if (
        !Number.isFinite(num)
    ) {
        return "—";
    }

    return num.toLocaleString(
        "en-US"
    );
}


/**
 * Truncate text safely while preserving a reasonable readable boundary.
 */
function truncateText(text, maxLength) {
    if (
        typeof text !== "string"
    ) {
        return "";
    }

    if (
        !Number.isFinite(maxLength) ||
        maxLength <= 0
    ) {
        return "";
    }

    const limit = Math.floor(
        maxLength
    );

    if (
        text.length <= limit
    ) {
        return text;
    }

    if (limit <= 1) {
        return "…";
    }

    const truncated =
        text
            .slice(
                0,
                limit - 1
            )
            .trimEnd();

    return (
        truncated ||
        text.slice(
            0,
            limit - 1
        )
    ) + "…";
}


/**
 * CSS severity class for possibly-null severity.
 */
function severityClass(severity) {
    const normalized =
        typeof severity === "string"
            ? severity
                .trim()
                .toLowerCase()
            : "";

    if (
        [
            "critical",
            "high",
            "medium",
            "low",
            "none"
        ].includes(normalized)
    ) {
        return normalized;
    }

    return "unscored";
}


/**
 * Human-readable severity label.
 */
function severityLabel(severity) {
    if (
        typeof severity !== "string" ||
        !severity.trim()
    ) {
        return "UNSCORED";
    }

    const normalized =
        severity
            .trim()
            .toLowerCase();

    if (
        [
            "critical",
            "high",
            "medium",
            "low",
            "none"
        ].includes(normalized)
    ) {
        return normalized.toUpperCase();
    }

    return "UNSCORED";
}


/* ---------------------------------------------------------
   States — loading / empty / error
   --------------------------------------------------------- */


/**
 * Render an empty state.
 *
 * Message is escaped before HTML insertion.
 */
function renderEmptyState(
    container,
    message
) {
    if (!container) {
        return;
    }

    const text =
        message ||
        "No data available";

    container.innerHTML =
        `<div class="empty-state">` +
        `${escapeHtml(text)}` +
        `</div>`;
}


/**
 * Render an error state.
 *
 * The supplied message is treated as untrusted text.
 */
function renderErrorState(
    container,
    message
) {
    if (!container) {
        return;
    }

    const text =
        message ||
        "Something went wrong while loading this view.";

    container.innerHTML =
        `<div class="empty-state empty-state--error" role="status">` +
        `<strong>Unable to load data</strong>` +
        `<span>${escapeHtml(text)}</span>` +
        `</div>`;
}


/**
 * Render loading skeletons.
 */
function renderSkeletons(
    container,
    count,
    variant
) {
    if (!container) {
        return;
    }

    let skeletonCount = Number(
        count
    );

    if (
        !Number.isFinite(
            skeletonCount
        ) ||
        skeletonCount < 0
    ) {
        skeletonCount = 3;
    }

    skeletonCount = Math.min(
        Math.floor(
            skeletonCount
        ),
        20
    );

    const variantClass =
        variant
            ? ` skeleton--${escapeHtml(variant)}`
            : "";

    const skeletons = [];

    for (
        let i = 0;
        i < skeletonCount;
        i += 1
    ) {
        skeletons.push(
            `<div class="skeleton${variantClass}" aria-hidden="true">` +
            `<span class="skeleton-line"></span>` +
            `<span class="skeleton-line skeleton-line--short"></span>` +
            `</div>`
        );
    }

    container.innerHTML =
        skeletons.join("");
}
