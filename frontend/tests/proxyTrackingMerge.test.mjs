import assert from 'node:assert/strict';

import { mergeProxyResultsWithTrackedSessions } from '../src/lib/proxyTrackingMerge.js';

const mmdbProxy = {
  session: 'ff8a6475',
  input_proxy: 'geo.iproyal.com:12321:user:pass_session-ff8a6475',
  proxy: 'geo.iproyal.com:12321:user:pass_session-ff8a6475',
  proxy_id: 'opaque-handle-1',
  proxy_display: 'geo.iproyal.com:12321:user:****',
  protocol: 'socks5',
  status: 'success',
  query: '102.91.5.107',
  local_region: 'Kano State',
  local_city: 'Kano',
  geo_source: 'db-ip-mmdb',
  geo_provider: 'DB-IP MMDB',
  dbip_source: 'mmdb',
  geo_quality: 'provisional-mmdb',
  geo_confirmation_pending: true,
  isp: 'MTN NIGERIA Communication',
  mobile: true,
  risk_level: 'CLEAN'
};

assert.deepEqual(
  mergeProxyResultsWithTrackedSessions(
    [mmdbProxy],
    {
      ff8a6475: {
        session: 'ff8a6475',
        run_id: 'ff8a6475-1',
        last_ip: '102.91.5.107',
        last_region: 'FCT',
        last_city: 'Bwari',
        last_result: {
          status: 'success',
          query: '102.91.5.107',
          local_region: 'FCT',
          local_city: 'Bwari',
          geo_source: 'browserleaks-db-ip',
          geo_provider: 'BrowserLeaks (DB-IP)',
          dbip_source: 'browserleaks',
          geo_quality: 'online-confirmed',
          geo_confirmation_pending: false,
          isp: 'MTN NIGERIA Communication',
          mobile: true,
          risk_level: 'CLEAN'
        }
      }
    }
  )[0],
  {
    ...mmdbProxy,
    local_region: 'FCT',
    local_city: 'Bwari',
    geo_source: 'browserleaks-db-ip',
    geo_provider: 'BrowserLeaks (DB-IP)',
    dbip_source: 'browserleaks',
    geo_quality: 'online-confirmed',
    geo_confirmation_pending: false,
    tracking_geo_overlay: true,
    tracking_run_id: 'ff8a6475-1'
  },
  'uses tracked BrowserLeaks geo over provisional MMDB while preserving proxy identity fields'
);

const apiMerged = mergeProxyResultsWithTrackedSessions(
  [mmdbProxy],
  {
    ff8a6475: {
      session: 'ff8a6475',
      last_result: {
        status: 'success',
        query: '102.91.5.107',
        local_region: 'Lagos',
        local_city: 'Ikeja',
        geo_source: 'db-ip-api',
        geo_provider: 'DB-IP API',
        dbip_source: 'api',
        mobile: true,
        risk_level: 'CLEAN'
      }
    }
  }
)[0];

assert.equal(apiMerged.local_region, 'Lagos');
assert.equal(apiMerged.local_city, 'Ikeja');
assert.equal(apiMerged.geo_source, 'db-ip-api');
assert.equal(apiMerged.geo_confirmation_pending, false);
assert.equal(apiMerged.geo_quality, 'online-confirmed');

assert.deepEqual(
  mergeProxyResultsWithTrackedSessions(
    [mmdbProxy],
    {
      ff8a6475: {
        session: 'ff8a6475',
        last_result: {
          status: 'fail',
          query: '102.91.5.107',
          local_region: 'FCT',
          local_city: 'Bwari'
        }
      }
    }
  )[0],
  mmdbProxy,
  'does not overwrite a valid row with a failed tracking result'
);

const preserved = mergeProxyResultsWithTrackedSessions(
  [mmdbProxy],
  {
    ff8a6475: {
      session: 'ff8a6475',
      last_result: {
        status: 'success',
        session: 'different-session',
        proxy: false,
        input_proxy: 'different-proxy',
        protocol: 'http',
        query: '102.91.5.107',
        local_region: 'FCT',
        local_city: 'Bwari',
        geo_source: 'browserleaks-db-ip',
        dbip_source: 'browserleaks'
      }
    }
  }
)[0];

assert.equal(preserved.session, mmdbProxy.session);
assert.equal(preserved.proxy, mmdbProxy.proxy);
assert.equal(preserved.proxy_id, mmdbProxy.proxy_id);
assert.equal(preserved.proxy_display, mmdbProxy.proxy_display);
assert.equal(preserved.proxy_risk, false);
assert.equal(preserved.input_proxy, mmdbProxy.input_proxy);
assert.equal(preserved.protocol, mmdbProxy.protocol);

const historical = mergeProxyResultsWithTrackedSessions(
  [mmdbProxy],
  {},
  [{
    run_id: 'ff8a6475-history',
    session: 'ff8a6475',
    started_at: 1777990000,
    latest_ip: '102.91.5.107',
    latest_region: 'FCT',
    latest_city: 'Bwari',
    latest_country: 'Nigeria',
    latest_isp: 'MTN NIGERIA Communication',
    latest_mobile: 1,
    latest_risk_level: 'CLEAN',
    latest_geo_source: 'db-ip-api',
    latest_geo_provider: 'DB-IP API'
  }],
  [{
    id: 10,
    run_id: 'ff8a6475-history',
    session: 'ff8a6475',
    checked_at: 1777990300,
    status: 'success',
    ip: '102.91.5.107',
    region: 'FCT',
    city: 'Bwari',
    country: 'Nigeria',
    isp: 'MTN NIGERIA Communication',
    mobile: 1,
    risk_level: 'CLEAN',
    geo_source: 'db-ip-api'
  }]
)[0];

assert.equal(historical.local_region, 'FCT');
assert.equal(historical.local_city, 'Bwari');
assert.equal(historical.local_country, 'Nigeria');
assert.equal(historical.isp, 'MTN NIGERIA Communication');
assert.equal(historical.mobile, true);
assert.equal(historical.geo_source, 'db-ip-api');
assert.equal(historical.geo_confirmation_pending, false);
assert.equal(historical.tracking_run_id, 'ff8a6475-history');

const historicalMissingLogMobile = mergeProxyResultsWithTrackedSessions(
  [mmdbProxy],
  {},
  [{
    run_id: 'ff8a6475-history',
    session: 'ff8a6475',
    started_at: 1777990000,
    latest_ip: '102.91.5.107',
    latest_region: 'FCT',
    latest_city: 'Bwari',
    latest_mobile: 1
  }],
  [{
    run_id: 'ff8a6475-history',
    session: 'ff8a6475',
    checked_at: 1777990300,
    status: 'success',
    ip: '102.91.5.107',
    region: 'FCT',
    city: 'Bwari',
    geo_source: 'db-ip-api'
  }]
)[0];

assert.equal(
  historicalMissingLogMobile.mobile,
  true,
  'keeps known run mobile flag when a newer historical log omits mobile'
);

const activeWins = mergeProxyResultsWithTrackedSessions(
  [mmdbProxy],
  {
    ff8a6475: {
      session: 'ff8a6475',
      run_id: 'ff8a6475-active',
      last_result: {
        status: 'success',
        query: '102.91.5.107',
        local_region: 'Lagos',
        local_city: 'Ikeja',
        geo_source: 'browserleaks-db-ip',
        dbip_source: 'browserleaks'
      }
    }
  },
  [{
    run_id: 'ff8a6475-history',
    session: 'ff8a6475',
    started_at: 1777990000,
    latest_ip: '102.91.5.107',
    latest_region: 'FCT',
    latest_city: 'Bwari'
  }],
  [{
    run_id: 'ff8a6475-history',
    session: 'ff8a6475',
    checked_at: 1777990300,
    status: 'success',
    ip: '102.91.5.107',
    region: 'FCT',
    city: 'Bwari',
    geo_source: 'db-ip-api'
  }]
)[0];

assert.equal(activeWins.local_region, 'Lagos');
assert.equal(activeWins.local_city, 'Ikeja');
assert.equal(activeWins.tracking_run_id, 'ff8a6475-active');
