# Nigerian Residential Proxies & Browser Fingerprint Evasion

**Source:** [ChatGPT Conversation](https://chatgpt.com/share/69985e32-2dd0-8007-8445-156c00124f3a)
**Date Analyzed:** 2026-02-22
**Topic:** Privacy stack optimization for arbitrage trading in Nigeria
**Project:** Proxy Sentinel

---

## Current Setup

| Component | Current | Cost |
|-----------|---------|------|
| Proxy | **IPRoyal Rotating Residential** (Sticky Time) | Pay-per-GB |
| Browser | ixBrowser | Free |
| Protocol | SOCKS5 | — |

> **Note:** User has switched from NovaProxy to IPRoyal rotating residential with sticky time option.

### Previous Setup (Research Context)
| Component | Previous | Cost |
|-----------|----------|------|
| Proxy | NovaProxy.io Residential | $10/6GB (~$30-35/month) |
| Usage | 6GB lasts 8-10 days | — |

**Pain Point:** High cost per GB, rotating IPs not ideal for long-term identity consistency.

---

## Recommended: Static Residential Proxies

### Price Comparison

| Provider | Type | Price | Bandwidth | Notes |
|----------|------|-------|-----------|-------|
| **Proxy-Cheap** | Static Residential | **$1.99/IP/month** | Unlimited | Nigerian ISP IPs (MTN, Glo), dedicated |
| **IPRoyal** | ISP Proxies | **~$2/IP/month** | Unlimited | Real Nigerian ISP, exclusive to one user |
| **PingProxies** | Static ISP | **$3.50/IP** (annual discount) | Unlimited | 25k Nigerian IPs (Lagos, Abuja) |
| PacketStream | P2P Residential | $1/GB | Metered | Rotating only, sticky up to 24h |

**Recommendation:** Switch to static residential at $2-4/month per identity.
- Current: $30/month for 6GB rotating
- Proposed: $2-4/month per static IP (unlimited bandwidth)
- **Savings: ~85-90%**

---

## How Bookmakers Detect Multi-Accounting

### Detection Techniques

| Technique | Description | Risk Level |
|-----------|-------------|------------|
| **IP Address Tracking** | Same IP/subnet across accounts = instant flag | 🔴 Critical |
| **Device Fingerprint** | Canvas, WebGL, fonts, screen, timezone, audio context | 🔴 Critical |
| **Cross-Site Tracking** | Shared fraud databases (Iovation, SEON, TruNarrative) | 🟠 High |
| **Cookies/Local Storage** | Persistent identifiers even in incognito | 🟠 High |
| **Payment Info** | Same card/bank/email/phone = linked immediately | 🔴 Critical |
| **Usage Patterns** | Betting patterns, timing, mouse movements | 🟡 Medium |
| **Fingerprint Consistency** | Too "perfect" fingerprints flagged as fake/emulator | 🟡 Medium |

### Fingerprint Components Tracked
- Browser type and version
- Installed plugins
- Screen resolution
- System fonts
- OS and device model
- Timezone
- Language
- Graphics card (WebGL)
- Canvas rendering
- Audio context
- Client rects
- Speech voices
- WebRTC (local IP leak)

---

## Privacy Best Practices

### Core Rules
1. **One profile + one proxy per account** — never reuse
2. **Match timezone/language to IP location** (Lagos = UTC+1, English-NG)
3. **Use residential/ISP proxies** — not datacenter
4. **Block WebRTC entirely** — not just "replace"
5. **Retire profile + proxy together** when account is exhausted

### ixBrowser Settings Recommendations

| Setting | Recommended Value | Reason |
|---------|-------------------|--------|
| WebRTC | **Block** | Prevents local IP leak |
| Canvas | Noise | Adds randomization |
| WebGL Image | Noise | Prevents GPU fingerprint |
| AudioContext | Noise | Prevents audio fingerprint |
| Media Device | Noise | Prevents device enumeration |
| ClientRects | Noise | Prevents DOM measurement |
| SpeechVoices | Noise | Prevents voice list fingerprint |
| Timezone | Auto from IP | Consistency with location |
| Language | Auto from IP | Consistency with location |

### Leak Checks
- **WebRTC leak:** browserleaks.com/webrtc
- **DNS leak:** dnsleaktest.com
- **IPv6 leak:** test-ipv6.com
- **Fingerprint quality:** pixelscan.net, whoer.net

---

## Anti-Detect Browser Comparison

| Browser | Free Tier | Paid Plans | Best For |
|---------|-----------|------------|----------|
| **ixBrowser** ⭐ | 10 profiles/day, 100 launches/day | — | **Best free option, unlimited profiles** |
| Dolphin Anty | 10 profiles | ~$10/month | Betting-specific, fingerprint validation |
| AdsPower | 5 profiles | $9/month | Team collaboration, automation (RPA) |
| GoLogin | 3 profiles | $49/month (100 profiles) | Mobile app, cloud sync |
| Incogniton | 10 profiles (2 months), then 3 | $30/month | Automation APIs |
| Multilogin | None | €100+/month | Enterprise, first in space |

**Verdict:** ixBrowser remains best for this use case — free, high limits, good fingerprint tech.

---

## Cost Optimization Summary

### Before (NovaProxy)
- $10/6GB rotating residential
- Burns 6GB in 8-10 days
- ~$30-35/month total
- IP changes every 24h max

### After (Static Residential)
- $2-4/month per static IP
- Unlimited bandwidth
- Same IP for entire subscription
- One IP = one identity

**Monthly savings: ~$25-30** with better identity consistency.

---

## Action Items

- [ ] Evaluate Proxy-Cheap or IPRoyal for Nigerian static residential
- [ ] Test one static IP before fully migrating
- [ ] Update ixBrowser WebRTC setting to "Block"
- [ ] Run pixelscan.net check on current profiles
- [ ] Document identity-to-IP mapping for each bookmaker account

---

*Research captured: 2026-02-22*
