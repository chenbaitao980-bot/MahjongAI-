# iOS .mobileconfig 方案：梦想栈的落地路径

> 2026-06-11 — Research Agent
> Context: PRD 中描述的"梦想栈"（系统 IKEv2 + Always-On + 无 app + 零配置）在 Android 上无法兑现，
> 但在 iOS 上完全原生支持且无需 MDM。如果专用读牌设备可以是 iPhone，这就是最优解。

---

## iOS 原生 VPN 能力全景

| 能力 | iOS 原生支持? | 需要 MDM? |
|------|-------------|----------|
| IKEv2/IPSec (系统级) | ✅ 内置 | ❌ |
| 二维码/链接下发 VPN 配置 | ✅ `.mobileconfig` | ❌ |
| On-Demand (按 SSID/网络类型自动切换) | ✅ `OnDemandRules` | ❌ |
| Always-On VPN | ✅ `OnDemandRules` 可达 | 仅 Supervised 模式强制 |
| 证书认证 | ✅ SCEP / 手动安装 | ❌ (SCEP 需 MDM) |
| PSK 认证 | ✅ | ❌ |

**关键洞察：iOS .mobileconfig 可以用纯 PSK 认证（与当前 strongSwan 配置完全兼容），无需证书、无需 SCEP、无需 MDM。用户只需扫码 → 点几下确认 → 之后就自动连接。**

---

## .mobileconfig 文件结构 (IKEv2 PSK + OnDemand)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>PayloadContent</key>
    <array>
        <dict>
            <key>PayloadType</key>
            <string>com.apple.vpn.managed</string>
            <key>PayloadVersion</key>
            <integer>1</integer>
            <key>PayloadIdentifier</key>
            <string>com.mahjong.vpn</string>
            <key>PayloadUUID</key>
            <string>00000000-0000-0000-0000-000000000001</string>
            <key>PayloadDisplayName</key>
            <string>Mahjong VPN</string>
            <key>UserDefinedName</key>
            <string>Mahjong VPN</string>
            <key>VPNType</key>
            <string>IKEv2</string>
            <key>IKEv2</key>
            <dict>
                <key>RemoteAddress</key>
                <string>8.136.37.136</string>
                <key>RemoteIdentifier</key>
                <string>8.136.37.136</string>
                <key>LocalIdentifier</key>
                <string></string>
                <key>AuthenticationMethod</key>
                <string>SharedSecret</string>
                <key>SharedSecret</key>
                <string>your-psk-here</string>
                <key>ServerCertificateIssuerCommonName</key>
                <string></string>
                <!-- iOS 15+ 支持 PSK 无需证书 -->
                <key>EnablePFS</key>
                <true/>
                <key>UseConfigurationAttributeInternalIPSubnet</key>
                <false/>
            </dict>
            <key>OnDemandEnabled</key>
            <integer>1</integer>
            <key>OnDemandRules</key>
            <array>
                <!-- 在家连 WiFi 时断开 VPN -->
                <dict>
                    <key>InterfaceTypeMatch</key>
                    <string>WiFi</string>
                    <key>SSIDMatch</key>
                    <array>
                        <string>HomeWiFi</string>
                        <string>家WiFi名称</string>
                    </array>
                    <key>Action</key>
                    <string>Disconnect</string>
                </dict>
                <!-- 其他任何网络自动连接 -->
                <dict>
                    <key>Action</key>
                    <string>Connect</string>
                </dict>
            </array>
        </dict>
    </array>
    <key>PayloadDisplayName</key>
    <string>Mahjong VPN Profile</string>
    <key>PayloadIdentifier</key>
    <string>com.mahjong.vpn.profile</string>
    <key>PayloadType</key>
    <string>Configuration</string>
    <key>PayloadUUID</key>
    <string>00000000-0000-0000-0000-000000000000</string>
    <key>PayloadVersion</key>
    <integer>1</integer>
</dict>
</plist>
```

---

## 用户流程

```
步骤 1: 用户用 iPhone 相机扫 QR 码（或点链接）
        └─ Safari 打开 URL → 自动下载 .mobileconfig 文件

步骤 2: 系统弹出 "此网站正尝试下载一个配置描述文件"
        └─ 用户点 "允许"

步骤 3: Settings 自动打开 "已下载描述文件" 页面
        └─ 用户点 "Mahjong VPN Profile"
        └─ 用户点右上角 "安装"
        └─ 输入设备密码 (Face ID / Touch ID)
        └─ 点 "安装" 确认

步骤 4: VPN 配置已安装
        └─ 无需手动做任何事
        └─ OnDemandRules 生效: 出门用蜂窝 → 自动连 IKEv2
        └─ 回家连白名单 WiFi → 自动断开

总点击：约 6 下（允许→点profile→安装→输密码→安装确认→完成）
总时间：约 30 秒
之后：完全自动，零操作
```

**关键差异 vs. 当前 Android**:
- Android: 12-15 点击 + 手动输入 IP + PSK（有打错风险）
- iOS: ~6 点击 + 零输入（QR 码 / 链接直接下载）

---

## QoS: 二维码投送方式

### 方式 A: 托管在云 relay 静态目录（推荐）

```python
# 在 vpn_configure.py 中新增 --ios 模式
# 生成 .mobileconfig 文件放在 relay static/ 下
# QR 码指向 http://<云IP>:8000/mahjong-vpn.mobileconfig
```

### 方式 B: data: URI 二维码

```
data:application/x-apple-aspen-config;base64,PD94bWwgdm...
```
直接编码 .mobileconfig 到二维码，但 URL 太长可能超出 QR 码容量（建议用短链接）。

### 方式 C: 短链接服务

```
https://t.co/xxxx → 302 → http://<云IP>:8000/mahjong-vpn.mobileconfig
```

---

## .mobileconfig 签名 vs 未签名

| 属性 | 签名 (由受信任机构签发) | 未签名 |
|------|----------------------|--------|
| 安装界面 | 绿色 "已验证" | 红色 "未签名" 警告 |
| 用户信任 | 高 | 中等 (显示"未签名"但允许安装) |
| 所需资源 | 需要 Apple Developer 企业证书 ($299/yr) 或第三方签名 | 无需任何证书 |
| 适用场景 | 企业/大规模部署 | 个人/小范围使用 |

**对于本项目的"给自己/朋友用"，未签名 .mobileconfig 完全够用**。iOS 会显示 "此描述文件未签名" 但用户仍可点 "安装" 确认。这与 Android 上安装 APK 的 "未知来源" 类似。

若需要签名（更专业的外观），可使用：
- Apple Configurator 2 (Mac 免费工具) 签名
- 第三方签名服务
- LetsEncrypt + 自建描述文件签名基础设施

---

## 与现有 strongSwan 的兼容性

好消息：**.mobileconfig 中指定的 IKEv2 PSK 方案与现有 strongSwan 配置 100% 兼容**。

当前 strongSwan 已经配置了：
```
leftauth=psk
rightauth=psk
```

这意味着：
- iPhone 用 .mobileconfig 装了 IKEv2 PSK 配置后，直接连现有的 strongSwan 服务器
- Android 继续用手打方案连同一个 strongSwan
- 不需要改任何服务端配置
- 两台设备可以同时连接（strongSwan 的 `uniqueids=no` 允许多客户端）

**唯一需要的是生成一个 .mobileconfig 文件 + QR 码，挂在云 relay 的静态目录。**

---

## iPhone 作为专用读牌设备的可行性

### 硬件需求极低：
- 任何支持 iOS 12+ 的 iPhone（iPhone 5s 及以上，2013年+）
- 不需要插 SIM 卡（连 WiFi 也能 On-Demand Connect，用蜂窝才会切 4G）
- 不需要最新 iOS（IKEv2 + OnDemand 从 iOS 9 就开始支持）
- 二手 iPhone SE (2016) ≈ ¥200-300，完全够用

### 与 Android 读牌手机的关系：
- iPhone 作为"专用读牌设备"：始终开着，插着电，蜂窝数据只打牌用
- 用户自己的 Android 手机正常使用，不受影响
- 或者：如果用户本来就双持，直接 iPhone 装 .mobileconfig

---

## Android vs iOS 路线总结

```
         ┌─ 必须 Android ───┬─ 接受装 1 个 app ─── WireGuard QR (~8 taps)
         │                  │
         │                  └─ 不接受 app ─────── 手打 IKEv2 (当前方案)
         │
         选平台 ─┤
         │
         │      ┌─ 不用 MDM ─── .mobileconfig + QR (~6 taps, 零输入)
         │      │
         └─ 可用 iOS ───┤
                │
                └─ 用 MDM (Supervised) ──── 零点击全自动
                   (不需本项目范围)
```

---

## 实施建议

1. **不做 iOS 支持作为正式目标**（PRD 说了 "iOS 支持 out of scope"）
2. **但可为 iPhone 用户提供便利**：在 `vpn_configure.py` 加一个 `--ios-mobileconfig` 标志，生成 .mobileconfig + QR 码放在 relay static/
3. **这样 Android 主力 + iOS 可选**，云端 strongSwan 不变
4. .mobileconfig 生成器很简单（~50 行 Python）

### 最小实施：
```python
# 在 vpn_configure.py 中
python vpn_configure.py --server-ip <IP> --ios-mobileconfig

# 输出:
# mobileconfig/mahjong-vpn.mobileconfig  (放在 relay/static/)
# mobileconfig/vpn-qr-ios.png             (QR 指向 mobileconfig URL)
# relay/static/ios-vpn.html               (引导页，含 QR + 安装说明)
```

**总代码量**: ~80 行 Python + ~60 行 HTML。成本极低，用户多一个选择。
