export function buildTrackingPayload(session, proxyStr, proxyId) {
  if (!session || session === 'N/A') {
    return { error: 'Invalid session ID' };
  }

  const normalizedProxyId = typeof proxyId === 'string' ? proxyId.trim() : '';
  const normalizedProxy = typeof proxyStr === 'string' ? proxyStr.trim() : '';

  if (normalizedProxyId) {
    return { payload: { session, proxy_id: normalizedProxyId } };
  }

  if (normalizedProxy) {
    return { payload: { session, proxy: normalizedProxy } };
  }

  return {
    error: 'This proxy row does not include a live tracking handle. Re-run the scan or paste the full proxy string before tracking.'
  };
}
