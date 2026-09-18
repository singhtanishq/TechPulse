/* =========================================================
   TECHPULSE — COMPONENTS
   Reusable UI components
   ========================================================= */

// Empty state component
function renderEmptyState(container, message) {
    if (container) {
        container.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
    }
}

// Loading state component
function renderLoadingState(container) {
    if (container) {
        container.innerHTML = '<div class="loading-state">Loading...</div>';
    }
}

// Severity badge component
function createSeverityBadge(severity) {
    const span = document.createElement('span');
    span.className = `severity ${(severity || '').toLowerCase()}`;
    span.textContent = severity || 'UNKNOWN';
    return span;
}

// Date formatter
function formatDisplayDate(dateString) {
    if (!dateString) return '—';
    const date = new Date(`${dateString}T00:00:00Z`);
    return date.toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        timeZone: "UTC"
    }).toUpperCase();
}

// Relative date formatter
function formatRelativeDate(dateString) {
    if (!dateString) return '—';
    const date = new Date(dateString);
    const now = new Date();
    const diffDays = Math.floor((now - date) / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return `${diffDays} days ago`;
    return formatDisplayDate(dateString);
}

// Number formatter
function formatNumber(num) {
    if (num === null || num === undefined) return '—';
    return num.toLocaleString();
}

// HTML escape
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Truncate text
function truncate(text, maxLength) {
    if (!text || text.length <= maxLength) return text;
    return text.slice(0, maxLength).trim() + '...';
}

// Create element with attributes
function createElement(tag, attributes = {}, children = []) {
    const element = document.createElement(tag);
    Object.entries(attributes).forEach(([key, value]) => {
        if (key === 'class') element.className = value;
        else if (key === 'dataset') Object.entries(value).forEach(([k, v]) => element.dataset[k] = v);
        else element.setAttribute(key, value);
    });
    children.forEach(child => {
        if (typeof child === 'string') element.appendChild(document.createTextNode(child));
        else if (child instanceof Node) element.appendChild(child);
    });
    return element;
}