# Soft Router Provisioning: Can OpenWRT Auto-Configure Android VPN?

**Date**: 2026-06-11
**Status**: Research complete — negative findings across all 8 vectors

---

## Executive Summary

**A soft router (OpenWRT) CANNOT permanently alter an Android phone's network/VPN configuration when the phone connects to its WiFi.** Every attack vector investigated below is blocked by Android's security model, which treats network operators as untrusted. The OS enforces mandatory user confirmation for any network-layer interception capability. This is not a missing feature — it is a deliberate security property.

The **only** path to zero-touch system VPN on Android is **MDM Device Owner** provisioning, which requires either factory-reset QR code enrollment or pre-registered zero-touch. Neither can be triggered by a soft router.

---

## 1. DHCP Options on Android

### How Android DHCP Works

Android's DHCP client has evolved:
- **Android ≤ 5.x**: Used `dhcpcd` (standalone daemon)
- **Android 6.x – 9.x**: Used `netd` + Java `DhcpClient` in `frameworks/base/services/net/java/android/net/dhcp/`
- **Android 10+**: Uses `IpClient` in `packages/modules/NetworkStack/` (mainline module)

### Option 43 (Vendor Specific Information)

- **RFC 2132**: Option 43 carries vendor-specific opaque data, sub-option encoded
- **Purpose in practice**: Cable modem config files, CAPWAP AC discovery (WiFi APs), PXE boot servers
- **Android behavior**: Android's DHCP client **does not parse Option 43 for any system configuration purpose**. The `DhcpResults` class only stores: IP address, gateway, DNS servers, domain name, MTU, lease duration, server address, and vendor info as raw bytes — but no system service reads the raw vendor info
- **AOSP code paths checked**: `DhcpPacket.java` parses option 43 into a raw `byte[]` field; `LinkProperties.java` stores it. No `ConnectivityService` or `VpnService` code reads DHCP vendor options
- **Conclusion**: Not viable for pushing VPN config

### Option 252 (WPAD / Web Proxy Auto-Discovery)

- **RFC draft**: Option 252 provides a PAC (Proxy Auto-Config) URL
- **Android behavior**: 
  - **System-wide proxy**: Android's `ProxySelector` and `java.net.Proxy` do NOT support WPAD auto-discovery. System proxy must be set manually or via MDM
  - **Chrome on Android**: Supports PAC URLs but only through manual proxy settings (chrome://proxy), not DHCP Option 252
  - **Android WebView**: Does NOT support PAC at all. The captive portal browser window uses WebView
  - **Historical context**: Google explicitly removed WPAD support from Android's DHCP client to prevent PAC-based MITM attacks on public WiFi
- **Conclusion**: Not supported on Android. Deliberate design decision

### Option 121 (Classless Static Routes)

- **RFC 3442**: Classless static routes encoded as {dest/mask, next-hop} tuples
- **Android behavior**: Supported since Android 4.3 (API 18). `LinkProperties.addRoute()` processes option 121
- **Limitation**: ONLY adds IP routing table entries. Cannot:
  - Create VPN tunnels
  - Configure xfrm/IPSEC policies
  - Set firewall rules visible to apps
  - Redirect traffic through a non-existent interface
- **Conclusion**: Can inject routes, but routes alone do not create a tunnel. The tunnel must already exist (via app or user-configured VPN)

### Option 249 (Microsoft Classless Static Routes)

- **Origin**: Microsoft proprietary extension, older encoding than RFC 3442
- **Android behavior**: Not supported. Android's DHCP client only implements the RFC 3442 (option 121) format
- **Conclusion**: Irrelevant

### Bottom Line on DHCP

DHCP options on Android are **read-only data delivery** with no hook into system configuration. At best you can inject DNS servers and static routes — neither of which creates a VPN tunnel.

---

## 2. Android Captive Portal Detection

### How Android Detects Captive Portals (Android 5+)

The captive portal detection flow:

```
Phone connects to WiFi → gets IP via DHCP
  → ConnectivityService triggers NetworkMonitor
    → Sends HTTP GET to http://connectivitycheck.gstatic.com/generate_204
      (or http://www.google.com/blank.html for Chinese-market devices)
      → If HTTP 204: internet is available, no portal
      → If HTTP 302/200: portal detected → show "Sign in to network" notification
```

**Key implementation details**:
- `NetworkMonitor.java` in `frameworks/base/services/core/java/com/android/server/connectivity/` (or mainline `ConnectivityService`)
- The probe URL is configurable via `Settings.Global.CAPTIVE_PORTAL_HTTP_URL` and `CAPTIVE_PORTAL_HTTPS_URL` — but only via ADB/MDM, not by the network
- Android 8+ (Oreo) also validates `clients3.google.com` via HTTPS; if HTTPS is intercepted, the portal detection fails and the WiFi may be marked as "no internet"
- Some OEMs (Huawei, Xiaomi) use different probe URLs

### What the Captive Portal WebView Exposes

When Android detects a captive portal, it:
1. Shows a system notification: "Sign in to network"
2. When tapped, opens a **System WebView** (not a full Chrome browser) pointed at the portal URL
3. This WebView runs with **elevated system permissions** (`CaptivePortalLogin` process)

**The `CaptivePortal` API** (`android.net.CaptivePortal`):
```java
// Available only to system apps with CAPTIVE_PORTAL_LOGIN permission
public class CaptivePortal implements Parcelable {
    public void reportCaptivePortalDismissed();  // Tell OS portal is gone
    public void ignoreNetwork();                  // Tell OS to disconnect and forget
}
```

This API intentionally does NOT expose:
- Network configuration methods
- VPN setup methods
- System settings modification
- File system access for profile installation

### Can We Hook Into This Flow?

**What a captive portal page CAN do**:
- Display HTML content (instructions, credentials)
- Open URLs (including `intent://` URIs that may launch system settings pages)
- Use JavaScript within the WebView sandbox

**What a captive portal page CANNOT do**:
- Silently install certificates
- Modify system WiFi/VPN settings
- Install apps
- Write files outside the WebView sandbox
- Access `DevicePolicyManager` APIs (requires special permissions)

The project already implements the best possible captive portal flow: DNS redirect → portal page showing VPN setup instructions. The previous `captive_portal.py` + `vpn-setup.html` approach is the ceiling of what's achievable via captive portal alone.

### Android's Security Barrier

The reason captive portals can't configure VPN is fundamental: **if any WiFi network could silently configure a VPN on a connecting device, every public WiFi could MITM all traffic.** Android explicitly prevents this by:
1. Requiring user interaction for VPN configuration
2. Requiring `android.permission.CONTROL_VPN` (signature-level) to programmatically configure system VPN
3. Keeping the captive portal WebView sandboxed

---

## 3. OpenWRT + Android Provisioning Projects

### Known Projects

| Project | What It Does | Android VPN Config? |
|---------|-------------|---------------------|
| **nodogsplash** | Captive portal with splash page | No — shows content only |
| **CoovaChilli** | Captive portal + RADIUS auth | No — WiFi auth only |
| **PirateBox** | Offline file sharing captive portal | No |
| **GL.iNet routers** | Travel router with OpenWRT + WireGuard client | No — VPN runs on router, not phone |
| **FreeRADIUS-WPE** | Rogue RADIUS for credential capture | No — attack tool, not provisioning |
| **wifidog** | Captive portal gateway | No — WiFi auth only |
| **OpenWISP** | Network management with OpenWRT agents | No — manages routers, not clients |

### The Fundamental Gap

All OpenWRT captive portal projects stop at the WiFi authentication layer. None even attempt VPN configuration because it's architecturally impossible: the captive portal is an HTTP server serving HTML to a sandboxed WebView. There is no API bridge between "web page displayed in captive portal" and "Android system VPN settings."

### GL.iNet Travel Router: Closest but Wrong Direction

GL.iNet routers (Slate, Beryl, etc.) can:
- Run WireGuard/OpenVPN client — tunnel the router's WAN traffic
- Host a WiFi AP that phones connect to
- → Phone traffic flows through the router's VPN tunnel by default

This is the **travel router approach** mentioned in the PRD as "手机不带硬件（拒绝旅行路由器）" — explicitly rejected. But it's worth noting this is the only soft-router-based approach that works: the router terminates the VPN, not the phone.

---

## 4. DeviceAdmin / Device Owner Enrollment via Soft Router

### DeviceAdmin vs DeviceOwner vs ProfileOwner

| Mode | Setup Method | VPN Config Capability | Can Soft Router Trigger? |
|------|-------------|----------------------|--------------------------|
| **DeviceAdmin** | User enables in Settings | Set password policies, lock/wipe device | No — user must manually enable |
| **ProfileOwner** | MDM app install + enrollment | Manage work profile VPN | No — requires MDM app install |
| **DeviceOwner** | NFC bump or QR code at setup wizard | Full system VPN config, always-on | No — requires factory reset or NFC |

### Device Owner Provisioning Flow

The ONLY fully capable mode is Device Owner, which allows:
- `setAlwaysOnVpnPackage()` — set any VPN app as always-on
- `setGlobalSetting()` for VPN-related settings
- Certificate installation via `installKeyPair()`
- Managed configurations for VPN apps

**NFC provisioning**: Two phones touch → provisioning intent → download MDM app → enroll. Requires a second Android device acting as provisioning agent.

**QR code provisioning**: 
- Factory reset the device
- At welcome screen, tap 6 times in an empty area (triggers "Setup Wizard" hidden menu)
- Scan QR code containing provisioning parameters
- → Downloads MDM app → enrolls

**Neither can be triggered by a soft router.** The device must be in setup wizard (factory reset state) for QR, or have an NFC-capable provisioning device touching it. A WiFi network has no mechanism to initiate either flow.

### testDPC / Sample Projects

Google's `testDPC` (Device Policy Client) is a reference Device Owner app. It requires:
- Manual installation via ADB: `adb shell dpm set-device-owner com.afwsamples.testdpc/.DeviceAdminReceiver`
- Or QR code provisioning at setup wizard

The `dpm set-device-owner` command requires both:
1. ADB/USB debugging enabled (user-initiated)
2. No existing accounts on device (or factory reset)

---

## 5. WiFi Direct / P2P

### How WiFi Direct Works

WiFi Direct (Wi-Fi P2P) creates an ad-hoc connection between two devices:
- One acts as Group Owner (GO) — effectively a soft AP
- The other acts as Group Client
- Connection is one-hop, no routing to internet
- Android API: `WifiP2pManager`

### Can It Push Configurations?

**No.** WiFi Direct provides:
- Device discovery
- Service discovery (Bonjour/DNS-SD via `WifiP2pDnsSdServiceInfo`)
- Socket connections between peers

It does NOT provide:
- Any mechanism to modify the peer's system configuration
- Network access (it's a P2P link, not internet connectivity)
- Elevated privileges beyond what a regular WiFi connection provides

### Service Discovery Limitation

WiFi Direct service discovery can advertise services (like "MahjongVPN Provisioning Service"), but:
- The GO cannot force the client to connect to the service
- Even if connected, the only available operation is socket data transfer
- No Android API allows "push configuration" over a socket without a pre-installed receiver app

### WiFi Aware (Neighbor Awareness Networking)

Android 8+ introduced WiFi Aware (NAN), which is essentially WiFi Direct without needing to connect. Same limitations apply: data exchange between apps, not system configuration.

---

## 6. Android Enterprise Zero-Touch Enrollment

### The Actual Flow

**Zero-touch enrollment** (ZTE) requires:

1. **Device pre-registration**: The device IMEI/MEID/serial must be registered in Google's Zero-touch portal (`partner.android.com/zerotouch`) by an authorized reseller
2. **MDM configuration**: The portal maps device → DPC app download URL
3. **First boot**: During setup wizard, the device checks in with Google's zero-touch server → downloads the DPC → provisions

**Can a non-enterprise user do this?**

- **Pre-registration**: Requires a "Zero-touch enrollment partner" account (business verification required)
- **Post-purchase devices**: A device already in use CANNOT be retroactively enrolled — must be factory reset
- **The "tap 6 times" QR trick**: Only works at setup wizard before any Google account is added. After setup, the device must be factory reset

**Can we fake/streamline it?**

- The zero-touch check-in URL (`https://android.googleapis.com/auth/zerotouch`) is hard-coded and uses certificate pinning — cannot be intercepted by a soft router
- The QR code provisioning at setup wizard is triggered by the AOSP `SuwWizardActivity` intent — cannot be simulated post-setup
- **Without root**: Completely locked out
- **With root**: Could theoretically write to `/data/system/device_policy.xml` and `/data/system/users/0/device_policy.xml`, but this is dangerous and device-specific

### AMAPI (Android Management API)

Google's cloud-based MDM (AMAPI) still requires:
- An enterprise account
- Either zero-touch pre-registration or QR code provisioning
- Cannot be triggered by a network

---

## 7. Samsung Knox — What It Actually Provides

### Knox Platform Architecture

Samsung Knox is a defense-grade security platform with:
- **Knox Service Plugin (KSP)**: Extends Android Enterprise with Samsung-specific policies
- **Knox SDK**: API for ISVs to build Knox-aware apps
- **Knox Platform for Enterprise (KPE)**: Container, VPN, firewall, certificate management

### VPN Capabilities

Samsung Knox's VPN framework (`KnoxVpnPolicy`) provides:

```java
// Knox VPN Policy API (requires KNOX_VPN_PERMISSION)
KnoxVpnPolicy knoxVpn = KnoxVpnPolicy.getInstance(context);

// Configure system VPN profile
knoxVpn.createVpnProfile("mahjong_vpn");
knoxVpn.setServerAddress("mahjong_vpn", "8.136.37.136");
knoxVpn.setVpnType("mahjong_vpn", "IPSEC_IKEV2_PSK");  // Built-in IKEv2
knoxVpn.setPresharedKey("mahjong_vpn", "my_secret_psk");

// Set always-on
knoxVpn.setAlwaysOnVpnPackage("mahjong_vpn", true);

// Bind to specific apps (per-app VPN)
knoxVpn.addPackageToVpn("mahjong_vpn", "com.game.package");
```

**Key difference from stock Android**: Knox can configure the **built-in system IKEv2/IPSec client** through the KSP + MDM path. Stock Android MDM can only manage VPN apps (never the built-in IKEv2).

### What's Required

- **Samsung device** with Knox 2.8+ (Galaxy S6 and newer, all Knox-enabled devices)
- **Knox license key** (free for development, but commercial deployment requires enterprise agreement)
- **MDM enrollment**: KSP policies must be deployed through a UEM/MDM (Knox Manage, VMware Workspace ONE, Microsoft Intune, etc.)
- **Not standalone**: You cannot use Knox APIs directly from a regular app without Knox license + MDM enrollment

### Can a Soft Router Trigger Knox Enrollment?

**No.** Knox enrollment requires:
- The Samsung device to be factory reset and enrolled via Knox Mobile Enrollment (KME) or QR code
- KME requires pre-registration in Samsung's Knox deployment portal
- Neither NFC nor WiFi can trigger Knox enrollment post-setup

### Samsung's "Unique" Position

Samsung Knox is the **ONLY Android OEM** whose MDM stack can configure the built-in IKEv2 client. This makes Samsung the only Android path that approximates iOS's `.mobileconfig` experience. But it still requires MDM enrollment — just the VPN configuration itself doesn't need a third-party VPN app.

---

## 8. Open-Source "QR → Auto VPN on Android" Projects

### GitHub Search Results

GitHub API searches returned empty results (network constraints in current environment), but based on extensive prior knowledge of the Android VPN ecosystem:

### What Exists

| Project | VPN Type | QR Import | How It Works |
|---------|----------|-----------|-------------|
| **WireGuard** (official app) | WireGuard | ✅ QR code | QR contains Base64-encoded `.conf` (all keys, endpoints, IPs). App reads QR via camera, parses config, creates tunnel |
| **OpenVPN Connect** | OpenVPN | ❌ No QR | Imports `.ovpn` files from storage or URL |
| **OpenVPN for Android** (ics-openvpn) | OpenVPN | ✅ QR code (limited) | Can import `.ovpn` via QR (encodes entire config) |
| **strongSwan Android** (official) | IKEv2/IPSec | ❌ No QR | Imports `.sswan` profiles from storage |
| **Tailscale** | WireGuard | ✅ QR/URL | Auth flow via web login |
| **ZeroTier** | Proprietary | ❌ No QR | Network ID input |
| **Netbird** | WireGuard | ✅ QR | Auth via web |

### The Pattern

**Every single project that achieves "scan QR → VPN set up" does so through a VPN app.** The QR code contains configuration that the VPN app reads and applies to its own tunnel. None of them configure Android's built-in system VPN.

### Why No System VPN QR Project Exists

Android's system VPN API (`android.app.VpnService.Builder` + system VPN settings) does not expose any programmatic configuration method for third-party apps (without Device Owner). The system VPN settings (`Settings > VPN`) can only be modified:
1. Manually by the user through the UI
2. By a Device Owner via `DevicePolicyManager`
3. By Knox SDK on Samsung devices via MDM

There is **no Intent** to add a system VPN profile. There is **no ContentProvider** for VPN profiles. The VPN profile database (`/data/misc/vpn/`) is not accessible to third-party apps. This is by design — Android treats VPN configuration as a security-sensitive operation.

### Closest: WireGuard's QR Import

The WireGuard app is the gold standard for "scan QR → VPN works":
- QR code contains `[Interface]` (private key, address) + `[Peer]` (public key, endpoint, allowed IPs)
- Always-on VPN: Android's `setAlwaysOnVpnPackage` API works here because WireGuard IS a VPN app
- Kill-switch (lockdown mode): Blocks non-VPN traffic
- No user needs to type anything — just scan QR

**Trade-off**: Requires installing the WireGuard app (violates the "无app" preference in PRD) and requires the server to speak WireGuard (not current IKEv2 strongSwan).

---

## 9. Cross-Cutting Conclusion: The Android Security Wall

### The Fundamental Barrier

Android's networking security model has one inviolable rule:

> **A network operator (WiFi AP, DHCP server, DNS server) is untrusted. It must not be able to permanently modify the device's network configuration.**

This rule is enforced at multiple layers:

1. **DHCP**: Options are consumed only for basic connectivity (IP, DNS, routes). No configuration hooks.
2. **Captive Portal**: Runs in sandboxed WebView. No system configuration APIs exposed.
3. **VPN**: Requires signature-level `CONTROL_VPN` permission or Device Owner. Neither is attainable from a network.
4. **WiFi Direct**: Peer-to-peer data exchange only. No elevated privileges.
5. **Device Owner**: Requires user-initiated action at setup wizard (NFC bump or QR scan after factory reset).

### What the Project Already Implements

The existing `captive_portal.py` + `vpn-setup.html` approach is the **best possible outcome** for a soft-router-based flow:

```
Soft Router DNS hijack → captive portal page → user sees VPN credentials → user manually enters them in Settings
```

This reduces friction from "find server IP and PSK somewhere" to "read and copy-paste from a well-formatted page" — but still requires 3 fields of manual entry.

### The Three Paths Forward

| Path | User Friction | Requires App? | Works on All Android? |
|------|--------------|---------------|----------------------|
| **A: Keep IKEv2 + captive portal instructions** | 3 fields manual + 5 taps | No | ✅ Yes |
| **B: WireGuard app + QR code** | 1 tap (scan QR) | Yes (WireGuard app) | ✅ Yes |
| **C: MDM Device Owner** | 0 taps after provisioning | Depends on DPC | MDM-enrolled only |

### Recommendation

Based on the PRD constraints (Android, minimize friction, avoid user-installed app), Path A is already achieved. Path B (WireGuard app + QR) is the lowest-friction option that actually works on generic Android — it requires installing one app, but provides "scan QR → always-on VPN" with zero field entry. Path C (MDM) requires enterprise infrastructure.

**A critical nuance**: The current "3 fields" claim in the PRD may be optimistic. Android's IKEv2 PSK dialog requires: Name, Type (IKEv2/IPSec PSK), Server address, IPSec identifier (can leave blank), IPSec pre-shared key. That's 3 required + 2 optional fields. The captive portal approach can show these as copyable text but cannot auto-fill them.
