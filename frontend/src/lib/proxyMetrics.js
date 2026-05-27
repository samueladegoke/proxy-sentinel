export function getProxyLatencyMs(proxy) {
    const latency = proxy?.latency_ms ?? proxy?.latencyMs ?? proxy?.response_time_ms ?? proxy?.responseTimeMs;
    const parsed = Number(latency);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export function formatProxyLatency(proxy) {
    const latencyMs = getProxyLatencyMs(proxy);
    if (latencyMs === null) return 'N/A';
    if (latencyMs >= 1000) return `${(latencyMs / 1000).toFixed(2)} s`;
    return `${Math.round(latencyMs)} ms`;
}

export function isCleanMobileProxy(proxy) {
    return proxy?.status === 'success' && proxy?.mobile === true && proxy?.risk_level === 'CLEAN';
}

export function isRiskFlaggedProxy(proxy) {
    return proxy?.hosting === true || proxy?.proxy === true || proxy?.proxy_risk === true;
}

function asSortableText(value) {
    return typeof value === 'string' ? value : '';
}

function ipv4SortParts(value) {
    const parts = asSortableText(value).split('.');
    if (parts.length !== 4) return null;
    const parsed = parts.map(part => Number(part));
    if (parsed.some(part => !Number.isInteger(part) || part < 0 || part > 255)) return null;
    return parsed;
}

export function sortProxyResults(proxies, sortConfig, isTargetProxy = () => false) {
    return [...proxies].sort((a, b) => {
        const aTarget = isTargetProxy(a) ? 1 : 0;
        const bTarget = isTargetProxy(b) ? 1 : 0;
        if (aTarget !== bTarget) return bTarget - aTarget;

        if (!sortConfig?.column) return 0;

        let aVal;
        let bVal;

        switch (sortConfig.column) {
            case 'mobile':
                aVal = a.mobile ? 1 : 0;
                bVal = b.mobile ? 1 : 0;
                break;
            case 'ip': {
                const aParts = ipv4SortParts(a.query || a.ip);
                const bParts = ipv4SortParts(b.query || b.ip);
                if (aParts === null && bParts === null) return 0;
                if (aParts === null) return 1;
                if (bParts === null) return -1;
                for (let i = 0; i < 4; i++) {
                    if (aParts[i] !== bParts[i]) {
                        return (aParts[i] - bParts[i]) * (sortConfig.direction === 'asc' ? 1 : -1);
                    }
                }
                return 0;
            }
            case 'risk':
                aVal = isRiskFlaggedProxy(a) ? 1 : 0;
                bVal = isRiskFlaggedProxy(b) ? 1 : 0;
                break;
            case 'isp':
                aVal = asSortableText(a.isp).toUpperCase();
                bVal = asSortableText(b.isp).toUpperCase();
                break;
            case 'proxy':
                aVal = asSortableText(a.proxy_display || a.input_proxy || a.proxy);
                bVal = asSortableText(b.proxy_display || b.input_proxy || b.proxy);
                break;
            case 'latency': {
                aVal = getProxyLatencyMs(a);
                bVal = getProxyLatencyMs(b);
                if (aVal === null && bVal === null) return 0;
                if (aVal === null) return 1;
                if (bVal === null) return -1;
                break;
            }
            default:
                return 0;
        }

        if (typeof aVal === 'string') {
            if (!aVal && !bVal) return 0;
            if (!aVal) return 1;
            if (!bVal) return -1;
            return aVal.localeCompare(bVal) * (sortConfig.direction === 'asc' ? 1 : -1);
        }

        return (aVal - bVal) * (sortConfig.direction === 'asc' ? 1 : -1);
    });
}
