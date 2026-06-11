# Creative Data Paths: Android → Cloud Without VPN

> Research date: 2026-06-11
> Question: Can we get mahjong game data (TCP port 7777, cocos2d-x, hardcoded IP 47.96.0.227) from an Android phone to a cloud server with minimal/zero user config — thinking outside the VPN box entirely?
> Answer: **Every path leads back to VPN (or root/repackaging).** But several approaches have interesting partial viability.

---

## 1. APN-Based Routing (Carrier Gateway)

**Verdict: ❌ Dead end for consumer phones**

### Mechanism
APN (Access Point Name) on Android controls how mobile data connects to the carrier's packet gateway. In theory, a custom APN could specify a proxy/gateway that routes traffic.

### Why It Fails
- **APN proxy only affects HTTP traffic**: Android APN settings have a "Proxy" field, but like WiFi proxy, it only affects `HttpURLConnection` and `WebView`. Raw TCP sockets — which the game's `libcocos2dlua.so` uses — bypass proxy settings entirely.
- **Enterprise APN requires carrier cooperation**: Corporate/enterprise APNs with custom gateways (GGSN/PGW/UPF in 4G/5G) require the mobile carrier to configure a private APN on their infrastructure. Not feasible for consumer SIM cards.
- **MVNO APN**: Even on MVNOs, the APN gateway is carrier-controlled. There is no self-host APN gateway for consumer cellular networks.
- **No OS-level traffic redirection via APN**: Android's `ConnectivityManager` and `TelephonyManager` do not expose any API to redirect raw TCP traffic via APN configuration changes. The APN's proxy field only affects HTTP-aware clients.

**Reference**: 3GPP TS 23.401 (LTE EPC architecture) / TS 23.501 (5GC) — the PGW/UPF is the anchor point for all user-plane traffic. Configuring it requires carrier network access.

---

## 2. Dual-SIM / Multi-Network Routing

**Verdict: ❌ Dead end for raw TCP sockets**

### Mechanism
Android 12+ introduced per-app network selection API (`ConnectivityManager.registerDefaultNetworkCallback`), allowing apps to prefer WiFi or cellular per-app.

### Why It Fails
- **The game doesn't use Android's Network API**: cocos2d-x's native networking (`libcocos2dlua.so`) uses POSIX `socket()`/`connect()` directly, not `java.net.Socket` with `Network.bindSocket()`. Android's per-app network binding only works for Java/Kotlin code that explicitly binds sockets to a `Network` object.
- **No OS-level "send app X traffic via interface Y"**: Android's `ConnectivityService` does per-UID routing table entries via `fwmark` (policy routing), but this only **selects** which of the available default interfaces to use (WiFi vs cellular). It cannot **add** a new routing destination or redirect to a specific gateway.
- **Networking is single-homed by default**: With two SIMs active, only one provides the default route at a time. Dual-SIM "smart" switching by app is limited to the network selection APIs, which the game doesn't use.

**Null finding in APK Lua**: The game code contains **zero references** to Android network APIs (`ConnectivityManager`, `Network`, `NetworkCapabilities`). All networking is native.

---

## 3. USB-C Ethernet Adapter + Portable Router

**Verdict: ⚠️ Works technically, but rejected by user**

### Mechanism
```
Phone → USB-C Ethernet adapter → portable router (e.g., GL.iNet) → router runs WireGuard/IKEv2 → Cloud
```
The phone connects via wired Ethernet (Android supports USB-C Ethernet adapters natively since 6.0+). The portable router runs a VPN client. The phone sees only Ethernet; the router transparently tunnels all traffic.

### Assessment
- **Android USB Ethernet support**: Stock Android supports USB-C Ethernet adapters out of the box (CDC-Ethernet / RNDIS drivers in kernel). The phone gets an IP via DHCP from the portable router.
- **Portable router**: GL.iNet Mango ($20), GL-MT300N, etc. Can run OpenWRT + WireGuard client. Very small (matchbox-sized).
- **Zero phone config**: Once router is configured (one-time), plugging in the USB-C Ethernet adapter is the only action on the phone. No VPN app, no system settings changes.
- **Rejected by user**: PRD explicitly states "手机不带硬件（拒绝旅行路由器）". User wants zero hardware beyond the phone itself.

**Verdict**: The only hardware-based path that avoids ALL phone configuration. But explicitly out of scope per user preference.

---

## 4. Bluetooth PAN (Personal Area Network)

**Verdict: ❌ Not feasible on stock Android**

### Mechanism
Phone connects via Bluetooth PAN to a gadget (ESP32, Raspberry Pi Zero W, etc.) that acts as a network gateway and VPN endpoint.

### Why It Fails
- **Android PAN roles are asymmetric**: Android supports Bluetooth tethering as **server** (sharing the phone's cellular connection) and can **connect** to Bluetooth devices for audio/calls/data-transfer. But Android does NOT support acting as a PAN **client** (getting internet from a Bluetooth PAN gateway). The Bluetooth PAN profile (PAN-NAP) on Android is specifically for tethering-server mode.
- **No standard `BluetoothPan` client API**: `android.bluetooth.BluetoothPan` (hidden `@SystemApi`, added in API 21) has `connect()` but only for the tethering case. Third-party apps cannot use this as an internet client.
- **Workaround**: Write a custom Bluetooth RFCOMM/SPP app that tunnels IP packets. This is essentially a VPN app over Bluetooth — same complexity as WireGuard app, plus Bluetooth limitations (low bandwidth, high latency).
- **ESP32 constraint**: ESP32 can do Bluetooth PAN-Nap server (BlueKitchen BTstack), but Android won't use it for internet access.

---

## 5. Notification Mirroring (Push Data Extraction)

**Verdict: ❌ Dead end — push notifications don't carry game hand data**

### What the Game Has
From APK Lua analysis:
- **GeTui (个推)** push SDK: `app/Req/SDK/ReqGeTui.lua`, `app/GtInit.lua`
- **JPush (极光推送)** SDK: Referenced as alternative in `ReqGeTui.lua` (`jpush_get_registrationid`)
- Push features: `push_get_clientid`, `push_bind_alias`, `gt_get_notify_info`
- `KW_PUSH_STATE` (UserDefault key 112): Whether push is enabled
- `KW_GETUI_ANDROID_MSG` (UserDefault key 80): Stores push message content

### What Push Carries
Based on the code:
- Push is used for **marketing notifications** (game invites, promotions, awards)
- Push notifications are standard user-facing alerts (notifications in the notification drawer)
- **No game hand data is sent via push**: The game's state data (tiles, player actions) flows exclusively through the TCP 7777 connection. The push SDK is unrelated to game state.

### Android NotificationListenerService
- Android `NotificationListenerService` can capture all notifications (requires user granting notification access permission)
- Even if enabled, it would only capture marketing push text — no tile data
- The game does not create local notifications with hand data during play

---

## 6. Local File/Database Extraction (Sync to Cloud)

**Verdict: ❌ Live hand data not stored locally — only replay records exist**

### What the Game Stores Locally
From APK Lua analysis and APK reverse engineering:

| Storage | Location | Content | Live Hand Data? |
|---------|----------|---------|-----------------|
| `cc.UserDefault` | SharedPreferences XML | Settings, login state, preferences | ❌ No |
| `SessionLoginData_<lobbyID>.dat` | App writable path | 16-byte session token for re-login | ❌ No |
| `KW_DATA_BOX_ROOM_WATCHGAME_Record.bin` | App writable path | Zlib-compressed game record (spectated games) | ❌ Only for watched games, not own active games |
| Lua memory | RAM | Active game state (tiles, hands, etc.) | ✅ Yes (but in-memory only) |

### Watch Record Files
The game's Watch system (`lobby/Req/Watch/ReqRealtimeGameRecord.lua`) downloads game records:
- Server sends game record in chunks (`msgData.payload`, `msgData.total` chunks)
- Client merges chunks → decompresses with zlib → saves to `gameID_KW_DATA_BOX_ROOM_WATCHGAME_Record.bin`
- Format: Binary, zlib-compressed `zip == 1`, proprietary game record protocol
- These are **spectator replay files**, only created when actively watching another player's game
- They are NOT auto-generated for your own games during play

### File Syncing Approaches
- **Syncthing / FolderSync**: Could sync the writable path directory, but no useful live data exists there
- **ADB pull**: `adb pull /data/data/<package>/files/` — same issue, no live data
- **Android SAF (Storage Access Framework)**: Could theoretically let a companion app read game files, but SAF requires user authorization per-access and can't read app-private directories without root

### In-Memory Data (RAM)
- The game's hand/tile data exists in memory (Lua tables + C++ game state)
- `/proc/<pid>/mem` requires root
- Frida/Gadget can read process memory but needs injection (see angle #11)

---

## 7. Screen Mirroring (scrcpy + OCR)

**Verdict: ⚠️ Theoretically feasible but fragile, high friction**

### Mechanism
```
Phone ──[ADB over TCP/IP]──▶ Remote machine ──[scrcpy H.264]──▶ OCR hand tiles
```
scrcpy (Genymobile) streams Android screen via ADB using H.264 encoding. Combined with OCR, it could theoretically read hand tiles.

### Feasibility Analysis
- **scrcpy over TCP/IP**: `adb tcpip 5555` enables ADB over network. scrcpy then connects to `phone-ip:5555`. BUT: initial `adb tcpip` requires USB connection once, and the ADB port is only reachable on the same local network (not routable). A VPN tunnel would be needed to reach the phone from the cloud.
- **Performance**: scrcpy streams at ~30fps with low latency. H.264 decoding and OCR processing adds overhead. For a turn-based game (mahjong), this might be acceptable.
- **OCR accuracy**: Chinese mahjong tiles are complex characters (萬/筒/索/字). Standard OCR (Tesseract) trained on general Chinese text may struggle with tile fonts. Specialized mahjong tile detection (template matching) would be more reliable than general OCR.
- **ADB security**: ADB over TCP/IP has no encryption (plaintext over TCP). Must be tunneled through VPN. If using a VPN to tunnel ADB... we're back to VPN.
- **Android scrcpy server**: scrcpy works by pushing a small Java server to the phone via ADB. ADB must be enabled and authorized (one-time USB connection with "Always allow from this computer").

### Scorecard
| Factor | Rating |
|--------|--------|
| Phone config required | USB + Developer Options + ADB authorization (one-time) |
| Requires VPN for remote access | Yes (ADB TCP/IP is LAN-only) |
| CPU/bandwidth cost | High (H.264 streaming 24/7) |
| OCR reliability | Unknown/unproven for mahjong tiles |
| Battery impact | Significant (constant screen+encoding) |

### Alternatives Considered
- **Vysor / AirDroid / TeamViewer**: Same fundamental limitations (VPN needed for remote access, screen streaming overhead)
- **Android MediaProjection + WebRTC**: Could stream screen via WebRTC to a cloud server, but requires a custom app on the phone
- **Android 14+ app streaming to Chromebook/PC**: Phone Link / Link to Windows — not programmable for data extraction

**Verdict**: A circuitous path that ends up requiring VPN anyway to reach the phone from the cloud. Adds OCR fragility on top. Not recommended.

---

## 8. WiFi Direct + Companion Device

**Verdict: ❌ Fragile, requires user interaction per session**

### Mechanism
Phone connects to a companion device (ESP32, Raspberry Pi Zero W, etc.) via WiFi Direct. The companion device runs a VPN client to the cloud. Phone traffic routes through the companion device.

### Why It Fails
- **WiFi Direct user interaction**: Android requires user to accept WiFi Direct connections in a system dialog. This is NOT automatic and cannot be bypassed.
- **No transparent routing**: WiFi Direct creates a peer-to-peer WiFi link, but Android does NOT automatically route internet traffic through it. WiFi Direct is designed for file transfer / screen casting, not internet connectivity.
- **ESP32 WiFi Direct**: ESP32 supports WiFi Direct (ESP-IDF `esp_wifi` + `esp_wps`) but as a peer, not a gateway. No IP forwarding stack on ESP32 is practical.
- **Pi Zero W**: Could run hostapd as a WiFi hotspot (Access Point mode) which is simpler and more reliable than WiFi Direct. But then the phone is connecting to a WiFi network, not "WiFi Direct" — and this is essentially the travel router scenario (angle #3).
- **Connection persistence**: WiFi Direct connections are temporary and need re-establishment. Not suitable for "always-on" data collection.

---

## 9. Game's Built-In Spectator/Replay System

**Verdict: ⚠️ Theoretically interesting but practically more complex than VPN**

### Discovery: The Game Has a Live Watch System
From APK Lua analysis:
- **`lobby/Modules/Watch/Module.lua`**: Full spectator module
- **`lobby/Req/Watch/ReqRealtimeGameRecord.lua`**: Requests to watch a live game
- **Protocol**: IMProtocol `ReqRealtimeGameRecord` / MatchLinkProtocol variant
- **Data flow**:
  1. `WatchModule:reqRealtimeGameRecord(roomid, offset, gameid, playercount)` — initiates watch
  2. Server sends chunks: `msgData.current` / `msgData.total` chunks of `msgData.payload`
  3. Chunks are written to `gameID_<n>_KW_DATA_BOX_ROOM_WATCHGAME_PART`
  4. All chunks received → `mergeFiles()` → zlib decompress → `gameID_KW_DATA_BOX_ROOM_WATCHGAME_Record.bin`
  5. `RoomManager:watchStart(param)` → `gameScene:playbackStart(...)` renders the replay

### How It Could Work as a Data Path
```
Phone (playing game) → Cloud Android emulator (spectating) → Relay
                                     ↓
                          Watches the same room
                          Receives game record protocol
                          → Contains all hand/tile data
                          → Forward to relay for display
```

### Why It's Practically Difficult
1. **Two accounts needed**: The cloud emulator needs a separate game account
2. **Room access**: Must be in the same room (private 包厢/比赛场) as the player
3. **RoomID/GameID knowledge**: Must know the exact room identifier to request watch
4. **Cloud Android emulator**: Needs to run a full Android environment (Android x86 in cloud, or ARM emulator). Significant resource and cost.
5. **Game record protocol parsing**: The `.bin` format is proprietary (zlib-compressed game protocol). Would need reverse engineering to extract hand data. OR we could use the game's own replay player as-is and scrape the displayed data.
6. **Authentication**: The cloud emulator must be logged in to the game, maintain session, handle reconnections, etc. This is a full game client with all its complexity.
7. **Always-on**: The cloud emulator must stay connected 24/7 to the game servers, consuming resources and risking idle-kicks.
8. **Anti-cheat risk**: A secondary client watching every game could be flagged as suspicious behavior.

### Comparison to VPN
| Factor | Watch/Replay | VPN (WG/strongSwan) |
|--------|-------------|---------------------|
| Phone config | None needed | WireGuard: install app, scan QR (~5 taps) |
| Cloud resources | Android emulator (2-4GB RAM, GPU) | Just WireGuard daemon (~50MB RAM) |
| Reliability | Depends on game server, auth, room access | Direct network tunnel |
| Data format | Proprietary binary records (need parsing) | Raw TCP (already parsed by extractor) |
| Maintenance | High (game updates break parsing) | Low (standard network protocols) |
| Anti-cheat risk | Moderate (suspicious watching pattern) | Minimal (VPN is indistinguishable from normal network traffic) |

**Verdict**: The spectator system is a genuine game feature that delivers hand data — but using it as a data exfiltration path is vastly more complex than VPN. The data parsing, cloud emulator, and authentication chain make this a multi-week engineering project with fragile maintenance burden.

---

## 10. MITM at ISP/Carrier Level

**Verdict: ❌ Not feasible for consumer use**

### Mechanism
Set up a VPN/inspection point at the carrier GGSN/PGW level so all phone traffic is already routed through our cloud when it exits the mobile network.

### Why It Fails
- Requires **carrier cooperation** (access to GGSN/PGW/UPF configuration)
- Only feasible for **enterprise/private APN** with corporate contracts
- For consumer SIMs: The carrier owns the gateway, not the end user
- Even with a commercial MVNO, the user doesn't control upstream routing

---

## 11. Bonus: Frida/Gadget In-Process Hooking

**Verdict: ⚠️ Technically feasible but high risk**

### Mechanism
Inject Frida Gadget (a dynamic instrumentation library) into the game APK. Hook the game's native `un.network.TcpConnection` methods or Lua-level game state processing to extract hand data at runtime and forward it to a cloud endpoint via HTTP.

### How It Works
1. **Repackage APK**: Decompile APK → inject Frida Gadget `.so` → add `System.loadLibrary("frida-gadget")` to the game's startup → re-sign APK
2. **Hook native functions**: `Interceptor.attach(Module.findExportByName("libcocos2dlua.so", "sendMessage"), ...)` to capture socket data
3. **OR hook Lua layer**: Hook `TcpConnection:sendMessageStream` or the game scene's tile update functions
4. **Forward data**: Frida script sends hand data to cloud via `XMLHttpRequest` or raw TCP

### Assessment
| Factor | Rating |
|--------|--------|
| Root required | No (Gadget mode injects into APK) |
| APK modification | Yes — re-signing breaks Play Store updates |
| Anti-cheat detection risk | **High** — libsgcore.so + libtobEmbedEncrypt.so are Tencent anti-tamper/anti-cheat SDKs |
| Account ban risk | Moderate-High — 腾讯 MTP/网易易盾 detect process injection |
| Maintenance | Every game update requires re-patching APK |
| Reliability | Moderate — Frida hooks can crash if offset changes |

### Alternative: Root + Frida Server
If the phone is rooted (unlikely — breaks SafetyNet/Play Integrity), Frida server can attach to running processes without APK modification. Same anti-cheat risks apply.

**Verdict**: The only VPN-free path that can directly extract data at the source. But anti-cheat/safety concerns make it risky for the primary gaming phone. Better suited for a secondary "burner" device.

---

## 12. Bonus: Android Accessibility Service Screen Reading

**Verdict: ❌ Dead end — cocos2d-x renders via OpenGL, not AccessibilityNodeInfo**

### Mechanism
An Accessibility Service app reads screen content via `AccessibilityNodeInfo` tree and extracts hand tile text.

### Why It Fails
- **Cocos2d-x renders via OpenGL ES**: Game UI elements are NOT Android View objects. They are rendered as textures in an OpenGL surface. The Accessibility tree is empty or contains only a single "GameView" node.
- **No text-to-speech data**: Accessibility services rely on `AccessibilityNodeInfo.getText()`, which is empty for OpenGL-rendered content.
- **Some games add content descriptions**: This game does not (verified via codebase — no `setContentDescription` or accessibility labels in the Lua code).
- **Exception**: If the game used Unity with TextMeshPro accessibility or native Android UI, this could work. But cocos2d-x + OpenGL = no accessibility data.

---

## Summary Matrix

| # | Approach | Phone Config | App Install | Root? | Feasibility | Recommendation |
|---|----------|-------------|-------------|-------|-------------|----------------|
| 1 | APN routing | APN change | No | No | ❌ | Consumer carrier can't do it |
| 2 | Dual-SIM routing | None | No | No | ❌ | Raw TCP bypasses per-app routing |
| 3 | USB-C Ethernet + router | Plug dongle | No | No | ⚠️ | Works but rejected (hardware) |
| 4 | Bluetooth PAN | None | No | No | ❌ | Android can't be PAN client |
| 5 | Push notifications | None (grant notification access) | No | No | ❌ | No hand data in push |
| 6 | Local file sync | None | File sync app | No | ❌ | No live data stored locally |
| 7 | scrcpy + OCR | USB once + dev options | No | No | ⚠️ | Fragile OCR + still needs VPN |
| 8 | WiFi Direct + gadget | Accept dialog each time | No | No | ❌ | No transparent routing |
| 9 | Game spectator system | None | No | No | ⚠️ | Needs cloud emulator, complex |
| 10 | Carrier MITM | None | No | No | ❌ | Not consumer feasible |
| 11 | Frida/Gadget hooking | Side-load APK | Custom APK | No | ⚠️ | Anti-cheat risk, maintenance |
| 12 | Accessibility service | Grant accessibility | Custom app | No | ❌ | OpenGL — no accessibility data |

---

## Key Takeaways

1. **Every path circles back to VPN or root/repackaging.** There is no magic non-VPN remote data exfiltration on stock Android for native binary protocol games.

2. **The game's spectator system (Watch/旁观) is the only non-VPN path to game data**, but it's more complex than VPN (cloud Android emulator, dual accounts, room access, proprietary protocol parsing).

3. **Frida/Gadget is the only path with zero network-layer reconfiguration**, but anti-cheat and maintenance burdens make it unsuitable for the primary gaming device.

4. **Hardware solutions (USB-C Ethernet + pocket router) eliminate all phone-side configuration** — just plug in a dongle. Only viable if the user relaxes the "no hardware" constraint for something as small as a thumb-drive-sized router.

5. **The WireGuard QR code + always-on VPN path remains the optimal trade-off**: minimal phone interaction (~5 taps, once), no hardware, no anti-cheat risk, mature technology, and the existing extractor pipeline stays unchanged.

