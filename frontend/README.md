# Proxy Sentinel Frontend

React/Vite dashboard for Proxy Sentinel scans, tracking ledger history, and stability cohort learning.

## Commands

```bash
npm install
npm run dev
npm test
npm run lint
$env:VITE_API_URL="http://127.0.0.1:8000"; npm run build
```

## Environment

- `VITE_API_URL` is required for production builds and should point at the FastAPI backend.
- `npm run build` runs a preflight check and fails before bundling if `VITE_API_URL` is missing or invalid.
- Do not put backend API tokens in `VITE_*` variables. Vite bundles them into browser code. If `PROXY_SENTINEL_API_TOKEN` is enabled on the backend, serve the dashboard behind a trusted server/session layer that adds credentials outside the client bundle.

The browser never needs full proxy credentials after a scan. Backend responses include redacted display text plus an opaque `proxy_id` for refresh and tracking actions.
