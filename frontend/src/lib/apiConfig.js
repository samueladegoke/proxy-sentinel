export function resolveApiBaseUrl({ envUrl, location, isProduction = false } = {}) {
    const explicitUrl = typeof envUrl === 'string' ? envUrl.trim() : '';
    if (explicitUrl) return explicitUrl.replace(/\/+$/, '');

    if (isProduction) {
        throw new Error('VITE_API_URL is required for production builds.');
    }

    const hostname = location?.hostname || 'localhost';
    return `http://${hostname}:8000`;
}

export function toWebSocketUrl(apiBaseUrl) {
    return apiBaseUrl.replace(/^http/i, 'ws');
}

export function formatApiError(error, action, apiBaseUrl) {
    const message = error?.message || String(error || '');
    const isConnectionFailure = /failed to fetch|network|websocket|connection/i.test(message);

    if (isConnectionFailure) {
        return `${action} could not reach Proxy Sentinel API at ${apiBaseUrl}. Start the backend API and retry.`;
    }

    if (/unauthorized|401/i.test(message)) {
        return `${action} was rejected by Proxy Sentinel API authentication. Browser builds cannot carry privileged API tokens; serve the dashboard behind a trusted session or disable backend token auth for local-only use.`;
    }

    return message || `${action} failed.`;
}
