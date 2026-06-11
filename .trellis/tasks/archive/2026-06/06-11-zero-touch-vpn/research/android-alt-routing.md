# Android Alternative Routing Approaches (to VPN)

> Research date: 2026-06-11  
> Question: Can we route TCP traffic on port 7777 from an Android phone to a remote server **without** installing an app, configuring system VPN fields, or rooting?  
> Answer: **No viable path with strict no-app constraint.** But documented findings inform the best available trade-off.

---

## 1. Android System-Wide HTTP/SOCKS Proxy

**Verdict: ❌ Dead end for raw TCP traffic**

Android's system proxy setting (Settings → Wi-Fi → Modify Network → Proxy) and DHCP option 252 (WPAD/PAC file) **only affect `HttpURLConnection` and `WebView`**. Raw TCP sockets — which the game's native `libcocos2dlua.so` uses for its custom binary protocol on port 7777 — **completely bypass proxy settings**.

Details:
- DHCP option 252 (WPAD) is a legacy IE-era mechanism. Android does not honor it for system-wide proxy; at most, Chrome might evaluate the PAC URL.
- PAC/WPAD proxy auto-config (.pac files) are evaluated only inside browsers and WebView contexts.
- SOCKS proxy is not a system-wide concept on Android without `iptables` (root) or a `VpnService` app (back to VPN).
- Even if the game used `HttpURLConnection` (which it doesn't — it's native), the proxy would only work for HTTP/HTTPS, not the custom binary protocol.

**Reference**: [Android Developer Docs: Proxy configuration](https://developer.android.com/reference/java/net/Proxy) — `java.net.Proxy` must be set per-connection. No system-wide mechanism exists.

---

## 2. DNS-Based Traffic Redirection

**Verdict: ❌ Dead end — game connects to hardcoded IP, not hostname**

DNS only translates hostnames → IP addresses. The game client connects directly to `47.96.0.227:7777` (a hardcoded IP), so:

- A custom DNS server pushed via DHCP cannot "intercept" an IP-based connection; DNS is never consulted.
- DNS poisoning / split DNS would require controlling the network gateway (not possible on arbitrary 4G/WiFi).
- Even if the game used a hostname, Android 9+ restricts DNS-over-TLS / Private DNS to hostnames the user trusts, and DHCP-pushed DNS servers can be partially overridden by Private DNS.

**Theoretical workaround**: Hijack the IP at the gateway level (DNAT/iptables), but this requires controlling the network gateway router, which the phone may not be connected to (when on 4G or random WiFi). Not feasible.

---

## 3. iptables / nftables Without Root

**Verdict: ❌ Dead end — requires root (`CAP_NET_ADMIN`)**

Linux iptables/nftables manipulation requires `CAP_NET_ADMIN` (or full root). Stock Android kernels do not grant this capability to user-space apps.

- Android's SELinux policies (`untrusted_app`) block iptables access from unprivileged processes.
- Even a device-owner app cannot gain `CAP_NET_ADMIN`.
- Rooting would break Google SafetyNet / Play Integrity (attestation API), which many games use for anti-cheat.
- The **only** Android-supported way to redirect IP traffic without root is the `VpnService` API — which is, by definition, a VPN app.

**Reference**: Android kernel source (`net/netfilter/`) — `CAP_NET_ADMIN` required for any netfilter rule changes. Confirmed in AOSP security model since Android 4.0.

---

## 4. Android Network Policy / Firewall API

**Verdict: ❌ Dead end — no routing API exists**

Android `ConnectivityManager` can:
- Set network preferences (metered/unmetered/restricted)
- Request network capability filtering (e.g., "only use Wi-Fi")

Android `NetworkPolicyManager` (hidden `@SystemApi`) can:
- Restrict background data per UID
- Set network usage limits
- **Cannot** add routing table entries
- **Cannot** redirect specific IP traffic

No Android API (public, system, or hidden) allows arbitrary routing table modification. This is by design: routing table modification = network interception capability = security boundary.

**The sole exception** is `VpnService.Builder.addRoute()`, which works only within the context of an active `VpnService` (requires BIND_VPN_SERVICE + user consent). This is the standard Android VPN model.

---

## 5. Captive Portal / Network Login

**Verdict: ❌ Dead end (already tested and confirmed)**

The repository already explored this with `captive_portal.py` (DNS hijack of `connectivitycheck.gstatic.com`), `portal.py` (VPN instruction page), and `vpn-setup.html`. **All deprecated.**

Why it fails:
- Android 8+ shows captive portal in a restricted WebView (`CaptivePortalLogin` activity) with minimal capabilities: no file downloads, no profile installation triggers, no JavaScript APIs for system configuration.
- After the user "signs in" (clicks through), Android re-checks `connectivitycheck.gstatic.com/generate_204` — if it returns HTTP 204, the captive portal notification dismisses. That's it. No persistent configuration.
- OS security wall: a freshly connected Wi-Fi network cannot silently install network-interception capabilities (otherwise any random coffee shop WiFi could perform MITM).
- This holds for **both iOS and Android**: both require explicit user action (multi-step confirmation) to install profiles or VPN configs.

**Reference**: AOSP `CaptivePortalLogin` source — the portal is purely a webview for authentication, not a profile deployment mechanism. Apple's captive network assistant similarly restricts profile installation to explicit user-initiated `.mobileconfig` downloads.

---

## 6. NFC / Bluetooth Configuration

**Verdict: ❌ Dead end — no VPN push via NFC/BT on Android**

NFC capabilities:
- WiFi credentials: **Yes** — NDEF WiFi Simple Configuration record can encode SSID + PSK. Android reads it and offers to connect.
- VPN configuration: **No** — No NDEF record type exists for IPsec/IKEv2/WireGuard profiles on Android.
- Enterprise enrollment: **Yes** — Android Zero Touch uses NFC ("bump") at factory provisioning to enroll into device management. But this is factory-state only; already-setup phones cannot use this path.

Bluetooth capabilities:
- Network sharing (PAN/NAP profile): Could theoretically share internet, but this is phone-as-client-to-tethering-host, not the direction we need.
- No standard Bluetooth service for pushing VPN profiles.

**Apple exception**: iOS supports NFC-triggered MDM enrollment (Apple Business Manager + NFC tag triggers "Do you want to enroll?" dialog → then .mobileconfig is pushed). Android has no equivalent for already-setup phones. Zero Touch enrollment requires factory-reset state.

---

## 7. Reverse Tunnel (Server → Phone)

**Verdict: ❌ Dead end — solves the wrong problem**

A reverse tunnel (phone connects to server, server tunnels data back to phone) is semantically identical to a VPN:
- The phone still needs to **initiate** the tunnel (phone → server), requiring an app/config.
- Once established, the game traffic still needs to be routed through the tunnel to reach the game server.
- This is just a different protocol for the same VPN concept (SSH `-R`, WireGuard, etc.).

No advantage over the current strongSwan/IKEv2 setup in terms of configuration friction.

**The extraction problem** also inverts: we want to **sniff** game traffic on the server. With a reverse tunnel, the game traffic already arrives at the server, but this is true of any VPN. The extractor's `tcpdump -i any port 7777` works regardless of tunnel protocol.

---

## 8. Game Client Modification (APK Patching)

**Verdict: ⚠️ Technically feasible but high risk, fragile, high maintenance**

The game uses cocos2d-x with `libcocos2dlua.so` for networking (including SRS auth in native code). Modifying the APK:

**How it could work**:
1. Decompile APK: `apktool d game.apk` (smali/dex) + extract `lib/arm64-v8a/libcocos2dlua.so`
2. Patch native `.so`: In the connection logic, replace the hardcoded IP `47.96.0.227:7777` with `127.0.0.1:7777` (or a configurable address)
3. Run a local SOCKS5 proxy app on the phone that tunnels `127.0.0.1:7777` → cloud server
4. Repackage: `apktool b` → re-sign with a new keystore
5. User sideloads the modified APK

**Why this is bad**:
- **Anti-tamper detection**: Many Chinese game publishers integrate anti-tamper SDKs (腾讯 MTP, 网易易盾, 360加固). Modified APK may be detected → account ban.
- **Sign-in**: Game might verify APK signature against server-stored hash.
- **Maintenance**: Every game update requires re-patching, re-signing, re-distribution.
- **Fragile**: Native code patching is delicate; wrong offsets can crash the game.
- **User friction**: Sideloading + "unknown sources" + trust required from users for a modified APK.

**Alternative**: Instead of patching native code, use **Xposed/LSPosed** framework (requires root or virtual environment) to hook `connect()` syscall and redirect connections. This is even more fragile and also requires root-like access.

**Verdict**: Not recommended. Too fragile for a tool meant for non-technical users.

---

## 9. Creative / Alternative Solutions

### 9A. WireGuard + QR Code (🏆 **RECOMMENDED — Best trade-off**)

**Flow**:
1. User installs **WireGuard** from Google Play (one-time, ~10 MB)
2. Generate a QR code containing the WireGuard tunnel config:
   ```
   [Interface]
   PrivateKey = (generated per-device or shared)
   Address = 10.99.0.x/24
   DNS = 1.1.1.1

   [Peer]
   PublicKey = <server public key>
   Endpoint = <cloud-ip>:51820
   AllowedIPs = 0.0.0.0/0
   PersistentKeepalive = 25
   ```
3. User opens WireGuard app → taps **"+"** → **"Scan from QR code"** → tunnel is configured instantly
4. Enable **"Always-on VPN"** and **"Block connections without VPN"** (kill-switch) in WireGuard settings
5. No more interaction needed — WireGuard auto-reconnects on network change

**Why this is the best**:
- QR scan = **zero manual fields** (meets "scan QR to connect" goal)
- Always-on + kill-switch = **no post-setup friction** (meets "auto-connect" goal)
- WireGuard is **fast**, well-supported, and mature
- Android's always-on VPN API (`setAlwaysOnVpnPackage`) works with WireGuard because it's a real app
- Kernel-level WireGuard is available in Android 12+ (no userspace overhead)
- WireGuard uses UDP, which has better NAT traversal than IPsec ESP

**Trade-offs vs. current strongSwan**:
- Must install **one app** from Play Store (violates "no app" preference, but minimally)
- Cloud server needs WireGuard alongside/besides strongSwan
- WireGuard has no built-in PSK-style shared secret — uses public-key crypto (more secure, just different)

**Server-side cost**: Install WireGuard on ECS (`apt install wireguard`), configure `wg0` interface, add `iptables` MASQUERADE rules. Existing `tcpdump -i any port 7777` works unchanged since WireGuard traffic appears on `wg0` (or `any`).

**PSK vs WireGuard consideration**: The current strongSwan PSK setup means `ipsec.secrets` holds the PSK. Anyone with the PSK and server IP can connect. WireGuard's Curve25519 key exchange provides forward secrecy and better security. For this use case, security isn't the differentiator — **QR configuration** is.

### 9B. Android Enterprise Device Owner (ADB One-Time Setup)

**Flow**:
1. Enable USB debugging on phone (Settings → Developer Options) — one-time
2. Connect phone to computer via USB
3. Build a minimal "VPN carrier" APK (thin `VpnService` wrapper that tunnels traffic)
4. Run: `adb install vpn-carrier.apk`
5. Run: `adb shell dpm set-device-owner com.example.vpncarrier/.DeviceAdminReceiver`
6. The device owner app can now programmatically configure always-on VPN, managed config, etc.
7. Unplug USB — phone is now "zero touch" thereafter

**Why this works**: Android's Device Policy Manager (`dpm`) can set a device owner app that acts as the full-device MDM. The device owner can:
- Set `alwaysOnVpnPackage` without user interaction
- Force VPN lockdown
- Silently install managed configurations

**Why this may not be acceptable**:
- Requires USB cable + USB debugging (not "remote zero touch")
- Device owner implies full device control — may be overkill for a single purpose
- Some phone manufacturers (Xiaomi, Huawei) have non-standard device owner behavior
- User needs to trust the device owner APK with full device management permissions
- Device owner can ONLY be set on a phone with no existing accounts (or after factory reset on some ROMs)

**Verdict**: Technically correct but over-engineered for this use case. WireGuard QR is much simpler.

### 9C. Android Work Profile (QR-Provisioned Managed Profile)

Android 7+ supports Android Enterprise managed provisioning via QR code:
1. User scans a QR code (encoding an enrollment token from Android Management API / a DPC)
2. This installs the Device Policy Controller app and sets up a "work profile"
3. The work profile can include managed VPN configuration

**Why this doesn't help**: The VPN in a work profile ONLY applies to apps in the work profile (sandboxed). The game app runs in the **personal profile** and won't use the work VPN. For cross-profile VPN, you'd need Device Owner (9B above).

### 9D. AOSP VPN Profile Injection via `adb shell`

Investigated whether `adb shell` can programmatically create IKEv2 VPN profiles:

- `settings put global` / `settings put secure` — VPN profiles are **not stored as simple Settings keys**. They're in Android's `keystore` (encrypted per-boot) and `ipsec` service databases.
- `cmd vpn` (Android 9+): Can query (`list`), prepare (`prepare-vpn`), but cannot **create** a new IKEv2/IKE profile.
- `vdc` (Volume Daemon): Not relevant for VPN configuration.
- `/data/misc/keystore/` requires root to access.
- `racoon` (legacy IPsec daemon) config files are in `/data/misc/vpn/` — also root-only.

**Verdict**: No ADB path to programmatically create a system IKEv2 VPN profile on stock Android. The only ADB-based VPN setup path is installing a VPN app + setting it as always-on via `dpm`, which requires device owner.

---

## 10. Practical Summary Matrix

| Approach | No App? | No Manual Fields? | No Root? | Works? | Recommendation |
|----------|---------|-------------------|----------|--------|---------------|
| HTTP Proxy | ✅ | ✅ | ✅ | ❌ | Raw TCP bypasses proxy |
| DNS redirect | ✅ | ✅ | ✅ | ❌ | Game uses hardcoded IP |
| iptables (no root) | ✅ | ✅ | ❌ | ❌ | Root required |
| Firewall API | ✅ | ✅ | ✅ | ❌ | No routing API exists |
| Captive Portal | ✅ | ✅ | ✅ | ❌ | OS security wall (confirmed) |
| NFC/BT config | ✅ | ✅ | ✅ | ❌ | No VPN NDEF standard |
| Reverse Tunnel | ✅ | ❌ | ✅ | ❌ | Same as VPN config |
| APK mod | ❌ (reinstall) | ✅ | ✅ | ⚠️ | Fragile, risky |
| **WireGuard QR** | ❌ (1 app) | ✅ | ✅ | ✅ | **🏆 RECOMMENDED** |
| Device Owner (ADB) | ❌ (1 app) | ✅ | ✅ | ⚠️ | Overkill, needs USB |
| Work Profile QR | ❌ (DPC) | ✅ | ✅ | ❌ | Profile-sandboxed VPN |

---

## 11. Recommendation

**Migrate from strongSwan/IKEv2-PSK to WireGuard** as the tunnel protocol, and use WireGuard's QR-code import as the "scan to connect" mechanism.

**Rationale**:
1. **Meets the "scan QR to connect" goal**: User opens WireGuard app, scans one QR code, tunnel is configured. Zero field-typing.
2. **Meets "auto-connect thereafter"**: WireGuard's built-in always-on VPN + kill-switch (natively supported by Android's `setAlwaysOnVpnPackage` for real apps).
3. **Minimal friction**: One Play Store install (WireGuard is tiny, well-known, no shady permissions), one QR scan, done forever.
4. **Server-side change is minor**: Install WireGuard on ECS alongside/ replacing strongSwan. The extractor (`tcpdump -i any port 7777`) works unchanged — WireGuard decrypted traffic appears on `wg0` interface, visible via `-i any`.
5. **Better than strongSwan for this use case**: WireGuard is simpler (no xfrm, no `pluto`/`charon` daemon complexity), faster reconnect on network change, better NAT traversal.

**What changes**:
- Cloud server: Install WireGuard, configure `wg0` with MASQUERADE
- Generate per-tunnel or shared keypair, encode as QR
- Deprecate strongSwan (`ipsec.conf`, `ipsec.secrets`, `charon`) — or keep both running if desired
- Update `package_extractor.py` to optionally bundle WireGuard config instead of / alongside strongSwan
- Documentation: replace "type IKEv2/IPSec PSK, server, PSK" with "install WireGuard, scan QR code"

**What stays the same**:
- Extractor (`tcpdump -i any port 7777`) — unchanged
- Relay HTTP API (`/register`, `/push`, `/state`) — unchanged
- Game client connection path — unchanged (phone connects to game server through tunnel)
- Deployment model — unchanged (ECS hosts relay + extractor + wireguard)

---

## Appendix: WireGuard QR Code Format

WireGuard QR codes use the standard `[Interface]` + `[Peer]` INI format, base64-encoded in a `wireguard://` URI or directly encoded as text in the QR. The WireGuard Android app supports QR import natively.

Example config for QR encoding:
```ini
[Interface]
Address = 10.99.0.2/24
PrivateKey = gNxnB0vBhO9fls6XP7aW5MW4hQ9LrFn2Xz5kL8jpHWc=
DNS = 1.1.1.1

[Peer]
PublicKey = 8gWfJdYtPKpNUxNtEmoCfjBXQTrS3G4mKX7w2hXApQo=
Endpoint = 47.xx.xx.xx:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

The QR encodes the full INI text. WireGuard app's "Scan from QR code" reads it and creates the tunnel.
