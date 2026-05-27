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

export function getApiAuthToken({ envToken } = {}) {
    return typeof envToken === 'string' ? envToken.trim() : '';
}

export function withApiAuth(options = {}, token = '') {
    if (!token) return options;

    const headers = new Headers(options.headers || {});
    headers.set('X-Proxy-Sentinel-Token', token);
    return { ...options, headers };
}

export function withWebSocketAuth(url, token = '') {
    if (!token) return url;

    const wsUrl = new URL(url);
    wsUrl.searchParams.set('token', token);
    return wsUrl.toString();
}

export function formatApiError(error, action, apiBaseUrl) {
    const message = error?.message || String(error || '');
    const isConnectionFailure = /failed to fetch|network|websocket|connection/i.test(message);

    if (isConnectionFailure) {
        return `${action} could not reach Proxy Sentinel API at ${apiBaseUrl}. Start the backend API and retry.`;
    }

    if (/unauthorized|401/i.test(message)) {
        return `${action} was rejected by Proxy Sentinel API authentication. Check the frontend/backend API token configuration.`;
    }

    return message || `${action} failed.`;
}
