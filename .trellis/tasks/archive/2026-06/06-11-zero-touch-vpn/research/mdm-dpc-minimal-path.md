# MDM / Device Owner 最低摩擦路径 (Android 无 app 幻想的唯一落脚点)

> 2026-06-11 — Research Agent
> Context: 用户在 PRD 中表达了强烈偏好 — "系统原生 IKEv2 + Always-On + 无 app + 零配置"。
> 本文档回答：这个偏好在通用 Android 上能走多远？什么是最接近的实现？

---

## 残酷事实：两重门

```
理想的栈:
  系统 IKEv2 ─── SCEP/PKI ─── Always-On ─── 零 app ─── 零用户操作
     ✅              ❌            ⚠️           ✅          ⚠️
     (内置)      (需 MDM)    (需 MDM+app 包名)           (需 MDM)

可兑现:
  [1] 系统 IKEv2      ✅  任何 Android
  [2] Always-On       ✅  但必须指向 VPN app 包名
  [3] 零 app          ❌  Always-On 与 "零 app" 互斥 (见下)
  [4] 零用户操作      ❌  必须 MDM Device Owner 才能实现
```

**互斥根源**：Android `setAlwaysOnVpnPackage()` 的签名是 `setAlwaysOnVpnPackage(ComponentName admin, String vpnPackage, boolean lockdown)`。

- `admin` = DevicePolicyManager admin (需要 DEVICE_OWNER)
- `vpnPackage` = **VPN 应用的包名**（如 `com.wireguard.android`）
- 系统内置 IKEv2 没有独立的包名 → **无法被这个 API 瞄准**

→ "系统 IKEv2 + Always-On" 在 Android 上合法存在（如三星 Knox），但通用 Android 上这是对 iOS 行为模式的错误投射。

---

## 三星 Knox：唯一的 "Android 版 iOS 体验"

三星设备通过 Knox Service Plugin (KSP) 提供了一个例外路径：

```
Knox Service Plugin (MDM profile)
    ↓
可下发:
  - 内置 IPsec VPN 配置 (server, PSK/cert, type)
  - Always-On VPN = ON
  - 锁定 VPN 设置 (禁止用户关闭)
  - 无需 VPN app
```

### Knox 需要的条件：
1. **Samsung 设备**（任何支持 Knox 2.8+ 的设备，Galaxy S6 起）
2. **Knox license key**（Samsung Knox 开发者免费，个人/小规模使用免费）
3. **MDM 平台或 Knox Service Plugin 兼容的 DPC**

### 最小的实施路径：
- 使用 **Samsung Knox Service Plugin** + **Android Management API (AMAPI)**
- AMAPI 是企业级但免费（无设备数量限制）
- 在 AMAPI 策略中配置 `alwaysOnVpnPackage` + VPN app 的 managed config
- 但注意：AMAPI 需要通过 Managed Google Play 下发 VPN app → 还是需要 VPN app

**或者**：直接用 Knox SDK 写一个最小 DPC，调用 Knox 的 `GenericVpnPolicy` 来配置系统内置 VPN + Always-On。

### 评估：
- ✅ 唯一能兑现 "系统 IKEv2 + Always-On + 零 VPN app" 的 Android 路径
- ❌ 锁定三星品牌
- ❌ 仍需要 MDM provisioning（QR/factory reset 流程）
- ⚠️ Knox 开发有一定学习曲线

**如果专用读牌设备可以买一台三星手机（Galaxy A 系列 ≈ ¥500-800），这是一个理论上可行的"零 app"方案。**

---

## 通用 Android：最小 DPC for WireGuard Auto-Install

如果接受"必须一个 VPN app" + "必须 Device Owner" 的前提，可以做一个极简 DPC：

### DPC 功能清单:
```
1. DeviceAdminReceiver (标准 DPC 骨架)
2. 监听 ACTION_PROFILE_PROVISIONING_COMPLETE
3. 通过 PackageInstaller 静默安装 WireGuard APK
4. 配置 WireGuard managed config:
   - wg-quick config string (JSON via setApplicationRestrictions)
   - 或直接放置配置文件在 app 的 data 目录
5. setAlwaysOnVpnPackage("com.wireguard.android", lockdown=true)
6. 禁用 DPC 图标 / 隐藏 UI (完全透明)
```

### 代码量估算:
- DeviceAdminReceiver: ~30 行
- WireGuard 安装 + 配置: ~80 行
- Always-On 设置: ~10 行
- Provisioning 响应: ~40 行
- **总计: ~160 行 Java/Kotlin**

### 用户流程:
```
1. 新手机 / 出厂重置后的手机 → 开机设置向导
2. 连续点 6 次欢迎屏幕 → 激活 QR 码扫描
3. 扫描 DPC provisioning QR 码
4. 点 "接受并继续" (~2 次确认)
5. DPC 在后台安装 WireGuard → 配置 → 启用 always-on
6. 完成 → VPN 已自动连接
```

### 限制:
- **必须出厂重置**（或新买的手机首次开机）
- 已有数据的手机无法这样操作（会丢数据）
- 仅适合"专用读牌设备"
- 用户失去设备控制权（Device Owner 拥有最高权限）

---

## MDM 方案总结表

| 方案 | 平台限制 | App 安装 | 初始摩擦 | 适用场景 |
|------|---------|---------|---------|---------|
| **三星 Knox + 系统 IKEv2** | 三星 | 零 | ~5 taps | 专用三星读牌设备 |
| **最小 DPC + WireGuard** | 任何 Android | 1 (自动) | ~5 taps | 专用读牌设备 (新手机) |
| **WireGuard QR (手动)** | 任何 Android | 1 (手动) | ~8 taps | 任何 Android (推荐) |
| **手打 IKEv2 (当前)** | 任何 Android | 零 | ~12-15 taps | 当前方案 (保留) |

---

## 推荐

**不要做 DPC/MDM 路线。** 理由：

1. **投入产出比极差**：DPC 需要 Play Store 发布、维护、MDM 平台账号、Signing key 管理等。节省用户 3-5 次点击 vs. WireGuard QR 手动方案，不值得。

2. **WireGuard QR 已经足够好**：8 次点击 + 零输入 ≈ "扫码即用" 的用户感知。用户不会纠结"多点了 3 下"。

3. **三星 Knox 锁定品牌**：如果未来换非三星设备，方案报废。

4. **MDM 对用户心理负担重**："这个软件要我交出整个手机的完全控制权"——比"装一个开源 VPN app" 更让人警惕。

5. **已有 Apple 的 .mobileconfig 兜底**：如果用户有 iPhone，~6 点击 + 零输入 + 零 app。

**最终推荐栈：WireGuard QR (Android 主力) + .mobileconfig (iOS 可选) + 保留手打 IKEv2 (回退)。DPC/MDM 不做。**
