/* =========================================================
   TECHPULSE — DATA LOADER
   Loads generated data from generated/data.json
   ========================================================= */

const TECHPULSE_DATA = {
    meta: {
        date: "",
        generatedAt: "",
        daysObserved: 0,
        snapshots: 0
    },
    snapshot: {
        cves: 0,
        knownExploited: 0,
        releases: 0,
        projects: 0,
        techEntries: 0
    },
    security: {
        critical: 0,
        high: 0,
        medium: 0,
        low: 0,
        unknown: 0,
        latest: []
    },
    releases: [],
    openSource: [],
    technology: [],
    history: [],
    sources: {}
};

let dataLoaded = false;

async function loadTechPulseData() {
    if (dataLoaded) return TECHPULSE_DATA;

    try {
        // Try to load from generated data first
        const response = await fetch('../generated/data.json', {
            cache: 'no-cache'
        });

        if (!response.ok) {
            throw new Error(`Failed to load: ${response.status}`);
        }

        const data = await response.json();
        mergeData(data);
        dataLoaded = true;

    } catch (error) {
        console.warn('Could not load generated data, using empty state:', error.message);
        // Data remains as empty defaults - UI will show empty states
    }

    return TECHPULSE_DATA;
}

function mergeData(data) {
    if (!data) return;

    // Meta
    if (data.meta) {
        TECHPULSE_DATA.meta.date = data.meta.date || '';
        TECHPULSE_DATA.meta.generatedAt = data.meta.generatedAt || '';
        TECHPULSE_DATA.meta.daysObserved = data.meta.daysObserved || 0;
        TECHPULSE_DATA.meta.snapshots = data.meta.snapshots || 0;
    }

    // Snapshot counts
    if (data.snapshot) {
        TECHPULSE_DATA.snapshot.cves = data.snapshot.cves || 0;
        TECHPULSE_DATA.snapshot.knownExploited = data.snapshot.knownExploited || 0;
        TECHPULSE_DATA.snapshot.releases = data.snapshot.releases || 0;
        TECHPULSE_DATA.snapshot.projects = data.snapshot.projects || 0;
        TECHPULSE_DATA.snapshot.techEntries = data.snapshot.techEntries || 0;
    }

    // Security
    if (data.security) {
        TECHPULSE_DATA.security.critical = data.security.critical || 0;
        TECHPULSE_DATA.security.high = data.security.high || 0;
        TECHPULSE_DATA.security.medium = data.security.medium || 0;
        TECHPULSE_DATA.security.low = data.security.low || 0;
        TECHPULSE_DATA.security.unknown = data.security.unknown || 0;
        TECHPULSE_DATA.security.latest = Array.isArray(data.security.latest) ? data.security.latest : [];
    }

    // Releases
    if (Array.isArray(data.releases)) {
        TECHPULSE_DATA.releases = data.releases;
    }

    // Open Source
    if (Array.isArray(data.openSource)) {
        TECHPULSE_DATA.openSource = data.openSource;
    }

    // Technology
    if (Array.isArray(data.technology)) {
        TECHPULSE_DATA.technology = data.technology;
    }

    // History
    if (Array.isArray(data.history)) {
        TECHPULSE_DATA.history = data.history;
    }

    // Sources
    if (data.sources) {
        TECHPULSE_DATA.sources = data.sources;
    }
}

function getData() {
    return TECHPULSE_DATA;
}

function isDataLoaded() {
    return dataLoaded;
}

// Export for other modules
window.TechPulseData = {
    load: loadTechPulseData,
    get: getData,
    isLoaded: isDataLoaded
};