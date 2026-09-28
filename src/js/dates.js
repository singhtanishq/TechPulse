/* =========================================================
   TECHPULSE — DATE UTILITIES
   All TechPulse reporting dates are India calendar days
   (Asia/Kolkata, UTC+05:30, no DST).

   Rules:
     - Date-only values ("YYYY-MM-DD") are calendar dates. They are
       read from their string parts — never parsed as UTC instants —
       so every visitor on Earth sees the same TechPulse date.
     - Full ISO timestamps carry their own offset and are formatted
       explicitly in Asia/Kolkata (never the browser timezone).
     - "Today / Yesterday / N days ago" are computed against the
       current IST calendar date, derived from the UTC clock — which
       is identical for every visitor regardless of their timezone.
   ========================================================= */

const TECHPULSE_IST_OFFSET_MINUTES = 330; // UTC+05:30

const TECHPULSE_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
];

const TECHPULSE_MONTHS_LONG = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
];

const TECHPULSE_WEEKDAYS = [
    "Sunday", "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday"
];

/** Is this string a bare calendar date ("YYYY-MM-DD")? */
function isDateOnlyString(value) {
    return typeof value === "string"
        && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

/** The current instant (same for every visitor). */
function techpulseNow() {
    return Date.now();
}

/**
 * Current TechPulse reporting "today" — the IST calendar date
 * derived from the universal UTC clock, optionally shifted by
 * whole minutes (mirrors the pipeline's jitter buffer semantics).
 */
function istTodayString(offsetMinutes = 0) {
    const shifted = new Date(techpulseNow() + offsetMinutes * 60000);
    const istMs = shifted.getTime() + TECHPULSE_IST_OFFSET_MINUTES * 60000;
    const ist = new Date(istMs);
    const y = ist.getUTCFullYear();
    const m = String(ist.getUTCMonth() + 1).padStart(2, "0");
    const d = String(ist.getUTCDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
}

/** Split a "YYYY-MM-DD" string into numeric parts (no Date parsing). */
function dateParts(dateString) {
    if (!isDateOnlyString(dateString)) return null;
    const [y, m, d] = dateString.split("-").map(Number);
    if (m < 1 || m > 12 || d < 1 || d > 31) return null;
    return { year: y, month: m, day: d };
}

/**
 * Parse an ISO timestamp as UTC. Sources emit timestamps both with an
 * explicit offset ("...Z") and without one ("2026-09-27T18:16:32.407").
 * JavaScript would read offset-less values as browser-local time — an
 * ambiguity that must never leak into TechPulse dates — so the UTC
 * designator is added when missing. Returns null when unparseable.
 */
function parseISOUTC(value) {
    if (typeof value !== "string") return null;
    const text = value.trim();
    if (!text) return null;
    const normalized = /[Zz]|[+-]\d{2}:?\d{2}$/.test(text) ? text : `${text}Z`;
    const parsed = new Date(normalized);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

/**
 * Whole days between a TechPulse calendar date and the current IST
 * calendar date. Positive = that many days ago.
 */
function daysAgoIST(dateString) {
    const parts = dateParts(isDateOnlyString(dateString)
        ? dateString
        : (typeof dateString === "string" ? dateString.slice(0, 10) : ""));
    if (!parts) return null;

    // Anchor the calendar date to its IST-midnight UTC instant so the
    // day diff is exact and timezone-independent.
    const asUTC = Date.UTC(parts.year, parts.month - 1, parts.day, -5, -30);
    const nowParts = dateParts(istTodayString());
    if (!nowParts) return null;
    const nowUTC = Date.UTC(nowParts.year, nowParts.month - 1, nowParts.day, -5, -30);
    return Math.round((nowUTC - asUTC) / 86400000);
}

/**
 * Human label for a TechPulse calendar date:
 * "Today" / "Yesterday" / "N days ago" / "28 Sep 2026".
 */
function formatRelativeIST(dateString) {
    const diff = daysAgoIST(dateString);
    if (diff === null) return "—";
    if (diff <= 0) return "Today";
    if (diff === 1) return "Yesterday";
    if (diff < 7) return `${diff} days ago`;
    return formatDisplayDate(dateString);
}

/**
 * IST calendar parts (year/month/day/hour/minute) for a UTC instant —
 * computed arithmetically so every browser and ICU build renders
 * identically (no Intl month-name variance).
 */
function istPartsFromInstant(ms) {
    const shifted = new Date(ms + TECHPULSE_IST_OFFSET_MINUTES * 60000);
    return {
        year: shifted.getUTCFullYear(),
        month: shifted.getUTCMonth() + 1,
        day: shifted.getUTCDate(),
        hour: shifted.getUTCHours(),
        minute: shifted.getUTCMinutes(),
    };
}

/**
 * Deterministic display label for any date value.
 * - Date-only strings: "28 SEP 2026" (from string parts).
 * - ISO timestamps: converted to the IST calendar, then formatted from
 *   parts (timestamps without an offset are treated as UTC).
 */
function formatDisplayDate(value) {
    if (!value || typeof value !== "string") return "—";

    if (isDateOnlyString(value)) {
        const parts = dateParts(value);
        if (!parts) return "—";
        return `${String(parts.day).padStart(2, "0")} ${TECHPULSE_MONTHS[parts.month - 1]} ${parts.year}`.toUpperCase();
    }

    const parsed = parseISOUTC(value);
    if (!parsed) return "—";
    const parts = istPartsFromInstant(parsed.getTime());
    return `${String(parts.day).padStart(2, "0")} ${TECHPULSE_MONTHS[parts.month - 1]} ${parts.year}`.toUpperCase();
}

/** Long-form label: "28 September 2026". */
function formatLongDate(dateString) {
    const parts = dateParts(typeof dateString === "string" ? dateString.slice(0, 10) : "");
    if (!parts) return "—";
    return `${parts.day} ${TECHPULSE_MONTHS_LONG[parts.month - 1]} ${parts.year}`;
}

/** Weekday name for a TechPulse calendar date: "Monday". */
function formatWeekday(dateString) {
    const parts = dateParts(typeof dateString === "string" ? dateString.slice(0, 10) : "");
    if (!parts) return "";
    // Plain UTC-midnight anchor: getUTCDay of this instant is exactly
    // the calendar day's weekday (the IST shift must NOT be applied
    // here — it would roll the anchor back to the previous day).
    const asUTC = new Date(Date.UTC(parts.year, parts.month - 1, parts.day));
    return TECHPULSE_WEEKDAYS[asUTC.getUTCDay()];
}

/** Day-of-month / short month / year parts for timeline chips. */
function dateChip(dateString) {
    const parts = dateParts(typeof dateString === "string" ? dateString.slice(0, 10) : "");
    if (!parts) return { day: "·", month: "—", monthShort: "—", year: "—", monthYear: "—" };
    return {
        day: String(parts.day).padStart(2, "0"),
        month: TECHPULSE_MONTHS_LONG[parts.month - 1],
        monthShort: TECHPULSE_MONTHS[parts.month - 1],
        year: String(parts.year),
        monthYear: `${TECHPULSE_MONTHS[parts.month - 1]} ${parts.year}`,
    };
}

/**
 * Timestamp formatted in IST from parts, e.g. "27 SEP 2026, 19:38 IST".
 * Arithmetic conversion — identical output in every browser/timezone.
 */
function formatTimestampIST(value) {
    if (!value || typeof value !== "string") return "—";
    const parsed = parseISOUTC(value);
    if (!parsed) return "—";
    const p = istPartsFromInstant(parsed.getTime());
    const day = String(p.day).padStart(2, "0");
    const month = TECHPULSE_MONTHS[p.month - 1];
    const time = `${String(p.hour).padStart(2, "0")}:${String(p.minute).padStart(2, "0")}`;
    return `${day} ${month} ${p.year}, ${time} IST`.toUpperCase()
        .replace(/ IST$/, " IST");
}

/**
 * Edition freshness status vs the current IST date:
 *   0 → "current edition"
 *   1 → "previous edition"
 *   N → "N days behind"
 */
function editionFreshness(editionDate) {
    const diff = daysAgoIST(editionDate);
    if (diff === null) return { state: "unknown", label: "edition" };
    if (diff <= 0) return { state: "current", label: "Current edition" };
    if (diff === 1) return { state: "stale", label: "Previous edition" };
    return { state: "stale", label: `${diff} days behind` };
}

window.TechPulseDates = {
    now: techpulseNow,
    istToday: istTodayString,
    isDateOnly: isDateOnlyString,
    parts: dateParts,
    daysAgo: daysAgoIST,
    relative: formatRelativeIST,
    display: formatDisplayDate,
    long: formatLongDate,
    weekday: formatWeekday,
    chip: dateChip,
    timestampIST: formatTimestampIST,
    freshness: editionFreshness,
};
