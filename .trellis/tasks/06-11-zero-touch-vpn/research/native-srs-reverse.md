# libcocos2dlua.so SRS 认证层逆向分析

> Date: 2026-06-11  
> Binary: `apk_research/native/libcocos2dlua.so` (23MB, ARM64 aarch64, NDK r21d, stripped)  
> Method: 静态符号分析（strings extraction + C++ mangled name parsing）

---

## 1. 一句话结论

**SRS 认证层全部在 native C++ 中实现，类名和函数签名已完全暴露。AES 加密 + 自定义 frame format + 四步握手协议。静态分析已给出完整架构，下一步用 Frida 动态 Hook 即可拿到真实握手流量，纯 Python 复现可行。**

---

## 2. 核心类架构

### 2.1 连接管理器: `universe::network::GuoPengFei`

相当于 Lua 层看到的 `un.network.TcpConnection`:

```
GuoPengFei::connect(int srsType, string host, string ip, int port)
  → 使用 libuv 异步 TCP 连接

GuoPengFei::sendMessage(int processid, int appid, int msgid, AUpdates* stream)
  → 序列化 + 加密 + 打包帧 + 发送到 socket

GuoPengFei::sendMessagePB(int processid, int appid, int msgid, const char* data, size_t len, uint32_t extra)
  → 带 extra 字段的发送（帧头 variant）

GuoPengFei::translateMessage()
  → 从 socket 接收 → 解密 → 解帧 → 分发给 Lua 回调

GuoPengFei::dispatchMessage()
  → 根据消息类型路由到具体 handler

GuoPengFei::setAesKey(const char* key, size_t len)
  → 接收 RespKey 后设置加密密钥

GuoPengFei::startHeartBeat(int interval, int timeout)
  → 心跳管理
```

### 2.2 加密引擎: `universe::network::Encryption`

```
Encryption::setAesKey(const char* key, size_t len)     // 设置 AES 密钥
Encryption::setDefaultAesKey()                         // hardcoded 默认密钥
Encryption::encrypt(const uint8_t* in, uint8_t* out, size_t len, const uint8_t* iv, int* result)
Encryption::decrypt(const uint8_t* in, uint8_t* out, size_t len, const uint8_t* iv, int* result)
Encryption::transformStr(const char* in, size_t inLen, char** out, size_t* outLen)      // 加密前变换
Encryption::untransformStr(const char* in, size_t inLen, char** out, size_t* outLen)    // 解密后逆变换
Encryption::encryptLua(string) / decryptLua(string)     // Lua 层调用入口
Encryption::Md5(const char*, size_t, char* out)         // MD5 hash
Encryption::Hmac(const char* key, size_t keyLen, const char* data, size_t dataLen, char* out, int* outLen)
```

### 2.3 SRS 握手协议对象

四个握手步骤，每个都有 `write(AUpdates&)` / `read(OStream&)`:

| 步骤 | 类 | 方向 | 语义 |
|------|-----|------|------|
| 1 | `SRS::EncryptVer` | C→S | 客户端声明加密协议版本 |
| 2 | `SRS::ReqKey` / `SRS::ReqKey32` | C→S | 请求加密密钥（16B? 32B?） |
| 3 | `SRS::RespKey` | S→C | 服务端下发密钥材料 |
| 4 | `SRS::CheckAct` / `SRS::CheckAct32` | C→S | 激活校验（互认） |

Handler 对应关系:
- `onEncryptVer(ZhouLuJun*)` → 收到 EncryptVer 响应
- `onRespKey(ZhouLuJun*)` → 收到 RespKey 后调用 setAesKey
- `onCheckAct(ZhouLuJun*)` → 握手完成

### 2.4 帧打包/解包: `Packer32` 和 `Proxy33`

```
Packer32::getHeaderSize(ZhouLuJun* msg) → int         // 帧头长度
Packer32::packMessage(ZhouLuJun* msg) → bytes          // 打包为 wire format
Packer32::translateMessage(Touchbar& buf, IncludeHistory& hist) → ZhouLuJun  // 解包

Proxy33::getHeaderSize(ZhouLuJun* msg) → int           // 变体帧头长度
Proxy33::packMessage(ZhouLuJun* msg) → bytes          
Proxy33::translateMessage(Touchbar& buf, IncludeHistory& hist) → ZhouLuJun
```

### 2.5 消息容器

```
ZhouLuJun:     单条协议消息（含 processid, appid, msgid, payload）
Touchbar:      接收缓冲区 + 连接状态
IncludeHistory: 消息历史跟踪（序号管理，防重放）
AUpdates:      输出流（写 buffer，operator<< 重载所有基础类型）
OStream:       输入流（读 buffer，operator>> 重载所有基础类型）
```

### 2.6 基础代理类: `BaseProxy`

```
BaseProxy (GuoPengFei 的父类？)
  → setDefaultAesKey() — 设置硬编码默认密钥
  → setAesKey(key, len) — 设置自定义密钥
```

---

## 3. 逆向方案

### 路径 A: Frida 动态 Hook（🏆 推荐，最可控）

**核心思路**: 在真机/模拟器上运行游戏，用 Frida hook 关键 native 函数，dump 所有握手和加密参数。

**Hook 点**:

```javascript
// 1. Hook Connect - 拿到连接目标
Interceptor.attach(Module.findExportByName(null, "_ZN8universe7network10GuoPengFei7connectE..."), {
    onEnter(args) {
        // args[0] = this, args[1] = srsType, args[2] = host string, args[3] = ip string, args[4] = port
        console.log("connect:", Memory.readCString(args[2]), Memory.readCString(args[3]), args[4].toInt32());
    }
});

// 2. Hook sendMessage - 拿到完整发送数据
Interceptor.attach(Module.findExportByName(null, "_ZN8universe7network10GuoPengFei11sendMessageEiiiPNS0_8AUpdatesE"), {
    onEnter(args) {
        // args[1] = processid, args[2] = appid, args[3] = msgid, args[4] = AUpdates*
        // AUpdates 内部是 buffer + cursor
        var updates = ptr(args[4]);
        var data = updates.readByteArray(updates.add(OFFSET_CURSOR).readU32());
        console.log("sendMessage:", args[1].toInt32(), args[2].toInt32(), args[3].toInt32(), hexdump(data));
    }
});

// 3. Hook packMessage - 拿到打包后的帧 bytes
var packMessage = Module.findExportByName(null, "_ZN8universe7network8Packer3211packMessageEPNS0_9ZhouLuJunE");
Interceptor.attach(packMessage, {
    onLeave(retval) {
        // retval 可能是 malloc'd buffer，需要解析
    }
});

// 4. Hook encrypt - 拿到 AES 参数
var encrypt = Module.findExportByName(null, "_ZN8universe7network10Encryption7encryptEPKhPhmS3_Pi");
Interceptor.attach(encrypt, {
    onEnter(args) {
        // args[0] = this, args[1] = plaintext, args[2] = ciphertext(out), args[3] = len, args[4] = iv, args[5] = result
        console.log("encrypt:", args[3].toInt32(), hexdump(args[1], {length: args[3].toInt32()}));
    }
});

// 5. Hook setAesKey - 拿到 m_key
Interceptor.attach(Module.findExportByName(null, "_ZN8universe7network10Encryption9setAesKeyEPKhm"), {
    onEnter(args) {
        console.log("setAesKey:", args[1].readCString(), args[1].readByteArray(args[2].toInt32()));
    }
});
```

**前提条件**:
- Android 真机/模拟器，已 root 或使用 frida-gadget
- 已有 frida-gadget 在 repo: `frida/frida-gadget-17.9.10-android-x86_64.so`（但是 x86_64，需 arm64 版本）

**产出**:
- 完整的 SRS 握手流量（每个消息的原始字节）
- AES 密钥和 IV
- 帧格式的字节级定义
- 可以使用现有的 `stable/protocol.py` 做比对验证

### 路径 B: Ghidra 静态分析

- 导入 ARM64 ELF
- 通过 mangled name 定位函数
- 分析 `transformStr` / `untransformStr` 的具体算法
- 分析 `Packer32::packMessage` 的帧格式
- 慢但完整，适合在 Frida 不可用时的备选

---

## 4. 关键未确认项

| 问题 | 确认方式 |
|------|---------|
| AES 是 ECB/CBC/CTR/CFB？ | Frida hook encrypt，看 IV 参数 |
| `transformStr` 具体做什么？（padding? salt?） | Ghidra 反汇编或 Frida hook |
| 帧头格式（`frame[0:2]`、`extra` 字段）？ | Frida hook packMessage，dump 输出 |
| 序号规则（包递增？按 processid 分组？） | Frida 连续 hook sendMessage |
| `IncludeHistory` 的 anti-replay 机制 | Frida track 序号变化 |
| SRS 服务器地址/端口 | Frida hook connect |

---

## 5. 已有资产

| 资产 | 位置 | 用途 |
|------|------|------|
| `libcocos2dlua.so` | `apk_research/native/libcocos2dlua.so` | 逆向目标 |
| `libsgcore.so` | `apk_research/native/libsgcore.so` | 安全加固（可能含反调试） |
| frida-gadget | `frida/frida-gadget-17.9.10-android-x86_64.so` | 需要 arm64 版本 |
| 解密 Lua 源码 | `apk_research/decrypted-lua/` | 协议结构体 + 调用链参考 |
| 现有 stable/protocol.py | `stable/protocol.py` | 已有帧解析实现，可参考 |
| Frida hook 脚本 | `frida/` (待创建) | |

---

## 6. 下一步行动

1. **获取 arm64 Frida gadget**（匹配手机架构）
2. **编写 Frida hook 脚本**，覆盖上述 5 个 hook 点
3. **部署到 Android 真机/模拟器**
4. **运行游戏 → dump 完整 SRS 握手流量**
5. **用 Python 复现握手 + 加密**
6. **实现旁观协议客户端**（ReqRealtimeGameRecord）

预估工作量：Frida hook 脚本 + 部署调试 = 半天。Python 复现 = 半天到一天。
