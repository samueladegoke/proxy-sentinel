const TRACKED_RESULT_FIELDS = [
    'status',
    'query',
    'ip',
    'city',
    'country',
    'region',
    'regionName',
    'isp',
    'mobile',
    'hosting',
    'risk_level',
    'is_valid_carrier',
    'local_city',
    'local_region',
    'local_country',
    'local_country_code',
    'local_lat',
    'local_lon',
    'geo_source',
    'geo_provider',
    'geo_fallback_source',
    'dbip_source',
    'dbip_city',
    'dbip_region',
    'dbip_country',
    'dbip_country_code',
    'browserleaks_city',
    'browserleaks_region',
    'browserleaks_country',
    'browserleaks_country_code',
    'geo_quality',
    'geo_confirmation_pending',
    'latency_ms',
    'check_duration_ms'
];

const PRESERVED_PROXY_FIELDS = [
    'session',
    'proxy_id',
    'proxy_display',
    'proxy',
    'input_proxy',
    'protocol'
];

function hasValue(value) {
    return value !== null && value !== undefined && value !== '';
}

function pickTrackedResultFields(result) {
    const overlay = {};
    for (const field of TRACKED_RESULT_FIELDS) {
        if (Object.prototype.hasOwnProperty.call(result, field)) {
            overlay[field] = result[field];
        }
    }
    if (typeof result.proxy === 'boolean') {
        overlay.proxy_risk = result.proxy;
    }
    return overlay;
}

function onlineGeoIsConfirmed(result) {
    const source = result.geo_source || result.geo_fallback_source || '';
    return result.geo_confirmation_pending !== true && Boolean(source) && source !== 'db-ip-mmdb';
}

function finalizeOverlay(overlay) {
    if (!overlay) return null;

    if (onlineGeoIsConfirmed(overlay)) {
        overlay.geo_quality = overlay.geo_quality || 'online-confirmed';
        overlay.geo_confirmation_pending = false;
    }

    return overlay;
}

function trackedOverlayForSession(session) {
    const result = session?.last_result;
    if (!result || result.status !== 'success') return null;

    const overlay = pickTrackedResultFields(result);

    if (!hasValue(overlay.query) && hasValue(session.last_ip)) {
        overlay.query = session.last_ip;
    }
    if (!hasValue(overlay.local_region) && hasValue(session.last_region)) {
        overlay.local_region = session.last_region;
    }
    if (!hasValue(overlay.local_city) && hasValue(session.last_city)) {
        overlay.local_city = session.last_city;
    }
    if (!hasValue(overlay.local_region) && hasValue(session.latest_region)) {
        overlay.local_region = session.latest_region;
    }
    if (!hasValue(overlay.local_city) && hasValue(session.latest_city)) {
        overlay.local_city = session.latest_city;
    }

    return finalizeOverlay(overlay);
}

function historicalOverlayForRun(run) {
    if (!run || !hasValue(run.latest_ip)) return null;

    const overlay = {
        status: 'success',
        query: run.latest_ip,
        local_region: run.latest_region,
        local_city: run.latest_city,
        local_country: run.latest_country,
        isp: run.latest_isp,
        risk_level: run.latest_risk_level,
        geo_source: run.latest_geo_source,
        geo_provider: run.latest_geo_provider,
        tracking_run_id: run.run_id
    };
    if (hasValue(run.latest_mobile)) {
        overlay.mobile = run.latest_mobile === true || run.latest_mobile === 1;
    }
    return finalizeOverlay(overlay);
}

function historicalOverlayForLog(log) {
    if (!log || log.status !== 'success' || !hasValue(log.ip)) return null;

    return finalizeOverlay({
        status: 'success',
        query: log.ip,
        local_region: log.region,
        local_city: log.city,
        local_country: log.country,
        isp: log.isp,
        mobile: log.mobile === true || log.mobile === 1,
        risk_level: log.risk_level,
        geo_source: log.geo_source,
        tracking_run_id: log.run_id
    });
}

function buildHistoricalOverlayBySession(trackingRuns = [], trackingLogs = []) {
    const overlays = {};

    for (const run of [...trackingRuns].sort((a, b) => (a.started_at || 0) - (b.started_at || 0))) {
        const overlay = historicalOverlayForRun(run);
        if (overlay && run.session) {
            overlays[run.session] = overlay;
        }
    }

    for (const log of [...trackingLogs].sort((a, b) => (a.checked_at || 0) - (b.checked_at || 0))) {
        const overlay = historicalOverlayForLog(log);
        if (overlay && log.session) {
            overlays[log.session] = {
                ...(overlays[log.session] || {}),
                ...overlay
            };
        }
    }

    return overlays;
}

export function mergeProxyResultsWithTrackedSessions(
    proxies = [],
    trackedSessions = {},
    trackingRuns = [],
    trackingLogs = []
) {
    if (!Array.isArray(proxies) || proxies.length === 0) return [];

    const historicalOverlays = buildHistoricalOverlayBySession(trackingRuns, trackingLogs);

    return proxies.map(proxy => {
        const sessionId = proxy?.session;
        const session = sessionId ? trackedSessions[sessionId] : null;
        const overlay = trackedOverlayForSession(session) || historicalOverlays[sessionId];
        if (!overlay) return proxy;

        const preserved = {};
        for (const field of PRESERVED_PROXY_FIELDS) {
            if (Object.prototype.hasOwnProperty.call(proxy, field)) {
                preserved[field] = proxy[field];
            }
        }

        return {
            ...proxy,
            ...overlay,
            ...preserved,
            tracking_geo_overlay: true,
            tracking_run_id: session?.run_id || overlay.tracking_run_id || proxy.tracking_run_id
        };
    });
}
