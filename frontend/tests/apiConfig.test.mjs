import assert from 'node:assert/strict';

import {
  formatApiError,
  resolveApiBaseUrl,
  toWebSocketUrl
} from '../src/lib/apiConfig.js';

assert.equal(
  resolveApiBaseUrl({ envUrl: '', location: { hostname: '127.0.0.1' } }),
  'http://127.0.0.1:8000',
  'defaults the API host to the current browser hostname'
);

assert.equal(
  resolveApiBaseUrl({ envUrl: 'http://localhost:9000/', location: { hostname: '127.0.0.1' } }),
  'http://localhost:9000',
  'preserves explicit VITE_API_URL values and trims the trailing slash'
);

assert.throws(
  () => resolveApiBaseUrl({ envUrl: '', location: { hostname: 'app.example.com' }, isProduction: true }),
  /VITE_API_URL is required/,
  'refuses implicit localhost API URLs in production builds'
);

assert.equal(
  toWebSocketUrl('http://127.0.0.1:8000'),
  'ws://127.0.0.1:8000',
  'derives ws:// URLs from http:// API URLs'
);

assert.match(
  formatApiError(new TypeError('Failed to fetch'), 'Run IPRoyal scan', 'http://127.0.0.1:8000'),
  /Run IPRoyal scan could not reach Proxy Sentinel API at http:\/\/127\.0\.0\.1:8000/,
  'turns browser fetch failures into actionable API connection messages'
);

assert.match(
  formatApiError(new Error('Unauthorized'), 'Load tracking', 'http://127.0.0.1:8000'),
  /Browser builds cannot carry privileged API tokens/,
  'turns auth failures into token configuration messages'
);
