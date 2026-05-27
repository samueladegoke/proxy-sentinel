# Proxy Sentinel Frontend

React/Vite dashboard for Proxy Sentinel scans, tracking ledger history, and stability cohort learning.

## Commands

```bash
npm install
npm run dev
npm run lint
npm run build
```

## Environment

- `VITE_API_URL` is required for production builds and should point at the FastAPI backend.
- `VITE_PROXY_SENTINEL_API_TOKEN` is optional for local/private deployments that enable `PROXY_SENTINEL_API_TOKEN` on the backend. It is bundled into client code, so do not treat it as a public-site secret.

The browser never needs full proxy credentials after a scan. Backend responses include redacted display text plus an opaque `proxy_id` for refresh and tracking actions.
