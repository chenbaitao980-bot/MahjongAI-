# Cloud Android Emulation — Run Game in Cloud, Extract Data Locally

> **Research date**: 2026-06-11  
> **Core question**: Can we run the mahjong game on a cloud Android emulator (ECS), let the user play via remote control, and extract game data from the emulator's local network — bypassing the phone VPN configuration problem entirely?  
> **Answer**: **Technically feasible, but fundamentally different use case. High account-ban risk. Massive cost.** Not recommended as primary solution; documented here for completeness.

---

## 1. The "Killer" Insight

If the game runs on the **same server** that hosts extractor + relay, then:
- Game traffic goes through the ECS's local network stack
- extractor uses `tcpdump -i any port 7777` to sniff traffic locally
- **NO VPN needed at all** — game traffic never leaves the server
- relay serves `/state` as usual

The topology would be:

```
User (browser/scrcpy) ──WebRTC/scrcpy──▶ Aliyun ECS
                                            ├─ Redroid Container (Android emulator)
                                            │    └─ Game APK (login, play mahjong)
                                            │         │
                                            │    TCP to 47.96.0.227:7777
                                            │         │
                                            ├─ extractor (tcpdump -i any) ← sniffs local
                                            └─ relay (FastAPI :8000)
                                                  │
                                            GET /state → browser
```

This is fundamentally different from the current use case: the user would be **playing the game inside the cloud emulator via remote screen**, instead of playing on their phone and tunneling traffic through a VPN.

---

## 2. Android Emulators on Linux VPS (Production-Ready)

### 2A. Redroid (remote-android) — ★6,388 — **🏆 Primary Candidate**

**Repo**: [`remote-android/redroid-doc`](https://github.com/remote-android/redroid-doc) (Apache-2.0)

Redroid (Remote Android) is a GPU-accelerated Android-in-Container solution designed specifically for cloud deployment. Key facts:

- **Runs as Docker container** on Linux host (Ubuntu, Debian, CentOS, **Alibaba Cloud Linux**, etc.)
- **Supports both amd64 and arm64** architectures
- **Android 8.1 through 16** available
- **GPU acceleration**: `androidboot.redroid_gpu_mode=host` uses host GPU for hardware rendering
- **Native bridge**: includes `libndk_translation` for running **ARM/ARM64 apps on x86_64** hosts
- **Alibaba Cloud Linux officially supported** — has dedicated deploy doc (`deploy/alibaba-cloud-linux.md`)
- **ADB exposed**: `-p 5555:5555` for remote debugging
- **scrcpy compatible**: `scrcpy -s <ip>:5555` for screen mirroring
- **WebRTC streaming** planned (porting from cuttlefish)

**Launch on Aliyun ECS**:

```bash
# Install Docker
apt install docker.io

# Install kernel modules (Aliyun Linux / Ubuntu)
apt install linux-modules-extra-`uname -r`
modprobe binder_linux devices="binder,hwbinder,vndbinder"
modprobe ashmem_linux  # optional, deprecated in 5.18+

# Launch Android 12 container
docker run -itd --rm --privileged \
    --pull always \
    -v ~/redroid-data:/data \
    -p 5555:5555 \
    --name redroid \
    redroid/redroid:12.0.0_64only-latest \
    androidboot.redroid_width=1080 \
    androidboot.redroid_height=1920 \
    androidboot.redroid_dpi=480 \
    androidboot.redroid_fps=30

# Connect via ADB
adb connect <ecs-ip>:5555

# View screen
scrcpy -s <ecs-ip>:5555
```

**Key advantage**: Runs with `--privileged` in Docker — the container's network stack is directly on the host. Game traffic from the Android container to `47.96.0.227:7777` goes through the host kernel and can be sniffed by extractor's `tcpdump -i any port 7777` running on the same host.

### 2B. Dockerify-Android — ★580 — Integrated Web UI

**Repo**: [`Shmayro/dockerify-android`](https://github.com/Shmayro/dockerify-android) (MIT)

A more opinionated Docker Android emulator with:
- **Built-in web interface**: integrated [ws-scrcpy](https://github.com/NetrisTV/ws-scrcpy) (scrcpy over WebSocket) — user controls Android from any browser
- **ARM translation** via ndk_translation
- **Pre-rooted with Magisk**
- **PICO GAPPS** included
- **Environment variables**: `RAM_SIZE`, `SCREEN_RESOLUTION`, `ARM_TRANSLATION=1`, etc.
- **Android 11** (API 30) base
- **Docker Compose** for easy deployment

**Trade-off vs Redroid**: More user-friendly (web UI out of box), but only A11, less configurable. Redroid is more flexible (multiple Android versions, GPU mode control) but requires separate scrcpy-web setup.

### 2C. Other Candidates

| Project | Stars | Notes |
|---------|-------|-------|
| Waydroid | ~11k | Requires Wayland + kernel modules. Designed for desktop Linux, not headless servers. No official Docker image. |
| Anbox Cloud | Commercial | Canonical's paid offering. Overkill. |
| Android-x86 | ~10k | Bare-metal / VM install, not containerized. Needs ISO boot. No Docker. |
| AVD (Android SDK) | Official | `sdkmanager "system-images;android-34;google_apis;x86_64"` + `avdmanager` → `emulator -no-window`. Heavy, slow without KVM. |

**Winner**: Redroid is the clear choice for headless cloud deployment on Aliyun ECS.

---

## 3. Remote Control Solutions

### 3A. scrcpy (Genymobile) — ★120k+

**Direct ADB-over-TCP** — lowest latency, highest quality. The user runs `scrcpy -s <ecs-ip>:5555` on their local machine. The scrcpy client connects directly to the ECS's ADB port.

**Latency**: ~35-70ms (H.264 encoding + network RTT). Playable for turn-based games like mahjong.

**Problem**: Requires the user to install scrcpy locally. Exposing ADB port (5555) to the internet is a **severe security risk** — anyone can `adb install malware.apk`.

### 3B. ws-scrcpy (NetrisTV) — ★2,451

**scrcpy over WebSocket in browser**. User opens a web page, streams the Android screen, controls via touch/mouse. No local software needed.

Flow: Browser ←WebSocket→ ws-scrcpy server → ADB → Redroid container

**Benefits**: Browser-based, no install, can password-protect the web page.

**Architecture**:

```
User Browser ──HTTPS/WSS──▶ ECS
                              ├─ ws-scrcpy (Node.js, port 8000)
                              │    ├─ WebSocket proxy
                              │    └─ adb connect localhost:5555
                              ├─ Redroid (port 5555)
                              ├─ extractor
                              └─ relay
```

**Deployment**: Dockerify-Android already bundles this. Standalone:
```bash
git clone https://github.com/NetrisTV/ws-scrcpy.git
cd ws-scrcpy
npm install
npm start
# Open http://ecs-ip:8000
```

### 3C. scrcpy over WebRTC

**Repo**: `hqw700/ScrcpyOverWebRTC` (★129) — scrcpy + WebRTC for ultra-low latency.

WebRTC uses UDP with NAT traversal, potentially lower latency than WebSocket-over-TCP. But more complex to set up (STUN/TURN servers needed if behind NAT).

### 3D. Direct WebRTC (Redroid's Planned Feature)

Redroid's README mentions: "Plan to port WebRTC solutions from cuttlefish, including frontend (HTML5), backend and many virtual HALs." This would make redroid natively streamable to a browser without scrcpy intermediary.

**Status**: Planned, not yet released.

### 3E. VNC

Slow, high bandwidth, poor touch input handling. Not recommended for interactive gaming.

---

## 4. Game Compatibility: ARM/ARM64 Apps on x86 Emulator

### The Problem

Chinese mahjong games (cocos2d-x) ship native `.so` files for `arm64-v8a` and `armeabi-v7a`. These are **ARM-compiled native code** that cannot run directly on x86_64 CPUs.

### The Solution: Native Bridge Translation

Redroid includes **`libndk_translation`** — Google's official ARM-to-x86 binary translator (used in Android 11+ emulator images and ChromeOS ARCVM). It intercepts ARM syscalls and JIT-translates ARM instructions to x86 at runtime.

**Prebuilt source**: [`zhouziyang/libndk_translation`](https://github.com/zhouziyang/libndk_translation)

After installing, the emulator reports:
```
ro.product.cpu.abilist = x86_64,x86,arm64-v8a,armeabi-v7a,armeabi
```

**Performance**: ~70-85% native ARM speed for compute-bound code. For a cocos2d-x mahjong game (turn-based, 2D), this is more than sufficient.

**Dockerify-Android** has `ARM_TRANSLATION=1` env variable for one-click enable.

### Known Issues

1. **Some native libs use ARM NEON SIMD** — libndk_translation may not perfectly translate all NEON instructions. Game crash or rendering glitches possible.
2. **`libhoudini`** (Intel's alternative) — proprietary, harder to integrate. libndk_translation is the open-source path.
3. **Graphics (OpenGL ES)** — cocos2d-x uses OpenGL ES. x86 emulator translates OpenGL ES → host OpenGL (via SwiftShader or host GPU). Generally works but may have visual bugs (black textures, shader compilation errors).
4. **Audio** — typically works via OpenSL ES → host ALSA/PulseAudio passthrough.

**Bottom line**: There is a non-trivial risk that the specific mahjong game won't run properly on x86 emulator. Testing with the actual APK is required. ARM64-hosted redroid avoids this entirely but costs significantly more (ARM cloud instances are scarce and expensive).

---

## 5. Network Capture on Emulator — Simpler Than Phone VPN

**This is the one part that actually gets simpler.** If the game runs inside a Docker container on the same host as extractor:

```bash
# extractor runs on the ECS host, sniffing all interfaces
tcpdump -i any port 7777 -w game.pcap

# Or the existing Python extractor with TcpdumpCaptureAdapter
python remote/extractor/main.py  # tcpdump -i any port 7777
```

The game's TCP connections (container → 47.96.0.227:7777) traverse the Docker bridge network (`docker0`) and host network stack. `tcpdump -i any` captures all of them.

**No changes to extractor/relay needed** — they work exactly as they do for the VPN scenario.

**Even better**: If the emulator is on the same ECS as extractor, there's no WAN latency between sniffer and game traffic. Perfect capture fidelity.

---

## 6. Account Ban Risk — **CRITICAL CONCERN**

### The Detection Landscape

Chinese mahjong games commonly integrate anti-cheat/anti-fraud SDKs:

- **腾讯 MTP (Mobile Tencent Protect)**: Emulator detection, root detection, hook detection
- **网易易盾 (NetEase Dun)**: Device fingerprinting, emulator detection, VPN/proxy detection
- **360加固 (360 Jiagu)**: APK hardening + runtime integrity checks
- **数美 (Shumei)**: Behavioral anti-fraud, device fingerprinting

These SDKs check for:

| Detection Layer | What They Check | Redroid Exposure |
|----------------|-----------------|------------------|
| Build props | `ro.hardware`, `ro.build.fingerprint`, `ro.product.model` | **Default is generic** — must spoof to look like a real phone |
| Kernel | `/proc/version` (Linux host kernel, not Android kernel) | **Exposed** — redroid runs on host kernel, detectable |
| CPU info | `/proc/cpuinfo` shows host CPU model | **Exposed** — "Intel Xeon" or "AMD EPYC" = server, not phone |
| GPU | `ro.hardware.egl`, GPU renderer string | **Exposed** — "SwiftShader" or "llvmpipe" = software rendering, detectable |
| Sensors | Missing accelerometer/gyro/light/proximity sensors | **Exposed** — redroid has no physical sensors, detected via SensorManager |
| IMEI/SIM | Missing IMEI, no SIM card | **Exposed** — container has no baseband |
| WiFi MAC | Docker interface MAC vs OUI registry (real phone vendor) | **Exposed** — Docker MAC doesn't match phone vendor |
| IP/ASN | Aliyun/cloud datacenter IP range | **Exposed** — well-known cloud IPs are flagged |
| TEE/Keystore | Hardware-backed keystore attestation | **Exposed** — no TEE in container, software keystore only |
| Play Integrity | SafetyNet/Play Integrity API | **Exposed** — fails BASIC integrity without spoofing |

**PhantomDroid** (servas-ai/phantomdroid) catalogs 71 detection probes across 6 layers. Their research confirms: **Android containers are highly detectable** without extensive spoofing (Magisk modules, PIF, TrickyStore, sensor playback, etc.).

### Real-World Risk

- **Account ban** is the most likely outcome if a game uses any anti-fraud SDK
- Chinese mahjong platforms have financial incentives to detect emulators (防止刷分/多开/外挂)
- Cloud IP ranges are aggressively blocked by some game servers
- Even if it works today, a game update tomorrow could add emulator detection and ban the account

### Mitigation (Fragile, High Maintenance)

Possible but complex:
1. **Magisk + Play Integrity Fix** (PIF) — spoofs SafetyNet/Play Integrity
2. **TrickyStore** — spoofs TEE keystore attestation (needs leaked keybox)
3. **LSPosed modules** — spoof device props, sensor data, IMEI, MAC
4. **Custom kernel** — hide `/proc/version` Docker artifacts
5. **Residential proxy** — route game traffic through a residential IP (not datacenter)

This is an arms race. Game anti-cheat teams actively update detection methods. Each game update may break the spoofing stack. Maintaining this is a full-time job (see PhantomDroid's "8h Autonomous Run" — that's a team maintaining detection resistance).

**Verdict**: Account ban risk makes cloud emulation a **non-viable approach** for anyone who values their game account. The current VPN approach (real phone, real device fingerprint, no emulator artifacts) has zero emulator-detection risk.

---

## 7. Existing Cloud Android Services

### Commercial "Cloud Phone" Services (云手机)

China has a mature cloud phone industry:

| Service | Description | Price |
|---------|-------------|-------|
| 红手指 (Redfinger) | Cloud Android for gaming, 24/7 AFK farming | ~¥38-68/month |
| 多多云手机 (Duoduo) | ARM-based cloud phones for gaming | ~¥30-50/month |
| 华为云手机 (Huawei) | Enterprise ARM cloud phones | ~¥100-300/month |
| 阿里云手机 (Aliyun) | ARM-based, integrated with Alibaba ecosystem | Custom pricing |
| 雷电云手机 (LDCloud) | x86 emulator in cloud | ~¥1/day |

**Key fact**: These services use **real ARM-based servers** (Kunpeng 920 / Phytium), not x86 emulation. This solves the ARM compatibility problem. But they are:
- **Shared infrastructure** — many users share a physical ARM server
- **Not programmable** — you get an Android instance, not root or network access
- **Traffic still goes to game server** — you'd need to MITM the traffic somehow
- **No extractor integration** — these are consumer products, not hackable platforms

**Some services have been known to collaborate with game companies** to detect and ban accounts used for automation/cheating on their platforms.

### DIY ARM Cloud Server

Running your own ARM server for native Android performance:
- **AWS Graviton** (arm64): `c7g.medium` (~$0.05/hr, ~$36/month) — but limited to AWS regions, no China mainland
- **Aliyun ECS arm instances** (倚天710 / Kunpeng): ~¥200-400/month for 4vCPU+8GB
  - Aliyun has `ecs.c8y` and `ecs.g8y` series with Yitian 710 ARM processors
  - 4vCPU 8GB ~¥250/month (包年包月)
  - **However**: ARM instances may not easily run redroid (redroid on arm64 requires kernel config differences)

**Cost of DIY ARM**: ¥200-400/month for hardware, plus bandwidth.

---

## 8. Cost Analysis

### Self-Hosted on Aliyun ECS

| Configuration | Monthly Cost (包月) | Suitability |
|--------------|---------------------|-------------|
| 4vCPU 8GB (ecs.s6-c1m2.large, x86) | ~¥150-200 | Bare minimum for redroid (software rendering) |
| 4vCPU 16GB (ecs.s6-c1m2.xlarge, x86) | ~¥250-350 | Comfortable for redroid |
| 8vCPU 16GB (ecs.s6-c1m2.2xlarge, x86) | ~¥400-550 | Redroid + extractor + relay + ws-scrcpy |
| 4vCPU 8GB + GPU (ecs.gn6v, T4) | ~¥1,800-2,500 | GPU-accelerated redroid (smooth 30fps) |
| 4vCPU 8GB ARM (ecs.c8y, 倚天710) | ~¥200-350 | Native ARM — no translation needed |

**Bandwidth**: Game traffic is ~10-50 KB/s. scrcpy streaming is 2-8 Mbps depending on resolution. If the user plays 4 hours/day streaming at 5 Mbps: ~9 GB/day, ~270 GB/month. Aliyun charges ¥0.80/GB beyond included traffic → ~¥200/month extra bandwidth.

**Total estimate**: ¥400-800/month (x86 + software rendering + bandwidth) to ~¥3,000/month (GPU + high bandwidth).

### Commercial Cloud Phone Comparison

| Service | Monthly | Notes |
|---------|---------|-------|
| 红手指 (Redfinger) | ¥38-68 | ARM, shared, no root/extractor access |
| 多多云手机 | ¥30-50 | ARM, shared |
| DIY Aliyun x86 redroid | ¥400-800 | Full control, higher cost |

The commercial services are cheaper but **you can't run extractor on them** — you don't control the network. The whole point of this research is to host extractor alongside the game, which requires full server control.

---

## 9. Comparison: Cloud Emulator vs VPN Tunnel

| Dimension | Cloud Emulator | VPN Tunnel (Current) |
|-----------|---------------|---------------------|
| **User plays on** | Browser/scrcpy (remote screen) | Their own phone (native) |
| **Game runs on** | ECS emulator | User's phone |
| **Extraction** | Local tcpdump (trivial) | Needs VPN to route traffic through ECS |
| **Setup friction** | Medium (install game on emulator) | High (manual VPN config) / Low (WireGuard QR) |
| **Account risk** | **VERY HIGH** (emulator detected → ban) | **None** (real phone = no emulator artifacts) |
| **Latency (gameplay)** | 50-200ms (remote screen) | 0ms (native on phone) |
| **Cost** | ¥400-3000/month | ¥50-100/month (ECS for VPN relay only) |
| **Reliability** | Emulator crash, game update, detection | Stable (real device) |
| **Maintenance** | High (anti-detection arms race) | Low (just VPN server) |
| **Use case** | Playing via remote desktop | Playing on your phone, reading hand remotely |

---

## 10. Verdict

**Cloud emulation solves the "VPN configuration" problem at the cost of introducing much bigger problems:**

1. **It changes the use case fundamentally** — from "I play on my phone, someone reads my hand" to "I play inside a cloud emulator through a remote screen." These are completely different user experiences.

2. **Account ban risk is real and high** — Chinese mahjong games aggressively detect emulators. The PhantomDroid project catalogs 71 detection vectors. Fighting detection is an ongoing arms race.

3. **Cost is 5-10x higher** — ¥400-800/month minimum vs ¥50-100/month for VPN relay only.

4. **Gameplay latency** — even with scrcpy at 35-70ms, it's a degraded experience compared to native touch input on a real phone.

5. **The existing VPN approach (scenario C) already works end-to-end** — the only friction is manual VPN field entry (3 fields), which WireGuard QR already solves (see `wireguard-android-qr-alwayson.md`).

**Recommendation**: Do NOT pursue cloud emulation as the primary solution. The WireGuard QR approach achieves the "scan QR to connect" goal with:
- No account risk (real phone)
- No cost increase (same ECS)
- No gameplay degradation
- No anti-detection maintenance

Cloud emulation may have value as an **alternative extraction method for specific use cases** (e.g., automated testing/analysis of the game protocol without a real phone), but is not suitable for the primary "zero-touch read-hand" goal.

---

## 11. Appendix: If Cloud Emulation Were Pursued Anyway

### Minimum viable stack

```
Aliyun ECS (8vCPU 16GB, Ubuntu 22.04, ¥400/month)
├── Docker + redroid (Android 12, 64bit only)
│   ├── libndk_translation (ARM apps on x86)
│   ├── Magisk + PIF (Play Integrity spoofing)
│   ├── LSPosed + device props spoofing module
│   └── Game APK sideloaded
├── ws-scrcpy (browser-based remote control, port 8443 + Let's Encrypt)
├── extractor (tcpdump -i any port 7777)
└── relay (FastAPI :8000)
```

### Anti-detection layers (best-effort, not guaranteed)

| Layer | Tool | Coverage |
|-------|------|----------|
| L1 (build props) | MagiskHide Props Config | ro.build.fingerprint, model, brand |
| L2 (identity) | Custom IMEI/MAC spoof module | android_id, wifi_mac, IMEI |
| L3 (integrity) | Play Integrity Fix + TrickyStore | BASIC/DEVICE integrity |
| L4 (root hide) | Magisk Zygisk + Shamiko | Hide root from game |
| L5 (sensors) | Sensor playback module | Spoof accelerometer/gyro data |
| L6 (network) | Residential proxy/Tor | Datacenter IP → residential IP |

**Never guaranteed to work** — game anti-cheat teams actively counter these techniques.

### Why this stack fails

Even with all spoofing layers:
- `/proc/version` shows host Linux kernel (not Android kernel build string)
- `/proc/cpuinfo` shows server CPU (Xeon/EPYC → not a phone SoC)
- No TEE/StrongBox = hardware attestation fails (TrickyStore needs leaked keybox, which gets revoked)
- Behavioral analysis (no cellular tower changes, no WiFi scan results, no Bluetooth scans)
- Game-specific checks (some games detect Docker/LXC containment directly via `/proc/1/cgroup`)
