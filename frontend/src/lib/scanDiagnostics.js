const MAX_DIAGNOSTIC_ROWS = 6;

function asCount(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

function formatCount(value) {
    return asCount(value).toLocaleString();
}

function formatSourceLabel(source) {
    switch (source) {
        case 'browserleaks-db-ip':
            return 'BrowserLeaks + DB-IP';
        case 'db-ip-api':
            return 'DB-IP API';
        case 'db-ip-mmdb':
            return 'MMDB fallback';
        default:
            return source || 'Unknown source';
    }
}

function summarizeSources(sources = []) {
    if (!Array.isArray(sources) || sources.length === 0) return 'Source unknown';
    return sources
        .slice(0, 2)
        .map(source => formatSourceLabel(source.source))
        .join(' + ');
}

function summarizeReasons(reasons = []) {
    if (!Array.isArray(reasons) || reasons.length === 0) return 'No rejections';
    return reasons
        .slice(0, 2)
        .map(reason => `${reason.label || reason.reason || 'Rejected'} ${formatCount(reason.count)}`)
        .join(' · ');
}

export function prepareScanDiagnostics(diagnostics) {
    if (!diagnostics || typeof diagnostics !== 'object') return null;

    const checkedCount = asCount(diagnostics.checked_count);
    const successfulCount = asCount(diagnostics.successful_count);
    const acceptedCount = asCount(diagnostics.accepted_count);
    const rejectedCount = Math.max(0, checkedCount - acceptedCount);

    return {
        summary: [
            { label: 'Checked', value: formatCount(checkedCount) },
            { label: 'Successful', value: formatCount(successfulCount) },
            { label: 'Accepted', value: formatCount(acceptedCount) },
            { label: 'Rejected', value: formatCount(rejectedCount) },
        ],
        locations: Array.isArray(diagnostics.successful_locations)
            ? diagnostics.successful_locations.slice(0, MAX_DIAGNOSTIC_ROWS).map(location => ({
                label: location.label || 'Unknown location',
                count: asCount(location.count),
                countLabel: formatCount(location.count),
                acceptedCount: asCount(location.accepted_count),
                rejectedCount: asCount(location.rejected_count),
                sourceLabel: summarizeSources(location.geo_sources),
                rejectionText: summarizeReasons(location.rejection_reasons),
            }))
            : [],
        rejectionReasons: Array.isArray(diagnostics.rejection_reasons)
            ? diagnostics.rejection_reasons.slice(0, MAX_DIAGNOSTIC_ROWS).map(reason => ({
                reason: reason.reason || 'rejected',
                label: reason.label || reason.reason || 'Rejected',
                count: asCount(reason.count),
                countLabel: formatCount(reason.count),
            }))
            : [],
    };
}
