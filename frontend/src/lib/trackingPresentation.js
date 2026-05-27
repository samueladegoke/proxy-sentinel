const TRACKING_TIME_ZONE = 'Africa/Lagos';

export function formatHours(hours) {
    if (hours === null || hours === undefined || Number.isNaN(Number(hours))) return 'N/A';
    const value = Number(hours);
    if (value < 1) return `${Math.round(value * 60)}m`;
    return `${value.toFixed(value >= 10 ? 0 : 1)}h`;
}

export function formatPercent(value) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
    return `${Math.round(Number(value) * 100)}%`;
}

export function formatCountLabel(count, singular, plural = `${singular}s`) {
    const value = Number(count || 0);
    return `${value} ${value === 1 ? singular : plural}`;
}

export function formatTimestamp(value) {
    if (!value) return 'N/A';
    return new Date(Number(value) * 1000).toLocaleString([], {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
    });
}

export function formatObservationTimestamp(value) {
    if (!value) return 'N/A';
    const formatted = new Intl.DateTimeFormat([], {
        timeZone: TRACKING_TIME_ZONE,
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit'
    }).format(new Date(Number(value) * 1000));

    return `${formatted} WAT`;
}

export function formatLocation(...parts) {
    const cleanParts = parts.filter(part => part && part !== 'Unknown');
    return cleanParts.length ? cleanParts.join(' / ') : 'Unknown location';
}

function titleFromSlug(value) {
    if (!value) return '';
    return String(value)
        .replace(/^_?country-/, 'country-')
        .replace(/^country-/, '')
        .split(/[-_]+/)
        .filter(Boolean)
        .map(part => part.toUpperCase() === 'ng' ? 'NG' : `${part[0].toUpperCase()}${part.slice(1)}`)
        .join(' ');
}

export function formatCohortLabel(group) {
    const state = group?.expected_state;
    if (state && state !== 'Unknown State') return state;

    const location = String(group?.expected_location || '').replace(/^_/, '');
    if (location === 'country-ng') return 'Nigeria-wide sticky cohort';

    const stateMatch = location.match(/state-([^_]+)/);
    if (stateMatch) return `${titleFromSlug(stateMatch[1])} sticky cohort`;

    if (location.includes('country-ng')) return 'Nigeria sticky cohort';
    return 'Location not encoded cohort';
}

export function formatCohortScope(group) {
    const location = String(group?.expected_location || '').replace(/^_/, '');
    if (location === 'country-ng') return 'Country filter NG';

    const stateMatch = location.match(/state-([^_]+)/);
    if (stateMatch) return `State filter ${titleFromSlug(stateMatch[1])}`;

    return location ? titleFromSlug(location) : 'No encoded location filter';
}

export function formatGeoSourceLabel(source) {
    switch (source) {
        case 'db-ip-api':
            return 'DB-IP API online';
        case 'browserleaks-db-ip':
            return 'BrowserLeaks DB-IP';
        case 'db-ip-mmdb':
            return 'DB-IP MMDB fallback';
        default:
            return source || 'Unknown source';
    }
}

export function isOnlineGeoSource(source) {
    return Boolean(source) && source !== 'db-ip-mmdb';
}
