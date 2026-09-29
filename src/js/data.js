/* =========================================================
   TECHPULSE — DATA LOADER
   Loads generated data produced by the TechPulse pipeline.

   Path resolution:
     1. generated/data.json  — deployed GitHub Pages layout
     2. ../generated/data.json — repository-root local serving

   The browser never calls NVD/CISA/GitHub/RSS directly; it only reads
   generated static JSON produced by the pipeline.

   Integrity:
     - Required top-level sections are validated before data is accepted.
     - Invalid counts are rejected instead of silently becoming zero.
     - Invalid reporting dates are rejected.
     - Failed/malformed payloads never become a "loaded" zero-value dataset.
     - Archive loading follows the same fail-closed behavior.
   ========================================================= */

const TECHPULSE_DATA = {
    meta: {
        date: null,
        coveredDate: null,
        timezone: "Asia/Kolkata",
        generatedAt: null,
        daysObserved: 0,
        snapshots: 0
    },
    snapshot: {
        cves: 0,
        knownExploited: 0,
        kevAdded: 0,
        releases: 0,
        projects: 0,
        techEntries: 0
    },
    security: {
        critical: 0,
        high: 0,
        medium: 0,
        low: 0,
        none: 0,
        unscored: 0,
        kevCatalogTotal: 0,
        latest: []
    },
    releases: [],
    openSource: [],
    technology: [],
    history: [],
    sources: {}
};

const TECHPULSE_ARCHIVE = {
    meta: {
        generatedAt: null,
        totalSnapshots: 0,
        warnings: []
    },
    archive: []
};

let dataLoaded = false;
let archiveLoaded = false;
let dataError = null;
let archiveError = null;

/* Relative path candidates, tried in order. */
const DATA_PATHS = [
    "generated/data.json",
    "../generated/data.json"
];

const ARCHIVE_PATHS = [
    "generated/archive.json",
    "../generated/archive.json"
];

const REQUIRED_DATA_SECTIONS = [
    "meta",
    "snapshot",
    "security",
    "releases",
    "openSource",
    "technology",
    "history",
    "sources"
];

const SNAPSHOT_FIELDS = [
    "cves",
    "knownExploited",
    "kevAdded",
    "releases",
    "projects",
    "techEntries"
];

const SECURITY_COUNT_FIELDS = [
    "critical",
    "high",
    "medium",
    "low",
    "none",
    "unscored",
    "kevCatalogTotal"
];

const SOURCE_STATUSES = new Set([
    "success",
    "partial",
    "failed",
    "empty",
    "unknown"
]);


function isPlainObject(value) {
    return value !== null &&
        typeof value === "object" &&
        !Array.isArray(value);
}


function isNonNegativeInteger(value) {
    return Number.isInteger(value) && value >= 0;
}


function isValidDateOnly(value) {
    if (typeof value !== "string") return false;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;

    const [year, month, day] = value.split("-").map(Number);
    const date = new Date(Date.UTC(year, month - 1, day));

    return (
        date.getUTCFullYear() === year &&
        date.getUTCMonth() === month - 1 &&
        date.getUTCDate() === day
    );
}


function isValidIsoTimestamp(value) {
    if (typeof value !== "string" || !value.trim()) {
        return false;
    }

    const timestamp = Date.parse(value);

    return Number.isFinite(timestamp);
}


async function fetchFirstJson(paths) {
    let lastError = null;

    for (const path of paths) {
        try {
            const response = await fetch(path, {
                cache: "no-cache",
                headers: {
                    "Accept": "application/json"
                }
            });

            if (!response.ok) {
                lastError = new Error(
                    `${path} -> HTTP ${response.status}`
                );
                continue;
            }

            let data;

            try {
                data = await response.json();
            } catch (error) {
                lastError = new Error(
                    `${path} -> invalid JSON response`
                );
                continue;
            }

            return data;
        } catch (error) {
            lastError = error instanceof Error
                ? error
                : new Error(String(error));
        }
    }

    throw lastError || new Error("No data path succeeded");
}


function validateGeneratedData(data) {
    if (!isPlainObject(data)) {
        throw new Error(
            "Generated data root must be a JSON object."
        );
    }

    for (const section of REQUIRED_DATA_SECTIONS) {
        if (!(section in data)) {
            throw new Error(
                `Generated data is missing required section '${section}'.`
            );
        }
    }

    /* -------------------------------------------------------------
       Meta
       ------------------------------------------------------------- */

    if (!isPlainObject(data.meta)) {
        throw new Error(
            "Generated data 'meta' must be an object."
        );
    }

    if (!isValidDateOnly(data.meta.date)) {
        throw new Error(
            "Generated data meta.date is not a valid YYYY-MM-DD date."
        );
    }

    if (
        data.meta.coveredDate !== null &&
        data.meta.coveredDate !== undefined &&
        !isValidDateOnly(data.meta.coveredDate)
    ) {
        throw new Error(
            "Generated data meta.coveredDate is invalid."
        );
    }

    if (
        data.meta.generatedAt !== null &&
        data.meta.generatedAt !== undefined &&
        !isValidIsoTimestamp(data.meta.generatedAt)
    ) {
        throw new Error(
            "Generated data meta.generatedAt is invalid."
        );
    }

    for (const field of ["daysObserved", "snapshots"]) {
        if (!isNonNegativeInteger(data.meta[field])) {
            throw new Error(
                `Generated data meta.${field} must be a non-negative integer.`
            );
        }
    }

    /* -------------------------------------------------------------
       Snapshot
       ------------------------------------------------------------- */

    if (!isPlainObject(data.snapshot)) {
        throw new Error(
            "Generated data 'snapshot' must be an object."
        );
    }

    for (const field of SNAPSHOT_FIELDS) {
        if (!isNonNegativeInteger(data.snapshot[field])) {
            throw new Error(
                `Generated data snapshot.${field} must be a non-negative integer.`
            );
        }
    }

    /* -------------------------------------------------------------
       Security
       ------------------------------------------------------------- */

    if (!isPlainObject(data.security)) {
        throw new Error(
            "Generated data 'security' must be an object."
        );
    }

    for (const field of SECURITY_COUNT_FIELDS) {
        if (!isNonNegativeInteger(data.security[field])) {
            throw new Error(
                `Generated data security.${field} must be a non-negative integer.`
            );
        }
    }

    if (!Array.isArray(data.security.latest)) {
        throw new Error(
            "Generated data security.latest must be an array."
        );
    }

    /* -------------------------------------------------------------
       Collections
       ------------------------------------------------------------- */

    for (const field of [
        "releases",
        "openSource",
        "technology",
        "history"
    ]) {
        if (!Array.isArray(data[field])) {
            throw new Error(
                `Generated data '${field}' must be an array.`
            );
        }
    }

    /* -------------------------------------------------------------
       Sources
       ------------------------------------------------------------- */

    if (!isPlainObject(data.sources)) {
        throw new Error(
            "Generated data 'sources' must be an object."
        );
    }

    for (const group of Object.keys(data.sources)) {
        const groupSources = data.sources[group];

        if (!isPlainObject(groupSources)) {
            throw new Error(
                `Generated data sources.${group} must be an object.`
            );
        }

        for (const name of Object.keys(groupSources)) {
            const source = groupSources[name];

            if (!isPlainObject(source)) {
                throw new Error(
                    `Generated data sources.${group}.${name} must be an object.`
                );
            }

            if (
                source.status !== undefined &&
                !SOURCE_STATUSES.has(source.status)
            ) {
                throw new Error(
                    `Generated data sources.${group}.${name}.status is invalid.`
                );
            }
        }
    }

    /* -------------------------------------------------------------
       History
       ------------------------------------------------------------- */

    const seenHistoryDates = new Set();

    for (const record of data.history) {
        if (!isPlainObject(record)) {
            throw new Error(
                "Generated data history contains a non-object record."
            );
        }

        if (!isValidDateOnly(record.date)) {
            throw new Error(
                "Generated data history contains an invalid date."
            );
        }

        if (seenHistoryDates.has(record.date)) {
            throw new Error(
                `Generated data history contains duplicate date '${record.date}'.`
            );
        }

        seenHistoryDates.add(record.date);

        for (const field of [
            "cves",
            "knownExploited",
            "kevAdded",
            "releases",
            "projects",
            "techEntries"
        ]) {
            if (!isNonNegativeInteger(record[field])) {
                throw new Error(
                    `Generated data history.${record.date}.${field} must be a non-negative integer.`
                );
            }
        }
    }

    return data;
}


function validateArchiveData(data) {
    if (!isPlainObject(data)) {
        throw new Error(
            "Generated archive root must be a JSON object."
        );
    }

    if (!isPlainObject(data.meta)) {
        throw new Error(
            "Generated archive meta must be an object."
        );
    }

    if (
        data.meta.generatedAt !== null &&
        data.meta.generatedAt !== undefined &&
        !isValidIsoTimestamp(data.meta.generatedAt)
    ) {
        throw new Error(
            "Generated archive meta.generatedAt is invalid."
        );
    }

    if (!isNonNegativeInteger(data.meta.totalSnapshots)) {
        throw new Error(
            "Generated archive meta.totalSnapshots must be a non-negative integer."
        );
    }

    if (
        data.meta.warnings !== undefined &&
        !Array.isArray(data.meta.warnings)
    ) {
        throw new Error(
            "Generated archive meta.warnings must be an array."
        );
    }

    if (!Array.isArray(data.archive)) {
        throw new Error(
            "Generated archive 'archive' must be an array."
        );
    }

    const seenDates = new Set();

    for (const snapshot of data.archive) {
        if (!isPlainObject(snapshot)) {
            throw new Error(
                "Generated archive contains a non-object snapshot."
            );
        }

        if (!isValidDateOnly(snapshot.date)) {
            throw new Error(
                "Generated archive contains an invalid snapshot date."
            );
        }

        if (seenDates.has(snapshot.date)) {
            throw new Error(
                `Generated archive contains duplicate snapshot date '${snapshot.date}'.`
            );
        }

        seenDates.add(snapshot.date);

        if (!isPlainObject(snapshot.snapshot)) {
            throw new Error(
                `Generated archive snapshot ${snapshot.date} has invalid snapshot data.`
            );
        }
    }

    if (data.meta.totalSnapshots !== data.archive.length) {
        throw new Error(
            "Generated archive meta.totalSnapshots does not match archive length."
        );
    }

    return data;
}


function mergeData(data) {
    validateGeneratedData(data);

    TECHPULSE_DATA.meta = {
        date: data.meta.date,
        coveredDate: data.meta.coveredDate || null,
        timezone: data.meta.timezone || "Asia/Kolkata",
        generatedAt: data.meta.generatedAt || null,
        daysObserved: data.meta.daysObserved,
        snapshots: data.meta.snapshots
    };

    TECHPULSE_DATA.snapshot = {
        cves: data.snapshot.cves,
        knownExploited: data.snapshot.knownExploited,
        kevAdded: data.snapshot.kevAdded,
        releases: data.snapshot.releases,
        projects: data.snapshot.projects,
        techEntries: data.snapshot.techEntries
    };

    TECHPULSE_DATA.security = {
        critical: data.security.critical,
        high: data.security.high,
        medium: data.security.medium,
        low: data.security.low,
        none: data.security.none,
        unscored: data.security.unscored,
        kevCatalogTotal: data.security.kevCatalogTotal,
        latest: data.security.latest
    };

    TECHPULSE_DATA.releases = data.releases;
    TECHPULSE_DATA.openSource = data.openSource;
    TECHPULSE_DATA.technology = data.technology;
    TECHPULSE_DATA.history = data.history;
    TECHPULSE_DATA.sources = data.sources;
}


async function loadTechPulseData() {
    if (dataLoaded) {
        return TECHPULSE_DATA;
    }

    try {
        const data = await fetchFirstJson(
            DATA_PATHS
        );

        mergeData(data);

        dataError = null;
        dataLoaded = true;
    } catch (error) {
        dataLoaded = false;
        dataError = error instanceof Error
            ? error.message
            : String(error);

        console.warn(
            "TechPulse: generated data unavailable or invalid —",
            dataError
        );

        console.warn(
            "TechPulse: run 'python3 scripts/run_pipeline.py' to generate valid data, " +
            "or serve the repository root so '../generated/data.json' resolves from /src/."
        );
    }

    return TECHPULSE_DATA;
}


async function loadTechPulseArchive() {
    if (archiveLoaded) {
        return TECHPULSE_ARCHIVE;
    }

    try {
        const data = await fetchFirstJson(
            ARCHIVE_PATHS
        );

        validateArchiveData(data);

        TECHPULSE_ARCHIVE.meta = {
            generatedAt: data.meta.generatedAt || null,
            totalSnapshots: data.meta.totalSnapshots,
            warnings: Array.isArray(data.meta.warnings)
                ? data.meta.warnings
                : []
        };

        TECHPULSE_ARCHIVE.archive = data.archive;

        archiveError = null;
        archiveLoaded = true;
    } catch (error) {
        archiveLoaded = false;
        archiveError = error instanceof Error
            ? error.message
            : String(error);

        console.warn(
            "TechPulse: generated archive unavailable or invalid —",
            archiveError
        );
    }

    return TECHPULSE_ARCHIVE;
}


function getData() {
    return TECHPULSE_DATA;
}


function getArchive() {
    return TECHPULSE_ARCHIVE;
}


function isDataLoaded() {
    return dataLoaded;
}


function isArchiveLoaded() {
    return archiveLoaded;
}


function getDataError() {
    return dataError;
}


function getArchiveError() {
    return archiveError;
}


/* Source health summary across all datasets. */
function getSourceHealth() {
    const sources = TECHPULSE_DATA.sources || {};
    const health = [];

    if (!isPlainObject(sources)) {
        return health;
    }

    for (const group of Object.keys(sources)) {
        const groupSources = sources[group];

        if (!isPlainObject(groupSources)) {
            continue;
        }

        for (const name of Object.keys(groupSources)) {
            const source = groupSources[name];

            if (
                source &&
                typeof source === "object" &&
                !Array.isArray(source)
            ) {
                health.push({
                    group,
                    name,
                    status: SOURCE_STATUSES.has(source.status)
                        ? source.status
                        : "unknown"
                });
            }
        }
    }

    return health;
}


function hasSourceFailures() {
    return getSourceHealth().some(
        source =>
            source.status === "failed" ||
            source.status === "partial"
    );
}


window.TechPulseData = {
    load: loadTechPulseData,
    loadArchive: loadTechPulseArchive,
    get: getData,
    getArchive: getArchive,
    isLoaded: isDataLoaded,
    isArchiveLoaded: isArchiveLoaded,
    getError: getDataError,
    getArchiveError: getArchiveError,
    getSourceHealth: getSourceHealth,
    hasSourceFailures: hasSourceFailures
};
