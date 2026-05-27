import assert from 'node:assert/strict';

import { prepareScanDiagnostics } from '../src/lib/scanDiagnostics.js';

const prepared = prepareScanDiagnostics({
  generated_count: 4,
  checked_count: 4,
  successful_count: 3,
  accepted_count: 1,
  successful_locations: [
    {
      label: 'Lagos / Ikoyi',
      count: 2,
      accepted_count: 1,
      rejected_count: 1,
      geo_sources: [{ source: 'browserleaks-db-ip', count: 2 }],
      rejection_reasons: [{ reason: 'not_mobile', label: 'Not mobile', count: 1 }]
    },
    {
      label: 'Rivers State / Port Harcourt',
      count: 1,
      accepted_count: 0,
      rejected_count: 1,
      geo_sources: [{ source: 'db-ip-api', count: 1 }],
      rejection_reasons: [{ reason: 'risk_RISK', label: 'Risk: RISK', count: 1 }]
    }
  ],
  rejection_reasons: [
    { reason: 'not_mobile', label: 'Not mobile', count: 1 },
    { reason: 'risk_RISK', label: 'Risk: RISK', count: 1 }
  ]
});

assert.equal(prepared.summary[0].label, 'Checked');
assert.equal(prepared.summary[0].value, '4');
assert.equal(prepared.summary[2].label, 'Accepted');
assert.equal(prepared.summary[2].value, '1');
assert.equal(prepared.locations[0].label, 'Lagos / Ikoyi');
assert.equal(prepared.locations[0].sourceLabel, 'BrowserLeaks + DB-IP');
assert.equal(prepared.locations[1].rejectionText, 'Risk: RISK 1');
assert.equal(prepared.rejectionReasons.map(item => item.label).join(', '), 'Not mobile, Risk: RISK');
assert.equal(prepareScanDiagnostics(null), null);
