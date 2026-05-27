# Proxy Sentinel

High-performance async proxy checking tool with real-time progress streaming.

## Features

- **Fast Async Checking**: Check 100+ proxies concurrently with aiohttp
- **Real-time Progress**: WebSocket-based live progress streaming
- **IPRoyal Auto Scan**: Generate residential proxies through IPRoyal's API and return clean mobile results
- **Modern Frontend**: React + Vite + Tailwind CSS
- **FastAPI Backend**: High-performance Python async API

## Project Structure

```
proxy_check/
├── frontend/          # React + Vite frontend
│   ├── src/          # React components
│   ├── public/       # Static assets
│   └── package.json  # Frontend dependencies
├── backend/          # FastAPI backend
│   ├── main.py       # API server
│   ├── proxy_lib_async.py  # Async proxy checker
│   └── requirements.txt
└── README.md
```

## Quick Start

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

### Backend
- `CORS_ORIGINS` - Allowed CORS origins (default: localhost:5173,localhost:5174)
- `MAX_CONCURRENT` - Max concurrent proxy checks (default: 100)
- `PROXY_TIMEOUT` - Timeout per proxy check in seconds (default: 8)
- `IPROYAL_API_TOKEN` - IPRoyal residential proxy API token
- `IPROYAL_SUBUSER_HASH` - IPRoyal subuser hash for proxy generation
- `IPROYAL_USERNAME` / `IPROYAL_PASSWORD` - Alternative to `IPROYAL_SUBUSER_HASH`
- `IPROYAL_LOCATION` - Default IPRoyal location prefix (default: `_country-ng`)
- `IPROYAL_PROXY_COUNT` - Default number of generated proxies (default: 25)
- `IPROYAL_ROTATION` - Default rotation mode: `sticky` or `random` (default: `sticky`)
- `IPROYAL_LIFETIME` - Default sticky session lifetime (default: `2h`)
- `PROXY_SENTINEL_API_TOKEN` - Optional API/WebSocket token for protecting `/api/*`, `/ws/check`, and `/ws/tracking`
- `PROXY_SENTINEL_PROXY_ID_SALT` - Optional salt for stable opaque proxy handles returned to the frontend
- `DBIP_API_KEY` - DB-IP API key for primary IP geolocation (default: `free`)
- `DBIP_API_BASE_URL` - DB-IP API base URL (default: `https://api.db-ip.com/v2`)
- `DBIP_API_TIMEOUT` - DB-IP API lookup timeout in seconds (default: 5)
- `DBIP_API_MAX_CONCURRENT` - Max concurrent DB-IP API lookups during scans (default: 10)
- `DBIP_API_CACHE_TTL` - In-memory DB-IP API cache TTL in seconds (default: 3600)
- `BROWSERLEAKS_BASE_URL` - BrowserLeaks base URL for low-volume verification (default: `https://browserleaks.com`)
- `BROWSERLEAKS_TIMEOUT` - BrowserLeaks page lookup timeout in seconds (default: 8)
- `BROWSERLEAKS_CACHE_TTL` - BrowserLeaks parser cache TTL in seconds (default: 86400)
- `BROWSERLEAKS_CRAWL_DELAY` - Minimum seconds between uncached BrowserLeaks page fetches (default: 60)
- `TRACKING_LOG_DB` - SQLite path for durable proxy stability logs (default: `backend/tracking_logs.sqlite3`)

Proxy Sentinel validates the proxy exit IP and risk/mobile flags first, then uses DB-IP API as the primary geolocation source. If DB-IP API is unavailable, rate-limited, or missing city/state data, BrowserLeaks' DB-IP-backed IP page parser is the main online fallback. The downloaded `dbip-city-lite.mmdb` file is only a last-resort provisional fallback and specific-state filters do not accept MMDB-only matches as authoritative.
BrowserLeaks is cached and crawl-delay aware, so bulk scans stay responsive without silently downgrading quality. Use `/api/lookup/browserleaks/{ip}` and `/api/lookup/compare/{ip}` for direct lookup diagnostics.

Tracking sessions are persisted to SQLite. Each observation stores the session, expected state, expected lifetime hours, elapsed time, IP, location, risk/mobile metadata, and whether the IP or location changed. Use `/api/track/logs`, `/api/track/runs`, and `/api/track/analytics` to review stability by state and lifetime.

Scan responses redact proxy passwords before returning data to the browser. The frontend receives an opaque `proxy_id` for refresh and tracking actions, while the backend keeps the full proxy secret server-side.

### Frontend
- `VITE_API_URL` - Backend API URL. Required for production builds.
- `VITE_PROXY_SENTINEL_API_TOKEN` - Optional local/private deployment token matching `PROXY_SENTINEL_API_TOKEN`

## Deployment

### Frontend (Cloudflare Pages)
The frontend can be deployed to Cloudflare Pages:
1. Connect your GitHub repository
2. Set build command: `npm run build`
3. Set output directory: `dist`
4. Set root directory: `frontend`

### Backend
The FastAPI backend can be deployed to any Python hosting service (Railway, Render, Fly.io, etc.)

## License

MIT
