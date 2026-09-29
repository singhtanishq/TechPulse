/* =========================================================
   TECHPULSE — DATE UTILITIES

   All TechPulse reporting dates are India calendar days
   (Asia/Kolkata, UTC+05:30, no DST).

   Rules:
     - Date-only values ("YYYY-MM-DD") are calendar dates. They are
       interpreted from their string parts, never as UTC instants.
     - Full ISO timestamps carry their own offset. Offset-less ISO
       timestamps are explicitly treated as UTC.
     - Display and relative labels are always based on IST rather than
       the visitor's browser timezone.
     - Invalid calendar dates and invalid timestamps return null/— rather
       than being silently normalized into another date.
   ========================================================= */

const TECHPULSE_IST_OFFSET_MINUTES = 330; // UTC+05:30

const TECHPULSE_MS_PER_DAY = 86400000;

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


/** The current instant. */
function techpulseNow() {
    return Date.now();
}


/**
 * Validate and split a YYYY-MM-DD calendar date.
 *
 * The returned parts are guaranteed to represent a real calendar date,
 * so values such as 2026-02-31 are rejected.
 */
function dateParts(dateString) {
    if (!isDateOnlyString(dateString)) {
        return null;
    }

    const [year, month, day] = dateString
        .split("-")
        .map(Number);

    if (
        !Number.isInteger(year) ||
        !Number.isInteger(month) ||
        !Number.isInteger(day)
    ) {
        return null;
    }

    if (
        month < 1 ||
        month > 12 ||
        day < 1 ||
        day > 31
    ) {
        return null;
    }

    const asUTC = new Date(
        Date.UTC(
            year,
            month - 1,
            day
        )
    );

    if (
        asUTC.getUTCFullYear() !== year ||
        asUTC.getUTCMonth() !== month - 1 ||
        asUTC.getUTCDate() !== day
    ) {
        return null;
    }

    return {
        year,
        month,
        day
    };
}


/**
 * Current TechPulse reporting "today" — the IST calendar date
 * derived from the universal UTC clock, optionally shifted by
 * whole minutes.
 */
function istTodayString(offsetMinutes = 0) {
    const shiftedMs =
        techpulseNow() +
        Number(offsetMinutes || 0) * 60000;

    const istMs =
        shiftedMs +
        TECHPULSE_IST_OFFSET_MINUTES * 60000;

    const ist = new Date(istMs);

    const year = ist.getUTCFullYear();
    const month = String(
        ist.getUTCMonth() + 1
    ).padStart(2, "0");
    const day = String(
        ist.getUTCDate()
    ).padStart(2, "0");

    return `${year}-${month}-${day}`;
}


/**
 * Parse an ISO timestamp as UTC.
 *
 * Sources may emit timestamps with:
 *   - Z
 *   - +05:30 / -04:00
 *   - +0530 / -0400
 *   - no timezone
 *
 * Offset-less timestamps are explicitly interpreted as UTC so browser
 * locale cannot alter the resulting instant.
 */
function parseISOUTC(value) {
    if (typeof value !== "string") {
        return null;
    }

    const text = value.trim();

    if (!text) {
        return null;
    }

    const normalized =
        /[Zz]|[+-]\d{2}:?\d{2}$/.test(text)
            ? text
            : `${text}Z`;

    const parsed = new Date(
        normalized
    );

    return Number.isNaN(
        parsed.getTime()
    )
        ? null
        : parsed;
}


/**
 * Return the integer UTC serial for a calendar date.
 *
 * Using a plain UTC-midnight anchor makes calendar-date subtraction
 * independent of the visitor's browser timezone.
 */
function calendarDateSerial(parts) {
    return Date.UTC(
        parts.year,
        parts.month - 1,
        parts.day
    );
}


/**
 * Whole calendar days between a TechPulse calendar date and the current
 * IST calendar date.
 *
 * Positive  -> that many days ago
 * Zero      -> today
 * Negative  -> future date
 */
function daysAgoIST(dateString) {
    const normalizedDate =
        isDateOnlyString(dateString)
            ? dateString
            : (
                typeof dateString === "string"
                    ? dateString.slice(0, 10)
                    : ""
            );

    const parts = dateParts(
        normalizedDate
    );

    if (!parts) {
        return null;
    }

    const nowParts = dateParts(
        istTodayString()
    );

    if (!nowParts) {
        return null;
    }

    const asUTC =
        calendarDateSerial(parts);

    const nowUTC =
        calendarDateSerial(nowParts);

    return Math.round(
        (nowUTC - asUTC) /
        TECHPULSE_MS_PER_DAY
    );
}


/**
 * Human label for a TechPulse calendar date:
 *   Today
 *   Yesterday
 *   N days ago
 *   Upcoming
 *   28 Sep 2026
 */
function formatRelativeIST(dateString) {
    const diff = daysAgoIST(
        dateString
    );

    if (diff === null) {
        return "—";
    }

    if (diff === 0) {
        return "Today";
    }

    if (diff === 1) {
        return "Yesterday";
    }

    if (diff < 0) {
        return "Upcoming";
    }

    if (diff < 7) {
        return `${diff} days ago`;
    }

    return formatDisplayDate(
        dateString
    );
}


/**
 * IST calendar parts for a UTC instant.
 *
 * Arithmetic conversion is intentional so output does not depend on
 * browser timezone or ICU locale behavior.
 */
function istPartsFromInstant(ms) {
    const shifted = new Date(
        ms +
        TECHPULSE_IST_OFFSET_MINUTES * 60000
    );

    return {
        year: shifted.getUTCFullYear(),
        month: shifted.getUTCMonth() + 1,
        day: shifted.getUTCDate(),
        hour: shifted.getUTCHours(),
        minute: shifted.getUTCMinutes()
    };
}


/**
 * Deterministic display label for a date value.
 *
 * Date-only:
 *   "28 SEP 2026"
 *
 * ISO timestamp:
 *   converted to the IST calendar date first.
 */
function formatDisplayDate(value) {
    if (
        !value ||
        typeof value !== "string"
    ) {
        return "—";
    }

    if (isDateOnlyString(value)) {
        const parts = dateParts(
            value
        );

        if (!parts) {
            return "—";
        }

        return (
            `${String(parts.day).padStart(2, "0")} ` +
            `${TECHPULSE_MONTHS[parts.month - 1]} ` +
            `${parts.year}`
        ).toUpperCase();
    }

    const parsed = parseISOUTC(
        value
    );

    if (!parsed) {
        return "—";
    }

    const parts =
        istPartsFromInstant(
            parsed.getTime()
        );

    return (
        `${String(parts.day).padStart(2, "0")} ` +
        `${TECHPULSE_MONTHS[parts.month - 1]} ` +
        `${parts.year}`
    ).toUpperCase();
}


/** Long-form label: "28 September 2026". */
function formatLongDate(dateString) {
    const normalized =
        typeof dateString === "string"
            ? dateString.slice(0, 10)
            : "";

    const parts = dateParts(
        normalized
    );

    if (!parts) {
        return "—";
    }

    return (
        `${parts.day} ` +
        `${TECHPULSE_MONTHS_LONG[parts.month - 1]} ` +
        `${parts.year}`
    );
}


/** Weekday name for a TechPulse calendar date. */
function formatWeekday(dateString) {
    const normalized =
        typeof dateString === "string"
            ? dateString.slice(0, 10)
            : "";

    const parts = dateParts(
        normalized
    );

    if (!parts) {
        return "";
    }

    const asUTC = new Date(
        Date.UTC(
            parts.year,
            parts.month - 1,
            parts.day
        )
    );

    return TECHPULSE_WEEKDAYS[
        asUTC.getUTCDay()
    ];
}


/** Day-of-month / short month / year parts for timeline chips. */
function dateChip(dateString) {
    const normalized =
        typeof dateString === "string"
            ? dateString.slice(0, 10)
            : "";

    const parts = dateParts(
        normalized
    );

    if (!parts) {
        return {
            day: "·",
            month: "—",
            monthShort: "—",
            year: "—",
            monthYear: "—"
        };
    }

    return {
        day: String(
            parts.day
        ).padStart(2, "0"),
        month:
            TECHPULSE_MONTHS_LONG[
                parts.month - 1
            ],
        monthShort:
            TECHPULSE_MONTHS[
                parts.month - 1
            ],
        year: String(
            parts.year
        ),
        monthYear:
            `${TECHPULSE_MONTHS[parts.month - 1]} ${parts.year}`
    };
}


/**
 * Timestamp formatted in IST:
 * "27 SEP 2026, 19:38 IST".
 */
function formatTimestampIST(value) {
    if (
        !value ||
        typeof value !== "string"
    ) {
        return "—";
    }

    const parsed = parseISOUTC(
        value
    );

    if (!parsed) {
        return "—";
    }

    const parts =
        istPartsFromInstant(
            parsed.getTime()
        );

    const day = String(
        parts.day
    ).padStart(2, "0");

    const month =
        TECHPULSE_MONTHS[
            parts.month - 1
        ];

    const time =
        `${String(parts.hour).padStart(2, "0")}:` +
        `${String(parts.minute).padStart(2, "0")}`;

    return (
        `${day} ${month} ${parts.year}, ` +
        `${time} IST`
    ).toUpperCase();
}


/**
 * Edition freshness status versus the current IST date:
 *
 *   current  -> Current edition
 *   previous -> Previous edition
 *   stale    -> N days behind
 *   future   -> Future edition
 *   unknown  -> edition
 */
function editionFreshness(editionDate) {
    const diff = daysAgoIST(
        editionDate
    );

    if (diff === null) {
        return {
            state: "unknown",
            label: "Edition"
        };
    }

    if (diff < 0) {
        return {
            state: "future",
            label: "Future edition"
        };
    }

    if (diff === 0) {
        return {
            state: "current",
            label: "Current edition"
        };
    }

    if (diff === 1) {
        return {
            state: "stale",
            label: "Previous edition"
        };
    }

    return {
        state: "stale",
        label: `${diff} days behind`
    };
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
    freshness: editionFreshness
};
