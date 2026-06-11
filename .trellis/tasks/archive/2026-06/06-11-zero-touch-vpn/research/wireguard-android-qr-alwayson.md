# Research: WireGuard Android QR provisioning + Always-on/kill-switch + ECS coexistence + captive-portal QR

- **Query**: Lowest-friction one-time WireGuard setup on Android (no MDM) that then routes 100% egress through Aliyun ECS for passive tcpdump of mahjong traffic (47.96.0.227:7777). QR import, always-on kill-switch, ECS coexistence with existing strongSwan, OpenWRT captive-portal QR idea.
- **Scope**: external (web + GitHub API)
- **Date**: 2026-06-11
- **Tooling note**: `mcporter`/Exa MCP not available in this env; `gh` CLI unauthenticated. Used `curl` against GitHub public REST API, support.google.com, developer.android.com, wireguard.com, and raw GitHub READMEs.

---

## Findings

### Q1 — WireGuard official Android app: QR import flow

**App**: official WireGuard for Android — `com.wireguard.android` (Play Store). Source: `WireGuard/wireguard-android` (mirror, ★1508) → canonical `https://git.zx2c4.com/wireguard-android`. README confirms it "opportunistically uses the **kernel implementation**, and falls back to the non-root userspace implementation (wireguard-go)." (https://raw.githubusercontent.com/WireGuard/wireguard-android/master/README.md)

**Generating the QR from a wg config** — `qrencode` reads a standard `client.conf` and prints a scannable QR. The well-known one-liner is:

```bash
qrencode -t ansiutf8 < client.conf      # prints QR to terminal
qrencode -t png -o client.png < client.conf   # PNG for a poster/web page
```

This is exactly the mechanism OpenWRT/self-host generators use (see Q4/Q5). `qrencode` is the QR dependency every WireGuard config generator pulls in (confirmed in the Coralesoft OpenWRT installer "Optional Packages: `qrencode` - QR code generation for mobile devices").

**In-app flow (taps)**: From the WireGuard app FAB (`+` / "Add tunnel") → **"Scan from QR code"** → grant camera permission (one-time) → point at QR → it prompts for a **tunnel name** → Save. Then a single toggle on the tunnel row activates it; the **first** activation raises the Android system VPN-consent dialog ("Connection request" — see Q4) which you accept once.
Net: roughly **import = 3 taps** (Add → Scan from QR → name+save) plus the **camera-permission** and **VPN-consent** one-time confirmations, then **1 toggle** to connect. The QR payload is just the literal text of `client.conf`, so any standard wg config works.

> The config QR encodes the FULL config including the client **private key** in plaintext — treat the QR/poster as a secret (relevant to the captive-portal-poster idea in Q4).

### Q2 — Android "Always-on VPN" + "Block connections without VPN" (kill-switch)

Authoritative source: Google Android Help "Connect to a VPN on Android" (https://support.google.com/android/answer/9089766).

Key confirmed facts:
- The kill-switch lives in **Settings → Network & internet → VPN → (gear next to the tunnel) → "Always-on VPN"** and (on a separate toggle) **"Block connections without VPN"**.
- **Critical nuance from Google's own doc**: *"If you've set up a VPN through an app, you won't have the always-on option."* This refers to VPNs added as a *native system VPN profile*. For a `VpnService`-based app like WireGuard, the always-on toggle DOES appear in that Settings page once the app has been granted VPN consent at least once — it is set in Settings, not inside the WireGuard app. (Android's "Always-on VPN" is a system feature keyed to the app package.)
- **Persistence**: Always-on + block-connections is a **system setting that survives reboot** and re-establishes the tunnel on boot before normal app traffic. Block-connections means no traffic egresses until the tunnel is up (fail-closed) — exactly what's needed so the phone can never reach 47.96.0.227 outside the VPS.
- **Roaming cellular↔WiFi**: WireGuard's design is roaming-friendly ("capable of roaming between IP addresses, just like Mosh" — https://www.wireguard.com/). Combined with Android always-on, the tunnel auto-reconnects on network change; block-connections holds traffic until re-established.
- **Per-SSID exclusion (OFF at home)**: **Confirmed NOT available.** Android always-on VPN is **global only** — there is no built-in per-SSID/per-network bypass. The Settings page exposes only the global Always-on + Block-connections toggles plus optional per-app split (work profile / app exclusions inside the WireGuard app), with **no SSID condition**. To be "off at home" you must either (a) not block-connections and toggle manually, or (b) handle it server-side (the home soft-router could just route normally — but the phone's always-on still forces the wg tunnel regardless of SSID). This matches the user's belief.

### Q3 — Standing up a WireGuard SERVER on the Aliyun ECS that already runs strongSwan

- **Coexistence / ports**: WireGuard listens on **UDP 51820** (configurable) — completely disjoint from strongSwan's **UDP 500 + 4500** (IKE/NAT-T). No port conflict; both daemons can run simultaneously. (Aliyun security group already opens 500/4500 per the deployed VPN memo; adding wg = open **UDP 51820** inbound.)
- **Passive tcpdump still works**: WireGuard **decrypts into a kernel network interface** (`wg0`), confirmed by the official Android README noting kernel implementation and by wireguard.com (kernel module, cross-platform). On the server side the cleartext phone traffic appears on the `wg0` interface exactly as the strongSwan path currently surfaces it via `xfrm`/`-i any`. So the existing extractor pattern works with a one-word change:
  ```
  tcpdump -i wg0 port 7777        # or keep -i any
  ```
  The existing `stable/protocol.py` SLL2/SLL(276/113) parser fix already handles `-i any` capture, so reusing `-i any` needs no code change.
- **Effort vs reusing strongSwan**: strongSwan is **already working end-to-end** (deployed 2026-06-11, memo `vpn-readhand-deployed`). WireGuard's only advantage here is the **QR one-tap provisioning** (strongSwan/native IKEv2 has no QR import — that's the manual 3-field pain being solved). Net effort: install `wireguard-tools` + `kmod-wireguard`, generate server+peer keys, `wg0.conf` with `Address`, `ListenPort=51820`, peer block, enable IP forward + NAT (already in place for strongSwan), open SG UDP 51820. Both can coexist; you can migrate provisioning to wg while leaving strongSwan as fallback.

### Q4 — "Join home router WiFi → it hands you the WireGuard config via captive portal / QR poster"

**The OS security wall is REAL and confirmed.** A freshly-joined WiFi (or a captive portal) **cannot silently install or activate a system VPN**:
- Android `VpnService` requires `prepare(Context)` which returns an **Intent that must be launched and explicitly consented to by the user** ("An application must call `prepare(Context)` to grant the right… the right can be revoked at any time… When the user presses the button to connect, call `prepare()` and launch the returned intent"). Source: https://developer.android.com/reference/android/net/VpnService. There is **no API for a network/AP to push or auto-enable a VPN** without an installed app + user consent (only enterprise MDM/DPC can set always-on programmatically, which is excluded here — no MDM).
- Therefore the captive-portal idea reduces to: the home router (OpenWRT) **DISPLAYS a QR** (the wg `client.conf`) on a portal page or a printed poster; the **user scans it into the already-installed WireGuard app** (Q1 flow). The portal cannot do more than display. This **refutes** any "auto-install on join" expectation and **confirms** the "show-a-QR-the-user-scans" ceiling.

**Real OpenWRT projects that generate per-device configs + show QR:**
- **`Coralesoft/Openwrt-Wireguard-Installer`** (★17) — interactive OpenWRT installer; features include "**Interactive Peer Management**" and "**QR Code Generation - Instant mobile device setup with QR codes**", pulls optional `qrencode`. Targets OpenWrt 23.05+ (apk/opkg). (https://github.com/Coralesoft/Openwrt-Wireguard-Installer) — closest match to "router generates per-device wg config + QR".
- OpenWRT LuCI `luci-proto-wireguard` provides the in-router config but **no captive-portal QR page** out of the box; the QR-on-a-page pattern is custom (qrencode → PNG → served on a LAN page). No mainstream project ships a captive-portal-that-renders-wg-QR; it would be a small custom page.

### Q5 — Self-hosted WireGuard config generators with QR (GitHub)

| Repo | Stars | Notes |
|---|---|---|
| `wg-easy/wg-easy` | ★26012 | "Easiest way to run WireGuard VPN + Web-based Admin UI." Feature list explicitly: "**Show a client's QR code.**" Docker, add client → scan QR. Best-known turnkey option. (https://github.com/wg-easy/wg-easy) |
| `WGDashboard/WGDashboard` | ★3609 | Dashboard in Python+Vue; per-peer QR. (https://github.com/WGDashboard/WGDashboard) |
| `ngoduykhanh/wireguard-ui` | ★5106 | Web UI for WireGuard, per-client config + QR. (https://github.com/ngoduykhanh/wireguard-ui) |
| `Coralesoft/Openwrt-Wireguard-Installer` | ★17 | CLI, runs on the router itself, QR via qrencode (see Q4). |
| `pbengert/wireguard-config-generator` | ★29 | "Generate config files and qr codes for wireguard vpn." |
| `jacobgraf/wirewizardqr` | ★13 | "WireGuard Config and QR Code Generator." |
| `rig0/wireguard-qr` | ★1 | "Self hosted QR code generator for wireguard configs." |

**"Scan QR then always-on" Android guides**: the canonical chain is (a) generate config+QR with any tool above, (b) scan in the official app (Q1), (c) enable system Always-on VPN + Block connections without VPN per Google Help (Q2, https://support.google.com/android/answer/9089766). No single doc bundles all three; the Google Help page is the authoritative source for the always-on/kill-switch half.

---

## Recommended lowest-friction shape (synthesis, not a recommendation to change scope)

The minimal one-time setup that then works on ANY network, no MDM:
1. Stand up wg on the ECS (UDP 51820) alongside existing strongSwan; tcpdump `wg0`/`-i any` port 7777.
2. Generate one peer `client.conf` (AllowedIPs `0.0.0.0/0` for full tunnel) → `qrencode` → QR (PNG poster or LuCI/captive page).
3. User installs WireGuard app once, **Scan from QR code**, names tunnel, accepts VPN consent.
4. User enables **Settings → VPN → gear → Always-on VPN + Block connections without VPN** (survives reboot, roams cellular↔WiFi, fail-closed).

This makes per-use steps zero, at the cost of: no per-SSID "off at home" (global always-on only), and the QR/poster carries the client private key (treat as secret).

## Caveats / Not Found

- Could not load a step-by-step screenshot guide for the WireGuard Android QR screen (Pro Custodibus / Amnezia pages 404'd); tap-count above is from the app's known UI (Add tunnel → Scan from QR code) — verify exact wording on the installed app version.
- "Block connections without VPN" exact toggle availability can vary by OEM skin/Android version; Google Help confirms the feature but some OEMs relabel/relocate it.
- The claim that a `VpnService` app's Always-on toggle appears in system Settings (despite Google's "set up through an app, you won't have the always-on option" line) is based on Android platform behavior for VpnService packages; the Google line specifically concerns *native VPN profiles*. Worth a one-time on-device check on the target phone.
- Did not find any project that auto-pushes a VPN from a captive portal — consistent with the VpnService consent requirement (this is a hard OS limit, not a gap in tooling).
