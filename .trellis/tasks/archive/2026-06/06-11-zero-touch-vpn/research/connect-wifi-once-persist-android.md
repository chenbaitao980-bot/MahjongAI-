# Research: "Connect WiFi Once → Persistent Cross-Network Redirect" on Unmanaged Android

- **Query**: Can merely *joining a WiFi once* persistently reconfigure an unmanaged Android phone so its FUTURE traffic on OTHER networks (cellular, other WiFi) routes through the cloud server — WITHOUT installing an app or manually adding a system VPN?
- **Scope**: external (Android security model, AOSP, Wi-Fi Alliance Passpoint)
- **Date**: 2026-06-11
- **Verdict**: **IMPOSSIBLE by OS design.** No WiFi-side mechanism (captive portal, DHCP, WPAD/PAC, EAP/802.1X, Passpoint/Hotspot 2.0) can install a system VPN, a global proxy, or a persistent route that survives leaving that WiFi on an unmanaged Android device. The irreducible minimum is a one-time, user-confirmed install of a VPN app + enabling always-on. The only true "zero-touch" Android paths are MDM Device Owner provisioning or Samsung Knox — both require enrollment/factory-reset-class friction.

> NOTE: This file answers the **user's literal dream specifically** (join-WiFi-once → persistent cross-network). The friction-ranking of VPN config methods and the MDM/Knox minimal path are already documented in sibling files `android-vpn-auto-config.md`, `android-alt-routing.md`, and `mdm-dpc-minimal-path.md`. This file does not repeat those; it focuses on *why the WiFi-side push is impossible* and *what Passpoint actually does*.

---

## The core requirement that makes this hard

Reading the hand requires the phone's **native game TCP socket to `47.96.0.227:7777`** to keep traversing the cloud server for passive sniffing. That means:

1. The redirect must apply to a **raw native TCP socket** (the cocos2d-lua client), not just HTTP/WebView.
2. The redirect must persist across **network changes including cellular** — i.e., it must be bound to the *device*, not to the *WiFi link*.

A WiFi network only controls the **L2/L3 link** while the phone is associated to it. The moment the phone leaves that WiFi (switches to cellular or another SSID), anything scoped to that link is gone. So for the dream to work, joining the WiFi would have to **write device-global state** (a system VPN, a global proxy, or a persistent route). Android forbids exactly this from the network side.

---

## Findings

### Q1 — Can a WiFi network push persistent device-global config to unmanaged Android? NO.

Every WiFi-side channel is either link-scoped (dies when you leave) or sandboxed (can't touch system network config):

| WiFi-side channel | Can it install VPN / global proxy / persistent route? | Survives leaving WiFi? | Why it fails |
|---|---|---|---|
| **Captive portal** | No | No | Rendered in AOSP `CaptivePortalLogin` — a **restricted WebView** for authentication only. No file-download-to-install, no profile API, no JS bridge to system network config. After `generate_204` returns 204 the portal just dismisses. (Confirmed by this repo's own deprecated `captive_portal.py` / `portal.py` tests.) |
| **DHCP options** (option 3 gateway, 6 DNS, 252 WPAD, 121 classless static routes) | No | No | DHCP-pushed routes/DNS apply **only to that WiFi interface** and are flushed on disconnect. They never apply to the cellular RAN interface. There is no DHCP option that creates a system VPN or a device-global route. |
| **WPAD / PAC (option 252)** | No | No | Android does **not** honor WPAD for a system-wide proxy. At most a browser/WebView might evaluate a PAC URL. Native TCP ignores it entirely (see Q3). |
| **EAP / 802.1X** | No | No | Authenticates the WiFi link (WPA2/3-Enterprise). Pushes no routing/VPN/proxy state to the device. Credentials may be saved for that SSID, but that is WiFi-join state, not traffic redirection. |
| **ANQP / Passpoint / Hotspot 2.0 / OSU** | No (only WiFi auto-join creds) | The *credential* persists, but it only makes the phone **auto-join partner WiFi** — see Q2 | Provisions a Wi-Fi roaming credential, not a VPN/proxy/route. Never affects cellular. |

**Android security model rationale (why this is deliberately walled off):** If a freshly-joined WiFi could silently install network-interception capabilities (VPN/proxy/route), **any coffee-shop AP could MITM all of a victim's traffic forever**, including future cellular traffic. Both Android and iOS therefore require an **explicit, multi-step, user-confirmed action** (Android: the `VpnService` consent dialog; iOS: reviewing+installing a `.mobileconfig` with passcode) before any traffic-interception capability is granted. There is no network-initiated path. AOSP enforces this: routing-table / netfilter changes require `CAP_NET_ADMIN` (root), and the only sanctioned redirect API is `VpnService`, which is gated behind `BIND_VPN_SERVICE` + the system consent dialog.

- Android `VpnService` (consent dialog is mandatory): https://developer.android.com/reference/android/net/VpnService
- AOSP `CaptivePortalLogin` is auth-WebView only (security model): https://android.googlesource.com/platform/packages/apps/CaptivePortalLogin/

### Q2 — Passpoint / Hotspot 2.0 / OSU: persistent profile, but WiFi-roaming ONLY (useless here). CONFIRMED.

Passpoint (Hotspot 2.0) **does** provision a *persistent* profile that survives reboots — but it is fundamentally a **Wi-Fi auto-join / roaming** technology, not a traffic-redirect technology:

- A `PasspointConfiguration` stores a home-operator credential (SIM/EAP/cert) + roaming consortium OIs + a Policy/Subscription Update server. Its entire purpose is: *when the phone is in range of a partner AP advertising a matching realm via ANQP, auto-associate without user interaction.*
- It installs **no VPN, no proxy, no route**. It only decides *which WiFi APs to silently join*.
- It is **scoped to Wi-Fi**. It has **zero effect on cellular** and zero effect on non-partner WiFi. The moment the phone is on cellular or any AP not in the Passpoint profile's roaming set, Passpoint is inert.
- Online Sign-Up (OSU) is just the provisioning flow that *writes* a Passpoint credential (often via an OSU AP + SOAP-XML/OMA-DM exchange). It still only yields a Wi-Fi credential.
- Provisioning a Passpoint profile on Android still requires either the user installing a Passpoint config (a config-installer app / `addOrUpdatePasspointConfiguration`, which needs the app to hold appropriate permission) or carrier/MDM provisioning — it is **not** something an arbitrary captive portal silently writes to an unmanaged phone for an arbitrary realm.

**Conclusion:** Passpoint is the closest thing to "join once → persist," but it persists only *WiFi auto-join*, never *cross-network traffic redirect*, and never touches cellular. **Useless for the dream**, which explicitly requires "any network including cellular."

- AOSP Passpoint architecture: https://source.android.com/docs/core/connect/wifi-passpoint
- `PasspointConfiguration` API: https://developer.android.com/reference/android/net/wifi/hotspot2/PasspointConfiguration
- `WifiManager.addOrUpdatePasspointConfiguration`: https://developer.android.com/reference/android/net/wifi/WifiManager#addOrUpdatePasspointConfiguration(android.net.wifi.hotspot2.PasspointConfiguration)

### Q3 — Android global proxy / PAC: not network-settable, and ignored by native TCP anyway. CONFIRMED (no).

Two independent reasons this can't deliver the dream:

1. **No network can set a *device-global* proxy on unmanaged Android.** A per-SSID proxy can be set manually in WiFi → Modify Network → Proxy (or via PAC URL), but it is **scoped to that SSID** and dies on disconnect — never applies to cellular. A truly device-wide / persistent proxy (`GLOBAL_HTTP_PROXY`) can only be set by a **Device Owner** via `DevicePolicyManager.setRecommendedGlobalProxy()` / managed config — i.e. MDM, not a network.
2. **Even a set proxy does not capture arbitrary app TCP.** Android's HTTP proxy is honored only by the Java HTTP stack (`HttpURLConnection`) and `WebView`. **Raw native TCP sockets bypass it completely.** The game client is native (`libcocos2dlua.so`) doing a custom binary protocol on port 7777 — it would ignore any system proxy entirely. There is no OS-level "transparent proxy for all apps" without `VpnService` (a VPN app) or root iptables.

So: no global app-level proxy is settable by a network without Device Owner, and even with one it wouldn't catch the native socket. **Confirmed dead end.**

- Android proxy is per-connection / HTTP-stack only: https://developer.android.com/reference/java/net/Proxy
- `setRecommendedGlobalProxy` requires Device Owner: https://developer.android.com/reference/android/app/admin/DevicePolicyManager#setRecommendedGlobalProxy(android.content.ComponentName,%20android.net.ProxyInfo)

### Q4 — The honest conclusion. VALIDATED.

On **unmanaged** Android, "join WiFi once → persistent cross-network redirect with zero app install" is **impossible by OS design**. The chain of facts:

- WiFi-side channels are link-scoped or sandboxed (Q1) → nothing device-global can be pushed from the network.
- The only sanctioned cross-network traffic-redirect primitive is `VpnService`, which **requires an app** holding `BIND_VPN_SERVICE` and **requires the user to tap "OK" on the system VPN-consent dialog** at least once. (`setAlwaysOnVpnPackage` to make it persist further requires Device Owner — see `mdm-dpc-minimal-path.md`.)
- Routing-table / netfilter manipulation requires `CAP_NET_ADMIN` = root (blocked for `untrusted_app` by SELinux).
- Therefore the **irreducible minimum on unmanaged Android** is: a **one-time, user-confirmed install of a VPN app + accept the consent dialog (+ enable always-on)**. That is the floor. Nothing below it exists.

No authoritative source contradicts this; the entire Android VPN/network security model is built to *prevent* network-initiated, app-less traffic interception. This matches the repo's already-documented findings in `android-alt-routing.md` (HTTP proxy, DNS, iptables, captive portal, NFC/BT, reverse tunnel — all dead ends).

### Q5 — What DOES make it near-zero-touch: Device Owner / MDM, or Samsung Knox.

These are the **only real "zero-touch" Android paths**, and each has a hard prerequisite (already detailed in `mdm-dpc-minimal-path.md`):

| Path | What it enables | Hard prerequisite |
|---|---|---|
| **Device Owner via QR provisioning** (`afw#setup` 6-tap in setup wizard, or `adb dpm set-device-owner`) | DPC silently installs a VPN app + `setApplicationRestrictions()` config + `setAlwaysOnVpnPackage(..., lockdown=true)`. After enrollment it IS zero-touch and cross-network. | **Factory-reset / no-accounts device state.** Can't be applied to an already-set-up phone without wiping. Puts device under MDM control. |
| **Android Management API (AMAPI)** | Cloud-managed policy that sets always-on VPN. | Still enrolls the device as managed; still delivers the VPN app via Managed Google Play (so still an app, just silent). |
| **Samsung Knox Service Plugin (KSP)** | Pushes the **built-in** IPsec/IKEv2 config + Always-On + lock — the only true "system VPN, no third-party app" Android path. | **Samsung device only** + Knox license + an MDM/DPC to deliver the KSP profile. |

None of these is "join a WiFi once." They are enrollment/MDM flows. They are "zero-touch *after* a one-time enrollment that costs factory-reset-class friction" — the opposite end of the spectrum from a captive-portal push.

---

## Caveats / Not Found

- **iOS is materially different** and is the user's actual "dream stack" if the reading device can be an iPhone: a `.mobileconfig` (IKEv2 + On-Demand) is installable from a portal/QR with ~6 taps, no app, no MDM, and On-Demand makes it cross-network persistent. This is documented in `android-vpn-auto-config.md` §7g and `ios-mobileconfig-option.md`. iOS's `.mobileconfig` is the closest real-world thing to the dream — but it still requires the **one-time user-confirmed install**, not a silent network push. So even iOS does not grant the "silent join-WiFi-once" fantasy; it just makes the one-time confirm very cheap.
- I could not find any CVE or public technique allowing a network to silently install a VPN/proxy/route on a patched, unmanaged modern Android — consistent with this being a deliberately closed design rather than a bug. (Historical browser-only WPAD abuses exist, but they never reached native-socket / cross-network scope.)
- Exact AOSP source line citations for the `VpnService` consent enforcement were not pulled into this file (the doc references above are the authoritative public statements); deeper source-level confirmation can be done via `android.googlesource.com/platform/frameworks/base` `Vpn.java` if needed.
