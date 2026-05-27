"""
Proxy Sentinel API - High Performance Version
==============================================
FastAPI backend with async proxy checking and real-time progress streaming.

PERFORMANCE OPTIMIZATIONS:
1. True async with aiohttp (no thread pool overhead)
2. Large connection pool (100 concurrent connections)
3. Real-time progress streaming via WebSocket
4. Optimized timeout handling (8s default)
5. Streaming results to frontend
"""
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, field_validator, validator
from typing import List, Optional, Dict, Any, Set
import asyncio
import aiohttp
import ssl
import time
import threading
import os
import logging
import json
import re
import hashlib
import hmac
import ipaddress
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

# Import async proxy library
from proxy_lib_async import (
    check_proxies_stream,
    check_proxies_batch_async,
    check_single_proxy_async,
    check_single_proxy_async_wrapper,
    cleanup as cleanup_db,
    extract_session_id,
    get_db_stats,
    IP_PROBE_TIMEOUT,
    lookup_browserleaks_html,
    lookup_dbip_api,
    parse_proxy_string
)
from tracking_store import TrackingLogStore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration from environment
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:5174,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:5174"
)
CORS_ORIGINS = [origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()]
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "100"))  # Increased from 50
TARGET_POOL_MAX_CONCURRENT = int(os.getenv("TARGET_POOL_MAX_CONCURRENT", "200"))
DEFAULT_TRACKING_INTERVAL = int(os.getenv("TRACKING_INTERVAL_MINUTES", "5"))
PROXY_FILE = os.getenv("PROXY_FILE", "../proxies.txt")
PROXY_TIMEOUT = int(os.getenv("PROXY_TIMEOUT", "8"))  # Reduced from 12s
API_AUTH_TOKEN = (os.getenv("PROXY_SENTINEL_API_TOKEN") or os.getenv("API_AUTH_TOKEN") or "").strip()
PROXY_ID_SALT = (os.getenv("PROXY_SENTINEL_PROXY_ID_SALT") or API_AUTH_TOKEN or "proxy-sentinel-local").encode()
IPROYAL_API_BASE_URL = os.getenv("IPROYAL_API_BASE_URL", "https://resi-api.iproyal.com/v1")
IPROYAL_API_TOKEN = os.getenv("IPROYAL_API_TOKEN")
IPROYAL_SUBUSER_HASH = os.getenv("IPROYAL_SUBUSER_HASH")
IPROYAL_USERNAME = os.getenv("IPROYAL_USERNAME")
IPROYAL_PASSWORD = os.getenv("IPROYAL_PASSWORD")
IPROYAL_HOSTNAME = os.getenv("IPROYAL_HOSTNAME", "geo.iproyal.com")
IPROYAL_PORT = os.getenv("IPROYAL_PORT", "http|https")
IPROYAL_LOCATION = os.getenv("IPROYAL_LOCATION", "_country-ng")
IPROYAL_ROTATION = os.getenv("IPROYAL_ROTATION", "sticky")
IPROYAL_PROXY_COUNT = int(os.getenv("IPROYAL_PROXY_COUNT", "25"))
IPROYAL_LIFETIME = os.getenv("IPROYAL_LIFETIME", "2h")
IPROYAL_HIGH_END_POOL_MARKER = "_streaming-1"


# --- Pydantic Models ---

class TrackRequest(BaseModel):
    session: str = Field(..., min_length=1, max_length=100)
    proxy: Optional[str] = Field(None, description="Full proxy string (host:port:user:pass). Required when using custom proxies not in the default list.")
    proxy_id: Optional[str] = Field(None, max_length=64, description="Opaque server-side proxy handle returned by scan endpoints.")
    expected_location: Optional[str] = Field(None, max_length=120)
    expected_state: Optional[str] = Field(None, max_length=120)
    expected_lifetime_hours: Optional[float] = Field(None, ge=0.01, le=720)

    @validator('session')
    def validate_session(cls, v):
        # Allow alphanumeric with dashes and underscores
        cleaned = v.replace('-', '').replace('_', '')
        if not cleaned.isalnum():
            raise ValueError('Session ID contains invalid characters')
        return v


class CheckRequest(BaseModel):
    proxies: Optional[List[str]] = Field(None, max_items=500)
    proxy_ids: Optional[List[str]] = Field(None, max_items=500)
    protocol: str = Field("http")

    @validator('proxies')
    def validate_proxies(cls, v):
        if v is None:
            return v
        cleaned = []
        for proxy in v:
            if not isinstance(proxy, str):
                raise ValueError("Proxy entries must be strings")
            proxy = proxy.strip()
            if not proxy:
                continue
            if len(proxy) > 2048:
                raise ValueError("Proxy entries must be 2048 characters or fewer")
            cleaned.append(proxy)
        if len(cleaned) > 500:
            raise ValueError("A scan can include at most 500 proxies")
        return cleaned

    @validator('proxy_ids')
    def validate_proxy_ids(cls, v):
        if v is None:
            return v
        cleaned = []
        for proxy_id in v:
            if not isinstance(proxy_id, str) or not re.fullmatch(r"[a-f0-9]{16,64}", proxy_id):
                raise ValueError("Proxy IDs must be opaque hexadecimal handles returned by Proxy Sentinel")
            cleaned.append(proxy_id)
        if len(cleaned) > 500:
            raise ValueError("A scan can include at most 500 proxy IDs")
        return cleaned

    @validator('protocol')
    def validate_protocol(cls, v):
        valid = ["http", "https", "socks4", "socks5"]
        if v.lower() not in valid:
            raise ValueError(f'Protocol must be one of: {valid}')
        return v.lower()


class IPRoyalCheckRequest(BaseModel):
    proxy_count: int = Field(default=IPROYAL_PROXY_COUNT, ge=1, le=500)
    location: str = Field(default=IPROYAL_LOCATION, min_length=1, max_length=100)
    rotation: str = Field(default=IPROYAL_ROTATION)
    hostname: str = Field(default=IPROYAL_HOSTNAME, min_length=1, max_length=255)
    port: str = Field(default=IPROYAL_PORT)
    lifetime: Optional[str] = Field(default=IPROYAL_LIFETIME, max_length=20)
    high_end_pool: bool = Field(default=True)
    protocol: str = Field("http")
    target_ip_prefixes: Optional[List[str]] = Field(default=None, max_length=20)
    target_match_count: int = Field(default=0, ge=0, le=500)
    max_attempts: int = Field(default=1, ge=1, le=20)

    @validator('rotation')
    def validate_rotation(cls, v):
        valid = ["sticky", "random"]
        if v.lower() not in valid:
            raise ValueError(f'Rotation must be one of: {valid}')
        return v.lower()

    @validator('location')
    def validate_location(cls, v):
        value = v.strip().lower()
        match = re.fullmatch(r"_?country-ng(?:_state-([a-z0-9]+))?", value)
        if not match:
            raise ValueError("Location must be Nigeria-wide or one of the supported Nigeria state filters")
        allowed_states = {
            "abujafederalcapitalterritory", "akwaibom", "anambra", "edo", "jigawa",
            "kaduna", "kano", "lagos", "ogun", "oyo", "rivers"
        }
        state_slug = match.group(1)
        if state_slug and state_slug not in allowed_states:
            raise ValueError("Unsupported Nigeria state filter")
        return value if value.startswith("_") else f"_{value}"

    @validator('hostname')
    def validate_hostname(cls, v):
        if v != IPROYAL_HOSTNAME:
            raise ValueError("IPRoyal hostname is backend-controlled")
        return v

    @validator('port')
    def validate_port(cls, v):
        if v != IPROYAL_PORT:
            raise ValueError("IPRoyal port selector is backend-controlled")
        return v

    @validator('lifetime')
    def validate_lifetime(cls, v):
        if v is None:
            return v
        value = v.strip().lower()
        match = re.fullmatch(r"(\d+(?:\.\d+)?)([hm])", value)
        if not match:
            raise ValueError("Lifetime must be expressed in hours or minutes, for example 24h")
        amount = float(match.group(1))
        hours = amount if match.group(2) == "h" else amount / 60
        if hours < 1 or hours > 168:
            raise ValueError("Sticky lifetime must be between 1h and 168h")
        return value

    @validator('protocol')
    def validate_protocol(cls, v):
        valid = ["http", "https", "socks4", "socks5"]
        if v.lower() not in valid:
            raise ValueError(f'Protocol must be one of: {valid}')
        return v.lower()

    @field_validator('target_ip_prefixes')
    @classmethod
    def validate_target_ip_prefixes(cls, v):
        if not v:
            return None
        cleaned: List[str] = []
        seen: Set[str] = set()
        for prefix in v:
            value = str(prefix).strip()
            match = re.fullmatch(r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\.xxx|\.0/24)?", value, re.IGNORECASE)
            if not match:
                raise ValueError("Target IP prefixes must look like 197.211.52.XXX or 197.211.52")
            octets = [int(part) for part in match.groups()]
            if any(part < 0 or part > 255 for part in octets):
                raise ValueError("Target IP prefix octets must be between 0 and 255")
            normalized = ".".join(str(part) for part in octets) + "."
            if normalized not in seen:
                seen.add(normalized)
                cleaned.append(normalized)
        return cleaned


class TargetPoolStartRequest(IPRoyalCheckRequest):
    min_active: int = Field(default=3, ge=1, le=20)
    check_interval_seconds: int = Field(default=60, ge=15, le=600)
    replacement_cooldown_seconds: int = Field(default=0, ge=0, le=600)


class TrackingConfigRequest(BaseModel):
    interval_minutes: int = Field(..., ge=1, le=60)


# --- WebSocket Connection Manager ---

class ConnectionManager:
    """Manages WebSocket connections for real-time notifications."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = threading.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        with self._lock:
            self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        with self._lock:
            self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        if not self.active_connections:
            return

        message_json = json.dumps(message)
        disconnected = set()

        for connection in self.active_connections:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                disconnected.add(connection)

        if disconnected:
            with self._lock:
                self.active_connections -= disconnected

    def count(self) -> int:
        return len(self.active_connections)


# Global instances
ws_manager = ConnectionManager()


# --- Tracking Manager ---

class TrackingManager:
    """Thread-safe manager for tracked proxy sessions."""

    def __init__(self):
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._interval_minutes = DEFAULT_TRACKING_INTERVAL
        self._ip_change_events: List[Dict[str, Any]] = []

    def add(self, session_id: str, proxy: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            if session_id in self._sessions:
                return None

            started_at = time.time()
            session_data = {
                "run_id": f"{session_id}-{int(started_at)}",
                "session": session_id,
                "proxy": proxy,
                "last_ip": None,
                "last_check": None,
                "history": [],
                "started_at": started_at
            }
            if metadata:
                session_data.update(metadata)
            lifetime_hours = session_data.get("expected_lifetime_hours")
            if lifetime_hours:
                session_data["expected_expires_at"] = started_at + (float(lifetime_hours) * 3600)

            self._sessions[session_id] = session_data
            return dict(session_data)

    def restore(self, session_data: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            restored = dict(session_data)
            restored.setdefault("last_check", None)
            restored.setdefault("history", [])
            restored.setdefault("last_ip", restored.get("latest_ip"))
            latest_result = restored.get("last_result") or {}
            if restored.get("latest_ip") and not latest_result.get("query"):
                latest_result = {
                    "query": restored.get("latest_ip"),
                    "local_region": restored.get("latest_region"),
                    "local_city": restored.get("latest_city"),
                    "local_country": restored.get("latest_country"),
                    "geo_source": restored.get("latest_geo_source"),
                    "geo_provider": restored.get("latest_geo_provider"),
                    "isp": restored.get("latest_isp"),
                    "mobile": None if restored.get("latest_mobile") is None else bool(restored.get("latest_mobile")),
                    "risk_level": restored.get("latest_risk_level"),
                }
            restored["last_result"] = latest_result
            self._sessions[restored["session"]] = restored
            return dict(restored)

    def restore_many(self, runs: List[Dict[str, Any]]) -> int:
        restored_count = 0
        for run in runs:
            self.restore(run)
            restored_count += 1
        return restored_count

    def remove(self, session_id: str) -> bool:
        with self._lock:
            if session_id in self._sessions:
                self._sessions.pop(session_id)
                return True
            return False

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self._sessions.get(session_id)

    def get_all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._sessions)

    def update(self, session_id: str, data: Dict[str, Any]) -> bool:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].update(data)
                return True
            return False

    def record_ip_change(self, session_id: str, old_ip: str, new_ip: str, city: Optional[str] = None):
        event = {
            "type": "ip_change",
            "session": session_id,
            "old_ip": old_ip,
            "new_ip": new_ip,
            "city": city,
            "changed_ip": bool(old_ip and new_ip and old_ip != new_ip),
            "changed_location": False,
            "timestamp": time.time()
        }
        with self._lock:
            self._ip_change_events.append(event)
            if len(self._ip_change_events) > 100:
                self._ip_change_events = self._ip_change_events[-100:]
        return event

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def set_interval(self, minutes: int):
        with self._lock:
            self._interval_minutes = minutes

    def get_interval(self) -> int:
        with self._lock:
            return self._interval_minutes


tracking_manager = TrackingManager()
tracking_log_store = TrackingLogStore()
scheduler = AsyncIOScheduler()


def load_proxies_from_file(filepath: str) -> List[str]:
    """Load proxies from a file."""
    proxies = []

    if os.path.exists(filepath):
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    proxies.append(line)
        logger.info(f"Loaded {len(proxies)} proxies from {filepath}")

    return proxies


DEFAULT_PROXIES = load_proxies_from_file(PROXY_FILE)

_proxy_registry: Dict[str, str] = {}
_proxy_session_registry: Dict[str, str] = {}
_proxy_registry_lock = threading.Lock()


def _proxy_handle(proxy: str) -> str:
    return hmac.new(PROXY_ID_SALT, proxy.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def _redact_proxy_string(proxy: str) -> str:
    try:
        host, port, user, _password, parsed_protocol = parse_proxy_string(proxy)
    except ValueError:
        return "[redacted proxy]"

    prefix = f"{parsed_protocol}://" if "://" in proxy else ""
    return f"{prefix}{host}:{port}:{user}:****"


def _register_proxy_secret(proxy: str) -> Dict[str, str]:
    if not isinstance(proxy, str) or not proxy.strip():
        return {}

    proxy = proxy.strip()
    try:
        _host, _port, _user, password, _protocol = parse_proxy_string(proxy)
    except ValueError:
        return {}

    proxy_id = _proxy_handle(proxy)
    session_id = extract_session_id(password)
    with _proxy_registry_lock:
        _proxy_registry[proxy_id] = proxy
        if session_id and session_id != "N/A":
            _proxy_session_registry[session_id] = proxy
    return {
        "proxy_id": proxy_id,
        "proxy_display": _redact_proxy_string(proxy),
    }


def _resolve_proxy_secret(proxy_id: str) -> Optional[str]:
    with _proxy_registry_lock:
        return _proxy_registry.get(proxy_id)


def _resolve_proxy_secret_by_session(session_id: str) -> Optional[str]:
    with _proxy_registry_lock:
        return _proxy_session_registry.get(session_id)


def _sanitize_proxy_payload(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_sanitize_proxy_payload(item) for item in payload]
    if not isinstance(payload, dict):
        return payload

    sanitized: Dict[str, Any] = {}
    proxy_meta: Dict[str, str] = {}
    for key, value in payload.items():
        if key in {"proxy", "input_proxy"} and isinstance(value, str):
            proxy_meta = proxy_meta or _register_proxy_secret(value)
            sanitized[key] = proxy_meta.get("proxy_display", "[redacted proxy]")
            continue
        sanitized[key] = _sanitize_proxy_payload(value)

    if proxy_meta:
        sanitized.setdefault("proxy_id", proxy_meta["proxy_id"])
        sanitized.setdefault("proxy_display", proxy_meta["proxy_display"])
    return sanitized


def _validated_check_request_from_payload(payload: Any, require_explicit_proxies: bool = False) -> CheckRequest:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="WebSocket payload must be a JSON object")
    try:
        request = CheckRequest(**payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())
    if require_explicit_proxies and not (request.proxies or request.proxy_ids):
        raise HTTPException(status_code=400, detail="No proxies provided")
    return request


def _resolve_check_targets(request: Optional[CheckRequest], require_explicit_proxies: bool = False) -> List[str]:
    request = request or CheckRequest()
    proxies: List[str] = []

    for proxy_id in request.proxy_ids or []:
        proxy = _resolve_proxy_secret(proxy_id)
        if not proxy:
            raise HTTPException(
                status_code=410,
                detail="Proxy handle is no longer available. Re-run the scan to refresh proxy handles."
            )
        proxies.append(proxy)

    proxies.extend(request.proxies or [])

    if not proxies and not require_explicit_proxies:
        proxies = list(DEFAULT_PROXIES)

    if not proxies:
        raise HTTPException(status_code=400, detail="No proxies to check")
    if len(proxies) > 500:
        raise HTTPException(status_code=400, detail="A scan can include at most 500 proxies")

    for proxy in proxies:
        _register_proxy_secret(proxy)
    return proxies


def _resolve_tracking_target(request: TrackRequest) -> str:
    target_proxy = _resolve_proxy_secret(request.proxy_id) if request.proxy_id else request.proxy
    if request.proxy_id and not target_proxy:
        raise HTTPException(
            status_code=410,
            detail="Proxy handle is no longer available. Re-run the scan to refresh proxy handles."
        )

    if not target_proxy:
        target_proxy = _resolve_proxy_secret_by_session(request.session)

    if not target_proxy:
        # Legacy support for file-backed default proxy lists.
        target_proxy = next(
            (p for p in DEFAULT_PROXIES if request.session in p),
            None
        )

    if not target_proxy:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Session '{request.session}' does not have a live proxy handle. "
                "Re-run the scan, track from a row that includes proxy_id, or paste the full proxy string."
            )
        )

    return target_proxy


def _normalize_ip_address(ip: str) -> str:
    try:
        return str(ipaddress.ip_address(ip.strip()))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid IP address: {ip}")


def _token_from_headers(headers: Any) -> str:
    bearer = headers.get("authorization", "")
    if bearer.lower().startswith("bearer "):
        return bearer[7:].strip()
    return headers.get("x-proxy-sentinel-token", "").strip()


def _token_authorized(token: str) -> bool:
    return bool(token) and hmac.compare_digest(token, API_AUTH_TOKEN)


def _api_request_is_authorized(request: Request) -> bool:
    return not API_AUTH_TOKEN or _token_authorized(_token_from_headers(request.headers))


async def _reject_unauthorized_websocket(websocket: WebSocket) -> bool:
    if not API_AUTH_TOKEN:
        return False
    token = _token_from_headers(websocket.headers) or websocket.query_params.get("token", "")
    if _token_authorized(token):
        return False
    await websocket.close(code=1008)
    return True


NIGERIA_STATE_LABELS = {
    "abujafederalcapitalterritory": "Abuja FCT",
    "akwaibom": "Akwa Ibom",
    "anambra": "Anambra",
    "edo": "Edo",
    "jigawa": "Jigawa",
    "kaduna": "Kaduna",
    "kano": "Kano",
    "lagos": "Lagos",
    "ogun": "Ogun",
    "oyo": "Oyo",
    "rivers": "Rivers",
}


NIGERIA_STATE_ALIASES = {
    "abujafederalcapitalterritory": {
        "abuja",
        "abuja fct",
        "fct",
        "federal capital territory",
        "abuja federal capital territory",
    }
}


def _normalize_state_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    tokens = [token for token in normalized.split() if token not in {"state", "province", "region"}]
    return "".join(tokens) or None


def _title_from_slug(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if value in NIGERIA_STATE_LABELS:
        return NIGERIA_STATE_LABELS[value]
    words = []
    current = ""
    for char in value.replace("-", " ").replace("_", " "):
        if char.isupper() and current and current[-1].islower():
            words.append(current)
            current = char
        else:
            current += char
    if current:
        words.append(current)
    return " ".join(" ".join(words).split()).title()


def _state_slug_from_location(location: Optional[str]) -> Optional[str]:
    if not location or "_state-" not in location:
        return None
    return location.split("_state-", 1)[1].split("_", 1)[0].strip().lower() or None


def _state_aliases_for_slug(state_slug: str) -> Set[str]:
    label = _title_from_slug(state_slug)
    raw_aliases = {state_slug, label, f"{label} State"}
    raw_aliases.update(NIGERIA_STATE_ALIASES.get(state_slug, set()))
    return {alias for alias in (_normalize_state_name(value) for value in raw_aliases) if alias}


def _result_state_values(result: Dict[str, Any]) -> List[str]:
    values = [
        result.get("local_region"),
        result.get("regionName"),
        result.get("region"),
        result.get("local_city"),
        result.get("city"),
    ]
    return [str(value) for value in values if value]


def _annotate_requested_state(result: Dict[str, Any], location: str) -> bool:
    state_slug = _state_slug_from_location(location)
    if not state_slug:
        result["requested_location"] = location
        result["state_filter_enabled"] = False
        result["state_match"] = True
        return True

    aliases = _state_aliases_for_slug(state_slug)
    observed_values = _result_state_values(result)
    observed_normalized = {_normalize_state_name(value) for value in observed_values}
    observed_normalized.discard(None)
    source = result.get("geo_source") or result.get("geo_fallback_source")
    online_confirmed = (
        result.get("geo_confirmation_pending") is not True
        and source in {"db-ip-api", "browserleaks-db-ip"}
    )
    matched = bool(online_confirmed and aliases & observed_normalized)

    result["requested_location"] = location
    result["requested_state"] = _title_from_slug(state_slug)
    result["requested_state_slug"] = state_slug
    result["observed_state_values"] = observed_values
    result["state_filter_enabled"] = True
    result["state_match"] = matched
    result["state_match_source"] = source if online_confirmed else "unconfirmed-geo"
    return matched


def _parse_lifetime_hours(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    value = value.strip().lower()
    try:
        if value.endswith("h"):
            return float(value[:-1])
        if value.endswith("m"):
            return float(value[:-1]) / 60
        if value.endswith("d"):
            return float(value[:-1]) * 24
        return float(value)
    except ValueError:
        return None


def _parse_tracking_metadata(proxy: str, request: TrackRequest) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {
        "expected_location": request.expected_location,
        "expected_state": request.expected_state,
        "expected_lifetime_hours": request.expected_lifetime_hours,
    }

    try:
        _, _, _, password, _ = parse_proxy_string(proxy)
    except ValueError:
        password = proxy

    parts = password.split("_")
    country = None
    state_slug = None
    lifetime = None
    for part in parts:
        if part.startswith("country-"):
            country = part.replace("country-", "", 1)
        elif part.startswith("state-"):
            state_slug = part.replace("state-", "", 1)
        elif part.startswith("lifetime-"):
            lifetime = part.replace("lifetime-", "", 1)

    if not metadata.get("expected_location") and country:
        metadata["expected_location"] = f"country-{country}" + (f"_state-{state_slug}" if state_slug else "")
    if not metadata.get("expected_state") and state_slug:
        metadata["expected_state"] = _title_from_slug(state_slug)
    if state_slug:
        metadata["expected_state_slug"] = state_slug
    if not metadata.get("expected_lifetime_hours"):
        metadata["expected_lifetime_hours"] = _parse_lifetime_hours(lifetime)

    return {key: value for key, value in metadata.items() if value is not None}


def _is_clean_mobile(result: Dict[str, Any]) -> bool:
    return (
        result.get("status") == "success"
        and result.get("risk_level") == "CLEAN"
        and result.get("mobile") is True
    )


def _is_iproyal_best_result(result: Dict[str, Any]) -> bool:
    return (
        _is_clean_mobile(result)
        and result.get("state_match") is True
        and result.get("target_ip_prefix_match") is not False
    )


def _result_matches_target_prefix(result: Dict[str, Any], prefixes: Optional[Set[str]]) -> bool:
    if not prefixes:
        return True
    query = str(result.get("query") or "")
    return any(query.startswith(prefix) for prefix in prefixes)


def _is_target_pool_viable_result(result: Dict[str, Any], location: str, prefixes: Optional[Set[str]]) -> bool:
    if not result or result.get("status") != "success":
        return False
    _annotate_requested_state(result, location)
    if not _result_matches_target_prefix(result, prefixes):
        result["target_ip_prefix_match"] = False
        return False
    result["target_ip_prefix_match"] = result.get("target_ip_prefix_match", True)
    return _is_iproyal_best_result(result)


def _target_pool_drop_reason(result: Dict[str, Any], location: str, prefixes: Optional[Set[str]]) -> Optional[str]:
    """Return a removal reason only when the latest check gives confirmed negative evidence."""
    if not result or result.get("status") != "success":
        return None

    query = str(result.get("query") or "")
    if not query:
        return None

    if not _result_matches_target_prefix(result, prefixes):
        result["target_ip_prefix_match"] = False
        return "outside_target_prefix"

    result["target_ip_prefix_match"] = True
    _annotate_requested_state(result, location)
    if result.get("state_match") is False and result.get("state_match_source") != "unconfirmed-geo":
        return "outside_requested_state"
    if result.get("risk_level") and result.get("risk_level") != "CLEAN":
        return "risk_not_clean"
    if result.get("mobile") is False:
        return "not_mobile"
    return None


def _build_target_pool_tracking_metadata(
    result: Dict[str, Any],
    request: TargetPoolStartRequest,
    prefixes: Set[str],
) -> Dict[str, Any]:
    metadata = _parse_tracking_metadata(
        result.get("input_proxy") or result.get("proxy") or "",
        TrackRequest(
            session=result.get("session") or "target-pool",
            expected_location=request.location,
            expected_state=_title_from_slug(_state_slug_from_location(request.location)),
            expected_lifetime_hours=_parse_lifetime_hours(request.lifetime),
        )
    )
    metadata.update({
        "target_pool_managed": True,
        "target_pool_prefixes": sorted(prefixes),
        "target_pool_min_active": request.min_active,
        "target_pool_location": request.location,
        "target_pool_started_at": time.time(),
    })
    return {key: value for key, value in metadata.items() if value is not None}


def _result_location_parts(result: Dict[str, Any]) -> Dict[str, str]:
    region = (
        result.get("local_region")
        or result.get("regionName")
        or result.get("region")
        or "Unknown"
    )
    city = result.get("local_city") or result.get("city") or "Unknown"
    return {
        "region": str(region),
        "city": str(city),
        "label": f"{region} / {city}",
    }


def _diagnostic_geo_source(result: Dict[str, Any]) -> str:
    return str(
        result.get("geo_source")
        or result.get("geo_fallback_source")
        or result.get("geo_provider")
        or "unknown"
    )


def _scan_rejection_reason(result: Dict[str, Any]) -> Dict[str, str]:
    if result.get("status") != "success":
        return {"reason": "failed", "label": "Connection failed"}

    if result.get("target_ip_prefix_match") is False:
        return {"reason": "target_prefix_miss", "label": "Outside target IP groups"}

    risk_level = result.get("risk_level")
    if risk_level != "CLEAN":
        risk_label = str(risk_level or "UNKNOWN").upper()
        return {"reason": f"risk_{risk_label}", "label": f"Risk: {risk_label}"}

    if result.get("mobile") is not True:
        return {"reason": "not_mobile", "label": "Not mobile"}

    if result.get("state_match") is False:
        return {"reason": "outside_requested_state", "label": "Outside selected state"}

    return {"reason": "accepted", "label": "Accepted"}


def _build_iproyal_scan_diagnostics(
    results: List[Dict[str, Any]],
    location: str,
    generated_count: int,
) -> Dict[str, Any]:
    """Summarize raw scan outcomes without exposing proxy credentials."""
    reason_totals: Dict[str, Dict[str, Any]] = {}
    source_totals: Dict[str, Dict[str, Any]] = {}
    location_totals: Dict[str, Dict[str, Any]] = {}
    accepted_count = 0
    successful_count = 0

    def increment_source(source: str) -> None:
        if source not in source_totals:
            source_totals[source] = {"source": source, "count": 0}
        source_totals[source]["count"] += 1

    def increment_reason(reason: Dict[str, str]) -> None:
        key = reason["reason"]
        if key not in reason_totals:
            reason_totals[key] = {"reason": key, "label": reason["label"], "count": 0}
        reason_totals[key]["count"] += 1

    for result in results:
        reason = _scan_rejection_reason(result)
        source = _diagnostic_geo_source(result)
        increment_source(source)

        if reason["reason"] == "accepted":
            accepted_count += 1
        else:
            increment_reason(reason)

        if result.get("status") != "success":
            continue

        successful_count += 1
        location_parts = _result_location_parts(result)
        location_bucket = location_totals.setdefault(
            location_parts["label"],
            {
                "label": location_parts["label"],
                "region": location_parts["region"],
                "city": location_parts["city"],
                "count": 0,
                "accepted_count": 0,
                "rejected_count": 0,
                "geo_sources": {},
                "rejection_reasons": {},
            }
        )
        location_bucket["count"] += 1
        location_bucket["geo_sources"][source] = location_bucket["geo_sources"].get(source, 0) + 1

        if reason["reason"] == "accepted":
            location_bucket["accepted_count"] += 1
        else:
            location_bucket["rejected_count"] += 1
            location_reasons = location_bucket["rejection_reasons"]
            if reason["reason"] not in location_reasons:
                location_reasons[reason["reason"]] = {
                    "reason": reason["reason"],
                    "label": reason["label"],
                    "count": 0,
                }
            location_reasons[reason["reason"]]["count"] += 1

    successful_locations = []
    for location in location_totals.values():
        location["geo_sources"] = sorted(
            (
                {"source": source, "count": count}
                for source, count in location["geo_sources"].items()
            ),
            key=lambda item: (-item["count"], item["source"]),
        )
        location["rejection_reasons"] = sorted(
            location["rejection_reasons"].values(),
            key=lambda item: (-item["count"], item["label"]),
        )
        successful_locations.append(location)

    return {
        "generated_count": generated_count,
        "checked_count": len(results),
        "successful_count": successful_count,
        "failed_count": len(results) - successful_count,
        "accepted_count": accepted_count,
        "state_filter_enabled": bool(_state_slug_from_location(location)),
        "requested_location": location,
        "requested_state": _title_from_slug(_state_slug_from_location(location)),
        "successful_locations": sorted(
            successful_locations,
            key=lambda item: (-item["count"], item["label"]),
        ),
        "rejection_reasons": sorted(
            reason_totals.values(),
            key=lambda item: (-item["count"], item.get("label", item["reason"])),
        ),
        "geo_sources": sorted(
            source_totals.values(),
            key=lambda item: (-item["count"], item["source"]),
        ),
    }


def _append_valid_proxy(candidate: str, proxies: List[str], seen: Set[str]):
    candidate = candidate.strip()
    if not candidate or candidate.startswith("#") or candidate in seen:
        return

    try:
        parse_proxy_string(candidate)
    except ValueError:
        return

    seen.add(candidate)
    proxies.append(candidate)


def _extract_proxy_strings(payload: Any) -> List[str]:
    """Extract proxy strings from IPRoyal responses without depending on one JSON shape."""
    proxies: List[str] = []
    seen: Set[str] = set()

    def walk(value: Any):
        if isinstance(value, str):
            for line in value.replace("\r", "\n").split("\n"):
                _append_valid_proxy(line, proxies, seen)
            return

        if isinstance(value, list):
            for item in value:
                walk(item)
            return

        if isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(payload)
    return proxies


def _ensure_iproyal_high_end_pool_proxy(proxy: str) -> str:
    """Force generated IPRoyal credentials onto the high-end/streaming pool."""
    if not isinstance(proxy, str) or not proxy.strip():
        return proxy

    original = proxy.strip()
    prefix = ""
    body = original
    if "://" in body:
        protocol, body = body.split("://", 1)
        prefix = f"{protocol.lower()}://"

    parts = body.split(":")
    if len(parts) < 4:
        return original

    password = re.sub(r"_streaming-[^_:\s]+", "", parts[3])
    parts[3] = f"{password}{IPROYAL_HIGH_END_POOL_MARKER}"

    return prefix + ":".join(parts)


def _remove_iproyal_high_end_pool_proxy(proxy: str) -> str:
    """Remove generated IPRoyal high-end/streaming pool credentials."""
    if not isinstance(proxy, str) or not proxy.strip():
        return proxy

    original = proxy.strip()
    prefix = ""
    body = original
    if "://" in body:
        protocol, body = body.split("://", 1)
        prefix = f"{protocol}://"

    parts = body.split(":")
    if len(parts) < 4:
        return original

    parts[3] = re.sub(r"_streaming-[^_:\s]+", "", parts[3])
    return prefix + ":".join(parts)


def _apply_iproyal_pool_option(proxy: str, high_end_pool: bool = True) -> str:
    if high_end_pool:
        return _ensure_iproyal_high_end_pool_proxy(proxy)
    return _remove_iproyal_high_end_pool_proxy(proxy)


async def generate_iproyal_proxy_list(request: IPRoyalCheckRequest) -> List[str]:
    if not IPROYAL_API_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="IPROYAL_API_TOKEN is not configured on the backend"
        )

    payload = {
        "format": "{hostname}:{port}:{username}:{password}",
        "hostname": IPROYAL_HOSTNAME,
        "port": IPROYAL_PORT,
        "rotation": request.rotation,
        "location": request.location,
        "proxy_count": request.proxy_count,
    }

    if request.lifetime:
        payload["lifetime"] = request.lifetime

    if IPROYAL_SUBUSER_HASH:
        payload["subuser_hash"] = IPROYAL_SUBUSER_HASH
    elif IPROYAL_USERNAME and IPROYAL_PASSWORD:
        payload["username"] = IPROYAL_USERNAME
        payload["password"] = IPROYAL_PASSWORD
    else:
        raise HTTPException(
            status_code=503,
            detail="Configure IPROYAL_SUBUSER_HASH or IPROYAL_USERNAME/IPROYAL_PASSWORD on the backend"
        )

    url = f"{IPROYAL_API_BASE_URL.rstrip('/')}/access/generate-proxy-list"
    headers = {
        "Authorization": f"Bearer {IPROYAL_API_TOKEN}",
        "Content-Type": "application/json",
    }

    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                text = await response.text()
                if response.status >= 400:
                    logger.warning("IPRoyal generate-proxy-list failed: HTTP %s %s", response.status, text[:300])
                    raise HTTPException(
                        status_code=502,
                        detail=f"IPRoyal API returned HTTP {response.status}"
                    )

                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    data = text
    except HTTPException:
        raise
    except (asyncio.TimeoutError, aiohttp.ClientError, ssl.SSLError, OSError) as exc:
        logger.warning("IPRoyal generate-proxy-list network/TLS failure: %s", str(exc)[:160])
        raise HTTPException(
            status_code=502,
            detail="IPRoyal proxy generation temporarily failed due to a network/TLS error"
        ) from exc

    proxies = _extract_proxy_strings(data)
    if not proxies:
        raise HTTPException(
            status_code=502,
            detail="IPRoyal API response did not contain any usable proxy strings"
        )

    normalized_proxies: List[str] = []
    seen: Set[str] = set()
    for proxy in proxies:
        normalized_proxy = _apply_iproyal_pool_option(proxy, request.high_end_pool)
        if normalized_proxy not in seen:
            _register_proxy_secret(normalized_proxy)
            seen.add(normalized_proxy)
            normalized_proxies.append(normalized_proxy)

    return normalized_proxies


class TargetPoolKeeper:
    """Keeps a minimum number of tracked proxies inside the configured target prefixes."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._active = False
        self._config: Optional[TargetPoolStartRequest] = None
        self._last_error: Optional[str] = None
        self._last_action: Optional[str] = None
        self._last_scan_summary: Dict[str, Any] = {}
        self._last_reconcile_at: Optional[float] = None
        self._next_reconcile_at: Optional[float] = None
        self._replacement_runs = 0
        self._accepted_total = 0
        self._phase = "stopped"
        self._scan_progress: Dict[str, Any] = {}

    def _managed_sessions(self) -> Dict[str, Dict[str, Any]]:
        return {
            session_id: data
            for session_id, data in tracking_manager.get_all().items()
            if data.get("target_pool_managed")
        }

    def _active_target_count(self) -> int:
        if not self._config:
            return 0
        prefixes = set(self._config.target_ip_prefixes or [])
        count = 0
        for data in self._managed_sessions().values():
            result = dict(data.get("last_result") or {})
            if _is_target_pool_viable_result(result, self._config.location, prefixes):
                count += 1
        return count

    def status(self) -> Dict[str, Any]:
        managed = self._managed_sessions()
        return {
            "active": self._active,
            "min_active": self._config.min_active if self._config else 0,
            "check_interval_seconds": self._config.check_interval_seconds if self._config else None,
            "location": self._config.location if self._config else None,
            "target_ip_prefixes": sorted(self._config.target_ip_prefixes or []) if self._config else [],
            "managed_count": len(managed),
            "active_target_count": self._active_target_count(),
            "replacement_runs": self._replacement_runs,
            "accepted_total": self._accepted_total,
            "last_error": self._last_error,
            "last_action": self._last_action,
            "last_scan_summary": self._last_scan_summary,
            "last_reconcile_at": self._last_reconcile_at,
            "next_reconcile_at": self._next_reconcile_at,
            "phase": self._phase,
            "scan_progress": self._scan_progress,
        }

    async def _broadcast_status(self) -> None:
        await ws_manager.broadcast({
            "type": "target_pool_update",
            "timestamp": time.time(),
            "status": self.status(),
        })

    async def start(self, request: TargetPoolStartRequest) -> Dict[str, Any]:
        if not request.target_ip_prefixes:
            raise HTTPException(status_code=400, detail="Target pool automation requires at least one target IP prefix")

        async with self._lock:
            self._config = request
            self._active = True
            self._last_error = None
            self._last_action = "started"
            self._next_reconcile_at = time.time()
            self._phase = "queued"
            self._scan_progress = {
                "stage": "queued",
                "checked": 0,
                "generated": 0,
                "accepted": 0,
                "target": request.min_active,
            }
            if self._task and not self._task.done():
                self._task.cancel()
            self._task = asyncio.create_task(self._run_loop())
        return self.status()

    async def stop(self) -> Dict[str, Any]:
        self._active = False
        self._last_action = "stopped"
        self._next_reconcile_at = None
        self._phase = "stopped"
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            await asyncio.sleep(0)
        return self.status()

    async def reconcile_once(self) -> Dict[str, Any]:
        async with self._lock:
            if not self._config:
                raise HTTPException(status_code=400, detail="Target pool automation has not been configured")
            await self._ensure_pool_locked()
        return self.status()

    async def shutdown(self) -> None:
        await self.stop()

    async def _run_loop(self) -> None:
        while self._active:
            async with self._lock:
                await self._ensure_pool_locked()
                interval = self._config.check_interval_seconds if self._config else 60
                self._next_reconcile_at = time.time() + interval
            await asyncio.sleep(interval)

    async def _ensure_pool_locked(self) -> None:
        if not self._config:
            return

        self._last_reconcile_at = time.time()
        try:
            self._phase = "checking_tracked"
            self._scan_progress = {
                "stage": "checking tracked proxies",
                "checked": 0,
                "generated": 0,
                "accepted": 0,
                "target": self._config.min_active,
            }
            await self._broadcast_status()
            self._last_error = None
            dropped = await self._drop_non_target_sessions_locked()
            active_count = self._active_target_count()
            deficit = max(0, self._config.min_active - active_count)
            accepted = await self._replace_deficit_locked(deficit) if deficit else []
            if self._last_error:
                self._last_action = "replacement temporarily unavailable"
            else:
                self._last_action = (
                    f"pool healthy with {active_count} active target proxies"
                    if not deficit
                    else f"replaced {len(accepted)} of {deficit} missing target proxies"
                )
            self._last_scan_summary = {
                "dropped_count": dropped,
                "deficit": deficit,
                "accepted_count": len(accepted),
                "active_target_count": self._active_target_count(),
                "managed_count": len(self._managed_sessions()),
            }
            self._phase = "idle" if self._active else "stopped"
            self._scan_progress = {
                "stage": "idle" if self._active else "stopped",
                "checked": self._scan_progress.get("checked", 0),
                "generated": self._scan_progress.get("generated", 0),
                "accepted": len(accepted),
                "target": deficit,
            }
            await self._broadcast_status()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Target pool reconciliation failed: %s", exc)
            self._last_error = str(exc)
            self._last_action = "reconcile failed"
            self._phase = "error"
            await self._broadcast_status()

    async def _drop_non_target_sessions_locked(self) -> int:
        if not self._config:
            return 0

        prefixes = set(self._config.target_ip_prefixes or [])
        dropped = 0
        managed_items = list(self._managed_sessions().items())
        total = len(managed_items)
        for index, (session_id, data) in enumerate(managed_items, start=1):
            self._scan_progress = {
                "stage": "checking tracked proxies",
                "checked": index - 1,
                "generated": total,
                "accepted": self._active_target_count(),
                "target": self._config.min_active,
            }
            await self._broadcast_status()
            previous = dict(data)
            result = await check_single_proxy_async_wrapper(
                data["proxy"],
                protocol=self._config.protocol,
                timeout=PROXY_TIMEOUT,
            )
            result = result or {}
            drop_reason = _target_pool_drop_reason(result, self._config.location, prefixes)
            log_event = tracking_log_store.log_observation(data, result, previous)

            if not drop_reason:
                tracking_manager.update(session_id, {
                    "last_ip": result.get("query") or previous.get("last_ip"),
                    "last_check": time.time(),
                    "last_region": (
                        result.get("local_region")
                        or result.get("regionName")
                        or result.get("region")
                        or previous.get("last_region")
                    ),
                    "last_city": result.get("local_city") or result.get("city") or previous.get("last_city"),
                    "last_result": result if result.get("query") else previous.get("last_result", result),
                })
                continue

            tracking_manager.remove(session_id)
            if data.get("run_id"):
                tracking_log_store.end_run(data["run_id"])
            dropped += 1
            await ws_manager.broadcast({
                "type": "target_pool_proxy_dropped",
                "session": session_id,
                "old_ip": log_event.get("old_ip") or previous.get("last_ip"),
                "new_ip": (result or {}).get("query"),
                "reason": drop_reason,
                "timestamp": time.time(),
            })

        return dropped

    def _rejection_reason(self, result: Dict[str, Any], prefixes: Set[str]) -> str:
        if result.get("status") != "success":
            return "check_failed"
        if not _result_matches_target_prefix(result, prefixes):
            return "outside_target_prefix"
        if result.get("state_match") is not True:
            return "outside_requested_state"
        if result.get("risk_level") != "CLEAN":
            return "risk_not_clean"
        if result.get("mobile") is not True:
            return "not_mobile"
        return "not_viable"

    async def _replace_deficit_locked(self, deficit: int) -> List[Dict[str, Any]]:
        if not self._config or deficit <= 0:
            return []

        accepted_results: List[Dict[str, Any]] = []
        prefixes = set(self._config.target_ip_prefixes or [])
        request = self._config.model_copy(update={"target_match_count": deficit})
        attempts_allowed = request.max_attempts
        self._replacement_runs += 1
        checked = 0
        generated_total = 0
        generation_task: Optional[asyncio.Task[List[str]]] = asyncio.create_task(generate_iproyal_proxy_list(request))

        try:
            for attempt_index in range(attempts_allowed):
                self._phase = "generating"
                self._scan_progress = {
                    "stage": "generating candidate proxies",
                    "attempt": attempt_index + 1,
                    "attempts_allowed": attempts_allowed,
                    "checked": checked,
                    "generated": generated_total,
                    "accepted": len(accepted_results),
                    "target": deficit,
                }
                await self._broadcast_status()
                try:
                    proxies_to_check = await generation_task
                except HTTPException as exc:
                    if exc.status_code < 500:
                        raise
                    self._last_error = str(exc.detail)
                    self._phase = "idle" if self._active else "stopped"
                    self._scan_progress = {
                        "stage": "candidate generation unavailable",
                        "attempt": attempt_index + 1,
                        "attempts_allowed": attempts_allowed,
                        "checked": checked,
                        "generated": generated_total,
                        "accepted": len(accepted_results),
                        "target": deficit,
                    }
                    await self._broadcast_status()
                    return accepted_results

                generated_total += len(proxies_to_check)
                has_more_attempts = attempt_index < attempts_allowed - 1
                generation_task = (
                    asyncio.create_task(generate_iproyal_proxy_list(request))
                    if has_more_attempts
                    else None
                )
                self._phase = "searching"
                async for result in check_proxies_stream(
                    proxies_to_check,
                    protocol=request.protocol,
                    max_concurrent=TARGET_POOL_MAX_CONCURRENT,
                    timeout=IP_PROBE_TIMEOUT,
                    target_ip_prefixes=prefixes or None,
                    ip_only=True,
                ):
                    checked += 1
                    if result.get("status") != "success" or not _result_matches_target_prefix(result, prefixes):
                        self._scan_progress = {
                            "stage": "searching target prefixes",
                            "attempt": attempt_index + 1,
                            "attempts_allowed": attempts_allowed,
                            "checked": checked,
                            "generated": generated_total,
                            "accepted": len(accepted_results),
                            "target": deficit,
                        }
                        await self._broadcast_status()
                        continue

                    self._phase = "confirming"
                    self._scan_progress = {
                        "stage": f"confirming target candidate {result.get('query') or ''}".strip(),
                        "attempt": attempt_index + 1,
                        "attempts_allowed": attempts_allowed,
                        "checked": checked,
                        "generated": generated_total,
                        "accepted": len(accepted_results),
                        "target": deficit,
                    }
                    await self._broadcast_status()
                    confirmation_results = await check_proxies_batch_async(
                        [result.get("input_proxy") or result.get("proxy")],
                        protocol=request.protocol,
                        max_concurrent=1,
                        timeout=PROXY_TIMEOUT,
                        target_ip_prefixes=prefixes or None,
                    )
                    result = confirmation_results[0] if confirmation_results else result

                    if not _is_target_pool_viable_result(result, request.location, prefixes):
                        self._phase = "searching"
                        self._scan_progress = {
                            "stage": "searching target prefixes",
                            "attempt": attempt_index + 1,
                            "attempts_allowed": attempts_allowed,
                            "checked": checked,
                            "generated": generated_total,
                            "accepted": len(accepted_results),
                            "target": deficit,
                        }
                        await self._broadcast_status()
                        continue

                    added = self._track_target_result_locked(result, request, prefixes)
                    if added:
                        accepted_results.append(result)
                        self._accepted_total += 1
                    self._phase = "searching"
                    self._scan_progress = {
                        "stage": "searching target prefixes",
                        "attempt": attempt_index + 1,
                        "attempts_allowed": attempts_allowed,
                        "checked": checked,
                        "generated": generated_total,
                        "accepted": len(accepted_results),
                        "target": deficit,
                    }
                    await self._broadcast_status()
                    if len(accepted_results) >= deficit:
                        return accepted_results

                if has_more_attempts and self._config.replacement_cooldown_seconds:
                    self._phase = "cooldown"
                    self._scan_progress = {
                        "stage": "cooldown before next attempt",
                        "attempt": attempt_index + 1,
                        "attempts_allowed": attempts_allowed,
                        "checked": checked,
                        "generated": generated_total,
                        "accepted": len(accepted_results),
                        "target": deficit,
                    }
                    await self._broadcast_status()
                    await asyncio.sleep(self._config.replacement_cooldown_seconds)
        finally:
            if generation_task:
                if not generation_task.done():
                    generation_task.cancel()
                elif not generation_task.cancelled():
                    generation_task.exception()

        return accepted_results

    def _track_target_result_locked(
        self,
        result: Dict[str, Any],
        request: TargetPoolStartRequest,
        prefixes: Set[str],
    ) -> Optional[Dict[str, Any]]:
        proxy = result.get("input_proxy") or result.get("proxy")
        session_id = result.get("session") or extract_session_id(proxy or "")
        if not proxy or not session_id or session_id == "N/A":
            return None

        metadata = _build_target_pool_tracking_metadata(result, request, prefixes)
        added = tracking_manager.add(session_id, proxy, metadata)
        if not added:
            return None

        tracking_log_store.start_run(added)
        tracking_log_store.log_observation(added, result, {})
        tracking_manager.update(session_id, {
            "last_ip": result.get("query"),
            "last_check": time.time(),
            "last_region": result.get("local_region") or result.get("regionName") or result.get("region"),
            "last_city": result.get("local_city") or result.get("city"),
            "last_result": result,
        })
        return added


target_pool_keeper = TargetPoolKeeper()


# --- Application Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown."""
    logger.info("Starting Proxy Sentinel API (High Performance Mode)...")
    logger.info(f"CORS Origins: {CORS_ORIGINS}")
    logger.info(f"Max Concurrent: {MAX_CONCURRENT}")
    logger.info(f"Proxy Timeout: {PROXY_TIMEOUT}s")
    logger.info(f"DB Stats: {get_db_stats()}")
    restored_count = tracking_manager.restore_many(tracking_log_store.active_runs())
    if restored_count:
        logger.info(f"Restored {restored_count} active tracked proxy sessions from durable history")

    scheduler.add_job(
        perform_tracking_checks,
        'interval',
        minutes=tracking_manager.get_interval(),
        id='tracking_check'
    )
    scheduler.start()

    yield

    logger.info("Shutting down Proxy Sentinel API...")
    await target_pool_keeper.shutdown()
    scheduler.shutdown(wait=False)
    cleanup_db()
    logger.info("Cleanup complete")


app = FastAPI(
    title="Proxy Sentinel API",
    description="High-Performance Proxy Monitoring with Real-time Progress",
    version="3.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# --- Exception Handlers ---

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": exc.detail}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Internal server error"}
    )


@app.middleware("http")
async def require_api_token(request: Request, call_next):
    if request.method != "OPTIONS" and request.url.path.startswith("/api/") and not _api_request_is_authorized(request):
        return JSONResponse(
            status_code=401,
            content={"status": "error", "message": "Unauthorized"}
        )
    return await call_next(request)


# --- API Endpoints ---

@app.get("/")
def read_root():
    return {
        "message": "Proxy Sentinel API (High Performance)",
        "version": "3.0.0",
        "tracked_sessions": tracking_manager.count(),
        "default_proxies": len(DEFAULT_PROXIES),
        "websocket_connections": ws_manager.count(),
        "max_concurrent": MAX_CONCURRENT,
        "auth_required": bool(API_AUTH_TOKEN)
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "database": get_db_stats(),
        "tracked_sessions": tracking_manager.count(),
        "websocket_connections": ws_manager.count(),
        "tracking_interval": tracking_manager.get_interval(),
        "max_concurrent": MAX_CONCURRENT,
        "target_pool_max_concurrent": TARGET_POOL_MAX_CONCURRENT,
        "proxy_timeout": PROXY_TIMEOUT,
        "ip_probe_timeout": IP_PROBE_TIMEOUT,
        "auth_required": bool(API_AUTH_TOKEN)
    }


@app.get("/api/lookup/dbip/{ip}")
async def lookup_dbip_endpoint(ip: str):
    """Lookup an IP directly with DB-IP API."""
    ip = _normalize_ip_address(ip)
    async with aiohttp.ClientSession() as session:
        result = await lookup_dbip_api(session, ip)
    if not result:
        raise HTTPException(status_code=502, detail="DB-IP API lookup failed")
    return result


@app.get("/api/lookup/browserleaks/{ip}")
async def lookup_browserleaks_endpoint(ip: str, force: bool = False):
    """Lookup an IP through BrowserLeaks' DB-IP-backed page parser."""
    ip = _normalize_ip_address(ip)
    async with aiohttp.ClientSession() as session:
        result = await lookup_browserleaks_html(session, ip, respect_crawl_delay=not force)
    if not result:
        raise HTTPException(
            status_code=429 if not force else 502,
            detail="BrowserLeaks lookup unavailable or skipped to respect crawl-delay"
        )
    return result


@app.get("/api/lookup/compare/{ip}")
async def compare_lookup_endpoint(ip: str, force_browserleaks: bool = False):
    """Compare DB-IP API with BrowserLeaks' DB-IP-backed page result."""
    ip = _normalize_ip_address(ip)
    async with aiohttp.ClientSession() as session:
        dbip_result, browserleaks_result = await asyncio.gather(
            lookup_dbip_api(session, ip),
            lookup_browserleaks_html(session, ip, respect_crawl_delay=not force_browserleaks),
        )
    return {
        "ip": ip,
        "db_ip_api": dbip_result,
        "browserleaks": browserleaks_result,
        "same_city_region": bool(
            dbip_result
            and browserleaks_result
            and dbip_result.get("city") == browserleaks_result.get("city")
            and dbip_result.get("stateProv") == browserleaks_result.get("stateProv")
        )
    }


@app.post("/api/check", response_model=Dict[str, Any])
async def check_proxies_endpoint(request: Optional[CheckRequest] = None):
    """Check proxies and return all results at once."""
    request = request or CheckRequest()
    proxies_to_check = _resolve_check_targets(request, require_explicit_proxies=False)

    try:
        results = await check_proxies_batch_async(
            proxies_to_check,
            protocol=request.protocol,
            max_concurrent=MAX_CONCURRENT,
            timeout=PROXY_TIMEOUT
        )
    except Exception as e:
        logger.error(f"Error checking proxies: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "count": len(results),
        "results": _sanitize_proxy_payload(results)
    }


@app.post("/api/check/single", response_model=Dict[str, Any])
async def check_single_endpoint(request: CheckRequest):
    """Check a single proxy."""
    proxies = _resolve_check_targets(request, require_explicit_proxies=True)
    if len(proxies) != 1:
        raise HTTPException(status_code=400, detail="Provide exactly one proxy")

    result = await check_single_proxy_async_wrapper(
        proxies[0],
        protocol=request.protocol,
        timeout=PROXY_TIMEOUT
    )
    return _sanitize_proxy_payload(result)


@app.post("/api/iproyal/check-best", response_model=Dict[str, Any])
async def check_best_iproyal_proxies(request: IPRoyalCheckRequest):
    """Generate IPRoyal proxies, check them, and return clean mobile results."""
    target_prefixes = set(request.target_ip_prefixes or [])
    target_goal = request.target_match_count if target_prefixes else 0
    attempts_allowed = request.max_attempts if target_goal > 0 else 1
    results: List[Dict[str, Any]] = []
    generated_count = 0
    attempts_completed = 0

    for attempt in range(attempts_allowed):
        attempts_completed = attempt + 1
        proxies_to_check = await generate_iproyal_proxy_list(request)
        generated_count += len(proxies_to_check)

        try:
            batch_results = await check_proxies_batch_async(
                proxies_to_check,
                protocol=request.protocol,
                max_concurrent=MAX_CONCURRENT,
                timeout=PROXY_TIMEOUT,
                target_ip_prefixes=target_prefixes or None,
            )
        except Exception as e:
            logger.error(f"Error checking IPRoyal proxies: {e}")
            raise HTTPException(status_code=500, detail=str(e))

        for result in batch_results:
            _annotate_requested_state(result, request.location)
        results.extend(batch_results)

        if target_goal > 0:
            matched_count = sum(
                1
                for result in results
                if _is_iproyal_best_result(result)
            )
            if matched_count >= target_goal:
                break

    clean_mobile_results = [result for result in results if _is_clean_mobile(result)]

    state_filter_enabled = bool(_state_slug_from_location(request.location))
    best_results = [result for result in clean_mobile_results if _is_iproyal_best_result(result)]
    location_rejected_results = [
        result
        for result in clean_mobile_results
        if result.get("state_match") is False
    ]
    diagnostics = _build_iproyal_scan_diagnostics(
        results,
        location=request.location,
        generated_count=generated_count,
    )

    return {
        "status": "success",
        "generated_count": generated_count,
        "checked_count": len(results),
        "clean_mobile_count": len(clean_mobile_results),
        "best_count": len(best_results),
        "attempts_completed": attempts_completed,
        "target_ip_prefixes": sorted(target_prefixes),
        "target_match_count": target_goal,
        "location_rejected_count": len(location_rejected_results),
        "criteria": {
            "status": "success",
            "risk_level": "CLEAN",
            "mobile": True,
            "state_match": True if state_filter_enabled else None,
            "requested_location": request.location,
            "requested_state": _title_from_slug(_state_slug_from_location(request.location)),
            "target_ip_prefixes": sorted(target_prefixes),
            "high_end_pool": request.high_end_pool,
            "pool": "high-end" if request.high_end_pool else "standard"
        },
        "diagnostics": diagnostics,
        "best_results": _sanitize_proxy_payload(best_results)
    }


@app.post("/api/track")
async def track_proxy(request: TrackRequest, background_tasks: BackgroundTasks):
    """Start durable tracking for a proxy session until it is explicitly stopped."""
    target_proxy = _resolve_tracking_target(request)
    metadata = _parse_tracking_metadata(target_proxy, request)
    added = tracking_manager.add(request.session, target_proxy, metadata)

    if not added:
        return {
            "status": "success",
            "message": f"Session '{request.session}' is already being tracked"
        }

    tracking_log_store.start_run(added)

    # Trigger an immediate check so the user gets instant feedback
    background_tasks.add_task(perform_tracking_checks)

    return {
        "status": "success",
        "message": f"Started tracking session '{request.session}'",
        "interval_minutes": tracking_manager.get_interval(),
        "active_count": tracking_manager.count(),
        "run_id": added.get("run_id"),
        "expected_state": added.get("expected_state"),
        "expected_lifetime_hours": added.get("expected_lifetime_hours")
    }


@app.delete("/api/track/{session_id}")
async def stop_tracking(session_id: str):
    """Stop tracking a proxy session after recording a final observation."""
    session_data = tracking_manager.get(session_id)
    if not session_data:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found"
        )

    final_observation = None
    try:
        previous = dict(session_data)
        result = await check_single_proxy_async_wrapper(
            session_data["proxy"],
            timeout=PROXY_TIMEOUT
        )
        final_observation = tracking_log_store.log_observation(session_data, result or {}, previous)
        if result and result.get("status") == "success":
            tracking_manager.update(session_id, {
                "last_ip": result.get("query"),
                "last_check": time.time(),
                "last_region": result.get("local_region") or result.get("regionName") or result.get("region"),
                "last_city": result.get("local_city") or result.get("city"),
                "last_result": result,
            })
    except Exception as e:
        logger.warning(f"Final tracking observation failed for {session_id}: {e}")

    tracking_manager.remove(session_id)

    if session_data and session_data.get("run_id"):
        tracking_log_store.end_run(session_data["run_id"])

    return {
        "status": "success",
        "message": f"Stopped tracking session '{session_id}'",
        "run_id": session_data.get("run_id"),
        "final_observation": _sanitize_proxy_payload(final_observation)
    }


@app.post("/api/track/runs/{run_id}/retrack")
async def retrack_tracking_run(run_id: str, background_tasks: BackgroundTasks):
    """Start a fresh active tracking run from a stopped historical run."""
    details = tracking_log_store.run_details(run_id, observation_limit=1)
    run = details.get("run")
    if not run:
        raise HTTPException(status_code=404, detail=f"Tracking run '{run_id}' not found")
    if run.get("ended_at") is None:
        raise HTTPException(status_code=409, detail="This tracking run is already active")
    if tracking_manager.get(run["session"]):
        raise HTTPException(
            status_code=409,
            detail=f"Session '{run['session']}' is already being tracked"
        )

    metadata = _parse_tracking_metadata(
        run["proxy"],
        TrackRequest(
            session=run["session"],
            expected_location=run.get("expected_location"),
            expected_state=run.get("expected_state"),
            expected_lifetime_hours=run.get("expected_lifetime_hours"),
        ),
    )
    added = tracking_manager.add(run["session"], run["proxy"], metadata)
    if not added:
        raise HTTPException(
            status_code=409,
            detail=f"Session '{run['session']}' is already being tracked"
        )

    tracking_log_store.start_run(added)
    background_tasks.add_task(perform_tracking_checks)

    return {
        "status": "success",
        "message": f"Re-started tracking session '{run['session']}'",
        "run_id": added.get("run_id"),
        "session": added.get("session"),
        "active_count": tracking_manager.count(),
        "tracked": _sanitize_proxy_payload(added),
    }


@app.get("/api/track")
def get_tracked_sessions():
    """Get all currently tracked sessions."""
    return {
        "count": tracking_manager.count(),
        "interval_minutes": tracking_manager.get_interval(),
        "sessions": _sanitize_proxy_payload(tracking_manager.get_all())
    }


@app.get("/api/track/logs")
def get_tracking_logs(limit: int = 100, session: Optional[str] = None):
    """Get durable tracking observations for proxy stability analysis."""
    return {
        "count": min(max(limit, 1), 1000),
        "logs": _sanitize_proxy_payload(tracking_log_store.recent_observations(limit=limit, session=session))
    }


@app.get("/api/track/runs")
def get_tracking_runs(limit: int = 100, status: Optional[str] = None):
    """Get durable tracking runs."""
    normalized_status = status.lower() if status else None
    if normalized_status not in {None, "active", "stopped", "all"}:
        raise HTTPException(status_code=400, detail="status must be active, stopped, or all")
    store_status = None if normalized_status in {None, "all"} else normalized_status
    return {
        "count": min(max(limit, 1), 1000),
        "status": normalized_status or "all",
        "runs": _sanitize_proxy_payload(tracking_log_store.runs(limit=limit, status=store_status))
    }


@app.get("/api/track/runs/{run_id}")
def get_tracking_run_details(run_id: str, observation_limit: int = 500):
    """Get one tracking run with its observation/change timeline."""
    details = tracking_log_store.run_details(run_id, observation_limit=observation_limit)
    if not details.get("run"):
        raise HTTPException(status_code=404, detail=f"Tracking run '{run_id}' not found")
    return _sanitize_proxy_payload(details)


@app.delete("/api/track/runs/{run_id}")
def delete_tracking_run(run_id: str):
    """Delete a stopped tracking run and its observations from historical analytics."""
    details = tracking_log_store.run_details(run_id, observation_limit=1)
    run = details.get("run")
    if not run:
        raise HTTPException(status_code=404, detail=f"Tracking run '{run_id}' not found")
    if run.get("ended_at") is None:
        raise HTTPException(
            status_code=409,
            detail="Stop the proxy before deleting its tracking history"
        )

    deleted = tracking_log_store.delete_run(run_id)
    if not deleted:
        raise HTTPException(status_code=500, detail=f"Tracking run '{run_id}' could not be deleted")

    return {
        "status": "success",
        "message": f"Deleted tracking run '{run_id}'",
        "run_id": run_id
    }


@app.get("/api/track/analytics")
def get_tracking_analytics():
    """Summarize proxy stability by expected state and lifetime hours."""
    return tracking_log_store.analytics()


@app.get("/api/target-pool")
def get_target_pool_status():
    """Get target-prefix pool automation status."""
    return _sanitize_proxy_payload(target_pool_keeper.status())


@app.post("/api/target-pool/start")
async def start_target_pool(request: TargetPoolStartRequest):
    """Start automation that keeps tracked proxies inside the target IP prefixes."""
    status = await target_pool_keeper.start(request)
    return _sanitize_proxy_payload({"status": "success", "target_pool": status})


@app.post("/api/target-pool/stop")
async def stop_target_pool():
    """Stop target pool replacement automation without stopping tracked proxies."""
    status = await target_pool_keeper.stop()
    return _sanitize_proxy_payload({"status": "success", "target_pool": status})


@app.post("/api/target-pool/reconcile")
async def reconcile_target_pool():
    """Run one immediate target pool health/replacement pass."""
    status = await target_pool_keeper.reconcile_once()
    return _sanitize_proxy_payload({"status": "success", "target_pool": status})


@app.post("/api/track/config")
def set_tracking_config(request: TrackingConfigRequest):
    """Set tracking configuration."""
    old_interval = tracking_manager.get_interval()
    tracking_manager.set_interval(request.interval_minutes)

    if scheduler.get_job('tracking_check'):
        scheduler.reschedule_job(
            'tracking_check',
            trigger='interval',
            minutes=request.interval_minutes
        )

    return {
        "status": "success",
        "message": f"Tracking interval updated from {old_interval} to {request.interval_minutes} minutes",
        "old_interval": old_interval,
        "new_interval": request.interval_minutes
    }

@app.get("/api/debug/ip_change")
async def debug_ip_change():
    """Debug endpoint to broadcast a synthetic IP change event"""
    sessions_dict = tracking_manager.get_all()
    target_session = "DEBUG_SESSION"
    for sid in sessions_dict.keys():
        target_session = sid
        break

    await ws_manager.broadcast({
        "type": "ip_change",
        "session": target_session,
        "old_ip": "41.242.137.88",
        "new_ip": "102.89.34.12",
        "city": "Abuja",
        "isp": "MTN Nigeria",
        "changed_ip": True,
        "changed_location": False,
        "timestamp": time.time()
    })
    return {"status": "simulated", "session": target_session}

# --- WebSocket for Streaming Results ---

@app.websocket("/ws/check")
async def websocket_check_proxies(websocket: WebSocket):
    """
    WebSocket endpoint for streaming proxy check results.

    Client sends: {"proxies": [...], "protocol": "http"}
    Server sends: {"type": "progress", "completed": 5, "total": 100, "result": {...}}
    Server sends: {"type": "complete", "total": 100, "duration": 12.5}
    """
    if await _reject_unauthorized_websocket(websocket):
        return

    await websocket.accept()

    try:
        # Receive check request
        data = await websocket.receive_text()
        request = _validated_check_request_from_payload(
            json.loads(data),
            require_explicit_proxies=True
        )
        proxies = _resolve_check_targets(request, require_explicit_proxies=True)

        total = len(proxies)
        completed = 0
        start_time = time.time()

        # Send start message
        await websocket.send_json({
            "type": "start",
            "total": total,
            "protocol": request.protocol
        })

        # Stream results
        async for result in check_proxies_stream(
            proxies,
            protocol=request.protocol,
            max_concurrent=MAX_CONCURRENT,
            timeout=PROXY_TIMEOUT
        ):
            completed += 1
            try:
                await websocket.send_json({
                    "type": "progress",
                    "completed": completed,
                    "total": total,
                    "result": _sanitize_proxy_payload(result)
                })
            except Exception as e:
                logger.error(f"Error sending progress: {e}")
                break

        # Send completion message
        duration = time.time() - start_time
        await websocket.send_json({
            "type": "complete",
            "total": total,
            "duration": round(duration, 2),
            "proxies_per_second": round(total / duration, 2) if duration > 0 else 0
        })

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during check")
    except json.JSONDecodeError as e:
        await websocket.send_json({"type": "error", "message": f"Invalid JSON: {e}"})
    except HTTPException as e:
        await websocket.send_json({"type": "error", "message": e.detail})
    except Exception as e:
        logger.exception(f"Error in WebSocket check: {e}")
        try:
            await websocket.send_json({"type": "error", "message": "Proxy scan failed"})
        except:
            pass


@app.websocket("/ws/iproyal-check")
async def websocket_iproyal_check(websocket: WebSocket):
    """Stream generated IPRoyal scan progress one checked proxy at a time."""
    if await _reject_unauthorized_websocket(websocket):
        return

    await websocket.accept()

    try:
        payload = json.loads(await websocket.receive_text())
        request = IPRoyalCheckRequest(**payload)
        target_prefixes = set(request.target_ip_prefixes or [])
        target_goal = request.target_match_count if target_prefixes else 0
        attempts_allowed = request.max_attempts if target_goal > 0 else 1
        planned_total = request.proxy_count * attempts_allowed
        generated_count = 0
        completed = 0
        accepted_count = 0
        results: List[Dict[str, Any]] = []
        start_time = time.time()

        await websocket.send_json({
            "type": "start",
            "scan_type": "iproyal",
            "total": planned_total,
            "attempts_allowed": attempts_allowed,
            "protocol": request.protocol,
            "criteria": {
                "requested_location": request.location,
                "requested_state": _title_from_slug(_state_slug_from_location(request.location)),
                "target_ip_prefixes": sorted(target_prefixes),
                "high_end_pool": request.high_end_pool,
                "pool": "high-end" if request.high_end_pool else "standard",
            },
        })

        for attempt_index in range(attempts_allowed):
            proxies_to_check = await generate_iproyal_proxy_list(request)
            generated_count += len(proxies_to_check)
            await websocket.send_json({
                "type": "attempt_start",
                "attempt": attempt_index + 1,
                "attempts_allowed": attempts_allowed,
                "generated_count": generated_count,
                "total": planned_total,
            })

            async for result in check_proxies_stream(
                proxies_to_check,
                protocol=request.protocol,
                max_concurrent=MAX_CONCURRENT,
                timeout=PROXY_TIMEOUT,
                target_ip_prefixes=target_prefixes or None,
            ):
                completed += 1
                _annotate_requested_state(result, request.location)
                results.append(result)
                accepted = _is_iproyal_best_result(result)
                if accepted:
                    accepted_count += 1

                await websocket.send_json({
                    "type": "progress",
                    "completed": completed,
                    "total": planned_total,
                    "attempt": attempt_index + 1,
                    "attempts_allowed": attempts_allowed,
                    "accepted": accepted,
                    "accepted_count": accepted_count,
                    "result": _sanitize_proxy_payload(result),
                })

            if target_goal > 0 and accepted_count >= target_goal:
                break

        clean_mobile_results = [result for result in results if _is_clean_mobile(result)]
        best_results = [result for result in clean_mobile_results if _is_iproyal_best_result(result)]
        location_rejected_results = [
            result
            for result in clean_mobile_results
            if result.get("state_match") is False
        ]
        diagnostics = _build_iproyal_scan_diagnostics(
            results,
            location=request.location,
            generated_count=generated_count,
        )
        duration = time.time() - start_time

        await websocket.send_json({
            "type": "complete",
            "status": "success",
            "generated_count": generated_count,
            "checked_count": len(results),
            "clean_mobile_count": len(clean_mobile_results),
            "best_count": len(best_results),
            "attempts_completed": min(attempts_allowed, (generated_count + max(1, request.proxy_count) - 1) // max(1, request.proxy_count)),
            "target_ip_prefixes": sorted(target_prefixes),
            "target_match_count": target_goal,
            "location_rejected_count": len(location_rejected_results),
            "duration": round(duration, 2),
            "proxies_per_second": round(len(results) / duration, 2) if duration > 0 else 0,
            "criteria": {
                "status": "success",
                "risk_level": "CLEAN",
                "mobile": True,
                "state_match": True if bool(_state_slug_from_location(request.location)) else None,
                "requested_location": request.location,
                "requested_state": _title_from_slug(_state_slug_from_location(request.location)),
                "target_ip_prefixes": sorted(target_prefixes),
                "high_end_pool": request.high_end_pool,
                "pool": "high-end" if request.high_end_pool else "standard",
            },
            "diagnostics": diagnostics,
            "best_results": _sanitize_proxy_payload(best_results),
        })

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected during IPRoyal check")
    except json.JSONDecodeError as e:
        await websocket.send_json({"type": "error", "message": f"Invalid JSON: {e}"})
    except ValidationError as e:
        await websocket.send_json({"type": "error", "message": e.errors()})
    except HTTPException as e:
        await websocket.send_json({"type": "error", "message": e.detail})
    except Exception as e:
        logger.exception(f"Error in IPRoyal WebSocket check: {e}")
        try:
            await websocket.send_json({"type": "error", "message": "IPRoyal scan failed"})
        except:
            pass


@app.websocket("/ws/tracking")
async def websocket_tracking(websocket: WebSocket):
    """WebSocket endpoint for real-time tracking notifications."""
    if await _reject_unauthorized_websocket(websocket):
        return

    await ws_manager.connect(websocket)

    try:
        await websocket.send_text(json.dumps({
            "type": "connected",
            "message": "Connected to tracking notifications",
            "tracked_sessions": tracking_manager.count()
        }))

        while True:
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)


# --- Scheduled Tasks ---

async def perform_tracking_checks():
    """Perform periodic checks on tracked proxies."""
    logger.info("Performing scheduled tracking checks...")

    tracked = tracking_manager.get_all()

    for session_id, data in tracked.items():
        try:
            from proxy_lib_async import check_single_proxy_async_wrapper

            previous = dict(data)
            result = await check_single_proxy_async_wrapper(
                data['proxy'],
                timeout=PROXY_TIMEOUT
            )

            log_event = tracking_log_store.log_observation(data, result or {}, previous)

            if result and result.get('status') == 'success':
                current_ip = result.get('query')
                current_region = result.get('local_region') or result.get('regionName') or result.get('region')
                current_city = result.get('local_city') or result.get('city')

                if log_event["changed_ip"]:
                    event = tracking_manager.record_ip_change(
                        session_id,
                        log_event.get("old_ip"),
                        current_ip,
                        current_city
                    )

                    logger.warning(
                        f"[ALERT] IP Changed for {session_id}: "
                        f"{log_event.get('old_ip')} -> {current_ip}"
                    )

                    await ws_manager.broadcast({
                        "type": "ip_change",
                        "session": session_id,
                        "old_ip": log_event.get("old_ip"),
                        "new_ip": current_ip,
                        "old_region": log_event.get("old_region"),
                        "old_city": log_event.get("old_city"),
                        "new_region": current_region,
                        "new_city": current_city,
                        "city": current_city,
                        "isp": result.get('isp'),
                        "timestamp": log_event["checked_at"],
                        "changed_ip": log_event["changed_ip"],
                        "changed_location": log_event["changed_location"],
                        "elapsed_seconds": log_event["elapsed_seconds"],
                        "expected_lifetime_hours": log_event.get("expected_lifetime_hours"),
                        "lifetime_progress": log_event.get("lifetime_progress")
                    })
                elif log_event["changed_location"]:
                    logger.info(
                        "[TRACKING] Location drift for %s without IP change: %s/%s -> %s/%s",
                        session_id,
                        log_event.get("old_region"),
                        log_event.get("old_city"),
                        current_region,
                        current_city,
                    )

                tracking_manager.update(session_id, {
                    'last_ip': current_ip,
                    'last_check': time.time(),
                    'last_region': current_region,
                    'last_city': current_city,
                    'last_result': result
                })
            else:
                tracking_manager.update(session_id, {
                    'last_check': time.time(),
                    'last_result': previous.get('last_result', result)
                })

        except Exception as e:
            logger.error(f"Error checking tracked session {session_id}: {e}")

    if tracked:
        try:
            # Tell frontend the check loop finished so it can update "Last Update"
            await ws_manager.broadcast({
                "type": "tracking_check_complete",
                "timestamp": time.time()
            })
        except Exception as e:
            logger.error(f"Error broadcasting tracking complete: {e}")


# --- Main Entry Point ---

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("DEBUG", "false").lower() == "true"

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=debug,
        log_level="info"
    )
