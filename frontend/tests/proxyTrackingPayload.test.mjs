import assert from 'node:assert/strict';

import { buildTrackingPayload } from '../src/lib/proxyTrackingPayload.js';

assert.deepEqual(
  buildTrackingPayload('daef8a67', undefined, 'abc123'),
  { payload: { session: 'daef8a67', proxy_id: 'abc123' } },
  'uses backend-issued proxy handles for scanned rows'
);

assert.deepEqual(
  buildTrackingPayload('manual1', 'geo.iproyal.com:12321:user:pass_session-manual1_lifetime-24h', undefined),
  {
    payload: {
      session: 'manual1',
      proxy: 'geo.iproyal.com:12321:user:pass_session-manual1_lifetime-24h'
    }
  },
  'falls back to full raw strings for manual proxy lists'
);

assert.match(
  buildTrackingPayload('daef8a67', undefined, undefined).error,
  /does not include a live tracking handle/,
  'blocks session-only tracking requests before they reach the API'
);

assert.equal(buildTrackingPayload('N/A').error, 'Invalid session ID');

console.log('proxy tracking payload tests passed');
