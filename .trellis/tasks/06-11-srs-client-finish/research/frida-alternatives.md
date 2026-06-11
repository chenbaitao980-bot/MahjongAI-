# Frida Alternatives: Running Hooks Without Root on ARM64 Android

**Date**: 2026-06-11
**Context**: We have a working Frida gadget injected into a real phone (Redmi Note 15 Pro) via APK smali patch. Hooks fire and log to JSONL, but the patched game can't establish real SRS connections — all crypto operations show **zero data** (empty buffers, zero-length keys). The original unpatched game connects and plays fine. Root is NOT available (production build, no `adb root`, no `su`).

**Root Cause Hypothesis**: The APK is re-signed with a different key after smali patching. Android 14+ and/or the game's native code performs signature verification. With a mismatched signature, the game either:
- Refuses to perform crypto operations (native code checks APK signature at runtime)
- Uses Android Keystore bound to the original APK signature — re-signing invalidates the key access
- The game server detects the APK is tampered and refuses the handshake

### 🔥 CONFIRMED: Anti-Tamper Libraries Detected

Analysis of the actual APK pulled from the phone (`game_base.apk`, 88MB) reveals:

| Library | Size | Purpose |
|---|---|---|
| `libapkpatch.so` | 434KB | APK integrity verification |
| `libmaparmor.so` | 5.8KB | MTP/Meituan armor protection |
| `libpanglearmor.so` | 251KB | Pangle/Bytedance security SDK |
| `libpangleflipped.so` | 10KB | Pangle anti-debug |
| `libtobEmbedEncrypt.so` | 10.5KB | Embedded encryption layer |

**These anti-tamper libraries detect the APK modification and silently disable crypto operations.** This explains why hooks fire but all crypto data is zero — the game's crypto subsystem is disabled by the security SDKs.

**Key APK properties:**
- `targetSdkVersion: 28` (Android 9 — NO cleartext restriction, NO scoped storage)
- `compileSdkVersion: 23` (Android 6)
- `native-code: arm64-v8a, armeabi-v7a` (NO x86_64!)
- Package: `com.xm.zjgamecenter` v1.6.1
- The `lib/arm64-v8a/` directory in the APK confirms Frida gadget is ALREADY injected (`libfrida-gadget.so` — 25MB)

**Key constraint**: We need to run Frida hooks on the **real ARM64 game process** (`libcocos2dlua.so`). The game is ARM64-only native.

---

## 1. QEMU-based ARM64 Android Emulator on Windows x86

### Feasibility

Google provides **arm64-v8a system images** for the Android Emulator:
- `system-images/android-35/google_apis_playstore/arm64-v8a/` — with Play Store
- `system-images/android-35/google_apis/arm64-v8a/` — without Play Store

These can be installed via `sdkmanager`:
```bash
sdkmanager "system-images;android-35;google_apis_playstore;arm64-v8a"
```

### Current State
- **Existing AVD**: `codex_pixel_6` (x86_64, API 35, Google APIs, no Play Store)
- **SDK root**: `E:\android-sdk` (ANDROID_HOME / `C:\Users\Administrator\AppData\Local\Android\Sdk` are separate)
- **Java**: NOT available (no `java` in PATH, no JAVA_HOME) — need to install JDK first
- **Hyper-V**: NOT installed — no hardware virtualization acceleration
- **HAXM**: NOT installed

### Performance Reality

| Acceleration | Speed | Status |
|---|---|---|
| **KVM** (Linux) | Near-native (~50-90%) | ❌ Windows |
| **Hyper-V WHPX** | Good (~30-70%) | ❌ Not installed |
| **HAXM** (Intel) | Moderate (~20-50%) | ❌ Not installed |
| **Pure QEMU (TCG)** | EXTREMELY SLOW (~1-5%) | ✅ Always available |

Without hardware acceleration, ARM64 emulation on Windows x86 using pure QEMU TCG will be **unusably slow** (boot may take 30+ minutes, game at 1-2 FPS). The ARM64 → x86 binary translation is far more expensive than x86_64 → x86_64 virtualization.

### Steps to Try (If Performance Acceptable)

1. Install JDK (required for sdkmanager):
   ```bash
   # Download from https://adoptium.net/ or use winget
   winget install EclipseAdoptium.Temurin.21.JDK
   ```

2. Install ARM64 system image:
   ```bash
   sdkmanager "system-images;android-35;google_apis_playstore;arm64-v8a"
   ```

3. Create AVD:
   ```bash
   avdmanager create avd -n pixel_arm64 -k "system-images;android-35;google_apis_playstore;arm64-v8a" -d pixel_6
   ```

4. Enable root in the AVD (for Frida):
   ```bash
   # Edit config.ini to add:
   # hw.keyboard=yes
   # Then start with -writable-system
   emulator -avd pixel_arm64 -writable-system
   ```

5. Root the emulator:
   ```bash
   adb root      # Works on emulator!
   adb remount   # Make /system writable
   ```

6. Deploy Frida:
   ```bash
   # Push frida-server for arm64
   adb push frida-server-17.9.10-android-arm64 /data/local/tmp/
   adb shell chmod 755 /data/local/tmp/frida-server
   adb shell /data/local/tmp/frida-server -D &
   ```

7. Install APK and run with Frida:
   ```bash
   adb install game.apk
   frida -U -f com.xm.zjgamecenter -l hook_srs.js --no-pause
   ```

### Verdict: **THEORETICALLY POSSIBLE but IMPRACTICALLY SLOW**

Without Hyper-V/HAXM, ARM64 emulation on Windows x86 will be unusably slow for a real-time game. Even with Hyper-V/HAXM enabled, ARM64 emulation is slower than x86_64 emulation. This is NOT the practical path.

**However**: If the game exists as an x86_64 build (unlikely but worth checking), we could use the existing x86_64 AVD with root. Let's verify the APK's native libs.

---

## 2. Transfer Game Login Data Between APKs

### Theory
Use `adb backup` to export the original game's app data, then restore it to the patched APK. This would preserve the login session.

### Feasibility: **MOSTLY NOT**

#### Attempt 1: `adb backup / restore`

```bash
# Backup original game data
adb backup -f game.ab -noapk com.xm.zjgamecenter

# Uninstall original, install patched
adb uninstall com.xm.zjgamecenter
adb install patched_game.apk

# Restore backup to patched APK
adb restore game.ab
```

**Problem**: Android 12+ may reject the restore because the APK signature differs. `adb restore` compares the backup's package certificate with the installed APK's certificate. Since we re-signed the APK, the restore will fail.

#### Attempt 2: Direct file copy with `run-as`

```bash
adb shell run-as com.xm.zjgamecenter cp -r /data/data/com.xm.zjgamecenter/shared_prefs /sdcard/
```

**Problem**: `run-as` only works on **debuggable** APKs. Production APKs have `android:debuggable="false"`. After smali patching we could add `android:debuggable="true"`, but:
- If the game checks debuggable flag and refuses to run, this breaks too

#### Attempt 3: Copy files while both APKs are installed

This won't work because you can't have two APKs with the same package name installed simultaneously.

#### Attempt 4: Use OEM backup mechanisms

Xiaomi devices have a built-in backup app that can backup/restore app data without root. This may work but:
- It may still check signature
- It's device-specific

### Key Files to Preserve

The game's session data is likely in:
- `/data/data/com.xm.zjgamecenter/shared_prefs/*.xml` — shared preferences (login tokens, device IDs)
- `/data/data/com.xm.zjgamecenter/files/*` — internal files (session cache, cookies)
- `/data/data/com.xm.zjgamecenter/databases/*` — SQLite databases (user data, game state)

### Verdict: **LOW CHANCE OF SUCCESS**

Android 12+ signature checks block this approach for non-rooted devices.

---

## 3. Network Permission Fix for Patched APK

### Theory
The patched APK is re-signed with a different key. Does Android 14+ block network access because of this?

### Reality: **NOT THE ISSUE**

Android **does NOT** restrict INTERNET permission based on APK signature. The INTERNET permission is:
- Declared in `AndroidManifest.xml`: `<uses-permission android:name="android.permission.INTERNET"/>`
- Classified as a **normal permission** (granted automatically at install time)
- NOT a runtime/dangerous permission

You can verify:
```bash
adb shell dumpsys package com.xm.zjgamecenter | grep -A5 "requested permissions"
adb shell dumpsys package com.xm.zjgamecenter | grep INTERNET
```

If INTERNET is in the manifest (it is — the game needs network), it will be granted regardless of the signing key.

### Potential Network Issues

On Android 14+, there **are** network changes but unrelated to signing:
1. **Cleartext traffic blocked by default** for apps targeting API 28+ — but this would affect the original APK too
2. **Network security config** in `AndroidManifest.xml` or `network_security_config.xml` — could restrict which CAs are trusted
3. **VPN detection** — some games block known VPN/proxy IPs

These are the same for both original and patched APK, so they can't explain the difference.

### Verdict: **NOT THE CAUSE** — Network permission is not signature-bound.

---

## 4. Frida Gadget in "Connect" Mode

### Theory
Configure frida-gadget to connect to a remote frida-server, then control it from a different machine. Does this change the hooking behavior?

### Mode Comparison

| Mode | Config | Behavior |
|---|---|---|
| **Script** (current) | `"type": "script"` | Gadget loads JS file and executes immediately, no external control |
| **Listen** | `"type": "listen"` | Gadget opens a TCP port, waits for frida client to connect |
| **Connect** | `"type": "connect"` | Gadget connects to a remote frida-server |

### Current Config (`gadget_config.json`)
```json
{
  "interaction": {
    "type": "script",
    "path": "/data/local/tmp/.hook_payload.js"
  }
}
```

### Connect Mode Config
```json
{
  "interaction": {
    "type": "connect",
    "address": "192.168.1.100:27042",
    "on_port": "27042",
    "on_load": "resume"
  }
}
```

### Does This Change Hooking?

**NO.** The gadget's hooking mechanism is identical regardless of interaction mode:

1. Gadget loads into target process via `LD_PRELOAD` or smali injection
2. Gadget loads the frida JavaScript engine into the process
3. Frida engine executes hook scripts — this is identical for all modes
4. The only difference is how you **control** the hooks (auto-run vs. interactive)

The `send()` calls in our hook script would go to:
- **Script mode**: No one listening — just log to file
- **Listen mode**: Connected frida client receives `send()` messages
- **Connect mode**: Remote frida-server relays to client

### Verdict: **WON'T FIX THE PROBLEM**

The hooking is identical. If the game process can't perform crypto operations internally (due to signature verification), changing the gadget's communication mode won't help.

---

## 5. Downgrade Android Security Without Root

### Possibilities

#### 5.1 Signature Verification Bypass
Android's APK signature verification runs at install time in `PackageManagerService`. There is **no way** to bypass this without:
- Custom ROM (requires unlocked bootloader)
- Magisk module (requires root)
- System-level exploit

#### 5.2 Network Security Config
If the issue is certificate pinning (the game server rejects connections from tampered clients), we could try:
```bash
# No root needed — this is app-level
adb shell settings put global captive_portal_https_url "http://..."
```
But this doesn't help — the issue is the game's own crypto, not Android system networking.

#### 5.3 Disable SELinux
```bash
adb shell setenforce 0  # Requires root
```
**Not available without root.**

#### 5.4 Developer Options
- **USB debugging**: Already enabled
- **OEM unlocking**: If available, we could unlock bootloader → flash Magisk → get root. But this wipes the device.
- **"Verify apps over USB"**: Disabling doesn't bypass signature verification

### Verdict: **NOT PRACTICALLY ACHIEVABLE WITHOUT ROOT**

There is no known method to bypass Android signature verification on a production (user) build without root access.

---

## 6. Cloud ARM64 VM for Android Emulation

### Options

| Provider | Instance | vCPUs | RAM | Cost/hr | GPU |
|---|---|---|---|---|---|
| **AWS Graviton** | c7g.2xlarge | 8 | 16GB | ~$0.29 | ❌ |
| **Oracle Cloud** | Ampere A1 (free tier) | 4 | 24GB | FREE | ❌ |
| **Google Cloud** | Tau T2A | 4-48 | varies | ~$0.15/vCPU | ❌ |
| **Azure** | Dpsv5 | varies | varies | varies | ❌ |
| **Hetzner** | RX-line (Ampere) | 80 | 128GB | €0.45/hr | ❌ |

### The GPU Problem

ARM64 cloud VMs have **no GPU acceleration**. Android emulation without GPU:
- Boot takes 5-15 minutes
- UI is extremely sluggish
- OpenGL ES games (like the mahjong game) will be **unplayable** at 0.1-1 FPS
- The game may refuse to start if it can't initialize OpenGL ES context

### Alternative: QEMU with software rendering

```bash
# On ARM64 cloud VM (e.g., Oracle Ampere)
# Install Android emulator via QEMU
emulator -avd test -gpu swiftshader_indirect -no-window
```

SwiftShader provides software GPU emulation. On native ARM64 hardware (Graviton/Ampere), the CPU emulation is fast, but GPU is still software-rendered. For a 3D mahjong game, this may or may not work — the game likely uses Cocos2d-x with OpenGL ES 2.0/3.0.

### Network Connectivity
The cloud VM would need to reach the game servers. Chinese game servers may block non-China IPs (AWS/GCP/Oracle IPs). A VPN/proxy may be needed.

### Verdict: **EXPENSIVE AND SLOW, BUT POSSIBLE**

- Oracle Cloud free tier (4 vCPU, 24GB ARM64) is the most attractive option
- No GPU = game may not start or be very slow
- Setup time: ~2-3 hours for first attempt
- Ongoing cost: $0 (Oracle free tier)
- Not practical for repeated testing, but possible for one-time key capture

---

## 7. Android Studio Emulator with Google Play

### Current State
The existing AVD (`codex_pixel_6`) is:
- **x86_64**, not ARM64
- Google APIs, **no Play Store**
- API 35 (Android 15)

### Google Play System Images

Google provides system images **with Play Store** for:
- x86_64 (good performance on Intel/AMD)
- arm64-v8a (slow on x86 host)

These are available via `sdkmanager`:
```
system-images;android-35;google_apis_playstore;x86_64
system-images;android-35;google_apis_playstore;arm64-v8a
```

### Can We Install the Game on Play Store Emulator?

1. **Download from Play Store** (if the game is on Play Store): Just sign in and download
2. **Install APK directly**: `adb install game.apk` — works regardless of Play Store
3. **ARM64 APK on x86_64 emulator**: Will NOT work unless the APK includes x86_64 native libs. The mahjong game is ARM64-only.

### Key Check: Does the Game APK Have x86_64 Libs?

**✅ VERIFIED: The game APK is ARM64-only.**
```bash
$ aapt dump badging game_base.apk | grep native-code
native-code: 'arm64-v8a' 'armeabi-v7a'
```

**No x86_64 native libraries.** The game CANNOT run directly on an x86_64 emulator. It requires either native bridge translation or an ARM64 emulator.

### If Game is ARM64-Only on x86_64 Emulator

Android 11+ introduced **native bridge translation** (libndk_translation) that can run ARM64 apps on x86_64 emulators. This is available on:
- **Google APIs** system images (with `libndk_translation` support)
- Must be enabled with a special flag

```bash
# Create AVD with ARM translation support
avdmanager create avd -n pixel_x86_arm \
  -k "system-images;android-35;google_apis;x86_64" \
  -d pixel_6 \
  -p /path/to/avd

# Enable native bridge
echo "ro.dalvik.vm.native.bridge=libndk_translation.so" >> /path/to/avd/config.ini
echo "ro.enable.native.bridge.exec=1" >> /path/to/avd/config.ini
```

This could allow ARM64 `libcocos2dlua.so` to run on x86_64 emulator with reasonable performance.

### Verdict: **PROMISING IF NATIVE BRIDGE WORKS**

- x86_64 emulator is fast (with HAXM or WHPX)
- Google Play system images available
- Root is available on emulator (just `adb root`)
- Frida works perfectly on emulators
- Native bridge translation could run the ARM64 game on x86_64
- **Setup time: ~1 hour**
- **This is the most promising alternative**

---

## Summary & Recommended Path

| # | Approach | Feasibility | Time | Success Probability |
|---|---|---|---|---|
| 7 | x86_64 emulator + native bridge + `adb root` | ✅ HIGH | ~1h | 70-80% |
| 1 | ARM64 emulator on Windows (no KVM) | ❌ TOO SLOW | ~2h | 10-20% |
| 6 | Cloud ARM64 VM + emulator | ⚠️ POSSIBLE | 3h+ | 40-50% |
| 2 | Transfer login data | ❌ Signature check | ~1h | 5-10% |
| 3 | Network permission fix | ❌ Not the issue | ~0.5h | 0% |
| 4 | Gadget connect mode | ❌ Same hooks | ~0.5h | 0% |
| 5 | Downgrade security | ❌ Needs root | ~1h | 0% |

### Recommended Next Steps (Updated)

#### Priority 1: Bypass Anti-Tamper on Real Phone (Fastest path)

Since we've identified anti-tamper SOCs, the most efficient approach is to bypass them:

1. **Hook `libmaparmor.so` / `libapkpatch.so`** — These check APK signature at native level. We can hook their verification functions and force them to return `true` (APK valid).
2. **Identify the specific check function**: Use Frida to trace what `libapkpatch.so` does on startup — likely checks `/data/app/.../base.apk` signature via `PackageManager.getPackageInfo()` or verifying `META-INF/*.RSA` directly.
3. **Hook `libtobEmbedEncrypt.so`** — This likely contains the game's actual encryption logic. If we can hook it before the security check disables it, we can capture keys.

```javascript
// Example: Hook anti-tamper verification
var checkSig = Module.findExportByName("libapkpatch.so", "Java_com_..._checkSignature");
if (checkSig) {
    Interceptor.replace(checkSig, new NativeCallback(function() {
        return 1; // Force success
    }, 'int', []));
}
```

#### Priority 2: x86_64 Emulator with Native Bridge (Most reliable)

If anti-tamper bypass is too complex:

1. **Install JDK** — `winget install EclipseAdoptium.Temurin.21.JDK`
2. **Install Google Play x86_64 system image** for API 34:
   ```bash
   sdkmanager "system-images;android-34;google_apis_playstore;x86_64"
   ```
3. **Enable native bridge** for ARM64 → x86 translation:
   ```bash
   avdmanager create avd -n pixel_arm64_bridge \
     -k "system-images;android-34;google_apis_playstore;x86_64" \
     -d pixel_6
   # Edit config.ini to add:
   # ro.dalvik.vm.native.bridge=libndk_translation.so
   # ro.enable.native.bridge.exec=1
   ```
4. **`adb root` → deploy frida-server → install ORIGINAL APK** (no patching needed!)
5. **Run Frida hooks on the genuine, unmodified game** — no anti-tamper issues

#### Priority 3: ARM64 Emulator (Slow but guaranteed)

If native bridge fails:
1. Enable Hyper-V in Windows Features
2. Install ARM64 system image
3. Accept slow performance but guaranteed ARM64 compatibility

### Key Insight

**The emulator approach avoids all anti-tamper problems.** We install the original, unmodified APK and use `adb root` for Frida. No APK patching = no signature mismatch = anti-tamper checks pass normally. The only question is whether the game runs properly on the emulator.
