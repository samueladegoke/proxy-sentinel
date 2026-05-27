"""
Proxy Checker Library - Async Optimized Version
================================================
High-performance async proxy validation with aiohttp.

PERFORMANCE OPTIMIZATIONS:
1. True async with aiohttp (no thread pool overhead)
2. Large connection pool (200 connections)
3. Real-time progress streaming via WebSocket
4. Optimized timeout handling
5. Connection reuse across all requests
"""
import aiohttp
import asyncio
import maxminddb
import os
import time
import logging
import re
import ssl
import ipaddress
from html import unescape
from typing import Optional, Dict, Any, Tuple, List, Callable, AsyncGenerator, Set
from enum import Enum
import json

# SOCKS support for aiohttp
try:
    from aiohttp_socks import ProxyConnector
    from aiohttp_socks._errors import ProxyError as SocksProxyError
    SOCKS_SUPPORT = True
except ImportError:
    SOCKS_SUPPORT = False
    SocksProxyError = Exception  # Fallback to base Exception
    logging.warning("aiohttp-socks not installed. SOCKS proxy support limited.")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProxyProtocol(Enum):
    """Supported proxy protocols."""
    HTTP = "http"
    HTTPS = "https"
    SOCKS4 = "socks4"
    SOCKS5 = "socks5"


# Configuration
TIMEOUT = int(os.getenv("PROXY_TIMEOUT", "8"))  # Reduced from 12s
CONNECT_TIMEOUT = int(os.getenv("PROXY_CONNECT_TIMEOUT", "5"))  # Connection timeout
IP_PROBE_TIMEOUT = float(os.getenv("IP_PROBE_TIMEOUT", "4"))
IP_PROBE_CONNECT_TIMEOUT = float(os.getenv("IP_PROBE_CONNECT_TIMEOUT", "3"))
DB_PATH = os.getenv(
    "DBIP_MMDB_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "dbip-city-lite.mmdb",
    ),
)

# Carrier configuration
CARRIER_LIST = ['AIRTEL', 'MTN', 'SPECTRANET', 'GLOBACOM', '9MOBILE']
EXCLUDED_CARRIERS = ['AIRTEL RWANDA']
VERIFIED_SP217_FCT = ['Bwari', 'Abaji', 'Gwagwalada', 'Kuje', 'Kwali']

# IP validation providers (in order of preference)
# Fields to request from ip-api.com - must include mobile, proxy, hosting for accurate risk detection
IP_API_URL = "http://ip-api.com/json/?fields=status,message,country,countryCode,region,regionName,city,isp,org,mobile,proxy,hosting,query"
IP_ONLY_URL = os.getenv("IP_ONLY_URL", "http://ipv4.icanhazip.com")
DBIP_API_BASE_URL = os.getenv("DBIP_API_BASE_URL", "https://api.db-ip.com/v2").rstrip("/")
DBIP_API_KEY = os.getenv("DBIP_API_KEY", "free").strip()
DBIP_API_TIMEOUT = float(os.getenv("DBIP_API_TIMEOUT", "5"))
DBIP_API_MAX_CONCURRENT = int(os.getenv("DBIP_API_MAX_CONCURRENT", "10"))
DBIP_API_CACHE_TTL = int(os.getenv("DBIP_API_CACHE_TTL", "3600"))
DBIP_API_RATE_LIMIT_BACKOFF_SECONDS = int(os.getenv("DBIP_API_RATE_LIMIT_BACKOFF_SECONDS", "86400"))
BROWSERLEAKS_BASE_URL = os.getenv("BROWSERLEAKS_BASE_URL", "https://browserleaks.com")
BROWSERLEAKS_TIMEOUT = float(os.getenv("BROWSERLEAKS_TIMEOUT", "8"))
BROWSERLEAKS_CACHE_TTL = int(os.getenv("BROWSERLEAKS_CACHE_TTL", "86400"))
BROWSERLEAKS_CACHE_PATH = os.getenv(
    "BROWSERLEAKS_CACHE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "browserleaks_cache.json"),
)
BROWSERLEAKS_CRAWL_DELAY = int(os.getenv("BROWSERLEAKS_CRAWL_DELAY", "60"))
BROWSERLEAKS_FALLBACK_WAIT = os.getenv("BROWSERLEAKS_FALLBACK_WAIT", "true").lower() == "true"

IP_PROVIDERS = [
    {
        "name": "ip-api.com",
        "url": IP_API_URL,
        "timeout": 8
    }
]


class MaxMindDBManager:
    """Singleton manager for MaxMind database reader."""
    _instance = None
    _lock = asyncio.Lock()
    _reader = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def initialize(self, db_path: str = DB_PATH) -> bool:
        """Initialize the database reader."""
        async with self._lock:
            if self._reader is not None:
                return True
            
            if not os.path.exists(db_path):
                logger.warning(f"MaxMind DB not found at {db_path}")
                return False
            
            try:
                self._reader = maxminddb.open_database(db_path)
                logger.info(f"MaxMind DB initialized: {db_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to open MaxMind DB: {e}")
                return False
    
    def get_location(self, ip: str) -> Optional[Dict[str, Any]]:
        """Get geolocation data for an IP address."""
        if self._reader is None:
            return None
        
        try:
            return self._reader.get(ip)
        except Exception as e:
            logger.error(f"Geo lookup error for {ip}: {e}")
            return None
    
    def close(self):
        """Close the database reader."""
        if self._reader is not None:
            self._reader.close()
            self._reader = None
            logger.info("MaxMind DB closed")


# Global singleton
_db_manager = MaxMindDBManager()
_dbip_api_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_dbip_api_disabled_until = 0.0
_dbip_api_last_error: Optional[Dict[str, Any]] = None
_browserleaks_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_browserleaks_cache_loaded = False
_browserleaks_last_request_at = 0.0
_browserleaks_lock = asyncio.Lock()

_HTML_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_HTML_STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_BROWSERLEAKS_LOCATION_HEADING_RE = re.compile(
    r"<h3[^>]*>\s*IP Address Location\s*</h3>",
    re.IGNORECASE,
)
_BROWSERLEAKS_TABLE_ROW_RE = re.compile(
    r"<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>",
    re.IGNORECASE | re.DOTALL,
)
_BROWSERLEAKS_COORDS_RE = re.compile(
    r'id=["\']coords-data["\'][^>]*data-lat=["\']([^"\']+)["\'][^>]*data-lon=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_BROWSERLEAKS_COUNTRY_TITLE_RE = re.compile(r'title=["\']([^"\']+)\s+\([A-Z]{2}\)["\']')
_COUNTRY_CODE_SUFFIX_RE = re.compile(r"(?:\s*\(\s*[A-Z]{2}\s*\)\s*|\s+[A-Z]{2})$")


def _network_error_result(
    proxy: str,
    protocol: str,
    error: Exception,
    error_type: str = "network_error",
) -> Dict[str, Any]:
    """Return a failed proxy result when a task-level network/TLS error escapes."""
    session_id = "N/A"
    try:
        _, _, _, password, detected_protocol = parse_proxy_string(proxy)
        session_id = extract_session_id(password)
        if protocol == "http":
            protocol = detected_protocol
    except (ValueError, IndexError) as exc:
        logger.debug("Could not parse proxy metadata for network error result: %s", exc)

    message = str(error)[:100] or error.__class__.__name__
    return {
        "session": session_id,
        "status": "fail",
        "protocol": protocol,
        "error": f"Network/TLS error: {message}",
        "error_type": error_type,
    }


def parse_proxy_string(proxy_str: str) -> Tuple[str, str, str, str, str]:
    """Parse a proxy string into components."""
    if not proxy_str or not proxy_str.strip():
        raise ValueError("Empty proxy string")
    
    proxy_str = proxy_str.strip()
    protocol = "http"
    
    if "://" in proxy_str:
        protocol, proxy_str = proxy_str.split("://", 1)
        protocol = protocol.lower()
    
    parts = proxy_str.split(':')
    
    if len(parts) < 4:
        raise ValueError(f"Invalid proxy format: expected 4+ parts, got {len(parts)}")
    
    host, port, user, password = parts[0], parts[1], parts[2], parts[3]
    
    if len(parts) >= 5 and parts[4].lower() in ["http", "https", "socks4", "socks5"]:
        protocol = parts[4].lower()
    
    valid_protocols = ["http", "https", "socks4", "socks5"]
    if protocol not in valid_protocols:
        raise ValueError(f"Invalid protocol: {protocol}")
    
    try:
        port_num = int(port)
        if not (1 <= port_num <= 65535):
            raise ValueError(f"Port out of range: {port_num}")
    except ValueError:
        raise ValueError(f"Invalid port number: {port}")
    
    return host, port, user, password, protocol


def extract_session_id(password: str) -> str:
    """Extract session ID from password string."""
    if '_session-' in password:
        try:
            return password.split('_session-')[1].split('_')[0]
        except IndexError:
            pass
    return "N/A"


def analyze_risk(data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze proxy data for risk indicators."""
    is_hosting = data.get('hosting', False)
    is_proxy = data.get('proxy', False)
    city = data.get('local_city', data.get('city'))
    
    isp_upper = data.get('isp', '').upper()
    is_target_carrier = any(c in isp_upper for c in CARRIER_LIST)
    
    for excluded in EXCLUDED_CARRIERS:
        if excluded in isp_upper:
            is_target_carrier = False
            break
    
    is_sp217_verified = 'SP 217' in isp_upper and city in VERIFIED_SP217_FCT
    
    return {
        'is_valid_carrier': is_target_carrier or is_sp217_verified,
        'risk_level': "CLEAN" if not (is_hosting or is_proxy) else "RISK"
    }


async def validate_ip_with_provider(
    session: aiohttp.ClientSession,
    proxy_url: str,
    provider: dict,
    timeout: int
) -> Optional[Dict[str, Any]]:
    """Try to validate IP with a specific provider."""
    try:
        timeout_obj = aiohttp.ClientTimeout(total=provider.get("timeout", timeout))
        
        async with session.get(
            IP_API_URL,
            proxy=proxy_url,
            timeout=timeout_obj,
            ssl=False
        ) as response:
            if response.status != 200:
                return None
            
            # Check content type
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' not in content_type:
                return None
            
            text = await response.text()
            if not text or not text.strip():
                return None
            
            data = json.loads(text)
            
            if data.get('status') == 'fail':
                return None
            
            return data
            
    except (asyncio.TimeoutError, aiohttp.ClientError, json.JSONDecodeError):
        return None


def _clean_geo_value(value: Any) -> Optional[Any]:
    """Normalize empty geolocation values to None."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value if value is not None else None


def _set_geo_field(data: Dict[str, Any], key: str, value: Any) -> bool:
    value = _clean_geo_value(value)
    if value is None:
        return False
    data[key] = value
    return True


def _dbip_api_backoff_remaining(now: Optional[float] = None) -> int:
    now = time.monotonic() if now is None else now
    return max(0, int(_dbip_api_disabled_until - now))


def _record_dbip_api_error(ip: str, payload: Dict[str, Any]) -> None:
    global _dbip_api_disabled_until, _dbip_api_last_error

    error_code = str(payload.get("errorCode") or "").upper() or None
    error_message = str(payload.get("error") or "")[:240] or None
    rate_limit_codes = {"OVER_QUERY_LIMIT", "TEMPORARY_BLOCKED"}
    is_rate_limited = error_code in rate_limit_codes

    if is_rate_limited and DBIP_API_RATE_LIMIT_BACKOFF_SECONDS > 0:
        _dbip_api_disabled_until = max(
            _dbip_api_disabled_until,
            time.monotonic() + DBIP_API_RATE_LIMIT_BACKOFF_SECONDS,
        )

    _dbip_api_last_error = {
        "ip": ip,
        "code": error_code,
        "message": error_message,
        "rate_limited": is_rate_limited,
        "backoff_seconds": DBIP_API_RATE_LIMIT_BACKOFF_SECONDS if is_rate_limited else 0,
    }


def _apply_dbip_api_location(data: Dict[str, Any], dbip_geo: Dict[str, Any]) -> bool:
    """Apply DB-IP API geolocation as the primary local geolocation source."""
    city = _clean_geo_value(dbip_geo.get("city"))
    region = _clean_geo_value(
        dbip_geo.get("stateProv")
        or dbip_geo.get("state")
        or dbip_geo.get("regionName")
        or dbip_geo.get("region")
    )
    country = _clean_geo_value(dbip_geo.get("countryName") or dbip_geo.get("country"))
    country_code = _clean_geo_value(dbip_geo.get("countryCode"))

    applied = False
    applied |= _set_geo_field(data, "local_city", city)
    applied |= _set_geo_field(data, "local_region", region)
    applied |= _set_geo_field(data, "local_country", country)
    applied |= _set_geo_field(data, "local_country_code", country_code)

    latitude = _clean_geo_value(dbip_geo.get("latitude"))
    longitude = _clean_geo_value(dbip_geo.get("longitude"))
    if latitude is not None:
        data["local_lat"] = latitude
    if longitude is not None:
        data["local_lon"] = longitude

    if applied:
        data["geo_source"] = "db-ip-api"
        data["geo_provider"] = "DB-IP API"
        data["dbip_source"] = "api"
        data["dbip_city"] = city
        data["dbip_region"] = region
        data["dbip_country"] = country
        data["dbip_country_code"] = country_code

    return applied


def _apply_browserleaks_location(data: Dict[str, Any], browserleaks_geo: Dict[str, Any]) -> bool:
    """Apply BrowserLeaks' DB-IP-backed result after the primary DB-IP API is unavailable/incomplete."""
    if not browserleaks_geo:
        return False

    city = _clean_geo_value(browserleaks_geo.get("city"))
    region = _clean_geo_value(
        browserleaks_geo.get("stateProv")
        or browserleaks_geo.get("state")
        or browserleaks_geo.get("regionName")
        or browserleaks_geo.get("region")
    )
    country = _clean_geo_value(browserleaks_geo.get("countryName") or browserleaks_geo.get("country"))
    country_code = _clean_geo_value(browserleaks_geo.get("countryCode"))
    should_override = data.get("geo_source") == "db-ip-mmdb"

    applied = False
    if should_override or not data.get("local_city"):
        applied |= _set_geo_field(data, "local_city", city)
    if should_override or not data.get("local_region"):
        applied |= _set_geo_field(data, "local_region", region)
    if should_override or not data.get("local_country"):
        applied |= _set_geo_field(data, "local_country", country)
    if should_override or not data.get("local_country_code"):
        applied |= _set_geo_field(data, "local_country_code", country_code)

    latitude = _clean_geo_value(browserleaks_geo.get("latitude"))
    longitude = _clean_geo_value(browserleaks_geo.get("longitude"))
    if (should_override or data.get("local_lat") is None) and latitude is not None:
        data["local_lat"] = latitude
    if (should_override or data.get("local_lon") is None) and longitude is not None:
        data["local_lon"] = longitude

    if applied:
        if data.get("geo_source") == "db-ip-api":
            data["geo_fallback_source"] = "browserleaks-db-ip"
        else:
            data["geo_source"] = "browserleaks-db-ip"
            data["geo_provider"] = "BrowserLeaks (DB-IP)"
            data["dbip_source"] = "browserleaks"
        data["browserleaks_city"] = city
        data["browserleaks_region"] = region
        data["browserleaks_country"] = country
        data["browserleaks_country_code"] = country_code

    return applied


def _get_mmdb_name(record: Dict[str, Any], *path: str) -> Optional[str]:
    current: Any = record
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    if isinstance(current, dict):
        names = current.get("names", {})
        if isinstance(names, dict):
            return names.get("en") or next(iter(names.values()), None)
    return None


def _apply_mmdb_location(data: Dict[str, Any], ip: str) -> bool:
    """Apply downloaded DB-IP MMDB geolocation as a fallback source."""
    local_geo = _db_manager.get_location(ip)
    if not local_geo:
        return False

    city = _get_mmdb_name(local_geo, "city")
    country = _get_mmdb_name(local_geo, "country")
    country_code = local_geo.get("country", {}).get("iso_code")

    region = None
    subdivisions = local_geo.get("subdivisions", [])
    if subdivisions:
        region = _get_mmdb_name({"subdivision": subdivisions[0]}, "subdivision")

    applied = False
    if not data.get("local_city"):
        applied |= _set_geo_field(data, "local_city", city)
    if not data.get("local_region"):
        applied |= _set_geo_field(data, "local_region", region)
    if not data.get("local_country"):
        applied |= _set_geo_field(data, "local_country", country)
    if not data.get("local_country_code"):
        applied |= _set_geo_field(data, "local_country_code", country_code)

    location = local_geo.get("location", {})
    if isinstance(location, dict):
        if not data.get("local_lat") and location.get("latitude") is not None:
            data["local_lat"] = location.get("latitude")
        if not data.get("local_lon") and location.get("longitude") is not None:
            data["local_lon"] = location.get("longitude")

    if applied:
        if data.get("geo_source") == "db-ip-api":
            data["geo_fallback_source"] = "db-ip-mmdb"
        else:
            data["geo_source"] = "db-ip-mmdb"
            data["geo_provider"] = "DB-IP MMDB"
            data["dbip_source"] = "mmdb"

    return applied


async def lookup_dbip_api(
    session: aiohttp.ClientSession,
    ip: str,
    semaphore: Optional[asyncio.Semaphore] = None
) -> Optional[Dict[str, Any]]:
    """Lookup an exit IP with the DB-IP API, returning None when fallback is needed."""
    if not DBIP_API_KEY or not ip:
        return None

    now = time.monotonic()
    cached = _dbip_api_cache.get(ip)
    if cached and now - cached[0] < DBIP_API_CACHE_TTL:
        return dict(cached[1])

    backoff_remaining = _dbip_api_backoff_remaining(now)
    if backoff_remaining > 0:
        logger.info("DB-IP API skipped for %s: rate-limit backoff active for %ss", ip, backoff_remaining)
        return None

    async def fetch() -> Optional[Dict[str, Any]]:
        url = f"{DBIP_API_BASE_URL}/{DBIP_API_KEY}/{ip}"
        timeout = aiohttp.ClientTimeout(total=DBIP_API_TIMEOUT)
        try:
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    logger.warning("DB-IP API lookup failed for %s: HTTP %s", ip, response.status)
                    return None

                payload = await response.json(content_type=None)
                if not isinstance(payload, dict):
                    return None
                if payload.get("error") or payload.get("errorCode"):
                    _record_dbip_api_error(ip, payload)
                    logger.warning("DB-IP API returned an error for %s: %s", ip, payload)
                    return None

                if len(_dbip_api_cache) > 2048:
                    _dbip_api_cache.clear()
                _dbip_api_cache[ip] = (time.monotonic(), payload)
                return dict(payload)
        except (asyncio.TimeoutError, aiohttp.ClientError, ssl.SSLError, OSError, json.JSONDecodeError) as e:
            logger.warning("DB-IP API lookup unavailable for %s: %s", ip, str(e)[:120])
            return None

    if semaphore is not None:
        async with semaphore:
            return await fetch()
    return await fetch()


def _strip_html(value: str) -> str:
    if "<" not in value and "&" not in value:
        return " ".join(value.split())

    value = _HTML_SCRIPT_RE.sub("", value)
    value = _HTML_STYLE_RE.sub("", value)
    value = _HTML_TAG_RE.sub(" ", value)
    return " ".join(unescape(value).split())


def _browserleaks_location_table(html: str) -> str:
    """Return only the small location table; parsing the whole page is unnecessary."""
    heading = _BROWSERLEAKS_LOCATION_HEADING_RE.search(html)
    if not heading:
        return html

    table_start = html.rfind("<table", 0, heading.start())
    table_end = html.find("</table>", heading.end())
    if table_start == -1 or table_end == -1:
        return html
    return html[table_start:table_end + len("</table>")]


def _browserleaks_cell(location_html: str, label: str) -> Optional[str]:
    """Fast path for BrowserLeaks' simple two-column location rows."""
    marker = f"<tr><td>{label}</td><td"
    row_start = location_html.find(marker)
    if row_start == -1:
        return None

    value_start = location_html.find(">", row_start + len(marker))
    if value_start == -1:
        return None

    value_end = location_html.find("</td></tr>", value_start)
    if value_end == -1:
        return None

    return _strip_html(location_html[value_start + 1:value_end])


def _ensure_browserleaks_cache_loaded() -> None:
    global _browserleaks_cache_loaded

    if _browserleaks_cache_loaded or not BROWSERLEAKS_CACHE_PATH:
        return

    _browserleaks_cache_loaded = True
    if not os.path.exists(BROWSERLEAKS_CACHE_PATH):
        return

    now_monotonic = time.monotonic()
    now_wall = time.time()
    try:
        with open(BROWSERLEAKS_CACHE_PATH, "r", encoding="utf-8") as cache_file:
            payload = json.load(cache_file)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("BrowserLeaks persistent cache unavailable: %s", str(e)[:120])
        return

    if not isinstance(payload, dict):
        return

    entries = payload.get("entries", {})
    if not isinstance(entries, dict):
        return

    for ip, entry in entries.items():
        if not isinstance(ip, str) or not isinstance(entry, dict):
            continue
        cached_at = entry.get("cached_at")
        result = entry.get("result")
        if not isinstance(cached_at, (int, float)) or not isinstance(result, dict):
            continue
        age = max(0.0, now_wall - float(cached_at))
        if age < BROWSERLEAKS_CACHE_TTL:
            _browserleaks_cache[ip] = (now_monotonic - age, result)


def _save_browserleaks_cache() -> None:
    if not BROWSERLEAKS_CACHE_PATH:
        return

    now_monotonic = time.monotonic()
    now_wall = time.time()
    entries = {}
    for ip, (cached_at, result) in _browserleaks_cache.items():
        age = max(0.0, now_monotonic - cached_at)
        if age < BROWSERLEAKS_CACHE_TTL:
            entries[ip] = {
                "cached_at": now_wall - age,
                "result": result,
            }

    try:
        os.makedirs(os.path.dirname(BROWSERLEAKS_CACHE_PATH), exist_ok=True)
        tmp_path = f"{BROWSERLEAKS_CACHE_PATH}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as cache_file:
            json.dump({"entries": entries}, cache_file, separators=(",", ":"))
        os.replace(tmp_path, BROWSERLEAKS_CACHE_PATH)
    except OSError as e:
        logger.warning("BrowserLeaks persistent cache save failed: %s", str(e)[:120])


def _parse_browserleaks_lookup(html: str, ip: str) -> Optional[Dict[str, Any]]:
    location_html = _browserleaks_location_table(html)
    values: Dict[str, str] = {
        key: value
        for key, value in (
            ("country", _browserleaks_cell(location_html, "Country")),
            ("state/region", _browserleaks_cell(location_html, "State/Region")),
            ("city", _browserleaks_cell(location_html, "City")),
            ("isp", _browserleaks_cell(location_html, "ISP")),
            ("network", _browserleaks_cell(location_html, "Network")),
            ("usage type", _browserleaks_cell(location_html, "Usage Type")),
            ("timezone", _browserleaks_cell(location_html, "Timezone")),
        )
        if value
    }

    if not any(values.get(key) for key in ("city", "state/region", "country")):
        rows = _BROWSERLEAKS_TABLE_ROW_RE.findall(location_html)
        for key_html, value_html in rows:
            key = _strip_html(key_html).lower()
            value = _strip_html(value_html)
            if key and value:
                values[key] = value

    city = values.get("city")
    region = values.get("state/region")
    country = values.get("country")
    if country:
        country = _COUNTRY_CODE_SUFFIX_RE.sub("", country).strip()
    if not country:
        country_match = _BROWSERLEAKS_COUNTRY_TITLE_RE.search(location_html)
        if country_match:
            country = _strip_html(country_match.group(1))

    if not any([city, region, country]):
        return None

    coords_match = _BROWSERLEAKS_COORDS_RE.search(location_html)

    result: Dict[str, Any] = {
        "ipAddress": ip,
        "city": city,
        "stateProv": region,
        "countryName": country,
        "isp": values.get("isp"),
        "organization": values.get("organization"),
        "network": values.get("network"),
        "usageType": values.get("usage type"),
        "timezone": values.get("timezone"),
        "geo_source": "browserleaks-db-ip",
        "geo_provider": "BrowserLeaks (DB-IP)",
    }
    if coords_match:
        result["latitude"] = coords_match.group(1)
        result["longitude"] = coords_match.group(2)
    return {key: value for key, value in result.items() if value is not None}


async def lookup_browserleaks_html(
    session: aiohttp.ClientSession,
    ip: str,
    respect_crawl_delay: bool = True,
    wait_for_crawl_delay: bool = False,
) -> Optional[Dict[str, Any]]:
    """Low-volume BrowserLeaks lookup parser. BrowserLeaks publishes a 60s crawl delay."""
    global _browserleaks_last_request_at

    if not ip:
        return None

    _ensure_browserleaks_cache_loaded()

    now = time.monotonic()
    cached = _browserleaks_cache.get(ip)
    if cached and now - cached[0] < BROWSERLEAKS_CACHE_TTL:
        return dict(cached[1])

    async with _browserleaks_lock:
        cached = _browserleaks_cache.get(ip)
        if cached and time.monotonic() - cached[0] < BROWSERLEAKS_CACHE_TTL:
            return dict(cached[1])

        if respect_crawl_delay:
            elapsed = time.monotonic() - _browserleaks_last_request_at
            if _browserleaks_last_request_at and elapsed < BROWSERLEAKS_CRAWL_DELAY:
                delay = BROWSERLEAKS_CRAWL_DELAY - elapsed
                if not wait_for_crawl_delay:
                    logger.info("Skipping BrowserLeaks lookup for %s to respect crawl-delay", ip)
                    return None
                logger.info("Waiting %.1fs before BrowserLeaks lookup for %s to respect crawl-delay", delay, ip)
                await asyncio.sleep(delay)

        url = f"{BROWSERLEAKS_BASE_URL.rstrip('/')}/ip/{ip}"
        timeout = aiohttp.ClientTimeout(total=BROWSERLEAKS_TIMEOUT)
        try:
            async with session.get(url, timeout=timeout) as response:
                _browserleaks_last_request_at = time.monotonic()
                if response.status != 200:
                    logger.warning("BrowserLeaks lookup failed for %s: HTTP %s", ip, response.status)
                    return None
                html = await response.text()
        except (asyncio.TimeoutError, aiohttp.ClientError, ssl.SSLError, OSError) as e:
            logger.warning("BrowserLeaks lookup unavailable for %s: %s", ip, str(e)[:120])
            return None

    parsed = _parse_browserleaks_lookup(html, ip)
    if parsed:
        if len(_browserleaks_cache) > 512:
            _browserleaks_cache.clear()
        _browserleaks_cache[ip] = (time.monotonic(), parsed)
        _save_browserleaks_cache()
    return dict(parsed) if parsed else None


def _elapsed_ms(started_at: Optional[float]) -> Optional[float]:
    if started_at is None:
        return None
    return round((time.perf_counter() - started_at) * 1000, 2)


def _with_proxy_latency(result: Dict[str, Any], started_at: Optional[float]) -> Dict[str, Any]:
    latency_ms = _elapsed_ms(started_at)
    if latency_ms is not None:
        result["latency_ms"] = latency_ms
    return result


def _with_check_duration(result: Dict[str, Any], started_at: float) -> Dict[str, Any]:
    result["check_duration_ms"] = round((time.perf_counter() - started_at) * 1000, 2)
    return result


def _extract_ip_from_text(text: str) -> Optional[str]:
    """Extract a valid IP from simple what-is-my-IP text responses."""
    if not text:
        return None

    for token in re.split(r"[\s,;\"'<>]+", text.strip()):
        candidate = token.strip()
        if not candidate:
            continue
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if ip.version == 4:
            return str(ip)
    return None


async def check_single_proxy_exit_ip_async(
    proxy_str: str,
    session: aiohttp.ClientSession,
    protocol: str = "http",
    timeout: int = None,
    target_ip_prefixes: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """Fast path for target hunting: resolve only the proxy exit IP."""
    started_at = time.perf_counter()
    timeout = timeout if timeout is not None else IP_PROBE_TIMEOUT
    request_started_at = None

    try:
        host, port, user, password, detected_protocol = parse_proxy_string(proxy_str)
        protocol = protocol if protocol != "http" else detected_protocol
    except ValueError as e:
        return _with_check_duration({"session": "N/A", "status": "error", "error": str(e)}, started_at)

    session_id = extract_session_id(password)

    try:
        timeout_obj = aiohttp.ClientTimeout(total=timeout, connect=min(IP_PROBE_CONNECT_TIMEOUT, timeout))

        if protocol in ["socks4", "socks5"] and SOCKS_SUPPORT:
            connector = ProxyConnector.from_url(
                f"{protocol}://{user}:{password}@{host}:{port}",
                limit=1
            )
            async with aiohttp.ClientSession(connector=connector, timeout=timeout_obj) as socks_session:
                request_started_at = time.perf_counter()
                async with socks_session.get(IP_ONLY_URL, timeout=timeout_obj, ssl=False) as response:
                    text = await response.text()
        else:
            proxy_url = f"http://{user}:{password}@{host}:{port}"
            request_started_at = time.perf_counter()
            async with session.get(IP_ONLY_URL, proxy=proxy_url, timeout=timeout_obj, ssl=False) as response:
                text = await response.text()

        if response.status != 200:
            return _with_check_duration(_with_proxy_latency({
                "session": session_id,
                "status": "fail",
                "protocol": protocol,
                "error": f"IP probe HTTP {response.status}",
                "error_type": "ip_probe_http_error",
            }, request_started_at), started_at)

        ip = _extract_ip_from_text(text)
        if not ip:
            return _with_check_duration(_with_proxy_latency({
                "session": session_id,
                "status": "fail",
                "protocol": protocol,
                "error": "IP probe returned no IPv4 address",
                "error_type": "ip_probe_invalid_response",
            }, request_started_at), started_at)

        result: Dict[str, Any] = {
            "session": session_id,
            "status": "success",
            "protocol": protocol,
            "query": ip,
            "ip_probe_only": True,
            "geo_quality": "ip-only-prefilter",
            "geo_confirmation_pending": True,
        }
        if target_ip_prefixes:
            result["target_ip_prefix_match"] = any(ip.startswith(prefix) for prefix in target_ip_prefixes)
            result["target_ip_prefixes"] = sorted(target_ip_prefixes)
        return _with_check_duration(_with_proxy_latency(result, request_started_at), started_at)

    except asyncio.TimeoutError:
        error = TimeoutError(f"Timeout after {timeout}s")
        return _with_check_duration(_network_error_result(proxy_str, protocol, error, "timeout"), started_at)
    except (ssl.SSLError, aiohttp.ClientError, OSError) as e:
        return _with_check_duration(_network_error_result(proxy_str, protocol, e), started_at)
    except Exception as e:
        logger.exception("Unexpected fast IP probe error for proxy %s", session_id)
        return _with_check_duration(_network_error_result(proxy_str, protocol, e, "unknown"), started_at)


async def check_single_proxy_async(
    proxy_str: str,
    session: aiohttp.ClientSession,
    protocol: str = "http",
    timeout: int = None,
    dbip_semaphore: Optional[asyncio.Semaphore] = None,
    browserleaks_wait: Optional[bool] = None,
    target_ip_prefixes: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """Check a single proxy and attach full verification duration in milliseconds."""
    started_at = time.perf_counter()
    result = await _check_single_proxy_async_inner(
        proxy_str,
        session,
        protocol,
        timeout,
        dbip_semaphore,
        browserleaks_wait,
        target_ip_prefixes,
    )
    return _with_check_duration(result, started_at)


async def _check_single_proxy_async_inner(
    proxy_str: str,
    session: aiohttp.ClientSession,
    protocol: str = "http",
    timeout: int = None,
    dbip_semaphore: Optional[asyncio.Semaphore] = None,
    browserleaks_wait: Optional[bool] = None,
    target_ip_prefixes: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """
    Check a single proxy asynchronously.
    
    Args:
        proxy_str: Proxy string
        session: Shared aiohttp session (not used for SOCKS, we create our own)
        protocol: Proxy protocol
        timeout: Request timeout
    
    Returns:
        Dict with proxy check results
    """
    timeout = timeout or TIMEOUT
    
    try:
        host, port, user, password, detected_protocol = parse_proxy_string(proxy_str)
        protocol = protocol if protocol != "http" else detected_protocol
    except ValueError as e:
        return {"session": "N/A", "status": "error", "error": str(e)}
    
    session_id = extract_session_id(password)
    
    # For SOCKS proxies, we need to use ProxyConnector
    if protocol in ["socks4", "socks5"] and SOCKS_SUPPORT:
        request_started_at = None
        try:
            # Create connector for SOCKS proxy
            connector = ProxyConnector.from_url(
                f"{protocol}://{user}:{password}@{host}:{port}",
                limit=1
            )
            timeout_obj = aiohttp.ClientTimeout(total=timeout, connect=CONNECT_TIMEOUT)
            
            async with aiohttp.ClientSession(
                connector=connector,
                timeout=timeout_obj
            ) as socks_session:
                request_started_at = time.perf_counter()
                async with socks_session.get(
                    IP_API_URL,
                    timeout=timeout_obj,
                    ssl=False
                ) as response:
                    return await _process_response(
                        response,
                        session_id,
                        protocol,
                        session,
                        dbip_semaphore,
                        request_started_at,
                        browserleaks_wait,
                        target_ip_prefixes,
                    )
        
        except asyncio.TimeoutError:
            return _with_proxy_latency({
                "session": session_id,
                "status": "fail",
                "error": f"Timeout after {timeout}s",
                "error_type": "timeout"
            }, request_started_at)
        except aiohttp.ClientProxyConnectionError as e:
            return _with_proxy_latency({
                "session": session_id,
                "status": "fail",
                "error": f"Proxy connection failed: {str(e)[:80]}",
                "error_type": "proxy_error"
            }, request_started_at)
        except aiohttp.ClientConnectorError as e:
            return _with_proxy_latency({
                "session": session_id,
                "status": "fail",
                "error": f"Connection failed: {str(e)[:80]}",
                "error_type": "connection_error"
            }, request_started_at)
        
        except SocksProxyError as e:
            return _with_proxy_latency({
                "session": session_id,
                "status": "fail",
                "error": f"SOCKS proxy error: {str(e)[:80]}",
                "error_type": "socks_error"
            }, request_started_at)
        
        except aiohttp.ClientError as e:
            return _with_proxy_latency({
                "session": session_id,
                "status": "fail",
                "error": f"Client error: {str(e)[:80]}",
                "error_type": "client_error"
            }, request_started_at)
        except Exception as e:
            logger.exception(f"Unexpected error checking SOCKS proxy {session_id}")
            return _with_proxy_latency({
                "session": session_id,
                "status": "fail",
                "error": f"Unexpected error: {str(e)[:80]}",
                "error_type": "unknown"
            }, request_started_at)
    
    # HTTP/HTTPS proxy - use the shared session with proxy parameter
    proxy_url = f"http://{user}:{password}@{host}:{port}"
    request_started_at = None
    
    try:
        # Try ip-api.com first (with all required fields)
        timeout_obj = aiohttp.ClientTimeout(total=timeout, connect=CONNECT_TIMEOUT)
        
        request_started_at = time.perf_counter()
        async with session.get(
            IP_API_URL,
            proxy=proxy_url,
            timeout=timeout_obj,
            ssl=False
        ) as response:
            return await _process_response(
                response,
                session_id,
                protocol,
                session,
                dbip_semaphore,
                request_started_at,
                browserleaks_wait,
                target_ip_prefixes,
            )
    
    except asyncio.TimeoutError:
        return _with_proxy_latency({
            "session": session_id,
            "status": "fail",
            "error": f"Timeout after {timeout}s",
            "error_type": "timeout"
        }, request_started_at)
    
    except aiohttp.ClientProxyConnectionError as e:
        return _with_proxy_latency({
            "session": session_id,
            "status": "fail",
            "error": f"Proxy connection failed: {str(e)[:80]}",
            "error_type": "proxy_error"
        }, request_started_at)
    
    except aiohttp.ClientConnectorError as e:
        return _with_proxy_latency({
            "session": session_id,
            "status": "fail",
            "error": f"Connection failed: {str(e)[:80]}",
            "error_type": "connection_error"
        }, request_started_at)
    
    except aiohttp.ClientError as e:
        return _with_proxy_latency({
            "session": session_id,
            "status": "fail",
            "error": f"Client error: {str(e)[:80]}",
            "error_type": "client_error"
        }, request_started_at)
    
    except Exception as e:
        logger.exception(f"Unexpected error checking proxy {session_id}")
        return _with_proxy_latency({
            "session": session_id,
            "status": "fail",
            "error": f"Unexpected error: {str(e)[:80]}",
            "error_type": "unknown"
        }, request_started_at)


async def _process_response(
    response: aiohttp.ClientResponse,
    session_id: str,
    protocol: str,
    dbip_session: aiohttp.ClientSession,
    dbip_semaphore: Optional[asyncio.Semaphore] = None,
    request_started_at: Optional[float] = None,
    browserleaks_wait: Optional[bool] = None,
    target_ip_prefixes: Optional[Set[str]] = None
) -> Dict[str, Any]:
    """Process API response and return formatted result."""
    # Check HTTP status
    if response.status != 200:
        return _with_proxy_latency({
            "session": session_id,
            "status": "fail",
            "error": f"HTTP {response.status}",
            "error_type": "http_error"
        }, request_started_at)
    
    # Check content type
    content_type = response.headers.get('Content-Type', '')
    if 'application/json' not in content_type:
        text = await response.text()
        return _with_proxy_latency({
            "session": session_id,
            "status": "fail",
            "error": "Non-JSON response",
            "error_type": "invalid_response"
        }, request_started_at)
    
    # Parse JSON
    text = await response.text()
    proxy_latency_ms = _elapsed_ms(request_started_at)
    if not text or not text.strip():
        result = {
            "session": session_id,
            "status": "fail",
            "error": "Empty response",
            "error_type": "empty_response"
        }
        if proxy_latency_ms is not None:
            result["latency_ms"] = proxy_latency_ms
        return result
    
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        result = {
            "session": session_id,
            "status": "fail",
            "error": "Invalid JSON",
            "error_type": "json_error"
        }
        if proxy_latency_ms is not None:
            result["latency_ms"] = proxy_latency_ms
        return result
    
    # Check API status
    if data.get('status') == 'fail':
        result = {
            "session": session_id,
            "status": "fail",
            "error": data.get('message', 'API returned failure'),
            "error_type": "api_fail"
        }
        if proxy_latency_ms is not None:
            result["latency_ms"] = proxy_latency_ms
        return result
    
    # Success - normalize and add metadata
    data['status'] = 'success'  # Normalize ip-api 'ok' status to 'success'
    data['session'] = session_id
    data['protocol'] = protocol
    if proxy_latency_ms is not None:
        # Measures the proxy-mediated IP check request only; DB-IP/MMDB/risk work is tracked separately.
        data['latency_ms'] = proxy_latency_ms
    
    # Ensure boolean fields are actual booleans (ip-api returns them correctly, but coerce just in case)
    data['mobile'] = bool(data.get('mobile', False))
    data['hosting'] = bool(data.get('hosting', False))
    data['proxy'] = bool(data.get('proxy', False))

    if target_ip_prefixes:
        ip = data.get('query') or ''
        data['target_ip_prefix_match'] = any(ip.startswith(prefix) for prefix in target_ip_prefixes)
        data['target_ip_prefixes'] = sorted(target_ip_prefixes)
        if not data['target_ip_prefix_match']:
            data['geo_quality'] = 'skipped-non-target-prefix'
            data['geo_confirmation_pending'] = True
            data['risk_level'] = 'SKIPPED'
            data['risk_flags'] = ['non_target_ip_prefix']
            return data
    
    # DB-IP API is primary. BrowserLeaks is the main online fallback. MMDB is
    # only a provisional last resort when online sources are unavailable/skipped.
    if data.get('query'):
        ip = data.get('query')

        dbip_geo = await lookup_dbip_api(dbip_session, ip, dbip_semaphore)
        dbip_applied = _apply_dbip_api_location(data, dbip_geo) if dbip_geo else False

        browserleaks_applied = False
        wait_for_browserleaks = BROWSERLEAKS_FALLBACK_WAIT if browserleaks_wait is None else browserleaks_wait
        if not dbip_applied or not (data.get("local_city") and data.get("local_region")):
            browserleaks_geo = await lookup_browserleaks_html(
                dbip_session,
                ip,
                respect_crawl_delay=True,
                wait_for_crawl_delay=wait_for_browserleaks,
            )
            browserleaks_applied = _apply_browserleaks_location(data, browserleaks_geo) if browserleaks_geo else False

        mmdb_applied = False
        if not dbip_applied and not browserleaks_applied:
            mmdb_applied = _apply_mmdb_location(data, ip)
            if mmdb_applied:
                data["geo_quality"] = "provisional-mmdb"
                data["geo_confirmation_pending"] = True

        if dbip_applied or browserleaks_applied:
            data.pop("geo_quality", None)
            data.pop("geo_confirmation_pending", None)

        if not dbip_applied and not browserleaks_applied and not mmdb_applied:
            data["geo_source"] = "ip-api"
            data["geo_provider"] = "ip-api.com"
            data["dbip_source"] = "unavailable"
            data["geo_quality"] = "unconfirmed"
            data["geo_confirmation_pending"] = True
        elif dbip_applied or browserleaks_applied:
            data["geo_quality"] = "online-confirmed"
            data["geo_confirmation_pending"] = False
    
    # Risk analysis
    risk_data = analyze_risk(data)
    data.update(risk_data)
    
    return data


async def check_proxies_stream(
    proxy_list: List[str],
    protocol: str = "http",
    max_concurrent: int = 100,
    timeout: int = None,
    progress_callback: Callable[[int, int, Dict], None] = None,
    browserleaks_wait: bool = False,
    target_ip_prefixes: Optional[Set[str]] = None,
    ip_only: bool = False
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Check proxies with streaming results.
    
    Yields results as they complete, enabling real-time progress updates.
    
    Args:
        proxy_list: List of proxy strings
        protocol: Default proxy protocol
        max_concurrent: Maximum concurrent checks (default 100)
        timeout: Request timeout
        progress_callback: Optional callback(completed, total, result)
    
    Yields:
        Dict with proxy check results
    """
    # Initialize MaxMind DB
    await _db_manager.initialize()
    
    total = len(proxy_list)
    completed = 0
    
    # Configure connection pool
    connector = aiohttp.TCPConnector(
        limit=max_concurrent,
        limit_per_host=max_concurrent if ip_only else 20,
        ttl_dns_cache=300,
        enable_cleanup_closed=True
    )
    
    timeout_obj = aiohttp.ClientTimeout(total=timeout or TIMEOUT, connect=CONNECT_TIMEOUT)
    
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout_obj,
        trust_env=True
    ) as session:
        semaphore = asyncio.Semaphore(max_concurrent)
        dbip_semaphore = asyncio.Semaphore(max(1, DBIP_API_MAX_CONCURRENT))
        
        async def check_with_semaphore(proxy: str) -> Dict[str, Any]:
            nonlocal completed
            async with semaphore:
                try:
                    if ip_only:
                        result = await check_single_proxy_exit_ip_async(
                            proxy,
                            session,
                            protocol,
                            timeout,
                            target_ip_prefixes=target_ip_prefixes,
                        )
                    else:
                        result = await check_single_proxy_async(
                            proxy,
                            session,
                            protocol,
                            timeout,
                            dbip_semaphore,
                            browserleaks_wait=browserleaks_wait,
                            target_ip_prefixes=target_ip_prefixes,
                        )
                except (ssl.SSLError, aiohttp.ClientError, OSError) as e:
                    logger.warning("Proxy task network/TLS failure: %s", str(e)[:120])
                    result = _network_error_result(proxy, protocol, e)
                except Exception as e:
                    logger.exception("Unexpected proxy task failure")
                    result = _network_error_result(proxy, protocol, e, "unknown")
                result.setdefault("proxy", proxy)
                result.setdefault("input_proxy", proxy)
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, result)
                return result
        
        proxy_iter = iter(proxy_list)
        pending: Set[asyncio.Task] = set()

        def schedule_next() -> bool:
            try:
                proxy = next(proxy_iter)
            except StopIteration:
                return False
            pending.add(asyncio.create_task(check_with_semaphore(proxy)))
            return True

        for _ in range(min(max_concurrent, total)):
            schedule_next()

        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                yield await task
                schedule_next()


async def check_proxies_batch_async(
    proxy_list: List[str],
    protocol: str = "http",
    max_concurrent: int = 100,
    timeout: int = None,
    browserleaks_wait: bool = False,
    target_ip_prefixes: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    """
    Check all proxies and return results.
    
    For streaming results, use check_proxies_stream instead.
    """
    results = []
    async for result in check_proxies_stream(
        proxy_list,
        protocol,
        max_concurrent,
        timeout,
        browserleaks_wait=browserleaks_wait,
        target_ip_prefixes=target_ip_prefixes,
    ):
        results.append(result)
    return results


def cleanup():
    """Cleanup resources."""
    _db_manager.close()


def get_db_stats():
    """Return database manager status."""
    backoff_remaining = _dbip_api_backoff_remaining()
    last_error = dict(_dbip_api_last_error) if _dbip_api_last_error else None
    if last_error is not None:
        last_error["backoff_remaining_seconds"] = backoff_remaining

    return {
        "db_path": DB_PATH,
        "reader_active": _db_manager._reader is not None,
        "db_exists": os.path.exists(DB_PATH),
        "dbip_api_enabled": bool(DBIP_API_KEY),
        "dbip_api_key_mode": "free" if DBIP_API_KEY.lower() == "free" else "configured",
        "dbip_api_available": bool(DBIP_API_KEY) and backoff_remaining == 0,
        "dbip_api_rate_limited": backoff_remaining > 0,
        "dbip_api_backoff_remaining_seconds": backoff_remaining,
        "dbip_api_last_error": last_error,
        "dbip_api_base_url": DBIP_API_BASE_URL,
        "dbip_api_cache_size": len(_dbip_api_cache),
        "browserleaks_base_url": BROWSERLEAKS_BASE_URL,
        "browserleaks_cache_size": len(_browserleaks_cache),
        "browserleaks_crawl_delay_seconds": BROWSERLEAKS_CRAWL_DELAY,
        "browserleaks_fallback_wait": BROWSERLEAKS_FALLBACK_WAIT,
        "browserleaks_bulk_wait": False,
        "geo_primary_source": "db-ip-api" if DBIP_API_KEY else "browserleaks-db-ip",
        "geo_fallback_source": "browserleaks-db-ip -> db-ip-mmdb"
    }


# Synchronous wrapper for backward compatibility
def check_proxies_batch(proxy_list: list, protocol: str = "http", max_workers: int = 50, timeout: int = None) -> list:
    """Synchronous wrapper for backward compatibility."""
    return asyncio.run(check_proxies_batch_async(proxy_list, protocol, max_workers, timeout))


def check_single_proxy(proxy_str: str, protocol: str = "http", timeout: int = None, session=None) -> Dict[str, Any]:
    """Synchronous wrapper for single proxy check."""
    return asyncio.run(check_single_proxy_async_wrapper(proxy_str, protocol, timeout))


async def check_single_proxy_async_wrapper(proxy_str: str, protocol: str = "http", timeout: int = None) -> Dict[str, Any]:
    """Async wrapper for single proxy check."""
    await _db_manager.initialize()
    
    connector = aiohttp.TCPConnector(limit=1)
    timeout_obj = aiohttp.ClientTimeout(total=timeout or TIMEOUT, connect=CONNECT_TIMEOUT)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout_obj) as session:
        return await check_single_proxy_async(
            proxy_str,
            session,
            protocol,
            timeout,
            browserleaks_wait=BROWSERLEAKS_FALLBACK_WAIT,
        )
