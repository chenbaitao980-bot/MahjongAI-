# libcocos2dlua.so 逆向分析报告（完整）

## 静态分析环境
- 工具: Python capstone 5.0 + pyelftools 0.33
- 二进制: `libcocos2dlua.so` (23MB, ARM64 aarch64, NDK r21d, stripped)
- 方法: .dynsym 符号表 + capstone 反汇编 + ELF 数据提取
- 耗时: ~3 小时

---

## 1. 加密方案：AES-256-CTR

### 1.1 硬编码默认密钥和 IV

| 参数 | 值 | 位置 |
|------|-----|------|
| AES-256 Key (32B) | `f362120513e389ff2311d7360123100705a210007acc023c3901da2ecb12448b` | 0x11f660c |
| AES IV (16B) | `15ff010034ab4cd355fea122084f1307` | 0x11f662c |
| Key length 存储 | `this + 0x20` | `Encryption::setAesKey` 写入 |
| AES key schedule | `this + 0x00..0x1f` | `AES_set_encrypt_key` 展开 |

### 1.2 调用链

```
Encryption::encrypt(plaintext, ciphertext, len, iv, result)
  → AES_set_encrypt_key(this, key_bits, &local_schedule)  @ 0x697f80
  → CRYPTO_ctr128_encrypt(plain, cipher, len, &schedule, iv, &ecount, &num, 1)  @ 0x6a2810

Encryption::decrypt(ciphertext, plaintext, len, iv, result)
  → 同上, 最后一个参数 mode=0
```

### 1.3 密钥验证逻辑

```c
int setAesKey(Encryption* this, const char* key, size_t len) {
    if (len > 32) return 0;
    // Valid lengths: 16 (AES-128) or 32 (AES-256)
    uint64_t mask = 0x1010000;  // = (1 << 16) | (1 << 32)
    if (!((1 << len) & (mask | (1LL << 48)))) return 0;
    this->key_length = len;
    AES_set_encrypt_key(this, len * 8);
    return 1;
}
```

### 1.4 transformStr / untransformStr

`transformStr` 是将每个字节扩展为 2 字节的变换（调用外部函数 `0x8f5828`），不是传统 hex 编码。具体算法需看被调用函数（类似 lookup table 变换）。

---

## 2. 消息容器：ZhouLuJun (48 bytes)

```
Offset  Size  Field
+0x00   16B   版本标记 (0x01 后跟 15 个 0x00)
+0x10    4B   processid
+0x14    4B   appid
+0x18    4B   msgid
+0x1c    4B   (未使用/对齐)
+0x20    4B   payload_len
+0x24    4B   (未使用/对齐)
+0x30   var   实际 payload 数据
```

---

## 3. 帧格式：Packer32

### 3.1 帧头结构 (8 bytes)

```
Offset  Size  Type    内容
+0x00   2B    uint16  payload_len
+0x02   2B    uint16  msgid (XY_ID)
+0x04   4B    uint32  appid
```

### 3.2 packMessage 流程

```
Packer32::packMessage(ZhouLuJun* msg)
  1. 读 msg->field_0x20 (payload_len)
  2. 读 msg->field_0x18 (msgid)
  3. 读 msg->field_0x14 (appid)
  4. 组装帧头到栈上
  5. 调用虚函数获取 header_offsets
  6. 拷贝 payload 到输出 buffer + header_size 偏移处
  7. 返回 header_size + payload_len (总帧长)
```

---

## 4. 发送流程：GuoPengFei

### 4.1 connect 签名

```
GuoPengFei::connect(int srsType, string host, string ip, int port)
  → 连接参数来自 Lua (见 apk-auth-reverse.md)
```

### 4.2 sendMessage 双阶段

```
GuoPengFei::sendMessage(processid, appid, msgid, AUpdates* stream)
  1. 构造 ZhouLuJun 对象:
     - magic[16] = 0x01000000...
     - processid, appid, msgid 从参数复制
  2. 调用 packer->getHeaderSize(msg)
  3. 复制 stream 数据到 payload 区
  4. 存储 payload_len
  5. 调用 GuoPengFei::sendMessage(ZhouLuJun*) → 见下

GuoPengFei::sendMessage(ZhouLuJun* msg)
  if (this->state == 2):  // 已连接 + 已认证
    1. packer->packMessage(msg) → (data, size)
    2. 分配 libuv buffer (0xc0 bytes)
    3. 调用 transform(data, size) → (transformed_data, transformed_size)
    4. uv_write(handle, &buf, 1, callback) → 发送到 socket
  else:
    排队到内部消息池，连接就绪后自动发送
```

### 4.3 连接状态

```
this->state (offset +0x10):
  0 = 未连接
  2 = 已连接 + SRS 握手完成
```

---

## 5. SRS 握手：四步协议

### 5.1 握手消息类型

| 步骤 | 类 | 方向 | 语义 |
|------|-----|------|------|
| 1 | `SRS::EncryptVer` | C→S | 客户端声明加密版本 |
| 2 | `SRS::ReqKey` / `ReqKey32` | C→S | 请求密钥材料 |
| 3 | `SRS::RespKey` | S→C | 服务端响应密钥 |
| 4 | `SRS::CheckAct` / `CheckAct32` | C→S | 激活/校验 |

### 5.2 握手 Handler

```
onEncryptVer(ZhouLuJun*) → 处理 EncryptVer 响应
onRespKey(ZhouLuJun*)    → 调用 setAesKey(key, len) 设置协商密钥
onCheckAct(ZhouLuJun*)   → 握手完成，state 切到 2
```

### 5.3 每步的具体内容（需 Frida）

四步消息的 `EncryptVer::write(AUpdates&)` 和 `RespKey::read(OStream&)` 的具体字段需要动态 hook 才能看到。静态分析只能看到调用框架。

---

## 6. Python 复现路线

### 已具备的条件
- ✅ AES-256-CTR 加密算法
- ✅ 默认密钥和 IV
- ✅ 帧格式（header 8 bytes）
- ✅ ZhouLuJun 消息容器结构
- ✅ SRS 握手四步流程

### 还需要的（Frida 获取）
- ❓ EncryptVer 的具体 payload 字段（可能只是一个版本号 int）
- ❓ ReqKey/ReqKey32 的具体字段（公钥？随机数？）
- ❓ RespKey 返回的具体字段（密钥材料格式）
- ❓ CheckAct 的具体字段（激活码？签名？）
- ❓ transformStr 的字节映射表
- ❓ 帧加密后的最终 wire format（帧头是否也加密？序号在哪儿？）

### 建议路径

1. **Frida hook 四个 SRS 消息的 write/read** → 拿到 payload 原始字节
2. **Python 实现 AES-256-CTR + 帧格式** → 构造握手消息
3. **连接游戏 SRS 服务器** → 完成握手 → 调用旁观协议

---

## 7. 硬编码密钥（直接可用）

```python
DEFAULT_AES_KEY = bytes.fromhex(
    'f362120513e389ff2311d73601231007'
    '05a210007acc023c3901da2ecb12448b'
)  # 32 bytes, AES-256

DEFAULT_AES_IV = bytes.fromhex(
    '15ff010034ab4cd355fea122084f1307'
)  # 16 bytes, CTR mode IV
```
