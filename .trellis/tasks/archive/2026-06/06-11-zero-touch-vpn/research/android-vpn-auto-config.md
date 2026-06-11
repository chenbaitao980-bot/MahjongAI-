# Android VPN Zero-Touch / Auto-Configuration Research

> 2026-06-11 — Research Agent deep dive
> Context: stock Android 10+, no root, no MDM enterprise enrollment.
> Goal: configure VPN on Android with less friction than manually typing 3 IKEv2 fields.

---

## Question 1: Can built-in IKEv2/IPSec VPN be configured via any automated method?

**Short answer: No.**

The Android system VPN (Settings → VPN → Add → IKEv2/IPSec PSK) is implemented in
AOSP `packages/apps/Settings` as `VpnSettings` / `LegacyVpnSettings`. The VPN profiles
are stored internally in the Android `KeyStore` (credential-encrypted storage), with
no public API surface for programmatic create/edit/delete.

### What was checked:

| Method | Feasibility | Why not |
|--------|------------|---------|
| **QR code** | ❌ | No built-in QR handler for VPN profiles. Settings app has no QR scanner integration for VPN. |
| **NFC** | ❌ | No NDEF record type for VPN profiles. Android Beam deprecated (API 29) / removed (API 34). |
| **File import (.conf, .ovpn, .mobileconfig)** | ❌ | No Android equivalent of iOS `.mobileconfig`. No system-level VPN profile format exists. |
| **Intent / deep link** | ⚠️ partial | `intent://com.android.settings.Settings$VpnSettingsActivity` opens VPN settings page (reduces 1-2 taps), but user must still manually type fields. Already used in `vpn-setup.html`. |
| **ADB** | ❌ | No `cmd vpn` or `settings put` for VPN profiles. The `VpnManager` (API 30+) has no profile-level CRUD. `LegacyVpn` data in KeyStore is not exposed via `settings` CLI. |
| **`VpnService.Builder` API** | ❌ (for built-in) | Only usable by a VPN app extending `VpnService`. Cannot be used to inject a profile into the system built-in VPN client. |
| **Managed Configuration (ManagedProvisioning)** | ❌ (for built-in) | Can push config to a VPN app's `DeviceAdminReceiver`, but the built-in IKEv2 client is not a managed app. |

### Key architectural limitation:
Android's built-in VPN is part of the Settings app (package: `com.android.settings`).
It is NOT a standalone VPN client that can be targeted by `DevicePolicyManager` or
`VpnManager` APIs. The `setAlwaysOnVpnPackage()` and related methods require a
**VPN app package name** that implements `VpnService`. The Settings VPN does not
export such a service in a discoverable way.

**Bottom line: Stock Android's built-in IKEv2 VPN is locked behind manual UI interaction. There is no API, no file format, no QR code, no NFC, and no ADB command to bypass the manual typing.**

---

## Question 2: Does Android support importing VPN profiles?

**Short answer: No system-level import. Individual VPN apps implement their own import.**

Android has **no standardized VPN profile format** analogous to:
- iOS `.mobileconfig` (signed configuration profile with IKEv2 + OnDemand + certs)
- `.ovpn` files (OpenVPN config)
- WireGuard `.conf` files
- Windows VPN PowerShell profiles

### What exists per-app:

| App / Protocol | Import method | Notes |
|---------------|---------------|-------|
| **WireGuard (official app)** | QR code, file (.conf/.zip), direct input | QR = wg-quick config format, base64-encoded. This is the gold standard: scan → tunnel up. |
| **OpenVPN Connect** | .ovpn file (local/URL), URL import | User must browse to file or paste URL |
| **strongSwan (app)** | .sswan profile, CA cert import | NOT the built-in VPN; requires the strongSwan app from Play Store |
| **Tailscale** | Login via browser OAuth | Not protocol-specific; login-based |
| **ZeroTier** | Network ID input | 16-digit ID, but also requires app install |
| **Built-in IKEv2** | ❌ None | Manual entry only |

### The WireGuard QR code format:
```
[Interface]
PrivateKey = <base64>
Address = 10.99.0.2/24
DNS = 8.8.8.8

[Peer]
PublicKey = <base64>
PresharedKey = <base64>
Endpoint = <server_ip>:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```
Encoded as a QR code, scanned by WireGuard app → one-tap import → tunnel created.

**Bottom line: While there is no system-level VPN profile import, the WireGuard app's QR code mechanism achieves "scan → connect" with ~3 taps (install app, open app, scan QR). This is the lowest-friction path on Android.**

---

## Question 3: Can a captive portal / web page trigger Android VPN configuration?

**Short answer: No. Confirmed by this project's own testing.**

### What was tested (already in codebase):
- `captive_portal.py`: DNS hijack `connectivitycheck.gstatic.com` → redirect to portal on port 80
- `portal.py`: HTTP server serving VPN setup instructions
- `vpn-setup.html`: Step-by-step guide page with deep-link to VPN settings

### Limitations:
1. **Captive portal runs in a WebView**: The portal page is rendered by Android's `CaptivePortalLogin` activity (or Chrome's captive portal detection). This is a sandboxed web context with NO access to system VPN APIs.
2. **No Android captive portal VPN API**: Unlike iOS (where `.mobileconfig` can be served from a portal page and the user can tap to install), Android has no mechanism for a portal page to trigger system VPN configuration.
3. **Security wall**: If a WiFi network could silently install VPN profiles, any open WiFi could MITM all traffic. Both iOS and Android prevent this. iOS allows `.mobileconfig` but requires explicit user review + device passcode.

### Maximum achievable:
- Display instructions + clickable link to open VPN settings (already done)
- Deep-link to Play Store for WireGuard/strongSwan app install
- Cannot: auto-fill fields, auto-save, auto-connect

**Bottom line: Captive portals cannot configure VPN on Android. This path is exhausted at "display instructions."**

---

## Question 4: DevicePolicyManager.setAlwaysOnVpnPackage() — without a DPC app?

**Short answer: No.**

### Requirements for `setAlwaysOnVpnPackage()`:

```
┌─────────────────────────────────────────────────────┐
│ Permission: DEVICE_OWNER or PROFILE_OWNER            │
│ Target:   VPN app package name (implements VpnService) │
│ Not:      System built-in IKEv2 client               │
└─────────────────────────────────────────────────────┘
```

### Why it cannot work without Device Owner:

1. **Permission**: `setAlwaysOnVpnPackage()` requires `DEVICE_OWNER` or `PROFILE_OWNER` permission. A regular app cannot call this method — it throws `SecurityException`.

2. **Becoming Device Owner**: The ONLY ways to make an app Device Owner are:
   - **Managed provisioning** (QR code, NFC bump, Zero-Touch) → requires DPC app + provisioning flow
   - **ADB**: `adb shell dpm set-device-owner com.example.app/.DeviceAdminReceiver` → works ONLY if device has zero accounts (factory reset condition)
   - **Root**: Direct KeyStore/secure settings manipulation (out of scope)

3. **Target limitation**: Even if you ARE Device Owner, the method requires a **VPN app package name**. The built-in IKEv2 client inside `com.android.settings` is not addressable as a standalone VPN app.

### What a DPC could do (if provisioned as Device Owner):
- Install a VPN app silently (via `PackageInstaller` session as device owner)
- Push managed configuration to that VPN app (e.g., WireGuard config via `setApplicationRestrictions()`)
- Call `setAlwaysOnVpnPackage("com.wireguard.android", lockdown=true)`
- Result: VPN app auto-installed + auto-configured + always-on lock

But this requires: factory reset (or new device) → QR code provisioning → user confirms (~4-5 taps) → DPC runs → VPN configured. This IS "zero touch after first setup" — but initial setup costs a factory reset + 4-5 taps.

**Bottom line: `setAlwaysOnVpnPackage()` inherently requires a Device Owner DPC. No way around this. Even with Device Owner, it cannot target the system built-in IKEv2 — it MUST target a VPN app.**

---

## Question 5: Android Managed Provisioning via QR code — minimal user interaction?

**Short answer: ~4-5 taps + factory reset for device owner; work profile VPN can't cover main profile apps.**

### Provisioning flow (Device Owner):

```
1. Factory-reset device (or new device, no accounts)
2. On setup wizard: tap 6 times on welcome screen (triggers QR scanner)
   OR: from Settings → Google → Set up nearby device
3. Point camera at QR code (contains DPC enrollment URL)
4. Review what the DPC will manage → tap "Accept & Continue"
5. DPC app installs → policies applied → VPN configured
```

**Tap count**: 4-5 taps from QR scan to VPN active (after factory reset).

**The QR code format** (NFC provisioning can also work, but QR is simpler):
```
{
  "android.app.extra.PROVISIONING_DEVICE_ADMIN_COMPONENT_NAME":
    "com.example.dpc/.DeviceAdminReceiver",
  "android.app.extra.PROVISIONING_DEVICE_ADMIN_SIGNATURE_CHECKSUM":
    "Base64-encoded-cert-checksum",
  "android.app.extra.PROVISIONING_DEVICE_ADMIN_PACKAGE_DOWNLOAD_LOCATION":
    "https://example.com/dpc.apk",
  "android.app.extra.PROVISIONING_LOCALE": "zh_CN"
}
```

### Work Profile limitation:
- Work profile provisioning works on existing devices (no factory reset)
- BUT: VPN configured in work profile ONLY tunnels work profile app traffic
- The game client runs in the main profile → NOT tunneled through work VPN
- Android does not support cross-profile VPN scope (this has been discussed but not implemented in AOSP)
- **Work profile VPN is useless for this use case.**

### Minimum viable DPC for VPN-only Device Owner:
A ~200-line DPC app that:
1. Extends `DeviceAdminReceiver`
2. Upon provisioning, installs VPN app via `PackageInstaller`
3. Pushes managed config (WireGuard profile) via `setApplicationRestrictions()`
4. Calls `setAlwaysOnVpnPackage()` with lockdown
5. Optionally: hides/disables DPC icon, disables factory reset protection

This IS feasible but requires factory reset + Play Store publication (or sideload APK URL).

**Bottom line: QR code provisioning works, but costs factory reset (for device owner) and puts the device under MDM control. Work profile is not viable. This is enterprise-grade friction, not consumer-grade. Minimum ~4-5 taps after factory reset.**

---

## Question 6: VPN protocol with native QR code configuration?

**Short answer: WireGuard is the only one.**

### Comparison:

| Protocol | QR code import | App required | Friction | Always-On | Kill-switch |
|----------|---------------|--------------|----------|-----------|-------------|
| **IKEv2 (built-in)** | ❌ | No (system) | 3 fields manual | ✅ native | ⚠️ only when configured as always-on |
| **WireGuard (app)** | ✅ QR code | Yes (Play Store) | Install app → scan QR → toggle | ✅ via system setting | ✅ built-in |
| **OpenVPN Connect** | ❌ (file only) | Yes | More friction | ✅ via system | ⚠️ config-dependent |
| **strongSwan app** | ⚠️ profile import | Yes | Similar to IKEv2 manual | ✅ via system | ⚠️ |
| **Tailscale** | ❌ (OAuth login) | Yes | Login flow | ✅ via system | ⚠️ |

### WireGuard QR code workflow:
1. User installs WireGuard app (one-time, ~30s from Play Store)
2. User opens app, taps "+", selects "Scan from QR code"
3. Camera opens → scan QR → tunnel name auto-filled → tap "Create tunnel"
4. Toggle switch to activate
5. Go to Android Settings → VPN → WireGuard → "Always-on VPN" = ON

**Total taps**: ~8 taps (install app + scan + toggle + always-on setting).
**vs. built-in IKEv2**: ~12-15 taps (find VPN settings + type 3 fields + tap save + tap gear + enable always-on).

### Why WireGuard is significantly lower friction:
- No typing at all (server address, PSK — all encoded in QR)
- No risk of typos (PSK is long hex string)
- No "wrong type" pitfall (IKEv2 PSK vs RSA vs MSCHAPv2 confusion)
- QR is standard, well-documented, and used by millions
- WireGuard app is 4.6★ on Play Store, open source (zx2c4)

### Server-side changes needed:
- Replace strongSwan with WireGuard on cloud server
- Install `wireguard-tools` (kernel module built into Linux 5.6+)
- Configure `wg0` interface with IP forwarding + MASQUERADE
- Generate client configs (private key + peer public key) — same `vpn_configure.py` could output WireGuard configs
- extractor sniffs on `any` or `wg0` interface — same `tcpdump -i any port 7777` works
- WireGuard uses UDP only, single port (default 51820) — simpler firewall than IKEv2's UDP 500 + UDP 4500

**Bottom line: WireGuard with QR code is the only "scan → connect" path on stock Android without MDM. Trade: install one open-source app (vs. zero app for built-in IKEv2). For multi-device/sharing scenarios, QR code is massively lower friction than typing fields.**

---

## Question 7: Creative solutions

### 7a. NFC-based VPN config
- ❌ Android Beam deprecated (API 29), removed (API 34)
- ❌ No standard NDEF record type for VPN profiles
- ⚠️ Custom NDEF + companion app: technically possible to write an NFC tag → companion app reads → configures WireGuard/OpenVPN via `VpnService.Builder`. But this requires: (a) companion app, (b) NFC tag hardware, (c) user to tap phone to tag. **More friction than QR code, requires app anyway.**
- ✅ NFC bump for managed provisioning: Google's managed provisioning supports NFC bump between devices. But this is for enterprise DPC enrollment, not VPN config transfer.

### 7b. Zero-Touch Enrollment for non-enterprise
- ❌ Android Zero-Touch requires device purchase from authorized reseller + registration in Google Zero-Touch portal
- ❌ Requires Google Workspace or reseller account
- ❌ Not available for retail/existing devices
- **Not viable for consumer use case.**

### 7c. Work Profile VPN
- ❌ VPN in work profile only covers work profile apps
- ❌ Game client runs in main profile → not tunneled
- ❌ No cross-profile VPN scope in AOSP
- **Not viable.**

### 7d. ADB / developer-mode configuration
- ❌ `adb shell dpm set-device-owner` requires factory reset (no accounts)
- ❌ No `cmd vpn` or `settings` keys for VPN profile management
- ⚠️ With adb + companion app: app could use `VpnService.prepare()` + `VpnService.Builder` to programmatically create a VPN. But: (a) requires USB connection for adb, (b) still needs an app.
- ⚠️ `adb install` + `adb shell am start` + `adb shell input tap`: could theoretically automate the entire built-in VPN UI flow via input simulation. But extremely fragile, depends on screen size/layout, and requires USB. **Possible but impractical.**

### 7e. Android VPN intent deep-link (already implemented)
- `intent://com.android.settings.Settings$VpnSettingsActivity` opens VPN settings directly
- Already used in `vpn-setup.html`
- Saves ~2-3 taps (no need to find VPN in Settings)
- **Already explored, minimal gain.**

### 7f. Samsung Knox (OEM-specific)
- ✅ Samsung Knox Service Plugin can push built-in IPsec/IKEv2 config + always-on
- ✅ No third-party VPN app needed
- ✅ Closest Android equivalent to iOS `.mobileconfig`
- ❌ Samsung devices only
- ❌ Requires Knox license (free for development, ~$0 for private use up to certain device count)
- ✅ Could be the answer IF the dedicated reading device can be a Samsung phone

### 7g. "Reading device" — iOS/iPhone option (PRD open question)
- ✅ iOS `.mobileconfig` with IKEv2 + OnDemand: scan QR → tap install → enter passcode → done (~6 taps, one-time)
- ✅ No MDM required (`.mobileconfig` is a signed profile, but unsigned profiles are installable with a warning)
- ✅ OnDemand rules (SSID=home → disconnect; default → connect)
- ✅ Native IKEv2 (no app needed)
- ❌ Requires iPhone hardware
- This IS the "dream stack" the user described, fully achievable on iOS without MDM.
- **If a dedicated reading device CAN be an iPhone, this is the optimal path: zero app, ~6 taps one-time, native IKEv2, On-Demand, no MDM.**

### 7h. Minimal DPC for WireGuard-only Device Owner
- A ~200-line DPC app that:
  1. Upon Device Owner provisioning, installs WireGuard via PackageInstaller (silent)
  2. Pushes WireGuard config via managed configuration (`DevicePolicyManager.setApplicationRestrictions()`)
  3. Calls `setAlwaysOnVpnPackage("com.wireguard.android", lockdown=true)`
- User flow: factory reset → scan QR → 5 taps → WireGuard installed + configured + always-on
- **Feasible but costs factory reset. For a dedicated reading device that starts fresh, this is viable.**

---

## Summary: Viable Paths by Friction Level

| Path | Initial Friction | App Install | OS/Platform | "Zero Touch" after setup |
|------|-----------------|-------------|-------------|--------------------------|
| **WireGuard + QR code** | ~8 taps, 1 app | WireGuard (open source) | Any Android 5+ | ✅ auto-connects |
| **iOS .mobileconfig** | ~6 taps, 0 app | None | iOS only | ✅ On-Demand |
| **MDM Device Owner + WireGuard** | ~4-5 taps + factory reset | DPC + WireGuard | Any Android 6+ | ✅ always-on locked |
| **Samsung Knox** | ~3 taps | None | Samsung only | ✅ always-on |
| **Built-in IKEv2 (current)** | ~12-15 taps (type 3 fields) | None | Any Android | ✅ always-on |
| **ADB + UI automation** | USB cable + ~5 CLI commands | None | Any Android | ✅ (fragile) |

## Recommendation Matrix

```
                    No app install    Few taps    Works on any Android
                    ─────────────     ────────    ───────────────────
Built-in IKEv2          ✅               ❌               ✅
WireGuard QR            ❌               ✅               ✅
iOS .mobileconfig       ✅               ✅               ❌
MDM Device Owner        ❌               ✅               ✅
Samsung Knox            ✅               ✅               ❌
```

**If "dedicated reading device can be iPhone": iOS .mobileconfig wins (0 app, low friction).**
**If "must be stock Android, lowest friction": WireGuard QR code wins (1 open-source app, scan→connect).**
**If "must be stock Android, no app install": stick with built-in IKEv2, accept manual typing. There is no third option.**

---

## References

- Android VpnService: https://developer.android.com/reference/android/net/VpnService
- Android DevicePolicyManager: https://developer.android.com/reference/android/app/admin/DevicePolicyManager
- Android Managed Provisioning: https://developers.google.com/android/work/prov-devices
- WireGuard Android: https://github.com/WireGuard/android
- WireGuard QR format: wg-quick(8) config encoded as QR
- iOS Configuration Profile Reference: https://developer.apple.com/business/documentation/Configuration-Profile-Reference.pdf
- Samsung Knox Service Plugin: https://docs.samsungknox.com/admin/knox-service-plugin/
- AOSP VpnSettings: https://android.googlesource.com/platform/packages/apps/Settings/+/refs/heads/main/src/com/android/settings/vpn2/
