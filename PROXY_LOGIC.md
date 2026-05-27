# Proxy Logic & Priority — Sports Arbitrage Umbrella

This document captures the proxy validation logic and priority system used across Sports Arbitrage projects.

---

## Projects Using Proxies

| Project | Purpose | Proxy Use Case |
|---------|---------|----------------|
| **Proxy Sentinel** | Real-time proxy health monitoring | Check validity, location, carrier, risk |
| **Real Bird Book Dashboard** | Arbitrage analytics | Identity management for soft bookies |
| **Value Trading Pipeline** | Value bet detection | Access multiple bookmakers simultaneously |

---

## Proxy Sentinel — Core Logic

### Supported Protocols
| Protocol | Support | Notes |
|----------|---------|-------|
| HTTP | ✅ Full | Standard proxy protocol |
| HTTPS | ✅ Full | SSL-terminating proxy |
| SOCKS4 | ✅ Full | Via aiohttp-socks |
| SOCKS5 | ✅ Full | Via aiohttp-socks (recommended) |

### Proxy String Format
```
host:port:username:password[:protocol]

Example:
geo.iproyal.com:12321:customer-user_session-abc123_country-ng:password123_socks5
```

### Session ID Extraction
Session IDs are extracted from the password field:
```
Format: ..._session-<SESSION_ID>_...
Extract: session-abc123 → SESSION_ID = "abc123"
```

---

## Carrier Validation (Nigeria-Specific)

### Valid Nigerian Carriers
```python
CARRIER_LIST = ['AIRTEL', 'MTN', 'SPECTRANET', 'GLOBACOM', '9MOBILE']
```

### Excluded Carriers (False Positives)
```python
EXCLUDED_CARRIERS = ['AIRTEL RWANDA']  # Not Nigerian
```

### SP 217 Verified Locations (FCT)
For ISP proxies claiming to be mobile (SP 217 = Spectranet):
```python
VERIFIED_SP217_FCT = ['Bwari', 'Abaji', 'Gwagwalada', 'Kuje', 'Kwali']
```

### Carrier Validation Logic
```python
def is_valid_carrier(data):
    isp_upper = data.get('isp', '').upper()
    
    # Check if ISP matches target carriers
    is_target = any(carrier in isp_upper for carrier in CARRIER_LIST)
    
    # Exclude false positives
    for excluded in EXCLUDED_CARRIERS:
        if excluded in isp_upper:
            is_target = False
            break
    
    # Special case: SP 217 (Spectranet) only valid in FCT
    is_sp217_verified = 'SP 217' in isp_upper and city in VERIFIED_SP217_FCT
    
    return is_target or is_sp217_verified
```

---

## Risk Analysis

### Risk Indicators
| Indicator | Source | Meaning |
|-----------|--------|---------|
| `hosting: true` | ip-api.com | IP is from a datacenter/cloud provider |
| `proxy: true` | ip-api.com | IP is a known proxy/VPN exit |
| `mobile: false` | ip-api.com | Not a mobile connection (less trusted for soft bookies) |

### Risk Classification
```python
def analyze_risk(data):
    is_hosting = data.get('hosting', False)
    is_proxy = data.get('proxy', False)
    
    if is_hosting or is_proxy:
        return "RISK"
    return "CLEAN"
```

### Acceptable Proxy Profile for Soft Bookies
| Attribute | Required | Why |
|-----------|----------|-----|
| `mobile: true` | Preferred | Mobile IPs appear as real users |
| `hosting: false` | Required | Datacenter IPs are flagged |
| `proxy: false` | Required | Known proxies are blocked |
| `is_valid_carrier: true` | Required | Must be Nigerian ISP |
| `risk_level: CLEAN` | Required | No detected risk indicators |

---

## IP Validation Providers (Priority Order)

### Provider Fallback Chain

| Priority | Provider | Free Tier | Features |
|----------|----------|-----------|----------|
| **1** | ip-api.com | 45 req/min | Mobile, proxy, hosting detection |
| 2 | ipapi.co | 1000 req/day | Mobile detection, ASN |
| 3 | ipinfo.io | 50000 req/month | Basic geo, ASN |

### Why ip-api.com First?
- **Only provider** that returns `mobile`, `proxy`, and `hosting` fields
- Critical for risk analysis
- Free tier sufficient for monitoring (< 45 proxies)

### Fallback Logic
```python
for provider in providers:
    if provider.is_rate_limited():
        continue  # Skip to next
    
    result = provider.validate(proxy)
    
    if result['status'] == 'success':
        return result
    
    if result['status'] == 'fail':
        continue  # Try next provider
```

---

## Current Proxy Provider: IPRoyal

### Configuration
| Setting | Value |
|---------|-------|
| **Type** | Rotating Residential |
| **Feature** | Sticky Time (session persistence) |
| **Protocol** | SOCKS5 |
| **Geo-targeting** | Nigeria |

### IPRoyal Proxy Format
```
geo.iproyal.com:12321:customer-USER_session-SESSION_ID_country-ng:PASSWORD_socks5
```

### Key Parameters
| Parameter | Purpose |
|-----------|---------|
| `session-<ID>` | Sticky session ID (keeps same IP) |
| `country-ng` | Target Nigeria |
| `city-<name>` | Optional city targeting |
| `_lifetime-<seconds>` | Session duration (max 24h for sticky) |

---

## Cost Comparison (Nigerian Proxies)

| Provider | Type | Price | Bandwidth |
|----------|------|-------|-----------|
| **IPRoyal** (Current) | Rotating Residential | ~$1.50/GB | Metered |
| IPRoyal ISP | Static Residential | ~$2/IP/month | Unlimited |
| Proxy-Cheap | Static Residential | $1.99/IP/month | Unlimited |
| PingProxies | Static ISP | $3.50/IP | Unlimited |

### Recommendation by Use Case

| Use Case | Recommended | Why |
|----------|-------------|-----|
| **Identity persistence** (weeks/months) | Static Residential | Fixed IP per identity |
| **Monitoring** (many proxies, short sessions) | Rotating (IPRoyal) | Cost-effective for bulk checks |
| **High-volume** (100+ identities) | Proxy-Cheap Static | Cheapest unlimited |

---

## Integration Points

### Proxy Sentinel API
```bash
# Check single proxy
POST /check
{
  "proxy": "geo.iproyal.com:12321:user:pass_socks5"
}

# Response
{
  "session": "abc123",
  "status": "success",
  "country": "Nigeria",
  "city": "Lagos",
  "isp": "MTN Nigeria",
  "mobile": true,
  "proxy": false,
  "hosting": false,
  "is_valid_carrier": true,
  "risk_level": "CLEAN"
}
```

### Tracking Sessions
```bash
# Start tracking
POST /track
{
  "session": "identity-001",
  "proxy": "geo.iproyal.com:12321:user_session-identity-001_country-ng:pass"
}

# Check tracked sessions
GET /tracked
```

---

## Related Files

| File | Location | Purpose |
|------|----------|---------|
| PROXY_RESEARCH.md | `Proxy_Check/` | Cost analysis, alternatives |
| proxy_lib_async.py | `Proxy_Check/backend/` | Core validation logic |
| ip_providers.py | `Proxy_Check/backend/` | Multi-provider fallback |

---

*Last updated: 2026-02-22*
