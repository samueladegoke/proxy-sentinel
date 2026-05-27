import assert from 'node:assert/strict';

import {
  formatCohortLabel,
  formatCohortScope,
  formatCountLabel,
  formatGeoSourceLabel,
  formatObservationTimestamp,
  isOnlineGeoSource
} from '../src/lib/trackingPresentation.js';

assert.equal(
  formatCohortLabel({
    expected_location: 'country-ng',
    expected_state: null,
    expected_lifetime_hours: 24
  }),
  'Nigeria-wide sticky cohort'
);

assert.equal(
  formatCohortScope({
    expected_location: 'country-ng'
  }),
  'Country filter NG'
);

assert.equal(
  formatCohortLabel({
    expected_location: 'country-ng_state-lagos',
    expected_state: 'Lagos'
  }),
  'Lagos'
);

assert.equal(formatGeoSourceLabel('db-ip-api'), 'DB-IP API online');
assert.equal(formatGeoSourceLabel('db-ip-mmdb'), 'DB-IP MMDB fallback');
assert.equal(isOnlineGeoSource('db-ip-api'), true);
assert.equal(isOnlineGeoSource('db-ip-mmdb'), false);
assert.equal(formatCountLabel(1, 'run'), '1 run');
assert.equal(formatCountLabel(2, 'run'), '2 runs');

const exactObservationTime = formatObservationTimestamp(1778087203.4357796);
assert.match(exactObservationTime, /May 6, 2026/);
assert.match(exactObservationTime, /6:06:43/);
assert.match(exactObservationTime, /WAT$/);
