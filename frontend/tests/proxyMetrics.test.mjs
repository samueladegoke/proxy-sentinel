import assert from 'node:assert/strict';

import {
  formatProxyLatency,
  getProxyLatencyMs,
  isRiskFlaggedProxy,
  sortProxyResults
} from '../src/lib/proxyMetrics.js';

assert.equal(getProxyLatencyMs({ latency_ms: 142.4 }), 142.4);
assert.equal(getProxyLatencyMs({ response_time_ms: 211 }), 211);
assert.equal(getProxyLatencyMs({ latency_ms: null }), null);
assert.equal(getProxyLatencyMs({ check_duration_ms: 211 }), null);

assert.equal(formatProxyLatency({ latency_ms: 142.4 }), '142 ms');
assert.equal(formatProxyLatency({ latency_ms: 1250 }), '1.25 s');
assert.equal(formatProxyLatency({ latency_ms: null }), 'N/A');
assert.equal(isRiskFlaggedProxy({ proxy: 'geo.iproyal.com:12321:user:pass' }), false);
assert.equal(isRiskFlaggedProxy({ proxy_risk: true }), true);
assert.equal(isRiskFlaggedProxy({ proxy: true }), true);

assert.deepEqual(
  sortProxyResults(
    [
      { session: 'slow', latency_ms: 900 },
      { session: 'missing' },
      { session: 'fast', latency_ms: 120 }
    ],
    { column: 'latency', direction: 'asc' }
  ).map(proxy => proxy.session),
  ['fast', 'slow', 'missing'],
  'sorts lower latency first and keeps missing latency last'
);

assert.deepEqual(
  sortProxyResults(
    [
      { session: 'slow', latency_ms: 900 },
      { session: 'missing' },
      { session: 'fast', latency_ms: 120 }
    ],
    { column: 'latency', direction: 'desc' }
  ).map(proxy => proxy.session),
  ['slow', 'fast', 'missing'],
  'sorts higher latency first in descending order while keeping missing latency last'
);

assert.deepEqual(
  sortProxyResults(
    [
      { session: 'invalid', query: 'not-an-ip' },
      { session: 'later', query: '197.211.53.88' },
      { session: 'earlier', query: '41.217.86.12' }
    ],
    { column: 'ip', direction: 'asc' }
  ).map(proxy => proxy.session),
  ['earlier', 'later', 'invalid'],
  'sorts valid IPv4 addresses numerically and keeps malformed IPs last'
);

assert.deepEqual(
  sortProxyResults(
    [
      { session: 'risk-flag-only', proxy: true },
      { session: 'redacted', proxy_display: 'geo.iproyal.com:12321:user:****' },
      { session: 'manual', input_proxy: 'a.example:123:user:pass' }
    ],
    { column: 'proxy', direction: 'asc' }
  ).map(proxy => proxy.session),
  ['manual', 'redacted', 'risk-flag-only'],
  'sorts proxy display text and keeps risk-only booleans out of the proxy string order'
);
