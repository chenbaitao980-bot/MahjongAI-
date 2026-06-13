# PRD: SRS旁观客户端 — Python实现 + 云端部署

**Status**: in_progress
**Priority**: P2
**Assignee**: 陈柏涛

---

## 背景

游戏使用自定义SRS协议（基于TCP的自定义帧格式，AES-192-CTR加密）。已通过Frida逆向确认：
- AES-192密钥：24字节全零（`\x00` * 24）
- IV：`15ff010034ab4cd355fea122084f1307`（16字节）
- 加密流程：hex编码明文 → AES-CTR加密
- 帧格式：12字节头 + payload（flag=0x4001, msg_type, sub_type等）

Python客户端框架已全部写完（`remote/srs_spectator/`），但未端到端测试，原因：
1. 真机Frida注入的APK触发反篡改库，crypto数据全为零
2. 缺少有效的auth_token/handshake_blob进行Python客户端实测

## 目标

### 核心目标
1. **获取有效SRS握手凭据** — 从真机游戏进程中捕获auth_token(12B)、handshake_blob、m_key
2. **端到端验证Python旁观客户端** — 用捕获的凭据连接游戏服务器，完成SRS握手，请求并接收旁观数据
3. **云端部署配置** — Docker化spectator服务，支持与relay联动的完整部署

### 非目标
- 不在云服务器上长期运行模拟器
- 不修改游戏服务器协议
- 不破解付费墙/内购

---

## 技术路径

### 路径A：真机反篡改绕过（当前最直接）

已确认5个反篡改库在APK重签名后静默禁用crypto：
- `libapkpatch.so`（APK完整性校验）
- `libmaparmor.so`（美团加固）
- `libpanglearmor.so`（字节跳动安全SDK）
- `libpangleflipped.so`（反调试）
- `libtobEmbedEncrypt.so`（嵌入式加密层）

**方案**：在Frida hook脚本中增加反篡改库的hook，强制签名校验返回成功。

关键hook点：
- `libapkpatch.so` 的签名校验函数
- `PackageManager.getPackageInfo()` Java层（伪造原始签名）
- 各反篡改库的初始化/校验函数

### 路径B：x86_64模拟器 + Native Bridge（备用）

在现有x86_64 AVD（`codex_pixel_6`）上启用ARM64→x86翻译（libndk_translation），安装原版未修改APK，`adb root`后直接跑Frida server。

优点：无签名问题，`adb root`可用，hook完全有效
风险：native bridge可能不兼容游戏的ARM64原生库

### 路径C：Python客户端直连测试（验证路径）

用网络抓包（extractor）捕获的auth_token/handshake_blob直接测试Python SRS客户端。即使卡在m_key之后的阶段，也能验证握手流程正确性。

---

## 验收标准

- [ ] Python SRS spectator客户端成功完成握手（EncryptVer→ReqKey→HandshakeRsp→PlayerConnect→PlayerData→ReqPlusData→RespPlusData）
- [ ] 成功调用ReqRealtimeGameRecord并接收游戏数据
- [ ] spectator服务Docker化，可部署到ECS
- [ ] 与relay服务联动正常（POST /watch → 开始旁观）
- [ ] Frida hook能稳定捕获密钥（不再因反篡改返回空数据）

---

## 依赖

- 真机Redmi Note 15 Pro（已注入Frida gadget，需USB连接）
- 游戏服务器 `47.96.0.227:7777`（需从国内IP访问）
- ECS云服务器（部署spectator）

---

## 当前卡点

1. **真机反篡改阻断crypto** → 路径A
2. **Python客户端未实测** → 路径C（用extractor抓到的凭据先测）
3. **无Dockerfile** → 需创建
