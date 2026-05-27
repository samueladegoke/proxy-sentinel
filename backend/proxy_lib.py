"""
Proxy Checker Library - Fixed Version
=====================================
This module provides proxy validation functionality with support for
HTTP, HTTPS, SOCKS4, and SOCKS5 protocols.

FIXES IMPLEMENTED:
1. Singleton MaxMind DB reader for performance
2. SOCKS4/SOCKS5 protocol support
3. Specific exception handling (Timeout, ProxyError, ConnectionError)
4. HTTP status code validation
5. Connection pooling via requests.Session
6. Thread-safe operations
7. Proper resource cleanup
8. Multi-provider IP validation with automatic fallback
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import maxminddb
import os
import threading
import logging
from typing import Optional, Dict, Any, Tuple
from enum import Enum

# Import multi-provider IP validation
from ip_providers import IPValidator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProxyProtocol(Enum):
    """Supported proxy protocols."""
    HTTP = "http"
    HTTPS = "https"
    SOCKS4 = "socks4"
    SOCKS5 = "socks5"


# Configuration with environment variable support
TIMEOUT = int(os.getenv("PROXY_TIMEOUT", "12"))
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "dbip-city-lite.mmdb"
)

# Carrier configuration
CARRIER_LIST = ['AIRTEL', 'MTN', 'SPECTRANET', 'GLOBACOM', '9MOBILE']
EXCLUDED_CARRIERS = ['AIRTEL RWANDA']  # Blacklisted carriers
VERIFIED_SP217_FCT = ['Bwari', 'Abaji', 'Gwagwalada', 'Kuje', 'Kwali']

# Global IP validator instance (multi-provider with fallback)
_ip_validator = None
_validator_lock = threading.Lock()


def get_ip_validator() -> IPValidator:
    """Get or create the global IP validator instance."""
    global _ip_validator
    if _ip_validator is None:
        with _validator_lock:
            if _ip_validator is None:
                _ip_validator = IPValidator()
                logger.info("IP Validator initialized with multi-provider support")
    return _ip_validator


class MaxMindDBManager:
    """
    Singleton manager for MaxMind database reader.
    
    FIX: Prevents reopening the database on every request.
    The database file is ~129MB and opening it repeatedly causes
    significant performance degradation.
    """
    _instance = None
    _lock = threading.Lock()
    _reader = None
    _db_path = None
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def initialize(self, db_path: str = DB_PATH) -> bool:
        """Initialize the database reader. Thread-safe."""
        with self._lock:
            if self._reader is not None:
                return True
            
            if not os.path.exists(db_path):
                logger.warning(f"MaxMind DB not found at {db_path}")
                return False
            
            try:
                self._reader = maxminddb.open_database(db_path)
                self._db_path = db_path
                logger.info(f"MaxMind DB initialized: {db_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to open MaxMind DB: {e}")
                return False
    
    def get_location(self, ip: str) -> Optional[Dict[str, Any]]:
        """Get geolocation data for an IP address."""
        if self._reader is None:
            if not self.initialize():
                return None
        
        try:
            return self._reader.get(ip)
        except Exception as e:
            logger.error(f"Geo lookup error for {ip}: {e}")
            return None
    
    def close(self):
        """Close the database reader."""
        with self._lock:
            if self._reader is not None:
                self._reader.close()
                self._reader = None
                logger.info("MaxMind DB closed")
    
    def __del__(self):
        self.close()


# Global singleton instance
_db_manager = MaxMindDBManager()


def create_session_with_retry() -> requests.Session:
    """
    Create a requests session with retry logic and connection pooling.
    
    FIX: Connection pooling improves performance for batch checks.
    """
    session = requests.Session()
    
    # Configure retry strategy
    retry_strategy = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=50
    )
    
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session


def parse_proxy_string(proxy_str: str) -> Tuple[str, str, str, str, str]:
    """
    Parse a proxy string into its components.
    
    Supports formats:
    - host:port:user:password
    - protocol://host:port:user:password
    - host:port:user:password:protocol
    
    Returns: (host, port, user, password, protocol)
    
    FIX: Added protocol detection and validation.
    """
    if not proxy_str or not proxy_str.strip():
        raise ValueError("Empty proxy string")
    
    proxy_str = proxy_str.strip()
    
    # Check for protocol prefix (protocol://host:port:...)
    protocol = "http"  # Default
    if "://" in proxy_str:
        protocol, proxy_str = proxy_str.split("://", 1)
        protocol = protocol.lower()
    
    parts = proxy_str.split(':')
    
    if len(parts) < 4:
        raise ValueError(f"Invalid proxy format: expected 4+ parts, got {len(parts)}")
    
    host, port, user, password = parts[0], parts[1], parts[2], parts[3]
    
    # Check for protocol suffix (host:port:user:password:protocol)
    if len(parts) >= 5 and parts[4].lower() in ["http", "https", "socks4", "socks5"]:
        protocol = parts[4].lower()
    
    # Validate protocol
    valid_protocols = ["http", "https", "socks4", "socks5"]
    if protocol not in valid_protocols:
        raise ValueError(f"Invalid protocol: {protocol}. Must be one of {valid_protocols}")
    
    # Validate port
    try:
        port_num = int(port)
        if not (1 <= port_num <= 65535):
            raise ValueError(f"Port out of range: {port_num}")
    except ValueError:
        raise ValueError(f"Invalid port number: {port}")
    
    return host, port, user, password, protocol


def build_proxy_url(host: str, port: str, user: str, password: str, protocol: str = "http") -> Dict[str, str]:
    """
    Build proxy URLs for requests library.
    
    FIX: Added SOCKS4/SOCKS5 support.
    
    Returns dict with 'http' and 'https' keys for requests.proxies
    """
    if protocol in ["socks4", "socks5"]:
        # SOCKS proxies use the same URL for both http and https
        proxy_url = f"{protocol}://{user}:{password}@{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    else:
        # HTTP/HTTPS proxies
        proxy_url = f"http://{user}:{password}@{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}


def extract_session_id(password: str) -> str:
    """Extract session ID from password string."""
    if '_session-' in password:
        try:
            return password.split('_session-')[1].split('_')[0]
        except IndexError:
            pass
    return "N/A"


def analyze_risk(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze proxy data for risk indicators.
    
    Returns dict with risk_level and is_valid_carrier fields.
    """
    is_hosting = data.get('hosting', False)
    is_proxy = data.get('proxy', False)
    
    # Get city from local data first (more accurate)
    city = data.get('local_city', data.get('city'))
    
    # Check carrier
    isp_upper = data.get('isp', '').upper()
    is_target_carrier = any(c in isp_upper for c in CARRIER_LIST)
    
    # Exclude blacklisted carriers
    for excluded in EXCLUDED_CARRIERS:
        if excluded in isp_upper:
            is_target_carrier = False
            break
    
    # Special case for SP 217 in verified FCT areas
    is_sp217_verified = 'SP 217' in isp_upper and city in VERIFIED_SP217_FCT
    
    return {
        'is_valid_carrier': is_target_carrier or is_sp217_verified,
        'risk_level': "CLEAN" if not (is_hosting or is_proxy) else "RISK"
    }


def check_single_proxy(
    proxy_str: str,
    protocol: str = "http",
    timeout: int = None,
    session: requests.Session = None
) -> Dict[str, Any]:
    """
    Check a single proxy and return structured data.
    
    Args:
        proxy_str: Proxy string in format host:port:user:password
        protocol: Proxy protocol (http, https, socks4, socks5)
        timeout: Request timeout in seconds
        session: Optional requests.Session for connection reuse
    
    Returns:
        Dict with proxy check results including:
        - session: Session ID
        - status: 'success' or 'fail'
        - query: IP address
        - city, country, isp, etc.
        - local_city, local_region: High-precision geo data
        - risk_level: 'CLEAN' or 'RISK'
        - is_valid_carrier: bool
    
    FIXES APPLIED:
    - Specific exception handling for better error messages
    - HTTP status code validation
    - SOCKS protocol support
    - Connection pooling via session parameter
    - Singleton MaxMind DB reader
    """
    timeout = timeout or TIMEOUT
    own_session = session is None
    
    try:
        # Parse proxy string
        host, port, user, password, detected_protocol = parse_proxy_string(proxy_str)
        # Use explicitly provided protocol over detected one
        protocol = protocol if protocol != "http" else detected_protocol
    except ValueError as e:
        return {"session": "N/A", "status": "error", "error": str(e)}
    
    # Build proxy URL
    try:
        proxy_urls = build_proxy_url(host, port, user, password, protocol)
    except ValueError as e:
        return {"session": "N/A", "status": "error", "error": str(e)}
    
    # Extract session ID
    session_id = extract_session_id(password)
    
    # Create session if not provided
    if own_session:
        session = create_session_with_retry()
    
    try:
        # Use multi-provider IP validator with automatic fallback
        logger.debug(f"[{session_id}] Validating IP via {protocol} proxy to {host}:{port}")
        
        validator = get_ip_validator()
        data = validator.validate(proxy_urls, session, timeout)
        
        # Check if validation failed
        if data.get('status') == 'fail':
            data['session'] = session_id
            data['protocol'] = protocol
            return data
        
        # Success - add session and protocol info
        data['session'] = session_id
        data['protocol'] = protocol
        
        # Local Geo Lookup using singleton manager
        if data.get('query'):
            ip = data.get('query')
            local_geo = _db_manager.get_location(ip)
            if local_geo:
                # Extract city with fallback
                city_names = local_geo.get('city', {}).get('names', {})
                data['local_city'] = city_names.get('en', data.get('city'))
                
                # Extract region/subdivision with fallback
                subdivisions = local_geo.get('subdivisions', [{}])
                if subdivisions:
                    region_names = subdivisions[0].get('names', {})
                    data['local_region'] = region_names.get('en', data.get('region'))
        
        # Add risk analysis
        risk_data = analyze_risk(data)
        data.update(risk_data)
        
        return data
    
    except requests.exceptions.Timeout:
        return {
            "session": session_id,
            "status": "fail",
            "error": f"Connection timeout after {timeout}s",
            "error_type": "timeout"
        }
    
    except requests.exceptions.ProxyError as e:
        return {
            "session": session_id,
            "status": "fail",
            "error": f"Proxy connection failed: {str(e)[:100]}",
            "error_type": "proxy_error"
        }
    
    except requests.exceptions.ConnectionError as e:
        return {
            "session": session_id,
            "status": "fail",
            "error": f"Connection failed: {str(e)[:100]}",
            "error_type": "connection_error"
        }
    
    except requests.exceptions.SSLError as e:
        return {
            "session": session_id,
            "status": "fail",
            "error": f"SSL error: {str(e)[:100]}",
            "error_type": "ssl_error"
        }
    
    except requests.exceptions.RequestException as e:
        return {
            "session": session_id,
            "status": "fail",
            "error": f"Request failed: {str(e)[:100]}",
            "error_type": "request_error"
        }
    
    except Exception as e:
        logger.exception(f"Unexpected error checking proxy {session_id}")
        return {
            "session": session_id,
            "status": "fail",
            "error": f"Unexpected error: {str(e)[:100]}",
            "error_type": "unknown"
        }
    
    finally:
        # Close session if we created it
        if own_session and session is not None:
            session.close()


def check_proxies_batch(
    proxy_list: list,
    protocol: str = "http",
    max_workers: int = 50,
    timeout: int = None
) -> list:
    """
    Check multiple proxies concurrently with connection pooling.
    
    FIX: Uses shared session for better connection reuse.
    """
    import concurrent.futures
    
    results = []
    session = create_session_with_retry()
    
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_proxy = {
                executor.submit(
                    check_single_proxy,
                    proxy,
                    protocol,
                    timeout,
                    session
                ): proxy
                for proxy in proxy_list
            }
            
            for future in concurrent.futures.as_completed(future_to_proxy):
                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as e:
                    logger.error(f"Future execution error: {e}")
    
    finally:
        session.close()
    
    return results


def cleanup():
    """Cleanup resources. Call on application shutdown."""
    _db_manager.close()


# Backward compatibility
def get_db_stats():
    """Return database manager status for debugging."""
    return {
        "db_path": DB_PATH,
        "reader_active": _db_manager._reader is not None,
        "db_exists": os.path.exists(DB_PATH)
    }


if __name__ == "__main__":
    # Test the module
    print("=" * 60)
    print("Proxy Library Test")
    print("=" * 60)
    
    # Test proxy parsing
    test_cases = [
        "geo.iproyal.com:11200:user:pass_session-TEST123",
        "socks5://proxy.example.com:1080:user:pass",
        "proxy.example.com:8080:user:pass:socks4",
    ]
    
    for test in test_cases:
        try:
            host, port, user, password, protocol = parse_proxy_string(test)
            print(f"✓ Parsed: {protocol}://{host}:{port}")
        except ValueError as e:
            print(f"✗ Error: {e}")
    
    print(f"\nDB Stats: {get_db_stats()}")
    cleanup()
