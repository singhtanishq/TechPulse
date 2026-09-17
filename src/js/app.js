/* =========================================================
   TECHPULSE — APPLICATION
   ========================================================= */

document.addEventListener("DOMContentLoaded", () => {

    if (typeof TECHPULSE_DATA === "undefined") {
        console.error("TechPulse data could not be loaded.");
        return;
    }

    updateMeta();
    updateSnapshot();

});


/* =========================================================
   META
   ========================================================= */

function updateMeta() {

    const data = TECHPULSE_DATA.meta;

    const dateElement =
        document.querySelector("[data-today]");

    const observationsElement =
        document.querySelector("[data-observations]");

    if (dateElement) {
        dateElement.textContent =
            formatDate(data.date);
    }

    if (observationsElement) {
        observationsElement.textContent =
            String(data.daysObserved).padStart(3, "0");
    }

}


/* =========================================================
   SNAPSHOT
   ========================================================= */

function updateSnapshot() {

    const snapshot =
        TECHPULSE_DATA.snapshot;

    setText(
        "[data-cves]",
        snapshot.cves
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
        "[data-advisories]",
        snapshot.advisories
    );

}


/* =========================================================
   HELPERS
   ========================================================= */

function setText(selector, value) {

    const element =
        document.querySelector(selector);

    if (element) {
        element.textContent = value;
    }

}


function formatDate(dateString) {

    const date =
        new Date(`${dateString}T00:00:00Z`);

    return date
        .toLocaleDateString(
            "en-GB",
            {
                day: "2-digit",
                month: "short",
                year: "numeric",
                timeZone: "UTC"
            }
        )
        .toUpperCase();

}