"""
IP Validation Providers - Multi-Service Fallback System
=======================================================

This module provides a unified interface for multiple IP validation services
with automatic fallback when one service fails or is rate-limited.

Supported Providers:
1. ip-api.com (default, free tier: 45 req/min)
2. ipapi.co (free tier: 1000 req/day, 30000 req/month)
3. ipinfo.io (free tier: 50000 req/month)

Usage:
    from ip_providers import IPValidator
    
    validator = IPValidator()
    result = await validator.validate_ip(proxy_url)
"""
import requests
import time
import logging
import os
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ProviderStatus(Enum):
    """Status of a provider."""
    HEALTHY = "healthy"
    RATE_LIMITED = "rate_limited"
    FAILED = "failed"


@dataclass
class ProviderInfo:
    """Information about a provider's state."""
    name: str
    status: ProviderStatus
    last_error: Optional[str] = None
    rate_limit_until: Optional[float] = None
    request_count: int = 0


class BaseIPProvider:
    """Base class for IP validation providers."""
    
    name: str = "base"
    rate_limit_per_minute: int = 45
    
    def __init__(self):
        self.status = ProviderStatus.HEALTHY
        self.last_error = None
        self.rate_limit_until = None
        self.request_count = 0
    
    def build_url(self) -> str:
        """Build the API URL for this provider."""
        raise NotImplementedError
    
    def parse_response(self, data: Dict) -> Dict[str, Any]:
        """Parse provider-specific response into standard format."""
        raise NotImplementedError
    
    def is_rate_limited(self) -> bool:
        """Check if provider is currently rate limited."""
        if self.rate_limit_until and time.time() < self.rate_limit_until:
            return True
        # Reset status if rate limit expired
        if self.rate_limit_until and time.time() >= self.rate_limit_until:
            self.status = ProviderStatus.HEALTHY
            self.rate_limit_until = None
        return False
    
    def set_rate_limit(self, seconds: int = 60):
        """Set rate limit for this provider."""
        self.rate_limit_until = time.time() + seconds
        self.status = ProviderStatus.RATE_LIMITED
        logger.warning(f"[{self.name}] Rate limited for {seconds}s")


class IPApiProvider(BaseIPProvider):
    """
    ip-api.com provider.
    
    Free tier: 45 requests per minute
    Pro tier: Unlimited
    
    Response format:
    {
        "status": "success",
        "country": "Nigeria",
        "countryCode": "NG",
        "city": "Abuja",
        "regionName": "Federal Capital Territory",
        "isp": "MTN Nigeria",
        "as": "AS29465 MTN Nigeria",
        "mobile": true,
        "proxy": false,
        "hosting": false,
        "query": "105.112.123.45"
    }
    """
    
    name = "ip-api.com"
    rate_limit_per_minute = 45
    
    def build_url(self) -> str:
        fields = "status,country,countryCode,city,regionName,isp,as,mobile,proxy,hosting,query"
        return f"http://ip-api.com/json/?fields={fields}"
    
    def parse_response(self, data: Dict) -> Dict[str, Any]:
        """Parse ip-api.com response."""
        if data.get('status') == 'fail':
            return {
                'status': 'fail',
                'error': data.get('message', 'Unknown error'),
                'provider': self.name
            }
        
        return {
            'status': 'success',
            'query': data.get('query'),
            'country': data.get('country'),
            'country_code': data.get('countryCode'),
            'city': data.get('city'),
            'region': data.get('regionName'),
            'isp': data.get('isp'),
            'asn': data.get('as'),
            'mobile': data.get('mobile', False),
            'proxy': data.get('proxy', False),
            'hosting': data.get('hosting', False),
            'provider': self.name
        }


class IPApiCoProvider(BaseIPProvider):
    """
    ipapi.co provider.
    
    Free tier: 1000 requests per day, 30000 per month
    Paid: 100000+ per month
    
    Response format:
    {
        "ip": "105.112.123.45",
        "city": "Abuja",
        "region": "Federal Capital Territory",
        "country": "NG",
        "country_name": "Nigeria",
        "org": "MTN Nigeria",
        "asn": "AS29465",
        "mobile": true
    }
    """
    
    name = "ipapi.co"
    rate_limit_per_minute = 1000  # Per day actually
    
    def build_url(self) -> str:
        return "https://ipapi.co/json/"
    
    def parse_response(self, data: Dict) -> Dict[str, Any]:
        """Parse ipapi.co response."""
        if 'error' in data:
            return {
                'status': 'fail',
                'error': data.get('reason', data.get('error', 'Unknown error')),
                'provider': self.name
            }
        
        return {
            'status': 'success',
            'query': data.get('ip'),
            'country': data.get('country_name'),
            'country_code': data.get('country'),
            'city': data.get('city'),
            'region': data.get('region'),
            'isp': data.get('org'),
            'asn': data.get('asn'),
            'mobile': data.get('mobile', False),
            'proxy': False,  # Not provided
            'hosting': False,  # Not provided
            'provider': self.name
        }


class IPInfoProvider(BaseIPProvider):
    """
    ipinfo.io provider.
    
    Free tier: 50000 requests per month
    Paid: 100000+ per month
    
    Response format:
    {
        "ip": "105.112.123.45",
        "city": "Abuja",
        "region": "Federal Capital Territory",
        "country": "NG",
        "org": "AS29465 MTN Nigeria"
    }
    """
    
    name = "ipinfo.io"
    rate_limit_per_minute = 50000  # Per month actually
    
    def __init__(self, token: str = None):
        super().__init__()
        self.token = token or os.getenv("IPINFO_TOKEN")
    
    def build_url(self) -> str:
        if self.token:
            return f"https://ipinfo.io/json?token={self.token}"
        return "https://ipinfo.io/json"
    
    def parse_response(self, data: Dict) -> Dict[str, Any]:
        """Parse ipinfo.io response."""
        if 'error' in data or 'bogon' in data:
            return {
                'status': 'fail',
                'error': data.get('error', 'Unknown error'),
                'provider': self.name
            }
        
        # Parse org to get ASN and ISP
        org = data.get('org', '')
        asn = None
        isp = org
        if ' ' in org:
            parts = org.split(' ', 1)
            asn = parts[0]
            isp = parts[1] if len(parts) > 1 else org
        
        return {
            'status': 'success',
            'query': data.get('ip'),
            'country': data.get('country'),  # Country code
            'country_code': data.get('country'),
            'city': data.get('city'),
            'region': data.get('region'),
            'isp': isp,
            'asn': asn,
            'mobile': False,  # Not provided
            'proxy': False,  # Not provided
            'hosting': False,  # Not provided
            'provider': self.name
        }


class IPValidator:
    """
    Multi-provider IP validator with automatic fallback.
    
    Usage:
        validator = IPValidator()
        result = validator.validate(proxy_url, session)
        
        # Result contains:
        # - status: 'success' or 'fail'
        # - query: IP address
        # - country, city, isp, mobile, proxy, hosting
        # - provider: which provider was used
    """
    
    def __init__(self, providers: List[BaseIPProvider] = None):
        """
        Initialize validator with providers.
        
        Args:
            providers: List of provider instances. If None, uses default order.
        """
        if providers:
            self.providers = providers
        else:
            # Default provider order (ip-api.com first as it has most features)
            self.providers = [
                IPApiProvider(),
                IPApiCoProvider(),
                IPInfoProvider()
            ]
        
        # Track provider stats
        self.provider_stats = {p.name: ProviderInfo(
            name=p.name,
            status=ProviderStatus.HEALTHY
        ) for p in self.providers}
    
    def get_healthy_provider(self) -> Optional[BaseIPProvider]:
        """Get the first healthy provider."""
        for provider in self.providers:
            if not provider.is_rate_limited():
                return provider
        return None
    
    def validate(
        self,
        proxy_urls: Dict[str, str],
        session: requests.Session,
        timeout: int = 12
    ) -> Dict[str, Any]:
        """
        Validate IP through proxy using available providers.
        
        Args:
            proxy_urls: Dict with 'http' and 'https' proxy URLs
            session: requests.Session for connection reuse
            timeout: Request timeout in seconds
        
        Returns:
            Dict with IP validation results
        """
        last_error = None
        
        for provider in self.providers:
            # Skip rate-limited providers
            if provider.is_rate_limited():
                logger.debug(f"[{provider.name}] Skipping (rate limited)")
                continue
            
            try:
                url = provider.build_url()
                logger.debug(f"[{provider.name}] Making request to {url}")
                
                response = session.get(
                    url,
                    proxies=proxy_urls,
                    timeout=timeout,
                    headers={'User-Agent': 'ProxyChecker/2.0'}
                )
                
                provider.request_count += 1
                
                # Handle HTTP errors
                if response.status_code == 429:
                    # Rate limited
                    provider.set_rate_limit(60)
                    continue
                
                if response.status_code != 200:
                    last_error = f"HTTP {response.status_code}"
                    logger.warning(f"[{provider.name}] HTTP {response.status_code}")
                    continue
                
                # Check for empty response
                if not response.text or not response.text.strip():
                    last_error = "Empty response"
                    logger.warning(f"[{provider.name}] Empty response")
                    continue
                
                # Check for HTML response
                text = response.text.strip()
                if text.startswith('<'):
                    last_error = "HTML response (proxy error)"
                    logger.warning(f"[{provider.name}] HTML response")
                    continue
                
                # Parse JSON
                try:
                    data = response.json()
                except ValueError as e:
                    last_error = f"JSON error: {str(e)[:50]}"
                    logger.warning(f"[{provider.name}] JSON parse error")
                    continue
                
                # Parse provider-specific response
                result = provider.parse_response(data)
                
                if result.get('status') == 'fail':
                    last_error = result.get('error')
                    # Check for rate limit message
                    if 'rate limit' in str(last_error).lower():
                        provider.set_rate_limit(60)
                        continue
                    # For other errors, try next provider
                    continue
                
                # Success!
                logger.debug(f"[{provider.name}] Success: {result.get('query')}")
                return result
                
            except requests.exceptions.Timeout:
                last_error = f"Timeout after {timeout}s"
                logger.warning(f"[{provider.name}] Timeout")
                continue
            
            except requests.exceptions.ProxyError as e:
                # Proxy error - don't try other providers, return immediately
                return {
                    'status': 'fail',
                    'error': f"Proxy error: {str(e)[:80]}",
                    'error_type': 'proxy_error'
                }
            
            except requests.exceptions.ConnectionError as e:
                last_error = f"Connection error: {str(e)[:50]}"
                logger.warning(f"[{provider.name}] Connection error")
                continue
            
            except Exception as e:
                last_error = f"Error: {str(e)[:50]}"
                logger.error(f"[{provider.name}] Unexpected error: {e}")
                continue
        
        # All providers failed
        return {
            'status': 'fail',
            'error': last_error or "All providers failed",
            'error_type': 'all_providers_failed'
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get provider statistics."""
        return {
            name: {
                'status': info.status.value,
                'request_count': info.request_count,
                'rate_limit_until': info.rate_limit_until
            }
            for name, info in self.provider_stats.items()
        }


# Convenience function for single validation
def validate_ip(
    proxy_urls: Dict[str, str],
    session: requests.Session = None,
    timeout: int = 12
) -> Dict[str, Any]:
    """
    Validate IP through proxy.
    
    Convenience function that creates a validator if needed.
    """
    validator = IPValidator()
    
    if session is None:
        session = requests.Session()
        try:
            return validator.validate(proxy_urls, session, timeout)
        finally:
            session.close()
    
    return validator.validate(proxy_urls, session, timeout)


if __name__ == "__main__":
    # Test the providers
    print("IP Provider Test")
    print("=" * 50)
    
    validator = IPValidator()
    
    # Test without proxy (direct connection)
    print("\nTesting direct connection (no proxy):")
    result = validator.validate({}, requests.Session())
    print(f"Result: {result}")
    print(f"Stats: {validator.get_stats()}")
