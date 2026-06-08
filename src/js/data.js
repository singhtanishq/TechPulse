/* =========================================================
   TECHPULSE — DATA LOADER
   Loads generated data produced by the TechPulse pipeline.

   Path resolution:
     1. generated/data.json  — deployed layout (site root = src contents,
        generated/ copied alongside) and GitHub Pages deployment
     2. ../generated/data.json — repository layout (serving repo root,
        opening /src/index.html, e.g. Live Server)

   The browser never calls NVD/CISA/GitHub/RSS directly; it only reads
   the generated static JSON committed by the pipeline.
   ========================================================= */

const TECHPULSE_DATA = {
    meta: {
        date: null,
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
    meta: { generatedAt: null, totalSnapshots: 0 },
    archive: []
};

let dataLoaded = false;
let archiveLoaded = false;
let dataError = null;

/* Relative path candidates, tried in order. */
const DATA_PATHS = ["generated/data.json", "../generated/data.json"];
const ARCHIVE_PATHS = ["generated/archive.json", "../generated/archive.json"];

async function fetchFirstJson(paths) {
    let lastError = null;
    for (const path of paths) {
        try {
            const response = await fetch(path, { cache: "no-cache" });
            if (response.ok) {
                return await response.json();
            }
            lastError = new Error(`${path} -> HTTP ${response.status}`);
        } catch (error) {
            lastError = error;
        }
    }
    throw lastError || new Error("No data path succeeded");
}

async function loadTechPulseData() {
    if (dataLoaded) return TECHPULSE_DATA;

    try {
        const data = await fetchFirstJson(DATA_PATHS);
        mergeData(data);
        dataLoaded = true;
    } catch (error) {
        dataError = error && error.message ? error.message : String(error);
        console.warn("TechPulse: generated data unavailable —", dataError);
        console.warn(
            "TechPulse: run 'python3 scripts/run_pipeline.py' to generate data, " +
            "or serve the repository root (not src/) so 'generated/data.json' resolves."
        );
    }

    return TECHPULSE_DATA;
}

async function loadTechPulseArchive() {
    if (archiveLoaded) return TECHPULSE_ARCHIVE;

    try {
        const data = await fetchFirstJson(ARCHIVE_PATHS);
        if (data && Array.isArray(data.archive)) {
            TECHPULSE_ARCHIVE.meta = data.meta || TECHPULSE_ARCHIVE.meta;
            TECHPULSE_ARCHIVE.archive = data.archive;
        }
        archiveLoaded = true;
    } catch (error) {
        console.warn("TechPulse: generated archive unavailable —", error);
    }

    return TECHPULSE_ARCHIVE;
}

function mergeData(data) {
    if (!data || typeof data !== "object") return;

    if (data.meta) {
        TECHPULSE_DATA.meta = {
            date: data.meta.date || null,
            generatedAt: data.meta.generatedAt || null,
            daysObserved: Number(data.meta.daysObserved) || 0,
            snapshots: Number(data.meta.snapshots) || 0
        };
    }

    if (data.snapshot) {
        for (const key of Object.keys(TECHPULSE_DATA.snapshot)) {
            TECHPULSE_DATA.snapshot[key] = Number(data.snapshot[key]) || 0;
        }
    }

    if (data.security) {
        for (const key of ["critical", "high", "medium", "low", "none", "unscored", "kevCatalogTotal"]) {
            TECHPULSE_DATA.security[key] = Number(data.security[key]) || 0;
        }
        TECHPULSE_DATA.security.latest =
            Array.isArray(data.security.latest) ? data.security.latest : [];
    }

    TECHPULSE_DATA.releases = Array.isArray(data.releases) ? data.releases : [];
    TECHPULSE_DATA.openSource = Array.isArray(data.openSource) ? data.openSource : [];
    TECHPULSE_DATA.technology = Array.isArray(data.technology) ? data.technology : [];
    TECHPULSE_DATA.history = Array.isArray(data.history) ? data.history : [];
    TECHPULSE_DATA.sources = (data.sources && typeof data.sources === "object") ? data.sources : {};
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

function getDataError() {
    return dataError;
}

/* Source health summary across all datasets (honest partial status). */
function getSourceHealth() {
    const sources = TECHPULSE_DATA.sources || {};
    const health = [];
    for (const group of Object.keys(sources)) {
        const groupSources = sources[group] || {};
        for (const name of Object.keys(groupSources)) {
            const s = groupSources[name];
            if (s && typeof s === "object") {
                health.push({ group, name, status: s.status || "unknown" });
            }
        }
    }
    return health;
}

function hasSourceFailures() {
    return getSourceHealth().some(s => s.status === "failed" || s.status === "partial");
}

window.TechPulseData = {
    load: loadTechPulseData,
    loadArchive: loadTechPulseArchive,
    get: getData,
    getArchive: getArchive,
    isLoaded: isDataLoaded,
    getError: getDataError,
    getSourceHealth: getSourceHealth,
    hasSourceFailures: hasSourceFailures
};
