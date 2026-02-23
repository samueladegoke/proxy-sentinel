import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import {
  CheckCircle2, AlertTriangle, ShieldCheck, Play, Monitor, Search, RefreshCw,
  X, Info, ChevronUp, ChevronDown, ArrowUpDown, Clipboard, Trash2, Bell,
  BellOff, Settings, Volume2, VolumeX, Zap, Star, History
} from 'lucide-react'
import { cn } from './lib/utils'
import { soundNotifier } from './lib/sound'
import { Toast } from './components/Toast'
import { ProgressBar } from './components/ProgressBar'
import { SettingsPanel } from './components/SettingsPanel'
import { StatCard } from './components/StatCard'
import { RiskBadge } from './components/RiskBadge'

// Configuration
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const WS_URL = API_BASE_URL.replace('http', 'ws');

/**
 * Custom hook for WebSocket connection
 */
function useWebSocket(onMessage, enabled = true) {
  const wsRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);

  useEffect(() => {
    if (!enabled) return;

    const connect = () => {
      try {
        wsRef.current = new WebSocket(`${WS_URL}/ws/tracking`);

        wsRef.current.onopen = () => {
          // Connected
        };

        wsRef.current.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            onMessage(data);
          } catch {
            // Error parsing message
          }
        };

        wsRef.current.onclose = () => {
          reconnectTimeoutRef.current = setTimeout(connect, 3000);
        };

        wsRef.current.onerror = () => {
          // Error occurred
        };
      } catch {
        reconnectTimeoutRef.current = setTimeout(connect, 3000);
      }
    };

    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [enabled, onMessage]);

  return wsRef;
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
  const [loading, setLoading] = useState(false);
  const [tracking, setTracking] = useState(null);
  const trackingRef = useRef(null); // Keep in sync for websocket handler
  const [lastUpdate, setLastUpdate] = useState(null);
  const [error, setError] = useState(null);
  const [protocol, setProtocol] = useState('http');
  const [ipChanges, setIpChanges] = useState([]);

  // Progress state for streaming
  const [progress, setProgress] = useState({ completed: 0, total: 0, duration: 0 });
  const [checkStartTime, setCheckStartTime] = useState(null);

  // New state for dynamic proxy input
  const [customProxyInput, setCustomProxyInput] = useState('');

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

  // WebSocket ref for streaming
  const checkWsRef = useRef(null);

  // Apply settings to sound notifier
  useEffect(() => {
    soundNotifier.setEnabled(settings.soundEnabled);
    soundNotifier.setVolume(settings.volume);
    soundNotifier.setFrequency(settings.frequency);
  }, [settings]);

  // Keep trackingRef in sync with tracking state
  useEffect(() => {
    trackingRef.current = tracking;
  }, [tracking]);

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

  // WebSocket message handler for tracking
  const handleWebSocketMessage = useCallback((data) => {
    if (data.type === 'tracking_check_complete') {
      setLastUpdate(new Date().toLocaleTimeString());
    } else if (data.type === 'ip_change') {
      // Only filter if we have an active tracking session AND the session doesn't match AND it's not a debug event
      if (trackingRef.current && data.session !== trackingRef.current && data.session !== 'DEBUG_SESSION') {
        return; // Ignore updates for other sessions
      }

      if (settings.soundEnabled) {
        soundNotifier.playAlert();
      }

      if (settings.toastEnabled) {
        setToast({
          message: `IP Changed: ${data.old_ip} → ${data.new_ip}`,
          type: 'warning'
        });
      }

      const now = Date.now();
      const newEntry = {
        id: `${now}-${Math.random()}`,
        session: data.session,
        oldIp: data.old_ip,
        newIp: data.new_ip,
        time: new Date().toLocaleTimeString(),
        city: data.city || 'Unknown',
        _ts: now
      };
      setIpChanges(prev => {
        // Deduplicate: skip if identical event already captured within the last 5 seconds
        const isDuplicate = prev.length > 0 &&
          prev[0].oldIp === newEntry.oldIp &&
          prev[0].newIp === newEntry.newIp &&
          prev[0].session === newEntry.session &&
          (now - prev[0]._ts) < 5000;
        if (isDuplicate) return prev;
        return [newEntry, ...prev].slice(0, 50);
      });
    }
  }, [settings]);

  // WebSocket connection — always open so events are never missed due to race conditions
  useWebSocket(handleWebSocketMessage, true);

  const updateTrackingInterval = useCallback(async (interval) => {
    try {
      await fetch(`${API_BASE_URL}/api/track/config`, {
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
    const total = proxies.length;
    // Clean Mobile = succeeded, marked mobile by carrier, and risk_level is CLEAN
    const clean = proxies.filter(p =>
      p.status === 'success' &&
      p.mobile === true &&
      p.risk_level === 'CLEAN'
    ).length;
    // Risky = any proxy flagged as hosting or proxy (datacenter/VPN)
    const risky = proxies.filter(p =>
      p.status === 'success' && (p.hosting === true || p.proxy === true)
    ).length;
    const failed = proxies.filter(p => p.status !== 'success').length;

    return { total, clean, risky, failed };
  }, [proxies]);

  // Parse proxy input into array
  const parsedProxies = useMemo(() => {
    if (!customProxyInput.trim()) return [];
    return customProxyInput
      .split('\n')
      .map(line => line.trim())
      .filter(line => line && !line.startsWith('#'));
  }, [customProxyInput]);

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
    return [...proxies].sort((a, b) => {
      // 1. Primary sort: Target Match
      const aTarget = isTargetProxy(a) ? 1 : 0;
      const bTarget = isTargetProxy(b) ? 1 : 0;
      if (aTarget !== bTarget) {
        return bTarget - aTarget; // 1 (true) comes before 0 (false)
      }

      // 2. Secondary sort: Selected column
      if (!sortConfig.column) return 0;

      let aVal, bVal;

      switch (sortConfig.column) {
        case 'mobile':
          aVal = a.mobile ? 1 : 0;
          bVal = b.mobile ? 1 : 0;
          break;
        case 'ip': {
          aVal = a.query || '';
          bVal = b.query || '';
          const aParts = aVal.split('.').map(Number);
          const bParts = bVal.split('.').map(Number);
          for (let i = 0; i < 4; i++) {
            if (aParts[i] !== bParts[i]) {
              return (aParts[i] - bParts[i]) * (sortConfig.direction === 'asc' ? 1 : -1);
            }
          }
          return 0;
        }
        case 'risk':
          aVal = (a.hosting || a.proxy) ? 1 : 0;
          bVal = (b.hosting || b.proxy) ? 1 : 0;
          break;
        case 'isp':
          aVal = (a.isp || '').toUpperCase();
          bVal = (b.isp || '').toUpperCase();
          break;
        default:
          return 0;
      }

      if (typeof aVal === 'string') {
        return aVal.localeCompare(bVal) * (sortConfig.direction === 'asc' ? 1 : -1);
      }
      return (aVal - bVal) * (sortConfig.direction === 'asc' ? 1 : -1);
    });
  }, [proxies, sortConfig]);

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

    const inputToUse = customProxyInput;
    if (!inputToUse.trim()) {
      setError('Please enter at least one proxy to check.');
      setLoading(false); // Ensure loading state is reset if validation fails
      return;
    }

    const proxiesToCheck = parsedProxies.length > 0 ? parsedProxies : [];

    setLoading(true);
    setProxies([]);
    setIpChanges([]);
    setProgress({ completed: 0, total: proxiesToCheck.length, duration: 0 });
    setCheckStartTime(Date.now());

    try {
      // Create WebSocket connection for streaming results
      const ws = new WebSocket(`${WS_URL}/ws/check`);

      ws.onopen = () => {
        // Send check request
        ws.send(JSON.stringify({
          proxies: proxiesToCheck,
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
            setError(data.message);
            setLoading(false);
            setCheckStartTime(null);
            ws.close();
            break;
        }
      };

      ws.onerror = () => {
        setError('WebSocket error occurred');
        setLoading(false);
        setCheckStartTime(null);
      };

      ws.onclose = () => {
        setLoading(false);
        setCheckStartTime(null);
      };

      checkWsRef.current = ws;

    } catch (err) {
      setError(err.message || 'Failed to check proxies');
      console.error("Error checking proxies:", err);
      setLoading(false);
      setCheckStartTime(null);
    }
  }, [parsedProxies, protocol, settings.toastEnabled, customProxyInput]);

  // Cancel ongoing check
  const cancelCheck = useCallback(() => {
    if (checkWsRef.current) {
      checkWsRef.current.close();
    }
    setLoading(false);
    setCheckStartTime(null);
  }, []);

  // Start tracking a proxy
  // proxyStr is the full proxy string (host:port:user:pass) - required for custom proxies
  const startTracking = useCallback(async (session, proxyStr) => {
    if (!session || session === 'N/A') {
      setError('Invalid session ID');
      return;
    }

    // Enforce strict single-session tracking: delete the old session from the backend
    if (trackingRef.current && trackingRef.current !== session) {
      try {
        await fetch(`${API_BASE_URL}/api/track/${trackingRef.current}`, { method: 'DELETE' });
      } catch (err) {
        console.error("Error clearing old tracking session:", err);
      }
    }

    setTracking(session);
    setIpChanges([]);

    try {
      // Build payload - include proxyStr so backend can track custom (non-default) proxies
      const payload = { session };
      if (proxyStr) {
        payload.proxy = proxyStr;
      }

      const response = await fetch(`${API_BASE_URL}/api/track`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.message || `Failed to start tracking: ${response.statusText}`);
      }

      await updateTrackingInterval(settings.trackingInterval);

      if (settings.toastEnabled) {
        setToast({ message: `Started tracking: ${session}`, type: 'success' });
      }

    } catch (err) {
      console.error("Error starting tracking:", err);
      setError(err.message);
      setTracking(null);
    }
  }, [settings.trackingInterval, settings.toastEnabled, updateTrackingInterval, trackingRef]);

  // Stop tracking
  const stopTracking = useCallback(async () => {
    if (!tracking) return;

    try {
      await fetch(`${API_BASE_URL}/api/track/${tracking}`, { method: 'DELETE' });
    } catch (err) {
      console.error("Error stopping tracking:", err);
    } finally {
      setTracking(null);
      setIpChanges([]);
    }
  }, [tracking]);

  // Clear error
  const clearError = () => setError(null);

  // Handle settings change
  const handleSettingsChange = useCallback((newSettings) => {
    setSettings(newSettings);
    if (newSettings.trackingInterval !== settings.trackingInterval && tracking) {
      updateTrackingInterval(newSettings.trackingInterval);
    }
  }, [settings.trackingInterval, tracking, updateTrackingInterval]);

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
    <div className="min-h-screen bg-background text-foreground font-display selection:bg-primary/30 pb-20 overflow-x-hidden">
      {/* Toast Notification */}
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}

      {/* Settings Panel */}
      {showSettings && (
        <SettingsPanel
          settings={settings}
          onSettingsChange={handleSettingsChange}
          onClose={() => setShowSettings(false)}
        />
      )}

      {/* Header */}
      <header className="fixed top-0 w-full z-40 glassmorphism border-b border-white/5 px-8 py-4 bg-background/80 backdrop-blur-md">
        <div className="max-w-[1600px] mx-auto flex items-center justify-between">
          <div className="flex items-center gap-6">
            <div className="flex items-center gap-3">
              <ShieldCheck className="w-8 h-8 text-primary" />
              <h1 className="text-xl font-bold tracking-tight uppercase">Proxy Sentinel</h1>
            </div>
            <div className="hidden md:flex items-center gap-2 ml-8 px-3 py-1 bg-primary/10 rounded-full border border-primary/20">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
              </span>
              <span className="text-[10px] font-bold text-primary tracking-widest uppercase">Live System Operational</span>
            </div>
            {tracking && (
              <div
                className="hidden md:flex items-center gap-2 ml-4 px-3 py-1 bg-green-500/10 rounded-full border border-green-500/20 cursor-pointer hover:bg-green-500/20 transition-all"
                onClick={stopTracking}
                title="Click to stop tracking"
              >
                <RefreshCw className="w-3 h-3 text-green-400 animate-spin" />
                <span className="text-[10px] font-bold text-green-400 tracking-widest uppercase">Tracking: {tracking}</span>
                <X className="w-3 h-3 text-green-400" />
              </div>
            )}
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => setShowSettings(true)}
              className="p-2 hover:bg-white/5 rounded-lg transition-all text-slate-400 hover:text-primary"
              title="Notification Settings"
            >
              <Settings className="w-5 h-5" />
            </button>
            <div className="h-8 w-px bg-white/10 mx-2"></div>
            <div className="flex items-center gap-3 bg-white/5 p-1 pr-3 rounded-full border border-white/5">
              <div className="h-7 w-7 rounded-full bg-primary/20 flex items-center justify-center">
                <ShieldCheck className="w-4 h-4 text-primary" />
              </div>
              <span className="text-xs font-bold tracking-tight">ADMIN_ROOT</span>
            </div>
          </div>
        </div>
      </header>

      <main className="pt-28 px-8 max-w-[1600px] mx-auto">
        <div className="mb-12 flex flex-col md:flex-row md:items-end justify-between gap-6">
          <div>
            <h2 className="text-4xl font-bold tracking-tighter mb-2">Operational Overview</h2>
            <p className="text-slate-500 font-medium tracking-wide">Real-time status of your global proxy infrastructure.</p>
          </div>
        </div>

        {/* Global Statistics */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-12">
          <StatCard
            title="Total Proxies"
            value={stats.total}
            icon={<Monitor className="w-8 h-8 text-info" />}
            glowContext="info"
          />
          <StatCard
            title="Clean Mobile IPs"
            value={stats.clean}
            icon={<ShieldCheck className="w-8 h-8 text-primary" />}
            glowContext="primary"
          />
          <StatCard
            title="Risky IPs"
            value={stats.risky}
            icon={<AlertTriangle className="w-8 h-8 text-destructive" />}
            glowContext="danger"
          />
          <StatCard
            title="Last Update"
            value={lastUpdate || "Never"}
            icon={<CheckCircle2 className="w-8 h-8 text-cyan-400" />}
            glowContext="info"
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 items-start">
          {/* Sidebar Input Section */}
          <div className="lg:col-span-1 space-y-6 lg:sticky lg:top-28">
            <div className="glassmorphism p-6 rounded-xl">
              <h4 className="text-lg font-bold mb-4 flex items-center gap-2">
                <Zap className="w-5 h-5 text-primary" />
                Bulk Input
              </h4>
              <textarea
                value={customProxyInput}
                onChange={(e) => setCustomProxyInput(e.target.value)}
                placeholder={`Paste proxy list...

Examples:
192.168.1.1:8080:user:pass
socks5://proxy.example.com:1080`}
                className="w-full h-80 bg-black/40 border-white/10 rounded-lg text-slate-300 font-mono text-sm focus:ring-primary focus:border-primary placeholder:text-slate-700 p-4 resize-none transition-all"
                disabled={loading}
              />
              <div className="p-6 border-t border-white/5 flex flex-col gap-4 mt-4 -mx-6 -mb-6 bg-white/[0.02]">
                {error && (
                  <div className="bg-destructive/10 text-destructive border border-destructive/20 p-4 rounded-lg text-sm flex items-center justify-between font-medium">
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4" />
                      {error}
                    </div>
                    <button onClick={clearError} className="hover:text-white transition-colors">
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                )}

                {loading ? (
                  <div className="flex flex-col gap-3">
                    <ProgressBar completed={progress.completed} total={progress.total} duration={progress.duration} />
                    <button
                      onClick={cancelCheck}
                      className="flex justify-center items-center gap-2 px-6 py-2.5 bg-destructive/10 text-destructive border border-destructive/20 rounded-lg font-medium hover:bg-destructive/20 transition-all shadow-lg"
                    >
                      Cancel Check
                    </button>
                  </div>
                ) : (
                  <div className="flex flex-col gap-3">
                    <div className="flex gap-2 w-full">
                      <button
                        onClick={() => {
                          const cleanIps = proxies
                            .filter(p => p.status === 'success' && p.risk_level === 'CLEAN')
                            .map(p => p.proxy.split(':')[0])
                            .join('\n');
                          if (cleanIps) {
                            navigator.clipboard.writeText(cleanIps);
                            setToast({ message: `Copied ${cleanIps.split('\n').length} clean IPs to clipboard`, type: 'success' });
                          }
                        }}
                        disabled={loading || proxies.filter(p => p.status === 'success' && p.risk_level === 'CLEAN').length === 0}
                        className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-white/10 rounded-lg text-sm font-medium hover:bg-white/20 disabled:opacity-50 transition-colors text-slate-300"
                        title="Copy Clean IPs"
                      >
                        <Clipboard className="w-4 h-4" />
                        Copy
                      </button>
                      <button
                        onClick={() => { setProxies([]); setCustomProxyInput(''); }}
                        disabled={loading || (proxies.length === 0 && !customProxyInput.trim())}
                        className="flex-1 flex items-center justify-center gap-2 bg-destructive/10 text-destructive px-4 py-2 rounded-lg text-sm font-medium hover:bg-destructive/20 disabled:opacity-50 transition-colors"
                        title="Clear Results and Input"
                      >
                        <Trash2 className="w-4 h-4" />
                        Clear
                      </button>
                    </div>
                    <button
                      onClick={handleCheck}
                      disabled={loading || !customProxyInput.trim()}
                      className="w-full flex items-center justify-center gap-2 px-8 py-3 bg-primary text-primary-foreground rounded-lg font-bold tracking-widest uppercase hover:scale-[0.98] transition-all shadow-lg shadow-primary/20 disabled:opacity-50 disabled:hover:scale-100"
                    >
                      <Play className="w-4 h-4" />
                      Analyze & Import
                    </button>
                    <p className="text-xs text-muted-foreground text-center mt-2">
                      Results stream in real-time.
                    </p>
                  </div>
                )}
              </div>
            </div>

            {/* IP Changes History */}
            {ipChanges.length > 0 && (
              <div className="glassmorphism p-6 rounded-xl animate-in fade-in slide-in-from-top-4">
                <div className="flex items-center justify-between mb-4">
                  <h4 className="text-lg font-bold flex items-center gap-2">
                    <History className="w-5 h-5 text-primary" />
                    IP History
                  </h4>
                  <span className="text-xs font-medium text-primary bg-primary/10 px-2 py-1 rounded-full">{ipChanges.length} captured</span>
                </div>

                <div className="space-y-3 max-h-[300px] overflow-y-auto pr-2 custom-scrollbar">
                  {ipChanges.map(change => (
                    <div key={change.id} className="bg-black/40 border border-white/5 rounded-lg p-3 text-sm flex flex-col gap-2 relative group hover:border-primary/50 transition-colors">
                      <div className="flex justify-between items-center text-xs">
                        <span className="text-muted-foreground font-mono">{change.session}</span>
                        <span className="text-primary/70">{change.time}</span>
                      </div>
                      <div className="flex items-center justify-between font-mono gap-2">
                        <span className="text-destructive/80 line-through opacity-70 truncate" title={change.oldIp}>{change.oldIp}</span>
                        <ArrowUpDown className="w-3 h-3 text-muted-foreground rotate-90 shrink-0" />
                        <span className="text-emerald-400 font-bold truncate" title={change.newIp}>{change.newIp}</span>
                      </div>
                      <div className="text-[10px] text-muted-foreground uppercase tracking-wider text-right">
                        {change.city}
                      </div>
                    </div>
                  ))}
                </div>

                <button
                  onClick={() => setIpChanges([])}
                  className="w-full mt-4 flex items-center justify-center gap-2 px-4 py-2 bg-destructive/10 text-destructive border border-destructive/20 rounded-lg text-xs font-medium hover:bg-destructive/20 transition-all"
                >
                  <Trash2 className="w-3 h-3" />
                  Clear History
                </button>
              </div>
            )}
          </div>

          {/* Main Data Table Section */}
          <div className="lg:col-span-3 glassmorphism rounded-xl overflow-hidden min-h-[800px] flex flex-col">
            <div className="p-6 border-b border-white/5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white/[0.01]">
              <div className="flex items-center gap-4">
                <span className="text-sm font-bold tracking-widest uppercase text-slate-400">Live Traffic Logs</span>
                <div className="flex gap-2">
                  <select
                    value={protocol}
                    onChange={(e) => setProtocol(e.target.value)}
                    className="px-3 py-1 bg-black/40 border border-white/10 rounded text-xs font-bold text-slate-300 uppercase tracking-widest focus:ring-primary focus:border-primary"
                  >
                    <option value="http">HTTP/S</option>
                    <option value="socks4">SOCKS4</option>
                    <option value="socks5">SOCKS5</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="overflow-x-auto flex-1">
              <table className="w-full text-sm text-left">
                <thead className="text-[10px] font-bold tracking-[0.2em] uppercase text-slate-500 border-b border-white/5 bg-black/20">
                  <tr>
                    <th className="px-6 py-5">Session</th>
                    <th
                      className="px-6 py-5 cursor-pointer hover:text-primary transition-colors select-none"
                      onClick={() => handleSort('proxy')}
                    >
                      <div className="flex items-center">
                        Input Proxy
                        <SortIndicator column="proxy" />
                      </div>
                    </th>
                    <th
                      className="px-6 py-5 cursor-pointer hover:text-primary transition-colors select-none"
                      onClick={() => handleSort('ip')}
                    >
                      <div className="flex items-center">
                        Resolved IP
                        <SortIndicator column="ip" />
                      </div>
                    </th>
                    <th className="px-6 py-5">Protocol</th>
                    <th className="px-6 py-5">Geo State(City)</th>
                    <th
                      className="px-6 py-5 cursor-pointer hover:text-primary transition-colors select-none"
                      onClick={() => handleSort('isp')}
                    >
                      <div className="flex items-center">
                        ISP / Carrier
                        <SortIndicator column="isp" />
                      </div>
                    </th>
                    <th
                      className="px-6 py-5 text-center cursor-pointer hover:text-primary transition-colors select-none"
                      onClick={() => handleSort('mobile')}
                    >
                      <div className="flex items-center justify-center">
                        Mobile
                        <SortIndicator column="mobile" />
                      </div>
                    </th>
                    <th
                      className="px-6 py-5 text-center cursor-pointer hover:text-primary transition-colors select-none"
                      onClick={() => handleSort('risk')}
                    >
                      <div className="flex items-center justify-center">
                        Risk
                        <SortIndicator column="risk" />
                      </div>
                    </th>
                    <th className="px-6 py-5 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.03]">
                  {sortedProxies.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="px-6 py-12 text-center text-slate-500">
                        <Search className="w-8 h-8 mx-auto mb-3 opacity-50" />
                        {loading && progress.total > 0
                          ? `Starting check for ${progress.total} proxies...`
                          : parsedProxies.length > 0
                            ? `${parsedProxies.length} proxies ready. Click "Analyze & Import" to start scanning.`
                            : 'Paste a proxy list. Click "Analyze & Import" to start.'}
                      </td>
                    </tr>
                  ) : (
                    sortedProxies.map((proxy, index) => (
                      <tr
                        key={proxy.session || `proxy-${index}`}
                        className={cn(
                          "hover:bg-white/[0.02] transition-colors group",
                          proxy.status !== 'success' && "opacity-60",
                          isTargetProxy(proxy) && "bg-primary/5 hover:bg-primary/10"
                        )}
                      >
                        <td className="px-6 py-4 font-mono text-slate-500 flex items-center gap-2">
                          {isTargetProxy(proxy) && <Star className="h-4 w-4 text-primary fill-primary shadow-[0_0_8px_rgba(31,249,118,0.6)]" title="Target Match (Clean Mobile Abuja)" />}
                          {proxy.session || 'N/A'}
                        </td>
                        <td className="px-6 py-4 font-mono text-sm max-w-[150px] truncate" title={proxy.input_proxy || proxy.proxy || ""}>
                          {proxy.input_proxy || proxy.proxy || ""}
                        </td>
                        <td className="px-6 py-4 font-mono text-sm">
                          {proxy.status === 'success' ? (
                            <div className="flex items-center gap-2">
                              <span className={isTargetProxy(proxy) ? "text-primary font-bold" : "text-slate-300"}>
                                {proxy.query || proxy.ip || ""}
                              </span>
                              {proxy.mobile && <Monitor className="w-3 h-3 text-slate-500" title="Mobile Connection detected" />}
                            </div>
                          ) : (
                            <span className="text-destructive font-medium">FAILED</span>
                          )}
                        </td>
                        <td className="px-6 py-4">
                          <span className={cn(
                            "px-2 py-1 rounded text-xs font-bold uppercase tracking-widest",
                            proxy.protocol === 'socks5' && "bg-purple-500/20 text-purple-400",
                            proxy.protocol === 'socks4' && "bg-orange-500/20 text-orange-400",
                            proxy.protocol === 'https' && "bg-primary/20 text-primary",
                            (!proxy.protocol || proxy.protocol === 'http') && "bg-info/20 text-info"
                          )}>
                            {(proxy.protocol || 'http')}
                          </span>
                        </td>
                        <td className={cn(
                          "px-6 py-4 font-medium",
                          (proxy.local_region || proxy.local_city) ? "text-info" : "text-slate-400"
                        )}>
                          {proxy.local_region || proxy.regionName || proxy.region || 'Unknown'} <span className="text-[10px] text-slate-500 ml-1">({proxy.local_city || proxy.city || 'Unknown'})</span>
                        </td>
                        <td className="px-6 py-4 max-w-[200px] truncate text-slate-300" title={proxy.isp}>
                          {proxy.isp || 'N/A'}
                        </td>
                        <td className="px-6 py-4 text-center">
                          {proxy.mobile ? (
                            <span className="inline-flex w-2 h-2 rounded-full bg-primary shadow-[0_0_8px_rgba(31,249,118,0.6)] animate-pulse" />
                          ) : (
                            <span className="inline-flex w-2 h-2 rounded-full bg-slate-700" />
                          )}
                        </td>
                        <td className="px-6 py-4 flex justify-center">
                          <RiskBadge
                            clean={proxy.status === 'success' && proxy.risk_level === 'CLEAN'}
                            failed={proxy.status !== 'success'}
                          />
                        </td>
                        <td className="px-6 py-4 text-right">
                          {proxy.session && proxy.session !== 'N/A' ? (
                            <button
                              onClick={() => {
                                const proxyStr = sessionProxyMap[proxy.session];
                                startTracking(proxy.session, proxyStr);
                              }}
                              disabled={tracking === proxy.session}
                              className={cn(
                                "text-[10px] font-bold uppercase tracking-widest px-3 py-1.5 rounded-full transition-all border",
                                tracking === proxy.session
                                  ? "bg-primary/20 text-primary border-primary/50 cursor-default shadow-[0_0_10px_rgba(31,249,118,0.2)]"
                                  : "bg-white/5 text-slate-400 border-white/10 hover:bg-primary/10 hover:text-primary hover:border-primary/30"
                              )}
                            >
                              {tracking === proxy.session ? (
                                <span className="flex items-center gap-1.5">
                                  <RefreshCw className="w-3 h-3 animate-spin" /> Tracking
                                </span>
                              ) : 'Track'}
                            </button>
                          ) : (
                            <button className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-white transition-all">
                              <MoreVertical className="w-5 h-5" />
                            </button>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            {/* Info Footer */}
            <div className="p-6 border-t border-white/5 flex items-center justify-between text-slate-500 text-xs font-bold tracking-widest uppercase">
              <span>API: {API_BASE_URL}</span>
              <span>Sorted by: {sortConfig.column || 'None'}</span>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
