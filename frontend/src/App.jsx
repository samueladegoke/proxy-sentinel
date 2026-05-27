import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import {
  AlertTriangle, ShieldCheck, Play, Monitor, RefreshCw,
  X, ChevronUp, ChevronDown, ArrowUpDown, Clipboard, Trash2, Bell,
  BellOff, Settings, Zap, Star, History, CloudDownload, MoreVertical,
  Clock3, MapPin, Moon, Sun, RotateCcw
} from 'lucide-react'
import kpiCleanMobile from './assets/kpi-clean-mobile.webp'
import kpiLastUpdate from './assets/kpi-last-update.webp'
import kpiNeedsReview from './assets/kpi-needs-review.webp'
import kpiTotalProxies from './assets/kpi-total-proxies.webp'
import proxySentinelLogo from './assets/proxy-sentinel-logo.svg'
import proxySentinelHero from './assets/proxy-sentinel-hero.webp'
import {
  formatApiError,
  getApiAuthToken,
  resolveApiBaseUrl,
  toWebSocketUrl,
  withApiAuth,
  withWebSocketAuth
} from './lib/apiConfig'
import { formatProxyLatency, isRiskFlaggedProxy, sortProxyResults } from './lib/proxyMetrics'
import { prepareScanDiagnostics } from './lib/scanDiagnostics'
import { buildTrackingPayload } from './lib/proxyTrackingPayload'
import { mergeProxyResultsWithTrackedSessions } from './lib/proxyTrackingMerge'
import {
  formatCohortLabel,
  formatCohortScope,
  formatCountLabel,
  formatGeoSourceLabel,
  formatHours,
  formatLocation,
  formatObservationTimestamp,
  formatPercent,
  formatTimestamp,
  isOnlineGeoSource
} from './lib/trackingPresentation'
import { cn } from './lib/utils'
import { soundNotifier } from './lib/sound'
import { Toast } from './components/Toast'
import { ProgressBar } from './components/ProgressBar'
import { SettingsPanel } from './components/SettingsPanel'
import { StatCard } from './components/StatCard'
import { RiskBadge } from './components/RiskBadge'

// Configuration
const API_BASE_URL = resolveApiBaseUrl({
  envUrl: import.meta.env.VITE_API_URL,
  location: globalThis.location,
  isProduction: import.meta.env.PROD
});
const API_AUTH_TOKEN = getApiAuthToken({ envToken: import.meta.env.VITE_PROXY_SENTINEL_API_TOKEN });
const WS_URL = toWebSocketUrl(API_BASE_URL);
const apiFetch = (path, options = {}) => fetch(`${API_BASE_URL}${path}`, withApiAuth(options, API_AUTH_TOKEN));
const wsEndpoint = (path) => withWebSocketAuth(`${WS_URL}${path}`, API_AUTH_TOKEN);

const NIGERIA_LOCATION_OPTIONS = [
  { value: '_country-ng', label: 'Any Nigeria' },
  { value: '_country-ng_state-abujafederalcapitalterritory', label: 'Abuja FCT' },
  { value: '_country-ng_state-akwaibom', label: 'Akwa Ibom' },
  { value: '_country-ng_state-anambra', label: 'Anambra' },
  { value: '_country-ng_state-edo', label: 'Edo' },
  { value: '_country-ng_state-jigawa', label: 'Jigawa' },
  { value: '_country-ng_state-kaduna', label: 'Kaduna' },
  { value: '_country-ng_state-kano', label: 'Kano' },
  { value: '_country-ng_state-lagos', label: 'Lagos' },
  { value: '_country-ng_state-ogun', label: 'Ogun' },
  { value: '_country-ng_state-oyo', label: 'Oyo' },
  { value: '_country-ng_state-rivers', label: 'Rivers' }
];

const THEME_STORAGE_KEY = 'proxy-sentinel-theme';
const IPROYAL_OPTIONS_STORAGE_KEY = 'proxy-sentinel-iproyal-options';
const DEFAULT_IPROYAL_OPTIONS = {
  proxy_count: 25,
  location: '_country-ng',
  rotation: 'sticky',
  sticky_hours: 2,
  high_end_pool: true,
  target_hunt_enabled: true,
  target_ip_prefixes: '197.211.52.XXX, 129.205.124.XXX, 197.211.59.XXX, 154.120.67.XXX, 154.120.76.XXX, 154.120.121.XXX, 154.120.72.XXX, 154.120.120.XXX, 102.91.134.XXX',
  target_match_count: 25,
  max_attempts: 10,
  target_pool_min_active: 3
};

const getInitialTheme = () => {
  const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (storedTheme === 'light' || storedTheme === 'dark') return storedTheme;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
};

const getInitialIPRoyalOptions = () => {
  try {
    const storedOptions = window.localStorage.getItem(IPROYAL_OPTIONS_STORAGE_KEY);
    if (!storedOptions) return DEFAULT_IPROYAL_OPTIONS;
    const parsedOptions = JSON.parse(storedOptions);
    if (!parsedOptions || typeof parsedOptions !== 'object') return DEFAULT_IPROYAL_OPTIONS;

    return {
      ...DEFAULT_IPROYAL_OPTIONS,
      ...Object.fromEntries(
        Object.keys(DEFAULT_IPROYAL_OPTIONS)
          .filter(key => Object.hasOwn(parsedOptions, key))
          .map(key => [key, parsedOptions[key]])
      )
    };
  } catch {
    return DEFAULT_IPROYAL_OPTIONS;
  }
};

const parseTargetPrefixes = (value) => (
  String(value || '')
    .split(/[\s,]+/)
    .map(prefix => prefix.trim())
    .filter(Boolean)
);

/**
 * Custom hook for WebSocket connection
 */
function useWebSocket(onMessage, enabled = true) {
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const startTimeoutRef = useRef(null);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      try {
        const ws = new WebSocket(wsEndpoint('/ws/tracking'));
        wsRef.current = ws;

        ws.onopen = () => {
          // Connected
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            onMessage(data);
          } catch {
            // Error parsing message
          }
        };

        ws.onclose = () => {
          if (!disposed) {
            reconnectTimeoutRef.current = setTimeout(connect, 3000);
          }
        };

        ws.onerror = () => {
          // Error occurred
        };
      } catch {
        if (!disposed) {
          reconnectTimeoutRef.current = setTimeout(connect, 3000);
        }
      }
    };

    startTimeoutRef.current = setTimeout(connect, 0);

    return () => {
      disposed = true;
      if (startTimeoutRef.current) {
        clearTimeout(startTimeoutRef.current);
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      const ws = wsRef.current;
      if (ws) {
        ws.onmessage = null;
        ws.onerror = null;
        ws.onclose = null;
        if (ws.readyState === WebSocket.OPEN) {
          ws.close();
        } else if (ws.readyState === WebSocket.CONNECTING) {
          ws.onopen = () => ws.close();
        }
      }
    };
  }, [enabled, onMessage]);

  return wsRef;
}

function ScrollJumpRail({ label, show, onTop, onBottom }) {
  if (!show) return null;

  return (
    <div className="pointer-events-none absolute -inset-y-5 right-0 z-10 flex w-2 flex-col items-center justify-between">
      <button
        type="button"
        onClick={onTop}
        className="pointer-events-auto -mx-2 flex h-8 w-6 items-center justify-center border-0 bg-transparent text-primary drop-shadow transition hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        title={`Jump to first ${label}`}
        aria-label={`Jump to first ${label}`}
      >
        <ChevronUp className="h-5 w-5 max-w-none stroke-[3]" />
      </button>
      <button
        type="button"
        onClick={onBottom}
        className="pointer-events-auto -mx-2 flex h-8 w-6 items-center justify-center border-0 bg-transparent text-primary drop-shadow transition hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        title={`Jump to last ${label}`}
        aria-label={`Jump to last ${label}`}
      >
        <ChevronDown className="h-5 w-5 max-w-none stroke-[3]" />
      </button>
    </div>
  );
}

/**
 * Helper to identify TARGET proxies based on the backend criteria:
 * - Clean Risk
 * - Mobile True
 * - In Abuja FCT area
 * - Specific carrier (MTN, AIRTEL, SPECTRANET, GLOBACOM, 9MOBILE, SP 217 in FCT)
 */
const isTargetProxy = (p) => {
  if (p.status !== 'success') return false;
  if (p.risk_level !== 'CLEAN') return false;
  if (!p.mobile) return false;

  const city = p.local_city || p.city || '';
  const fctCities = ['Bwari', 'Abaji', 'Gwagwalada', 'Kuje', 'Kwali'];
  const cityInFct = city.startsWith('Abuja') || fctCities.includes(city);
  if (!cityInFct) return false;

  const ispUpper = (p.isp || '').toUpperCase();
  const carrierList = ['AIRTEL', 'MTN', 'SPECTRANET', 'GLOBACOM', '9MOBILE'];

  let isTargetCarrier = carrierList.some(c => ispUpper.includes(c));
  if (ispUpper.includes('AIRTEL RWANDA')) isTargetCarrier = false;

  const isSp217Verified = ispUpper.includes('SP 217') && fctCities.includes(city);

  return isTargetCarrier || isSp217Verified;
};

// Components have been extracted to /src/components/

/**
 * Proxy Sentinel Frontend - High Performance Version with Streaming Results
 */
function App() {
  // Core state
  const [proxies, setProxies] = useState([]);
  const [scanDiagnostics, setScanDiagnostics] = useState(null);
  const [loading, setLoading] = useState(false);
  const [trackedSessions, setTrackedSessions] = useState({});
  const trackingRef = useRef(new Set()); // Keep in sync for websocket handler
  const [lastUpdate, setLastUpdate] = useState(null);
  const [error, setError] = useState(null);
  const [protocol, setProtocol] = useState('http');
  const [ipChanges, setIpChanges] = useState([]);
  const [trackingAnalytics, setTrackingAnalytics] = useState(null);
  const [trackingLogs, setTrackingLogs] = useState([]);
  const [trackingRuns, setTrackingRuns] = useState([]);
  const [trackingInsightsLoading, setTrackingInsightsLoading] = useState(false);
  const [stoppingSession, setStoppingSession] = useState(null);
  const [deletingRunId, setDeletingRunId] = useState(null);
  const [retrackingRunId, setRetrackingRunId] = useState(null);
  const [selectedTrackingRunId, setSelectedTrackingRunId] = useState(null);
  const [trackingRunDetails, setTrackingRunDetails] = useState(null);
  const [trackingRunDetailsLoading, setTrackingRunDetailsLoading] = useState(false);
  const [targetPoolStatus, setTargetPoolStatus] = useState(null);
  const [targetPoolLoading, setTargetPoolLoading] = useState(false);

  // Progress state for streaming
  const [progress, setProgress] = useState({ completed: 0, total: 0, duration: 0 });
  const [checkStartTime, setCheckStartTime] = useState(null);

  // New state for dynamic proxy input
  const [customProxyInput, setCustomProxyInput] = useState('');
  const [ipRoyalOptions, setIpRoyalOptions] = useState(getInitialIPRoyalOptions);

  // Sorting state
  const [sortConfig, setSortConfig] = useState({
    column: null,
    direction: 'asc'
  });

  // Notification state
  const [toast, setToast] = useState(null);
  const [showSettings, setShowSettings] = useState(false);
  const [settings, setSettings] = useState({
    soundEnabled: true,
    toastEnabled: true,
    volume: 0.5,
    frequency: 800,
    trackingInterval: 5
  });
  const [theme, setTheme] = useState(getInitialTheme);

  // WebSocket ref for streaming
  const checkWsRef = useRef(null);
  const activeTrackingListRef = useRef(null);
  const stoppedTrackingListRef = useRef(null);
  // Dedup guard: tracks the last processed ip_change event key+time
  const lastIpChangeRef = useRef(null);

  // Apply settings to sound notifier
  useEffect(() => {
    soundNotifier.setEnabled(settings.soundEnabled);
    soundNotifier.setVolume(settings.volume);
    soundNotifier.setFrequency(settings.frequency);
  }, [settings]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  useEffect(() => {
    window.localStorage.setItem(IPROYAL_OPTIONS_STORAGE_KEY, JSON.stringify(ipRoyalOptions));
  }, [ipRoyalOptions]);

  const trackedSessionIds = useMemo(() => Object.keys(trackedSessions).sort(), [trackedSessions]);
  const trackedSessionSet = useMemo(() => new Set(trackedSessionIds), [trackedSessionIds]);
  const activeTrackedSessions = useMemo(() => (
    Object.values(trackedSessions).sort((a, b) => (b.started_at || 0) - (a.started_at || 0))
  ), [trackedSessions]);
  const displayProxies = useMemo(() => (
    mergeProxyResultsWithTrackedSessions(proxies, trackedSessions, trackingRuns, trackingLogs)
  ), [proxies, trackedSessions, trackingRuns, trackingLogs]);
  const stoppedTrackingRuns = useMemo(() => (
    trackingRuns.filter(run => run.ended_at)
  ), [trackingRuns]);
  const formatIpTransition = useCallback((firstIp, latestIp) => {
    if (!firstIp && !latestIp) return 'IP evidence pending';
    if (!firstIp) return `Started IP pending -> ${latestIp}`;
    if (!latestIp) return `${firstIp} -> latest IP pending`;
    if (firstIp === latestIp) return `${latestIp} unchanged`;
    return `${firstIp} -> ${latestIp}`;
  }, []);
  const preparedScanDiagnostics = useMemo(() => (
    prepareScanDiagnostics(scanDiagnostics)
  ), [scanDiagnostics]);
  const targetPoolPhase = targetPoolStatus?.phase || (targetPoolStatus?.active ? 'idle' : 'stopped');
  const targetPoolProgress = targetPoolStatus?.scan_progress || {};
  const targetPoolBusy = targetPoolStatus?.active && !['idle', 'stopped', 'error'].includes(targetPoolPhase);
  const targetPoolProgressPercent = targetPoolProgress.generated > 0
    ? Math.min(100, Math.round(((targetPoolProgress.checked || 0) / targetPoolProgress.generated) * 100))
    : targetPoolBusy
      ? 12
      : 0;
  const targetPoolStageLabel = targetPoolBusy
    ? (targetPoolProgress.stage || 'searching target prefixes')
    : targetPoolStatus?.active
      ? 'idle - watching tracked proxies'
      : targetPoolStatus?.last_action || 'stopped';

  const scrollTrackingList = useCallback((targetRef, edge) => {
    const node = targetRef.current;
    if (!node) return;

    node.scrollTo({
      top: edge === 'top' ? 0 : node.scrollHeight,
      behavior: 'smooth'
    });
  }, []);

  // Keep trackingRef in sync with tracked sessions
  useEffect(() => {
    trackingRef.current = trackedSessionSet;
  }, [trackedSessionSet]);

  // Update duration during checking
  useEffect(() => {
    if (loading && checkStartTime) {
      const interval = setInterval(() => {
        setProgress(prev => ({
          ...prev,
          duration: (Date.now() - checkStartTime) / 1000
        }));
      }, 100);
      return () => clearInterval(interval);
    }
  }, [loading, checkStartTime]);

  const fetchTrackingInsights = useCallback(async () => {
    setTrackingInsightsLoading(true);
    try {
      const [analyticsResponse, logsResponse, activeResponse, runsResponse, targetPoolResponse] = await Promise.allSettled([
        apiFetch('/api/track/analytics'),
        apiFetch('/api/track/logs?limit=1000'),
        apiFetch('/api/track'),
        apiFetch('/api/track/runs?limit=1000&status=all'),
        apiFetch('/api/target-pool')
      ]);

      const readPayload = async (settledResponse) => {
        if (settledResponse.status !== 'fulfilled' || !settledResponse.value.ok) return null;
        return settledResponse.value.json().catch(() => null);
      };

      const analyticsData = await readPayload(analyticsResponse);
      const logsData = await readPayload(logsResponse);
      const activeData = await readPayload(activeResponse);
      const runsData = await readPayload(runsResponse);
      const targetPoolData = await readPayload(targetPoolResponse);

      if (analyticsData) {
        setTrackingAnalytics(analyticsData);
      }
      if (logsData) {
        setTrackingLogs(logsData.logs || []);
      }
      if (activeData) {
        setTrackedSessions(activeData.sessions || {});
      }
      if (runsData) {
        setTrackingRuns(runsData.runs || []);
      }
      if (targetPoolData) {
        setTargetPoolStatus(targetPoolData);
      }
    } catch {
      // Stability insights are optional background telemetry; user actions surface API errors explicitly.
    } finally {
      setTrackingInsightsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTrackingInsights();
  }, [fetchTrackingInsights]);

  // WebSocket message handler for tracking
  const handleWebSocketMessage = useCallback((data) => {
    if (data.type === 'tracking_check_complete') {
      setLastUpdate(new Date().toLocaleTimeString());
      fetchTrackingInsights();
    } else if (data.type === 'target_pool_update' || data.type === 'target_pool_proxy_dropped') {
      if (data.status) {
        setTargetPoolStatus(data.status);
      }
      if (data.type === 'target_pool_proxy_dropped' || ['idle', 'stopped', 'error'].includes(data.status?.phase)) {
        fetchTrackingInsights();
      }
    } else if (data.type === 'ip_change') {
      // Reject ip_change events if not actively tracking any session
      const tracked = trackingRef.current;
      if (!tracked || tracked.size === 0) return;
      // Only accept events for sessions we're tracking (or debug events)
      if (!tracked.has(data.session) && data.session !== 'DEBUG_SESSION') {
        return;
      }

      if (!data.changed_ip || (data.old_ip && data.new_ip && data.old_ip === data.new_ip)) {
        return;
      }

      // Synchronous dedup via ref - works across concurrent closures and StrictMode double-mounts
      const now = Date.now();
      const eventKey = `${data.session}|${data.old_ip}|${data.new_ip}`;
      const last = lastIpChangeRef.current;
      if (last && last.key === eventKey && (now - last.ts) < 5000) return;
      lastIpChangeRef.current = { key: eventKey, ts: now };

      if (settings.soundEnabled) {
        soundNotifier.playAlert();
      }

      if (settings.toastEnabled) {
        setToast({
          message: `IP Changed: ${data.old_ip} → ${data.new_ip}`,
          type: 'warning'
        });
      }

      setIpChanges(prev => [{
        id: `${now}-${Math.random()}`,
        session: data.session,
        oldIp: data.old_ip,
        newIp: data.new_ip,
        time: new Date(now).toLocaleTimeString(),
        city: data.new_city || data.city || 'Unknown',
        oldCity: data.old_city,
        oldRegion: data.old_region,
        newRegion: data.new_region,
        elapsedSeconds: data.elapsed_seconds,
        lifetimeProgress: data.lifetime_progress,
        expectedLifetimeHours: data.expected_lifetime_hours,
        _ts: now
      }, ...prev].slice(0, 50));
      fetchTrackingInsights();
    }
  }, [fetchTrackingInsights, settings]);

  // WebSocket connection — always open so events are never missed due to race conditions
  useWebSocket(handleWebSocketMessage, true);

  const updateTrackingInterval = useCallback(async (interval) => {
    try {
      await apiFetch('/api/track/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interval_minutes: interval })
      });
    } catch {
      // Error updating tracking interval
    }
  }, []);

  // Stats calculation - uses authoritative risk_level field from backend
  const stats = useMemo(() => {
    const total = displayProxies.length;
    // Clean Mobile = succeeded, marked mobile by carrier, and risk_level is CLEAN
    const clean = displayProxies.filter(p =>
      p.status === 'success' &&
      p.mobile === true &&
      p.risk_level === 'CLEAN'
    ).length;
    // Risky = any proxy flagged as hosting or proxy (datacenter/VPN)
    const risky = displayProxies.filter(p =>
      p.status === 'success' && isRiskFlaggedProxy(p)
    ).length;
    const failed = displayProxies.filter(p => p.status !== 'success').length;

    return { total, clean, risky, failed };
  }, [displayProxies]);

  // Parse proxy input into array
  const parsedProxies = useMemo(() => {
    if (!customProxyInput.trim()) return [];
    return customProxyInput
      .split('\n')
      .map(line => line.trim())
      .filter(line => line && !line.startsWith('#'));
  }, [customProxyInput]);

  const currentProxyIds = useMemo(() => (
    proxies.map(proxy => proxy?.proxy_id).filter(Boolean)
  ), [proxies]);

  // Map session ID → original proxy string (for custom proxy tracking)
  const sessionProxyMap = useMemo(() => {
    const map = {};
    parsedProxies.forEach(proxyStr => {
      // Extract session ID using the same logic as the backend
      const match = proxyStr.match(/_session-([^_]+)/);
      if (match) {
        map[match[1]] = proxyStr;
      }
    });
    return map;
  }, [parsedProxies]);

  // Sorted proxies for display
  const sortedProxies = useMemo(() => {
    return sortProxyResults(displayProxies, sortConfig, isTargetProxy);
  }, [displayProxies, sortConfig]);

  // Handle sort column click
  const handleSort = useCallback((column) => {
    setSortConfig(prev => ({
      column,
      direction: prev.column === column && prev.direction === 'asc' ? 'desc' : 'asc'
    }));
  }, []);

  const handleCheck = useCallback(async () => {
    setError(null);
    setToast(null);

    const proxiesToCheck = parsedProxies.length > 0 ? parsedProxies : [];
    const proxyIdsToCheck = proxiesToCheck.length === 0 ? currentProxyIds : [];
    if (proxiesToCheck.length === 0 && proxyIdsToCheck.length === 0) {
      setError('Please enter at least one proxy or run a scan before refreshing the current list.');
      setLoading(false); // Ensure loading state is reset if validation fails
      return;
    }

    setLoading(true);
    setProxies([]);
    setScanDiagnostics(null);
    setIpChanges([]);
    setProgress({ completed: 0, total: proxiesToCheck.length || proxyIdsToCheck.length, duration: 0 });
    setCheckStartTime(Date.now());

    try {
      // Create WebSocket connection for streaming results
      const ws = new WebSocket(wsEndpoint('/ws/check'));

      ws.onopen = () => {
        // Send check request
        ws.send(JSON.stringify({
          proxies: proxiesToCheck,
          proxy_ids: proxyIdsToCheck,
          protocol: protocol
        }));
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        switch (data.type) {
          case 'start':
            setProgress(prev => ({ ...prev, total: data.total }));
            break;

          case 'progress':
            // Add result to list immediately
            setProxies(prev => [...prev, data.result]);
            setProgress(prev => ({
              ...prev,
              completed: data.completed,
              total: data.total
            }));
            break;

          case 'complete':
            setLastUpdate(new Date().toLocaleTimeString());
            setLoading(false);
            setCheckStartTime(null);
            if (settings.toastEnabled) {
              setToast({
                message: `Completed: ${data.total} proxies in ${data.duration}s (${data.proxies_per_second}/sec)`,
                type: 'success'
              });
            }
            ws.close();
            break;

          case 'error':
            setError(Array.isArray(data.message)
              ? data.message.map(item => item.msg || String(item)).join('; ')
              : data.message);
            setLoading(false);
            setCheckStartTime(null);
            ws.close();
            break;
        }
      };

      ws.onerror = () => {
        setError(formatApiError(new Error('WebSocket connection failed'), 'Analyze proxy list', API_BASE_URL));
        setLoading(false);
        setCheckStartTime(null);
      };

      ws.onclose = () => {
        setLoading(false);
        setCheckStartTime(null);
      };

      checkWsRef.current = ws;

    } catch (err) {
      setError(formatApiError(err, 'Analyze proxy list', API_BASE_URL));
      console.error("Error checking proxies:", err);
      setLoading(false);
      setCheckStartTime(null);
    }
  }, [parsedProxies, currentProxyIds, protocol, settings.toastEnabled]);

  const handleIPRoyalCheck = useCallback(async () => {
    setError(null);
    setToast(null);
    setLoading(true);
    setProxies([]);
    setScanDiagnostics(null);
    setIpChanges([]);
    const proxyCount = Math.min(500, Math.max(1, Number(ipRoyalOptions.proxy_count) || 1));
    const stickyHours = Math.min(168, Math.max(1, Number(ipRoyalOptions.sticky_hours) || 1));
    const targetPrefixes = ipRoyalOptions.target_hunt_enabled
      ? parseTargetPrefixes(ipRoyalOptions.target_ip_prefixes)
      : [];
    const targetMatchCount = Math.min(500, Math.max(1, Number(ipRoyalOptions.target_match_count) || 1));
    const maxAttempts = Math.min(20, Math.max(1, Number(ipRoyalOptions.max_attempts) || 1));
    const plannedTotal = proxyCount * (targetPrefixes.length > 0 ? maxAttempts : 1);
    setProgress({ completed: 0, total: plannedTotal, duration: 0 });
    const startedAt = Date.now();
    setCheckStartTime(startedAt);

    try {
      const ws = new WebSocket(wsEndpoint('/ws/iproyal-check'));
      let completedNormally = false;

      ws.onopen = () => {
        ws.send(JSON.stringify({
          proxy_count: proxyCount,
          location: ipRoyalOptions.location,
          rotation: ipRoyalOptions.rotation,
          lifetime: ipRoyalOptions.rotation === 'sticky' ? `${stickyHours}h` : null,
          high_end_pool: ipRoyalOptions.high_end_pool,
          protocol,
          target_ip_prefixes: targetPrefixes.length > 0 ? targetPrefixes : null,
          target_match_count: targetPrefixes.length > 0 ? targetMatchCount : 0,
          max_attempts: targetPrefixes.length > 0 ? maxAttempts : 1
        }));
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        switch (data.type) {
          case 'start':
            setProgress(prev => ({ ...prev, total: data.total || plannedTotal }));
            break;

          case 'attempt_start':
            setProgress(prev => ({ ...prev, total: data.total || prev.total }));
            break;

          case 'progress':
            if (data.accepted && data.result) {
              setProxies(prev => [...prev, data.result]);
            }
            setProgress(prev => ({
              ...prev,
              completed: data.completed || prev.completed,
              total: data.total || prev.total
            }));
            break;

          case 'complete': {
            completedNormally = true;
            const bestResults = data.best_results || [];
            setProxies(bestResults);
            setScanDiagnostics(data.diagnostics || null);
            setCustomProxyInput('');
            setProgress({
              completed: data.checked_count || 0,
              total: data.generated_count || data.checked_count || 0,
              duration: (Date.now() - startedAt) / 1000
            });
            setLastUpdate(new Date().toLocaleTimeString());
            setLoading(false);
            setCheckStartTime(null);

            if (settings.toastEnabled) {
              const rejectedCount = data.location_rejected_count || 0;
              const requestedState = data.criteria?.requested_state
                || NIGERIA_LOCATION_OPTIONS.find(option => option.value === ipRoyalOptions.location)?.label
                || 'selected state';
              const rejectionNote = rejectedCount > 0
                ? `; ${rejectedCount} clean mobile rejected outside ${requestedState}`
                : '';
              const huntNote = targetPrefixes.length > 0
                ? ` across ${data.attempts_completed || 1} hunt attempt${(data.attempts_completed || 1) === 1 ? '' : 's'}`
                : '';
              setToast({
                message: `IPRoyal scan complete: ${data.best_count || 0}/${data.checked_count || 0} matched proxies${huntNote}${rejectionNote}`,
                type: bestResults.length > 0 ? 'success' : 'warning'
              });
            }
            ws.close();
            break;
          }

          case 'error':
            setError(Array.isArray(data.message)
              ? data.message.map(item => item.msg || String(item)).join('; ')
              : data.message);
            setLoading(false);
            setCheckStartTime(null);
            ws.close();
            break;
        }
      };

      ws.onerror = () => {
        setError(formatApiError(new Error('WebSocket connection failed'), 'Run IPRoyal scan', API_BASE_URL));
        setLoading(false);
        setCheckStartTime(null);
      };

      ws.onclose = () => {
        if (!completedNormally) {
          setLoading(false);
          setCheckStartTime(null);
        }
      };

      checkWsRef.current = ws;
    } catch (err) {
      setError(formatApiError(err, 'Run IPRoyal scan', API_BASE_URL));
      setLoading(false);
      setCheckStartTime(null);
    }
  }, [ipRoyalOptions, protocol, settings.toastEnabled]);

  const toggleTargetPool = useCallback(async () => {
    setError(null);
    setTargetPoolLoading(true);

    try {
      if (targetPoolStatus?.active) {
        const response = await apiFetch('/api/target-pool/stop', { method: 'POST' });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.message || payload?.detail || 'Failed to stop target pool automation');
        }
        const payload = await response.json();
        setTargetPoolStatus(payload.target_pool || payload);
        if (settings.toastEnabled) {
          setToast({ message: 'Target pool automation stopped', type: 'success' });
        }
        await fetchTrackingInsights();
        return;
      }

      const stickyHours = Math.min(168, Math.max(1, Number(ipRoyalOptions.sticky_hours) || 1));
      const targetPrefixes = parseTargetPrefixes(ipRoyalOptions.target_ip_prefixes);
      if (targetPrefixes.length === 0) {
        throw new Error('Add at least one target IP prefix before starting target pool automation');
      }

      const request = {
        proxy_count: Math.min(500, Math.max(1, Number(ipRoyalOptions.proxy_count) || 1)),
        location: ipRoyalOptions.location,
        rotation: ipRoyalOptions.rotation,
        lifetime: ipRoyalOptions.rotation === 'sticky' ? `${stickyHours}h` : null,
        high_end_pool: ipRoyalOptions.high_end_pool,
        protocol,
        target_ip_prefixes: targetPrefixes,
        target_match_count: Math.min(20, Math.max(1, Number(ipRoyalOptions.target_pool_min_active) || 3)),
        max_attempts: Math.min(20, Math.max(1, Number(ipRoyalOptions.max_attempts) || 1)),
        min_active: Math.min(20, Math.max(1, Number(ipRoyalOptions.target_pool_min_active) || 3)),
        check_interval_seconds: 60,
        replacement_cooldown_seconds: 0
      };

      const response = await apiFetch('/api/target-pool/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request)
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.message || payload?.detail || 'Failed to start target pool automation');
      }
      const payload = await response.json();
      setTargetPoolStatus(payload.target_pool || payload);
      if (settings.toastEnabled) {
        setToast({ message: `Target pool automation started: keeping ${request.min_active} active`, type: 'success' });
      }
      await fetchTrackingInsights();
    } catch (err) {
      setError(formatApiError(err, 'Target pool automation', API_BASE_URL));
    } finally {
      setTargetPoolLoading(false);
    }
  }, [fetchTrackingInsights, ipRoyalOptions, protocol, settings.toastEnabled, targetPoolStatus?.active]);

  // Cancel ongoing check
  const cancelCheck = useCallback(() => {
    if (checkWsRef.current) {
      checkWsRef.current.close();
    }
    setLoading(false);
    setCheckStartTime(null);
  }, []);

  // Start tracking a proxy. Prefer the backend-issued opaque handle; use raw input only for manual lists.
  const startTracking = useCallback(async (session, proxyStr, proxyId) => {
    const { payload, error: payloadError } = buildTrackingPayload(session, proxyStr, proxyId);
    if (payloadError) {
      setError(payloadError);
      return;
    }

    try {
      const response = await apiFetch('/api/track', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || data.message || `Failed to start tracking: ${response.statusText}`);
      }

      await updateTrackingInterval(settings.trackingInterval);

      if (settings.toastEnabled) {
        setToast({ message: `Started tracking: ${session}`, type: 'success' });
      }
      await fetchTrackingInsights();

    } catch (err) {
      console.error("Error starting tracking:", err);
      setError(formatApiError(err, 'Start proxy tracking', API_BASE_URL));
    }
  }, [fetchTrackingInsights, settings.trackingInterval, settings.toastEnabled, updateTrackingInterval]);

  // Stop tracking
  const stopTracking = useCallback(async (session) => {
    if (!session) return;

    setStoppingSession(session);
    try {
      const response = await apiFetch(`/api/track/${session}`, { method: 'DELETE' });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || data.message || `Failed to stop tracking: ${response.statusText}`);
      }
      if (settings.toastEnabled) {
        setToast({ message: `Stopped tracking: ${session}`, type: 'success' });
      }
    } catch (err) {
      console.error("Error stopping tracking:", err);
      setError(formatApiError(err, 'Stop proxy tracking', API_BASE_URL));
    } finally {
      setStoppingSession(null);
      fetchTrackingInsights();
    }
  }, [fetchTrackingInsights, settings.toastEnabled]);

  const loadTrackingRunDetails = useCallback(async (runId) => {
    if (!runId) return;
    if (selectedTrackingRunId === runId) {
      setSelectedTrackingRunId(null);
      setTrackingRunDetails(null);
      return;
    }

    setSelectedTrackingRunId(runId);
    setTrackingRunDetailsLoading(true);
    try {
      const response = await apiFetch(`/api/track/runs/${encodeURIComponent(runId)}?observation_limit=500`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || data.message || `Failed to load tracking run: ${response.statusText}`);
      }
      setTrackingRunDetails(data);
    } catch (err) {
      setError(formatApiError(err, 'Load tracking history', API_BASE_URL));
      setTrackingRunDetails(null);
    } finally {
      setTrackingRunDetailsLoading(false);
    }
  }, [selectedTrackingRunId]);

  const deleteTrackingRun = useCallback(async (runId) => {
    if (!runId) return;

    setDeletingRunId(runId);
    try {
      const response = await apiFetch(`/api/track/runs/${encodeURIComponent(runId)}`, {
        method: 'DELETE'
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || data.message || `Failed to delete tracking run: ${response.statusText}`);
      }
      if (selectedTrackingRunId === runId) {
        setSelectedTrackingRunId(null);
        setTrackingRunDetails(null);
      }
      if (settings.toastEnabled) {
        setToast({ message: 'Deleted historical tracking run', type: 'success' });
      }
      await fetchTrackingInsights();
    } catch (err) {
      setError(formatApiError(err, 'Delete tracking history', API_BASE_URL));
    } finally {
      setDeletingRunId(null);
    }
  }, [fetchTrackingInsights, selectedTrackingRunId, settings.toastEnabled]);

  const retrackTrackingRun = useCallback(async (runId) => {
    if (!runId) return;

    setRetrackingRunId(runId);
    try {
      const response = await apiFetch(`/api/track/runs/${encodeURIComponent(runId)}/retrack`, {
        method: 'POST'
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || data.message || `Failed to re-track proxy: ${response.statusText}`);
      }
      if (settings.toastEnabled) {
        setToast({ message: `Re-tracking ${data.session || 'historical proxy'}`, type: 'success' });
      }
      await fetchTrackingInsights();
    } catch (err) {
      setError(formatApiError(err, 'Re-track historical proxy', API_BASE_URL));
    } finally {
      setRetrackingRunId(null);
    }
  }, [fetchTrackingInsights, settings.toastEnabled]);

  // Clear error
  const clearError = () => setError(null);

  // Handle settings change
  const handleSettingsChange = useCallback((newSettings) => {
    setSettings(newSettings);
    if (newSettings.trackingInterval !== settings.trackingInterval && trackedSessionIds.length > 0) {
      updateTrackingInterval(newSettings.trackingInterval);
    }
  }, [settings.trackingInterval, trackedSessionIds.length, updateTrackingInterval]);

  const selectedLocationLabel = useMemo(() => (
    NIGERIA_LOCATION_OPTIONS.find(option => option.value === ipRoyalOptions.location)?.label || 'Any Nigeria'
  ), [ipRoyalOptions.location]);
  const selectedPoolLabel = ipRoyalOptions.high_end_pool ? 'high-end pool' : 'standard pool';

  const readinessScore = stats.total > 0 ? Math.round((stats.clean / stats.total) * 100) : 0;
  const stabilityGroups = trackingAnalytics?.groups || [];
  const topStabilityGroup = stabilityGroups[0];

  const roadmapIdeas = [
    'Cohort score by state, carrier, ASN, and sticky lifetime.',
    'Environment drift alerts for IP, city, ISP, DNS, and device signals.',
    'Evidence export with lookup sources, screenshots, and lifetime history.'
  ];
  const canRefreshCurrentList = (parsedProxies.length > 0 || currentProxyIds.length > 0) && !loading;

  const toggleTheme = useCallback(() => {
    setTheme(prev => (prev === 'dark' ? 'light' : 'dark'));
  }, []);

  // Sort indicator component
  const SortIndicator = ({ column }) => {
    if (sortConfig.column !== column) {
      return <ArrowUpDown className="w-4 h-4 ml-1 opacity-40" />;
    }
    return sortConfig.direction === 'asc'
      ? <ChevronUp className="w-4 h-4 ml-1 text-primary" />
      : <ChevronDown className="w-4 h-4 ml-1 text-primary" />;
  };

  return (
    <div className="dashboard-shell min-h-screen overflow-x-hidden text-foreground selection:bg-primary/20" data-testid="proxy-dashboard">
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      {showSettings && (
        <SettingsPanel
          settings={settings}
          onSettingsChange={handleSettingsChange}
          onClose={() => setShowSettings(false)}
        />
      )}

      <header className="sticky top-0 z-40 border-b border-border/80 bg-background/90 px-4 py-3 backdrop-blur-xl sm:px-6 lg:px-8">
        <div className="mx-auto flex max-w-[1680px] items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center bg-transparent drop-shadow-[0_12px_28px_rgba(25,215,255,0.18)]">
              <img
                src={proxySentinelLogo}
                alt=""
                aria-hidden="true"
                className="h-10 w-10 object-contain"
              />
            </div>
            <div className="min-w-0">
              <h1 className="text-base font-extrabold tracking-tight sm:text-lg">Proxy Sentinel</h1>
              <p className="hidden text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground sm:block">
                Residential proxy intelligence
              </p>
            </div>
            <div className="hidden items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1.5 md:flex">
              <span className="status-dot" />
              <span className="text-xs font-bold text-primary">System online</span>
            </div>
            {trackedSessionIds.length > 0 && (
              <div className="hidden items-center gap-2 rounded-full border border-primary/20 bg-primary/10 px-3 py-1.5 text-xs font-bold text-primary md:flex">
                <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                Tracking {trackedSessionIds.length}
              </div>
            )}
          </div>

          <div className="flex items-center gap-2">
            <div className="hidden items-center gap-2 rounded-full border border-border bg-card px-3 py-2 text-xs font-bold text-muted-foreground lg:flex">
              {settings.toastEnabled ? <Bell className="h-4 w-4 text-primary" /> : <BellOff className="h-4 w-4" />}
              Alerts {settings.toastEnabled ? 'on' : 'off'}
            </div>
            <button
              type="button"
              onClick={toggleTheme}
              className="secondary-action flex items-center gap-2 px-3 py-2 text-xs"
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
              data-testid="theme-toggle"
            >
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              <span className="hidden sm:inline">{theme === 'dark' ? 'Light' : 'Dark'}</span>
            </button>
            <button
              type="button"
              onClick={() => setShowSettings(true)}
              className="ghost-action"
              title="Notification settings"
              aria-label="Open notification settings"
            >
              <Settings className="h-5 w-5" />
            </button>
          </div>
        </div>
      </header>

      <main className="relative z-10 mx-auto max-w-[1680px] px-4 py-8 sm:px-6 lg:px-8">
        <section className="mb-6 grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="dashboard-panel overflow-hidden rounded-[2rem]">
            <div className="grid min-h-[320px] lg:grid-cols-[minmax(0,1fr)_430px]">
              <div className="flex flex-col justify-between p-5 sm:p-6">
                <div>
                  <p className="mb-2 text-xs font-extrabold uppercase tracking-[0.22em] text-primary">Static residential proxy QA</p>
                  <h2 className="max-w-2xl text-3xl font-extrabold tracking-[-0.04em] text-foreground xl:text-4xl">
                    Find clean, mobile exits that keep their geography stable.
                  </h2>
                  <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
                    Generate, verify, track, and compare proxy cohorts using DB-IP first, BrowserLeaks second, and local MMDB only as a last resort.
                  </p>
                </div>

                <div className="mt-6 grid grid-cols-2 gap-3 sm:max-w-md">
                  <div className="panel-subtle rounded-2xl p-4">
                    <p className="text-xs font-bold uppercase tracking-[0.16em] text-muted-foreground">Readiness</p>
                    <p className="mt-2 text-3xl font-extrabold text-primary">{readinessScore}%</p>
                  </div>
                  <div className="panel-subtle rounded-2xl p-4">
                    <p className="text-xs font-bold uppercase tracking-[0.16em] text-muted-foreground">Lookup</p>
                    <p className="mt-2 text-sm font-extrabold text-foreground">DB-IP first</p>
                    <p className="text-xs text-muted-foreground">BrowserLeaks, then MMDB</p>
                  </div>
                </div>
              </div>

              <div className="relative min-h-[260px] overflow-hidden border-t border-border bg-secondary lg:border-l lg:border-t-0">
                <img
                  src={proxySentinelHero}
                  alt=""
                  aria-hidden="true"
                  className="h-full w-full object-cover"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-background/55 via-transparent to-transparent lg:bg-gradient-to-l lg:from-background/30 lg:to-transparent" />
                <div className="absolute bottom-4 left-4 right-4 rounded-2xl border border-border bg-card/90 p-3 shadow-2xl backdrop-blur-md">
                  <div className="flex items-center gap-2 text-[10px] font-extrabold uppercase tracking-[0.16em] text-primary">
                    <span className="status-dot h-2 w-2" />
                    Stable exit map
                  </div>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">
                    Track state signal, mobile carrier, resolved IP, and sticky-hour drift.
                  </p>
                </div>
              </div>
            </div>
          </div>

          <aside className="dashboard-panel h-fit rounded-[2rem] p-5">
            <div className="flex items-center justify-between">
              <p className="text-xs font-extrabold uppercase tracking-[0.2em] text-muted-foreground">Best cohort</p>
              <ShieldCheck className="h-5 w-5 text-primary" />
            </div>
            {topStabilityGroup ? (
              <div className="mt-5">
                <p className="text-2xl font-extrabold tracking-tight">{formatCohortLabel(topStabilityGroup)}</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  {formatCohortScope(topStabilityGroup)} · {formatHours(topStabilityGroup.max_stable_hours)} best stability across {formatCountLabel(topStabilityGroup.runs, 'run')}.
                </p>
                <div className="mt-5 grid grid-cols-2 gap-3 text-sm">
                  <div className="panel-subtle rounded-2xl p-3">
                    <span className="text-muted-foreground">Change rate</span>
                    <strong className="mt-1 block text-foreground">{formatPercent(topStabilityGroup.change_rate)}</strong>
                  </div>
                  <div className="panel-subtle rounded-2xl p-3">
                    <span className="text-muted-foreground">Lifetime</span>
                    <strong className="mt-1 block text-foreground">{formatHours(topStabilityGroup.expected_lifetime_hours)}</strong>
                  </div>
                </div>
              </div>
            ) : (
              <p className="mt-5 text-sm leading-6 text-muted-foreground">
                Track a proxy to build state and sticky-hour reliability evidence.
              </p>
            )}
          </aside>
        </section>

        <section className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="Total proxies"
            value={stats.total}
            icon={<img src={kpiTotalProxies} alt="" aria-hidden="true" className="h-full w-full object-contain" />}
            tone="info"
            helper={`${progress.completed || 0}/${progress.total || 0} in current scan`}
          />
          <StatCard
            title="Clean mobile"
            value={stats.clean}
            icon={<img src={kpiCleanMobile} alt="" aria-hidden="true" className="h-full w-full object-contain" />}
            tone="primary"
            helper="Clean risk plus mobile network signal"
          />
          <StatCard
            title="Needs review"
            value={stats.risky}
            icon={<img src={kpiNeedsReview} alt="" aria-hidden="true" className="h-full w-full object-contain" />}
            tone="danger"
            helper={`${stats.failed} failed checks`}
          />
          <StatCard
            title="Last update"
            value={lastUpdate || 'Never'}
            icon={<img src={kpiLastUpdate} alt="" aria-hidden="true" className="h-full w-full object-contain" />}
            tone="neutral"
            helper={`Protocol: ${protocol.toUpperCase()}`}
          />
        </section>

        <div className="grid grid-cols-1 items-start gap-6 lg:relative lg:pb-[980px] lg:grid-cols-[390px_minmax(0,1fr)] 2xl:grid-cols-[420px_minmax(0,1fr)]">
          <aside className="space-y-6 lg:contents">
            <section className="dashboard-panel rounded-3xl p-5 lg:sticky lg:top-24 lg:col-start-1 lg:row-start-1" data-testid="scan-controls">
              <div className="mb-5 flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs font-extrabold uppercase tracking-[0.2em] text-primary">Scan controls</p>
                  <h3 className="mt-2 text-xl font-extrabold">Source and verify</h3>
                </div>
                <Zap className="h-5 w-5 text-muted-foreground" />
              </div>

              <label className="block">
                <span className="mb-2 block text-sm font-bold text-foreground">Proxy list</span>
                <textarea
                  value={customProxyInput}
                  onChange={(e) => setCustomProxyInput(e.target.value)}
                  placeholder={`Paste proxy list...\n\nhost:port:user:pass\nsocks5://proxy.example.com:1080`}
                  className="control-input h-64 w-full resize-none font-mono text-sm placeholder:text-muted-foreground/70"
                  disabled={loading}
                />
              </label>

              <div className="mt-5 rounded-2xl border border-border bg-secondary/55 p-4" data-testid="iproyal-panel">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div>
                    <p className="text-xs font-extrabold uppercase tracking-[0.18em] text-muted-foreground">IPRoyal auto scan</p>
                    <p className="mt-1 text-sm font-semibold text-foreground">
                      {selectedLocationLabel} · {ipRoyalOptions.rotation} · {selectedPoolLabel}
                    </p>
                  </div>
                  <CloudDownload className="h-5 w-5 text-info" />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">Count</span>
                    <input
                      aria-label="Proxy count"
                      type="number"
                      min="1"
                      max="500"
                      value={ipRoyalOptions.proxy_count}
                      onChange={(e) => setIpRoyalOptions(prev => ({ ...prev, proxy_count: e.target.value }))}
                      disabled={loading}
                      className="control-input w-full font-mono text-sm"
                      title="Proxy count"
                    />
                  </label>
                  <label className="block">
                    <span className="mb-1.5 block text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">Rotation</span>
                    <select
                      aria-label="Rotation"
                      value={ipRoyalOptions.rotation}
                      onChange={(e) => setIpRoyalOptions(prev => ({ ...prev, rotation: e.target.value }))}
                      disabled={loading}
                      className="control-input w-full text-sm font-bold"
                    >
                      <option value="sticky">Sticky</option>
                      <option value="random">Random</option>
                    </select>
                  </label>
                </div>

                <label className="mt-3 block">
                  <span className="mb-1.5 block text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">State</span>
                  <select
                    aria-label="State"
                    value={ipRoyalOptions.location}
                    onChange={(e) => setIpRoyalOptions(prev => ({ ...prev, location: e.target.value }))}
                    disabled={loading}
                    className="control-input w-full text-sm font-bold"
                    title="State"
                  >
                    {NIGERIA_LOCATION_OPTIONS.map(option => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>

                <div className="mt-3 grid grid-cols-[minmax(0,1fr)_130px] gap-3">
                  <div className="flex min-w-0 items-center gap-2 rounded-xl border border-border bg-card px-3 py-2">
                    <MapPin className="h-4 w-4 shrink-0 text-info" />
                    <span className="truncate font-mono text-xs text-muted-foreground" title={ipRoyalOptions.location}>
                      {ipRoyalOptions.location}
                    </span>
                  </div>
                  <label className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2">
                    <Clock3 className="h-4 w-4 shrink-0 text-info" />
                    <input
                      aria-label="Sticky hours"
                      type="number"
                      min="1"
                      max="168"
                      value={ipRoyalOptions.sticky_hours}
                      onChange={(e) => setIpRoyalOptions(prev => ({ ...prev, sticky_hours: e.target.value }))}
                      disabled={loading || ipRoyalOptions.rotation !== 'sticky'}
                      className="w-full bg-transparent font-mono text-sm outline-none disabled:opacity-50"
                      title="Sticky hours"
                    />
                    <span className="text-xs font-bold uppercase text-muted-foreground">h</span>
                  </label>
                </div>

                <label className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-border bg-card px-3 py-2.5">
                  <span className="min-w-0">
                    <span className="block text-xs font-extrabold uppercase tracking-[0.12em] text-muted-foreground">
                      High-end pool
                    </span>
                    <span className="mt-1 block text-xs font-semibold text-muted-foreground">
                      {ipRoyalOptions.high_end_pool
                        ? 'Adds _streaming-1 to generated credentials.'
                        : 'Uses standard pool credentials without _streaming-1.'}
                    </span>
                  </span>
                  <input
                    aria-label="High-end pool"
                    type="checkbox"
                    checked={ipRoyalOptions.high_end_pool}
                    onChange={(e) => setIpRoyalOptions(prev => ({ ...prev, high_end_pool: e.target.checked }))}
                    disabled={loading}
                    className="h-5 w-5 shrink-0 accent-primary"
                  />
                </label>

                <div className="mt-3 rounded-xl border border-primary/20 bg-primary/5 p-3">
                  <label className="flex items-center justify-between gap-3">
                    <span className="min-w-0">
                      <span className="block text-xs font-extrabold uppercase tracking-[0.12em] text-primary">
                        Target IP group hunt
                      </span>
                      <span className="mt-1 block text-xs font-semibold text-muted-foreground">
                        Fast prefilters by exit IP prefix before slower geo confirmation.
                      </span>
                    </span>
                    <input
                      aria-label="Target IP group hunt"
                      type="checkbox"
                      checked={ipRoyalOptions.target_hunt_enabled}
                      onChange={(e) => setIpRoyalOptions(prev => ({ ...prev, target_hunt_enabled: e.target.checked }))}
                      disabled={loading}
                      className="h-5 w-5 shrink-0 accent-primary"
                    />
                  </label>

                  {ipRoyalOptions.target_hunt_enabled && (
                    <div className="mt-3 space-y-3">
                      <label className="block">
                        <span className="mb-1.5 block text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">
                          Target prefixes
                        </span>
                        <textarea
                          aria-label="Target IP prefixes"
                          value={ipRoyalOptions.target_ip_prefixes}
                          onChange={(e) => setIpRoyalOptions(prev => ({ ...prev, target_ip_prefixes: e.target.value }))}
                          disabled={loading}
                          className="control-input h-20 w-full resize-none font-mono text-xs"
                        />
                      </label>
                      <div className="grid grid-cols-2 gap-3">
                        <label className="block">
                          <span className="mb-1.5 block text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">
                            Stop after
                          </span>
                          <input
                            aria-label="Target match count"
                            type="number"
                            min="1"
                            max="500"
                            value={ipRoyalOptions.target_match_count}
                            onChange={(e) => setIpRoyalOptions(prev => ({ ...prev, target_match_count: e.target.value }))}
                            disabled={loading}
                            className="control-input w-full font-mono text-sm"
                          />
                        </label>
                        <label className="block">
                          <span className="mb-1.5 block text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">
                            Max tries
                          </span>
                          <input
                            aria-label="Maximum hunt attempts"
                            type="number"
                            min="1"
                            max="20"
                            value={ipRoyalOptions.max_attempts}
                            onChange={(e) => setIpRoyalOptions(prev => ({ ...prev, max_attempts: e.target.value }))}
                            disabled={loading}
                            className="control-input w-full font-mono text-sm"
                          />
                        </label>
                      </div>
                      <div className="rounded-xl border border-info/25 bg-info/10 p-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="text-xs font-extrabold uppercase tracking-[0.12em] text-primary">
                              Target pool automation
                            </p>
                            <p className="mt-1 text-xs font-semibold leading-5 text-muted-foreground">
                              Keeps replacement proxies tracked when a target exit leaves the selected IP groups.
                            </p>
                          </div>
                          <span className={cn(
                            'shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-extrabold uppercase tracking-widest',
                            targetPoolStatus?.active
                              ? 'border-primary/30 bg-primary/15 text-primary'
                              : 'border-border bg-secondary text-muted-foreground'
                          )}>
                            {targetPoolStatus?.active ? 'Running' : 'Off'}
                          </span>
                        </div>
                        <div className="mt-3 grid grid-cols-2 gap-3">
                          <label className="block">
                            <span className="mb-1.5 block text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">
                              Keep active
                            </span>
                            <input
                              aria-label="Target pool minimum active proxies"
                              type="number"
                              min="1"
                              max="20"
                              value={ipRoyalOptions.target_pool_min_active}
                              onChange={(e) => setIpRoyalOptions(prev => ({ ...prev, target_pool_min_active: e.target.value }))}
                              disabled={targetPoolLoading || targetPoolStatus?.active}
                              className="control-input w-full font-mono text-sm"
                            />
                          </label>
                          <div className="rounded-xl border border-border bg-card px-3 py-2">
                            <p className="text-[10px] font-extrabold uppercase tracking-[0.12em] text-muted-foreground">
                              Live target
                            </p>
                            <p className="mt-1 font-mono text-sm font-extrabold text-foreground">
                              {targetPoolStatus?.active_target_count ?? 0}/{targetPoolStatus?.min_active || ipRoyalOptions.target_pool_min_active}
                            </p>
                          </div>
                        </div>
                        {targetPoolStatus?.last_action && (
                          <p className="mt-2 text-xs font-semibold leading-5 text-muted-foreground">
                            {targetPoolStatus.last_action}
                          </p>
                        )}
                        <div className={cn(
                          'mt-3 overflow-hidden rounded-xl border px-3 py-2 transition',
                          targetPoolBusy
                            ? 'border-primary/30 bg-primary/10'
                            : 'border-border bg-card/70'
                        )}>
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-[10px] font-extrabold uppercase tracking-[0.14em] text-muted-foreground">
                              {targetPoolBusy ? 'Active search' : 'Automation state'}
                            </span>
                            <span className={cn(
                              'font-mono text-[10px] font-extrabold uppercase tracking-widest',
                              targetPoolBusy ? 'text-primary' : 'text-muted-foreground'
                            )}>
                              {targetPoolPhase}
                            </span>
                          </div>
                          <div className="mt-2 h-2 overflow-hidden rounded-full bg-secondary">
                            <div
                              className={cn(
                                'h-full rounded-full transition-all duration-500',
                                targetPoolBusy
                                  ? 'animate-pulse bg-gradient-to-r from-info via-primary to-info'
                                  : 'bg-muted-foreground/30'
                              )}
                              style={{ width: `${targetPoolProgressPercent}%` }}
                            />
                          </div>
                          <div className="mt-2 flex items-center justify-between gap-3 text-[10px] font-bold uppercase tracking-[0.1em] text-muted-foreground">
                            <span className="truncate">{targetPoolStageLabel}</span>
                            <span className="shrink-0 font-mono">
                              {targetPoolProgress.checked || 0}/{targetPoolProgress.generated || 0}
                              {targetPoolProgress.target ? ` · ${targetPoolProgress.accepted || 0}/${targetPoolProgress.target}` : ''}
                            </span>
                          </div>
                        </div>
                        {targetPoolStatus?.last_error && (
                          <p className="mt-2 text-xs font-bold leading-5 text-danger">
                            {targetPoolStatus.last_error}
                          </p>
                        )}
                        <button
                          type="button"
                          onClick={toggleTargetPool}
                          disabled={targetPoolLoading || (!targetPoolStatus?.active && parseTargetPrefixes(ipRoyalOptions.target_ip_prefixes).length === 0)}
                          className={cn(
                            'mt-3 flex w-full items-center justify-center gap-2 rounded-xl border px-4 py-2.5 text-sm font-extrabold transition',
                            targetPoolStatus?.active
                              ? 'border-danger/35 bg-danger/10 text-danger hover:bg-danger/15'
                              : 'border-primary/35 bg-primary/15 text-primary hover:bg-primary/20',
                            targetPoolLoading && 'cursor-not-allowed opacity-60'
                          )}
                        >
                          {targetPoolStatus?.active ? <X className="h-4 w-4" /> : <Zap className="h-4 w-4" />}
                          {targetPoolLoading
                            ? 'Updating automation'
                            : targetPoolStatus?.active
                              ? 'Stop target pool'
                              : 'Start target pool'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                <button
                  type="button"
                  onClick={handleIPRoyalCheck}
                  disabled={loading}
                  className="secondary-action mt-4 flex w-full items-center justify-center gap-2"
                >
                  <CloudDownload className="h-4 w-4" />
                  IPRoyal auto scan
                </button>
              </div>

              {preparedScanDiagnostics && (
                <div
                  className="mt-5 rounded-2xl border border-border bg-card/75 p-4"
                  data-testid="scan-diagnostics-panel"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-xs font-extrabold uppercase tracking-[0.18em] text-primary">
                        Scan diagnostics
                      </p>
                      <h4 className="mt-1 text-base font-extrabold">Raw filter evidence</h4>
                    </div>
                    <Monitor className="h-5 w-5 text-info" />
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">
                    Successful exits before clean/mobile/state filtering. Proxy credentials stay server-side.
                  </p>

                  <div className="mt-4 grid grid-cols-2 gap-2">
                    {preparedScanDiagnostics.summary.map(item => (
                      <div key={item.label} className="rounded-xl border border-border bg-secondary/55 px-3 py-2">
                        <p className="text-[10px] font-extrabold uppercase tracking-[0.14em] text-muted-foreground">
                          {item.label}
                        </p>
                        <p className="mt-1 font-mono text-lg font-extrabold text-foreground">
                          {item.value}
                        </p>
                      </div>
                    ))}
                  </div>

                  <div className="mt-4">
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <p className="text-[10px] font-extrabold uppercase tracking-[0.16em] text-muted-foreground">
                        Raw successful locations
                      </p>
                      <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                        Top {preparedScanDiagnostics.locations.length}
                      </span>
                    </div>
                    <div className="space-y-2">
                      {preparedScanDiagnostics.locations.length > 0 ? (
                        preparedScanDiagnostics.locations.map(location => (
                          <div key={location.label} className="rounded-xl border border-border/80 bg-secondary/45 p-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="truncate text-sm font-extrabold text-foreground" title={location.label}>
                                  {location.label}
                                </p>
                                <p className="mt-1 text-[11px] font-semibold text-muted-foreground">
                                  {location.sourceLabel}
                                </p>
                              </div>
                              <span className="shrink-0 font-mono text-sm font-extrabold text-primary">
                                {location.countLabel}
                              </span>
                            </div>
                            <p className="mt-2 text-[11px] font-bold uppercase tracking-[0.08em] text-muted-foreground">
                              Accepted {location.acceptedCount} · Rejected {location.rejectedCount}
                            </p>
                            {location.rejectedCount > 0 && (
                              <p className="mt-1 text-[11px] font-semibold text-warning">
                                {location.rejectionText}
                              </p>
                            )}
                          </div>
                        ))
                      ) : (
                        <p className="rounded-xl border border-dashed border-border p-3 text-xs font-semibold text-muted-foreground">
                          No successful locations were returned by the scan.
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="mt-4">
                    <p className="mb-2 text-[10px] font-extrabold uppercase tracking-[0.16em] text-muted-foreground">
                      Rejected before table
                    </p>
                    <div className="space-y-2">
                      {preparedScanDiagnostics.rejectionReasons.length > 0 ? (
                        preparedScanDiagnostics.rejectionReasons.map(reason => (
                          <div
                            key={reason.reason}
                            className="flex items-center justify-between gap-3 rounded-xl border border-border/80 bg-secondary/45 px-3 py-2"
                          >
                            <span className="text-xs font-bold text-foreground">{reason.label}</span>
                            <span className="font-mono text-sm font-extrabold text-warning">{reason.countLabel}</span>
                          </div>
                        ))
                      ) : (
                        <p className="rounded-xl border border-dashed border-border p-3 text-xs font-semibold text-muted-foreground">
                          No rejected proxies in the last auto scan.
                        </p>
                      )}
                    </div>
                  </div>
                </div>
              )}

              <div className="mt-5 space-y-3 border-t border-border pt-5">
                {error && (
                  <div className="flex items-start justify-between gap-3 rounded-2xl border border-destructive/20 bg-destructive/10 p-4 text-sm font-semibold text-destructive" role="alert">
                    <div className="flex gap-2">
                      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                      <span>{error}</span>
                    </div>
                    <button type="button" onClick={clearError} className="rounded-lg p-1 hover:bg-destructive/10" aria-label="Dismiss error">
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                )}

                {loading ? (
                  <div className="space-y-3">
                    <ProgressBar completed={progress.completed} total={progress.total} duration={progress.duration} />
                    <button
                      type="button"
                      onClick={cancelCheck}
                      className="danger-action flex w-full items-center justify-center gap-2"
                    >
                      Cancel check
                    </button>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        onClick={() => {
                          const cleanIps = proxies
                            .filter(p => p.status === 'success' && p.risk_level === 'CLEAN')
                            .map(p => p.query || p.ip || '')
                            .filter(Boolean)
                            .join('\n');
                          if (cleanIps) {
                            navigator.clipboard.writeText(cleanIps);
                            setToast({ message: `Copied ${cleanIps.split('\n').length} clean IPs to clipboard`, type: 'success' });
                          }
                        }}
                        disabled={loading || proxies.filter(p => p.status === 'success' && p.risk_level === 'CLEAN').length === 0}
                        className="secondary-action flex items-center justify-center gap-2"
                        title="Copy clean IPs"
                      >
                        <Clipboard className="h-4 w-4" />
                        Copy
                      </button>
                      <button
                        type="button"
                        onClick={() => { setProxies([]); setScanDiagnostics(null); setCustomProxyInput(''); }}
                        disabled={loading || (proxies.length === 0 && !customProxyInput.trim() && !preparedScanDiagnostics)}
                        className="danger-action flex items-center justify-center gap-2"
                        title="Clear results and input"
                      >
                        <Trash2 className="h-4 w-4" />
                        Clear
                      </button>
                    </div>
                    <button
                      type="button"
                      onClick={handleCheck}
                      disabled={loading || !customProxyInput.trim()}
                      className="primary-action flex w-full items-center justify-center gap-2"
                    >
                      <Play className="h-4 w-4" />
                      Analyze list
                    </button>
                    <p className="text-center text-xs font-semibold text-muted-foreground">
                      Results stream as each proxy resolves.
                    </p>
                  </div>
                )}
              </div>
            </section>

            {ipChanges.length > 0 && (
              <section className="dashboard-panel rounded-3xl p-5 animate-in fade-in slide-in-from-top-4 lg:col-start-1">
                <div className="mb-4 flex items-center justify-between">
                  <h3 className="flex items-center gap-2 text-lg font-extrabold">
                    <History className="h-5 w-5 text-primary" />
                    IP change history
                  </h3>
                  <span className="rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-xs font-bold text-primary">
                    {ipChanges.length} captured
                  </span>
                </div>

                <div className="max-h-[300px] space-y-3 overflow-y-auto pr-2">
                  {ipChanges.map(change => (
                    <div key={change.id} className="rounded-2xl border border-border bg-secondary/55 p-3 text-sm">
                      <div className="flex justify-between gap-3 text-xs">
                        <span className="truncate font-mono text-muted-foreground">{change.session}</span>
                        <span className="font-semibold text-primary">{change.time}</span>
                      </div>
                      <div className="mt-2 flex items-center justify-between gap-2 font-mono">
                        <span className="truncate text-destructive line-through" title={change.oldIp}>{change.oldIp}</span>
                        <ArrowUpDown className="h-3 w-3 shrink-0 rotate-90 text-muted-foreground" />
                        <span className="truncate font-bold text-primary" title={change.newIp}>{change.newIp}</span>
                      </div>
                      <div className="mt-2 text-right text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                        {change.newRegion || 'Unknown'} / {change.city}
                        {change.expectedLifetimeHours && (
                          <span className="ml-2 text-primary">
                            {formatHours((change.elapsedSeconds || 0) / 3600)} / {formatHours(change.expectedLifetimeHours)} ({formatPercent(change.lifetimeProgress)})
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>

                <button
                  type="button"
                  onClick={() => setIpChanges([])}
                  className="danger-action mt-4 flex w-full items-center justify-center gap-2 text-sm"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  Clear history
                </button>
              </section>
            )}

            <section className="dashboard-panel rounded-3xl p-5 lg:absolute lg:left-[calc(390px+1.5rem)] lg:right-0 lg:top-[760px] lg:z-10 2xl:left-[calc(420px+1.5rem)]" data-testid="tracking-ledger">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-extrabold uppercase tracking-[0.18em] text-primary">Tracking ledger</p>
                  <h3 className="mt-1 text-lg font-extrabold">Active and historical proxies</h3>
                </div>
                <span className="rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-xs font-bold text-primary">
                  {trackedSessionIds.length} active
                </span>
              </div>

              <div className="relative">
                <div
                  ref={activeTrackingListRef}
                  data-testid="active-tracking-list"
                  className={cn(
                    'space-y-3 pr-1',
                    activeTrackedSessions.length > 2 && 'max-h-[360px] overflow-y-auto pr-9'
                  )}
                >
                  {activeTrackedSessions.length > 0 ? (
                    activeTrackedSessions.map(session => {
                      const latestIp = session.last_ip || session.latest_ip;
                      const latestRegion = session.last_region || session.latest_region;
                      const latestCity = session.last_city || session.latest_city;
                      return (
                        <div key={session.run_id || session.session} className="rounded-2xl border border-primary/20 bg-primary/5 p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1 pr-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="status-dot mt-1 h-2 w-2 shrink-0" />
                                <span className="break-all font-mono text-sm font-extrabold">{session.session}</span>
                                <span className="rounded-full bg-primary/10 px-2 py-0.5 font-mono text-[10px] font-bold text-primary">
                                  {latestIp || 'IP pending'}
                                </span>
                              </div>
                              <p className="mt-1 break-all font-mono text-[11px] leading-5 text-muted-foreground" title={session.proxy}>
                                {session.proxy}
                              </p>
                            </div>
                            <button
                              type="button"
                              onClick={() => stopTracking(session.session)}
                              disabled={stoppingSession === session.session}
                              className="danger-action shrink-0 px-3 py-2 text-xs"
                            >
                              {stoppingSession === session.session ? 'Stopping' : 'Stop'}
                            </button>
                          </div>
                          <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                            <div className="rounded-xl bg-card/70 p-2">
                              <div className="font-bold uppercase tracking-widest">Started</div>
                              <div className="mt-1 font-semibold text-foreground">{formatTimestamp(session.started_at)}</div>
                            </div>
                            <div className="rounded-xl bg-card/70 p-2">
                              <div className="font-bold uppercase tracking-widest">Latest signal</div>
                              <div className="mt-1 break-all font-semibold text-foreground">{latestIp || 'Pending first check'}</div>
                              <div className="break-words leading-5">{formatLocation(latestRegion, latestCity)}</div>
                            </div>
                          </div>
                        </div>
                      );
                    })
                  ) : (
                    <div className="rounded-2xl border border-dashed border-border bg-secondary/55 p-4 text-sm text-muted-foreground">
                      No active tracked proxies. Use the Track action in the evidence table to persist a proxy run.
                    </div>
                  )}
                </div>
                <ScrollJumpRail
                  label="active tracked proxy"
                  show={activeTrackedSessions.length > 2}
                  onTop={() => scrollTrackingList(activeTrackingListRef, 'top')}
                  onBottom={() => scrollTrackingList(activeTrackingListRef, 'bottom')}
                />
              </div>

              <div className="mt-5 border-t border-border pt-4">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="text-[10px] font-extrabold uppercase tracking-widest text-muted-foreground">Stopped tracking history</div>
                  <button
                    type="button"
                    onClick={fetchTrackingInsights}
                    disabled={trackingInsightsLoading}
                    className="secondary-action px-3 py-2 text-xs"
                  >
                    {trackingInsightsLoading ? 'Refreshing' : 'Refresh'}
                  </button>
                </div>
                <div className="relative">
                  <div
                    ref={stoppedTrackingListRef}
                    data-testid="stopped-tracking-list"
                    className={cn(
                      'space-y-2 pr-1',
                      stoppedTrackingRuns.length > 3 && 'max-h-[560px] overflow-y-auto pr-9'
                    )}
                  >
                    {stoppedTrackingRuns.length > 0 ? (
                      stoppedTrackingRuns.map(run => (
                        <div key={run.run_id} className="rounded-2xl border border-border bg-card p-3">
                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0 flex-1 pr-1">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="break-all font-mono text-sm font-extrabold">{run.session}</span>
                                <span className="rounded-full bg-secondary px-2 py-0.5 font-mono text-[10px] font-bold text-primary">
                                  {run.first_ip || 'Original IP pending'}
                                </span>
                              </div>
                              <div className="mt-1 break-all font-mono text-[11px] leading-5 text-muted-foreground" title={run.proxy}>
                                {run.proxy}
                              </div>
                            </div>
                            <div className="flex shrink-0 items-center gap-2">
                              <button
                                type="button"
                                onClick={() => retrackTrackingRun(run.run_id)}
                                disabled={retrackingRunId === run.run_id}
                                className="secondary-action px-3 py-2 text-xs"
                                title={`Re-track historical run ${run.session}`}
                              >
                                {retrackingRunId === run.run_id ? 'Starting' : 'Re-track'}
                              </button>
                              <button
                                type="button"
                                onClick={() => loadTrackingRunDetails(run.run_id)}
                                className="secondary-action px-3 py-2 text-xs"
                              >
                                {selectedTrackingRunId === run.run_id ? 'Hide' : 'Details'}
                              </button>
                              <button
                                type="button"
                                onClick={() => deleteTrackingRun(run.run_id)}
                                disabled={deletingRunId === run.run_id || retrackingRunId === run.run_id}
                                className="flex h-8 w-8 items-center justify-center rounded-full border-0 text-destructive/70 transition hover:bg-destructive/10 hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-destructive/40 disabled:pointer-events-none disabled:opacity-50"
                                title={`Delete historical run ${run.session}`}
                                aria-label={`Delete historical run ${run.session}`}
                              >
                                {deletingRunId === run.run_id ? (
                                  <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <Trash2 className="h-3.5 w-3.5" />
                                )}
                              </button>
                            </div>
                          </div>
                          <div className="mt-3 grid grid-cols-2 gap-2 text-[11px] text-muted-foreground">
                            <div>
                              <span className="font-bold text-foreground">{formatTimestamp(run.started_at)}</span>
                              <span> start</span>
                            </div>
                            <div className="text-right">
                              <span className="font-bold text-foreground">{formatTimestamp(run.ended_at)}</span>
                              <span> stop</span>
                            </div>
                            <div className="col-span-2 break-words leading-5">
                              {formatLocation(run.first_region, run.first_city)} → {formatLocation(run.latest_region, run.latest_city)}
                            </div>
                            <div className="col-span-2 break-all font-mono text-[11px] font-semibold leading-5 text-primary">
                              {formatIpTransition(run.first_ip, run.latest_ip)}
                            </div>
                            <div className="col-span-2 break-words font-bold uppercase tracking-wider">
                              {run.observation_count || 0} checks · {run.change_count || 0} changes · stable {formatHours(((run.first_change_elapsed_seconds || (run.ended_at - run.started_at) || 0) / 3600))}
                            </div>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="rounded-2xl border border-dashed border-border bg-secondary/55 p-4 text-sm text-muted-foreground">
                        Stopped proxy runs will appear here with their start, change, and stop evidence.
                      </div>
                    )}
                  </div>
                  <ScrollJumpRail
                    label="stopped tracking run"
                    show={stoppedTrackingRuns.length > 3}
                    onTop={() => scrollTrackingList(stoppedTrackingListRef, 'top')}
                    onBottom={() => scrollTrackingList(stoppedTrackingListRef, 'bottom')}
                  />
                </div>

                {selectedTrackingRunId && (
                  <div className="mt-4 rounded-2xl border border-border bg-secondary/45 p-3">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div className="text-[10px] font-extrabold uppercase tracking-widest text-muted-foreground">Observation timeline</div>
                      {trackingRunDetailsLoading && <RefreshCw className="h-4 w-4 animate-spin text-primary" />}
                    </div>
                    <div className="max-h-[340px] space-y-2 overflow-y-auto pr-1">
                      {(trackingRunDetails?.observations || []).map(observation => {
                        const changed = observation.changed_ip || observation.changed_location;
                        return (
                          <div key={observation.id} className="rounded-xl bg-card px-3 py-2 text-[11px]">
                            <div className="flex items-center justify-between gap-3">
                              <span className="font-semibold text-foreground">{formatTimestamp(observation.checked_at)}</span>
                              <span className={changed ? 'font-bold text-destructive' : 'font-bold text-primary'}>
                                {changed ? 'changed' : 'stable'}
                              </span>
                            </div>
                            <div className="mt-1 font-mono text-muted-foreground">
                              {observation.old_ip ? `${observation.old_ip} → ` : ''}{observation.ip || 'No IP'}
                            </div>
                            <div className="mt-1 text-muted-foreground">
                              {formatLocation(observation.region, observation.city)} · {observation.isp || 'Unknown ISP'} · {formatGeoSourceLabel(observation.geo_source)} · {formatHours((observation.elapsed_seconds || 0) / 3600)}
                            </div>
                          </div>
                        );
                      })}
                      {!trackingRunDetailsLoading && (trackingRunDetails?.observations || []).length === 0 && (
                        <div className="rounded-xl border border-dashed border-border p-3 text-sm text-muted-foreground">
                          No observations recorded for this run yet.
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </section>

            <section className="dashboard-panel rounded-3xl p-5 lg:col-start-1" data-testid="stability-intelligence">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <p className="text-xs font-extrabold uppercase tracking-[0.18em] text-primary">Stability intelligence</p>
                  <h3 className="mt-1 text-lg font-extrabold">Cohort learning</h3>
                </div>
                <button
                  type="button"
                  onClick={fetchTrackingInsights}
                  disabled={trackingInsightsLoading}
                  className="secondary-action px-3 py-2 text-xs"
                >
                  {trackingInsightsLoading ? 'Refreshing' : 'Refresh'}
                </button>
              </div>

              <div className="mb-4 grid grid-cols-3 gap-2">
                <div className="panel-subtle rounded-2xl p-3">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Runs</div>
                  <div className="text-xl font-extrabold">{trackingAnalytics?.totals?.runs || 0}</div>
                </div>
                <div className="panel-subtle rounded-2xl p-3">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Checks</div>
                  <div className="text-xl font-extrabold">{trackingAnalytics?.totals?.observations || 0}</div>
                </div>
                <div className="panel-subtle rounded-2xl p-3">
                  <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Changes</div>
                  <div className="text-xl font-extrabold">{trackingAnalytics?.totals?.changes || 0}</div>
                </div>
              </div>

              <div className="space-y-3">
                {stabilityGroups.slice(0, 4).map((group, index) => (
                  <div key={`${group.expected_state_slug || 'unknown'}-${group.expected_lifetime_hours || 'any'}-${index}`} className="rounded-2xl border border-border bg-card p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <div className="text-sm font-extrabold">{formatCohortLabel(group)}</div>
                        <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                          {formatCohortScope(group)} · lifetime {formatHours(group.expected_lifetime_hours)} · {formatCountLabel(group.runs, 'run')}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-sm font-extrabold text-primary">{formatHours(group.max_stable_hours)}</div>
                        <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Best</div>
                      </div>
                    </div>
                    <div className="mt-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                      Change rate {formatPercent(group.change_rate)} · Avg first change {formatHours(group.avg_first_change_hours)}
                    </div>
                  </div>
                ))}
                {stabilityGroups.length === 0 && (
                  <div className="rounded-2xl border border-dashed border-border bg-secondary/55 p-4 text-sm text-muted-foreground">
                    Track a proxy to start building state and sticky-hour reliability data.
                  </div>
                )}
              </div>

              {trackingLogs.length > 0 && (
                <div className="mt-4 space-y-2 border-t border-border pt-4">
                  <div className="text-[10px] font-extrabold uppercase tracking-widest text-muted-foreground">Recent observations</div>
                  {trackingLogs.slice(0, 5).map(log => {
                    const onlineSource = isOnlineGeoSource(log.geo_source);
                    return (
                      <div
                        key={log.id}
                        className="grid grid-cols-[4.75rem_minmax(0,1fr)_auto] items-start gap-2 rounded-xl bg-secondary/55 px-3 py-2 text-[11px] text-muted-foreground"
                        title={`${formatObservationTimestamp(log.checked_at)} · ${formatGeoSourceLabel(log.geo_source)}`}
                      >
                        <span className="truncate font-mono">{log.session}</span>
                        <span className="min-w-0">
                          <span className="block truncate font-semibold text-foreground">
                            {formatLocation(log.region, log.city)}
                          </span>
                          <span className="mt-0.5 block leading-4">
                            {formatObservationTimestamp(log.checked_at)}
                          </span>
                          <span
                            className={cn(
                              'mt-0.5 block font-bold',
                              onlineSource ? 'text-primary' : 'text-warning'
                            )}
                          >
                            {formatGeoSourceLabel(log.geo_source)}
                          </span>
                        </span>
                        <span className={log.stable ? 'font-bold text-primary' : 'font-bold text-destructive'}>
                          {log.stable ? 'stable' : 'changed'}
                        </span>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            <section className="dashboard-panel rounded-3xl p-5 lg:col-start-1">
              <p className="text-xs font-extrabold uppercase tracking-[0.18em] text-primary">Product backlog</p>
              <h3 className="mt-1 text-lg font-extrabold">Next practical features</h3>
              <div className="mt-4 space-y-3">
                {roadmapIdeas.map((idea) => (
                  <div key={idea} className="flex gap-3 rounded-2xl border border-border bg-card p-3 text-sm text-muted-foreground">
                    <Star className="mt-0.5 h-4 w-4 shrink-0 text-accent-foreground" />
                    <span>{idea}</span>
                  </div>
                ))}
              </div>
            </section>
          </aside>

          <section className="dashboard-panel flex min-h-[760px] flex-col overflow-hidden rounded-3xl lg:col-start-2 lg:row-start-1 lg:h-[760px]" data-testid="results-panel">
            <div className="border-b border-border bg-card/70 p-5">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <p className="text-xs font-extrabold uppercase tracking-[0.2em] text-primary">Verification results</p>
                  <h3 className="mt-1 text-2xl font-extrabold tracking-tight">Proxy evidence table</h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Showing clean mobile matches returned by the current scan.
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={handleCheck}
                    disabled={!canRefreshCurrentList}
                    className="secondary-action flex items-center gap-2 px-3 py-2 text-sm"
                    title="Re-run the current proxy list"
                    aria-label="Refresh current proxy list"
                  >
                    <RefreshCw className={cn('h-4 w-4', loading && 'animate-spin')} />
                    {loading ? 'Refreshing' : 'Refresh list'}
                  </button>
                  <label className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-sm font-bold">
                    Protocol
                    <select
                      aria-label="Protocol"
                      value={protocol}
                      onChange={(e) => setProtocol(e.target.value)}
                      className="bg-transparent text-sm font-extrabold outline-none"
                    >
                      <option value="http">HTTP/S</option>
                      <option value="socks4">SOCKS4</option>
                      <option value="socks5">SOCKS5</option>
                    </select>
                  </label>
                  <div className="rounded-xl border border-border bg-secondary/70 px-3 py-2 text-sm font-bold text-muted-foreground">
                    Sorted by {sortConfig.column || 'target fit'}
                  </div>
                </div>
              </div>
            </div>

            {sortedProxies.length === 0 ? (
              <div className="flex flex-1 items-center justify-center px-6 py-20 text-center">
                <div className="mx-auto flex max-w-md flex-col items-center">
                  <div className="relative h-32 w-full max-w-[280px] overflow-hidden rounded-[1.5rem] bg-transparent shadow-[0_24px_70px_rgba(0,0,0,0.18)]">
                    <img
                      src={proxySentinelHero}
                      alt=""
                      aria-hidden="true"
                      className="h-full w-full object-cover opacity-90"
                    />
                    <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,transparent_38%,hsl(var(--card)/0.76)_100%)]" />
                    <div className="absolute inset-0 bg-gradient-to-t from-card/90 via-card/20 to-transparent" />
                    <div className="absolute bottom-3 left-3 flex items-center gap-2 rounded-full bg-card/80 px-3 py-1.5 text-xs font-extrabold text-primary shadow-[0_10px_30px_rgba(0,0,0,0.18)] backdrop-blur-md">
                      <ShieldCheck className="h-3.5 w-3.5" />
                      Ready for verification
                    </div>
                  </div>
                  <h4 className="mt-5 text-lg font-extrabold">No verified proxies yet</h4>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    {loading && progress.total > 0
                      ? `Starting check for ${progress.total} proxies...`
                      : parsedProxies.length > 0
                        ? `${parsedProxies.length} proxies are ready. Start analysis to stream results here.`
                        : 'Paste a proxy list or run IPRoyal auto scan to begin.'}
                  </p>
                </div>
              </div>
            ) : (
              <div className="flex-1 overflow-auto">
                <table className="w-full min-w-[1180px] text-left text-sm">
                  <thead className="border-b border-border bg-secondary/70 text-[10px] font-extrabold uppercase tracking-[0.18em] text-muted-foreground">
                    <tr>
                      <th className="px-5 py-4">Session</th>
                      <th className="px-5 py-4">
                        <button type="button" onClick={() => handleSort('proxy')} className="flex items-center gap-1 hover:text-primary">
                          Input proxy
                          <SortIndicator column="proxy" />
                        </button>
                      </th>
                      <th className="px-5 py-4">
                        <button type="button" onClick={() => handleSort('ip')} className="flex items-center gap-1 hover:text-primary">
                          Resolved IP
                          <SortIndicator column="ip" />
                        </button>
                      </th>
                      <th className="px-5 py-4">Protocol</th>
                      <th className="px-5 py-4">Geo state</th>
                      <th className="px-5 py-4">
                        <button type="button" onClick={() => handleSort('isp')} className="flex items-center gap-1 hover:text-primary">
                          ISP / carrier
                          <SortIndicator column="isp" />
                        </button>
                      </th>
                      <th className="px-5 py-4 text-center">
                        <button
                          type="button"
                          onClick={() => handleSort('latency')}
                          className="mx-auto flex items-center gap-1 hover:text-primary"
                          title="Proxy-use latency measured before DB-IP/BrowserLeaks/MMDB/risk annotation"
                        >
                          Latency
                          <SortIndicator column="latency" />
                        </button>
                      </th>
                      <th className="px-5 py-4 text-center">
                        <button type="button" onClick={() => handleSort('mobile')} className="mx-auto flex items-center gap-1 hover:text-primary">
                          Mobile
                          <SortIndicator column="mobile" />
                        </button>
                      </th>
                      <th className="px-5 py-4 text-center">
                        <button type="button" onClick={() => handleSort('risk')} className="mx-auto flex items-center gap-1 hover:text-primary">
                          Risk
                          <SortIndicator column="risk" />
                        </button>
                      </th>
                      <th className="px-5 py-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sortedProxies.map((proxy, index) => (
                      <tr
                        key={proxy.session || `proxy-${index}`}
                        className={cn(
                          'table-row group',
                          proxy.status !== 'success' && 'opacity-60',
                          isTargetProxy(proxy) && 'bg-primary/5'
                        )}
                      >
                        <td className="px-5 py-4">
                          <div className="flex items-center gap-2 font-mono text-xs text-muted-foreground">
                            {isTargetProxy(proxy) && <Star className="h-4 w-4 fill-primary text-primary" title="Target match" />}
                            <span>{proxy.session || 'N/A'}</span>
                          </div>
                        </td>
                        <td
                          className="max-w-[190px] truncate px-5 py-4 font-mono text-xs text-muted-foreground"
                          title={proxy.proxy_display || proxy.input_proxy || (typeof proxy.proxy === 'string' ? proxy.proxy : '')}
                        >
                          {proxy.proxy_display || proxy.input_proxy || (typeof proxy.proxy === 'string' ? proxy.proxy : '')}
                        </td>
                        <td className="px-5 py-4 font-mono text-sm">
                          {proxy.status === 'success' ? (
                            <div className="flex items-center gap-2">
                              <span className={isTargetProxy(proxy) ? 'font-extrabold text-primary' : 'font-semibold text-foreground'}>
                                {proxy.query || proxy.ip || ''}
                              </span>
                              {proxy.mobile && <Monitor className="h-3.5 w-3.5 text-muted-foreground" title="Mobile connection detected" />}
                            </div>
                          ) : (
                            <span className="font-bold text-destructive">Failed</span>
                          )}
                        </td>
                        <td className="px-5 py-4">
                          <span className="rounded-full border border-border bg-secondary px-2.5 py-1 text-xs font-extrabold uppercase tracking-wider text-muted-foreground">
                            {proxy.protocol || 'http'}
                          </span>
                        </td>
                        <td className="px-5 py-4">
                          <div className="font-semibold text-foreground">
                            {proxy.local_region || proxy.regionName || proxy.region || 'Unknown'}
                            <span className="ml-1 text-xs font-medium text-muted-foreground">({proxy.local_city || proxy.city || 'Unknown'})</span>
                          </div>
                          {proxy.geo_source && (
                            <div className="mt-1 flex flex-wrap gap-1.5">
                              <span
                                className="inline-flex rounded-full border border-info/20 bg-info/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-info"
                                title={proxy.geo_provider || proxy.geo_source}
                              >
                                {proxy.geo_source}
                              </span>
                              {proxy.geo_confirmation_pending && (
                                <span
                                  className="inline-flex items-center gap-1 rounded-full border border-warning/25 bg-warning/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest text-warning"
                                  title="Bulk scan used local MMDB as a last-resort display fallback. Re-check or track this proxy for DB-IP/BrowserLeaks online confirmation."
                                >
                                  <AlertTriangle className="h-3 w-3" />
                                  Online geo pending
                                </span>
                              )}
                            </div>
                          )}
                        </td>
                        <td className="max-w-[240px] truncate px-5 py-4 text-sm font-semibold text-muted-foreground" title={proxy.isp}>
                          {proxy.isp || 'N/A'}
                        </td>
                        <td
                          className="px-5 py-4 text-center font-mono text-sm font-bold text-foreground"
                          title={
                            proxy.check_duration_ms
                              ? `Proxy-use latency; full check ${formatProxyLatency({ latency_ms: proxy.check_duration_ms })}`
                              : 'Proxy-use latency'
                          }
                        >
                          {formatProxyLatency(proxy)}
                        </td>
                        <td className="px-5 py-4 text-center">
                          {proxy.mobile ? (
                            <span className="inline-flex items-center rounded-full border border-primary/20 bg-primary/10 px-2.5 py-1 text-xs font-bold text-primary">
                              Mobile
                            </span>
                          ) : (
                            <span className="inline-flex items-center rounded-full border border-border bg-secondary px-2.5 py-1 text-xs font-bold text-muted-foreground">
                              Fixed
                            </span>
                          )}
                        </td>
                        <td className="px-5 py-4">
                          <div className="flex justify-center">
                            <RiskBadge
                              clean={proxy.status === 'success' && proxy.risk_level === 'CLEAN'}
                              failed={proxy.status !== 'success'}
                            />
                          </div>
                        </td>
                        <td className="px-5 py-4 text-right">
                          {proxy.session && proxy.session !== 'N/A' ? (
                            <button
                              type="button"
                              onClick={() => {
                                const proxyStr = sessionProxyMap[proxy.session];
                                startTracking(proxy.session, proxyStr, proxy.proxy_id);
                              }}
                              disabled={trackedSessionSet.has(proxy.session)}
                              className={cn(
                                'rounded-full border px-3 py-1.5 text-[10px] font-extrabold uppercase tracking-widest transition',
                                trackedSessionSet.has(proxy.session)
                                  ? 'cursor-default border-primary/30 bg-primary/10 text-primary'
                                  : 'border-border bg-card text-muted-foreground hover:border-primary/30 hover:text-primary'
                              )}
                            >
                              {trackedSessionSet.has(proxy.session) ? (
                                <span className="flex items-center gap-1.5">
                                  <RefreshCw className="h-3 w-3 animate-spin" /> Tracking
                                </span>
                              ) : 'Track'}
                            </button>
                          ) : (
                            <button type="button" className="rounded-lg p-1.5 text-muted-foreground opacity-0 transition hover:bg-secondary hover:text-foreground group-hover:opacity-100" aria-label="More actions">
                              <MoreVertical className="h-5 w-5" />
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="flex flex-col gap-2 border-t border-border bg-card/70 p-5 text-xs font-bold uppercase tracking-[0.14em] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
              <span>API: {API_BASE_URL}</span>
              <span>{sortedProxies.length} visible results</span>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

export default App;
