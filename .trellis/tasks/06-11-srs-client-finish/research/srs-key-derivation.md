# Research: SRS AES Key Derivation (静态逆向 libcocos2dlua.so)

- **Query**: 逆出游戏 SRS 加密的真 AES key 怎么来的，能在纯 Python 复刻被动解密
- **Scope**: internal (静态反汇编 `apk_research/native/libcocos2dlua.so`)
- **Date**: 2026-06-11
- **Tooling**: pyelftools 解析 ELF/符号/重定位 + capstone 5.0.7 (ARM64) 反汇编。机器无 objdump/nm/strings/radare2，全程 Python。`.so` 是 AArch64、未 strip 的 `.dynsym`（45678 符号）。

---

## TL;DR（一句话结论）

**默认 key 是 32 字节 AES-256（`f362120513e389ff…cb12448b`，硬编码在 .rodata @0x11f660c），加密模式是 AES-CFB128（OpenSSL `AES_cfb128_encrypt`），IV 固定 `15ff010034ab4cd355fea122084f1307`。服务端 `RespKey` 报文会下发一段新 key（payload 里 len(1B) + key(len B)）覆盖默认 key，key 长度决定 AES-128/192/256。Frida 读到的"24字节全零 key"是被反篡改库清零的假数据。**

被动嗅探要解密：抓到 RespKey 报文 → 取出其中的 key → 用 **AES-CFB128**（不是 CTR！）+ 固定 IV 解密后续流。**还差最后一步**：确认 RespKey 在 TCP 线缆上的字节结构（payload 在解密后还是明文阶段），见末尾"还差哪一步"。

---

## 关键函数地址表（.dynsym，均已确认）

| 符号 | vaddr | size | 作用 |
|---|---|---|---|
| `Encryption::setDefaultAesKey()` | `0x8f53d8` | 40 | 把 .rodata 的 32B 默认 key 装进 Encryption 对象 |
| `Encryption::setAesKey(key,len)` | `0x8f5314` | 72 | 校验 len∈{16,24,32}，memcpy key，存 len |
| `Encryption::encrypt(...)` | `0x8f5400` | 180 | 调 `AES_set_encrypt_key` + `AES_cfb128_encrypt` |
| `Encryption::transformStr(in,len,**out,*outlen)` | `0x8f5794` | 148 | 逐字节 `snprintf("%02x")` → hex 字符串 |
| `Encryption::setAesKeyLua(string)` | `0x8f535c` | 124 | Lua 绑定入口 |
| `GuoPengFei::setAesKey(char*,len)` | `0x90b23c` | 72 | 转发给 `Encryption::setAesKey` |
| `GuoPengFei::onRespKey(ZhouLuJun*)` | `0x907b9c` | 188 | 解析 RespKey，取出 key 调 setAesKey |
| `GuoPengFei::receiveMessageFromPack<SRS::RespKey>` | `0x678a40` (import thunk) | — | 反序列化 RespKey payload |
| `BaseProxy::setAesKey(key,len)` | `0x6a0260` (import thunk) | — | onRespKey/GuoPengFei 最终落点 |

OpenSSL（静态链接进 .so，shndx=11 有实体）：

| 符号 | vaddr | size |
|---|---|---|
| `AES_set_encrypt_key` | `0x9f8864` | 832 |
| `AES_cfb128_encrypt` | `0x9f8840` | 12 (thunk→CRYPTO_cfb128_encrypt) |
| `AES_encrypt` | `0x9f8dd8` | 932 |

> `CRYPTO_ctr128_encrypt`、`AES_cbc_encrypt`、`EVP_EncryptUpdate` 也都在二进制里，但 **encrypt() 实际只调用 `AES_cfb128_encrypt`**（见下证据），所以 mode 确定是 CFB。

---

## Findings

### 1. 静态默认 key —— 已确认 32 字节 AES-256

`Encryption::setDefaultAesKey` @0x8f53d8 反汇编：

```asm
adrp   x9, #0x11f6000
add    x9, x9, #0x60c        ; x9 = 0x11f660c  (key 地址)
ldp    q1, q0, [x9]          ; 加载 32 字节 (2×16B SIMD)
mov    w9, #0x20             ; len = 0x20 = 32
mov    x8, x0
str    x9, [x0, #0x20]       ; obj+0x20 = key_len = 32
str    q0, [x0, #0x10]       ; obj+0x10 = key[16:32]
mov    w0, #1
str    q1, [x8]              ; obj+0x00 = key[0:16]
ret
```

直接 dump `.rodata @0x11f660c`（48 字节，key 32 + iv 16）：

```
key: f362120513e389ff2311d7360123100705a210007acc023c3901da2ecb12448b   (32B, AES-256)
iv : 15ff010034ab4cd355fea122084f1307                                   (16B, @0x11f662c)
```

- **完全等于**之前注释里的那把 key，长度精确 **32 字节 = AES-256**（不是 192）。
- **用在哪个阶段**：握手最开始（RespKey 之前），客户端用这把默认 key + 固定 IV 加密最初的消息（含请求 key 的报文），让服务端能解。RespKey 到达后才被会话 key 覆盖。

### 2. key 派生算法 —— RespKey 直接下发 key（拷贝，非 KDF）

`GuoPengFei::onRespKey` @0x907b9c 核心几行：

```asm
ldrb   w8, [x19, #0x459]     ; 某个 flag，置位才解析
...
add    x8, x8, #0x10
str    x8, [sp, #8]          ; 准备一个输出结构在栈 sp+8
add    x1, sp, #8
mov    x0, x19
mov    x2, x20               ; x20 = ZhouLuJun* (RespKey 消息)
bl     #0x678a40            ; → receiveMessageFromPack<SRS::RespKey>(out=sp+8, msg)
                            ;   反序列化 RespKey payload 到栈结构
ldr    x0, [x19, #0x3b0]     ; x0 = Encryption 对象指针 (obj+0x3b0)
ldrb   w2, [sp, #0x10]       ; w2 = len  ← key 长度，1 字节，在 out+0x08
add    x1, x22, #9           ; x1 = key 指针 = (sp+8)+9 = out+0x09
bl     #0x6a0260            ; → BaseProxy::setAesKey(enc, key=out+9, len=out+8)
```

**结论（已确认）**：onRespKey **不做任何 KDF / XOR / AES-decrypt 变换**。它把 `receiveMessageFromPack<RespKey>` 反序列化出来的结构里的 `key` 字段**原样**（指针 `out+9`，长度 `out+8` 的那 1 字节）交给 `setAesKey`。也就是说：

```
session_key = RespKey.key            # 直接来自服务端报文，无变换
key_len     = RespKey.key_len        # 1 字节，决定 AES-128/192/256
```

反序列化后的栈布局（`out` = sp+8）：
- `out+0x00`：某 8B 头/对象指针（被 `str x8,[sp,#8]` 预填）
- `out+0x08`：`key_len`（1 字节，`ldrb`）
- `out+0x09`：`key` 字节起始（`add x1,x22,#9`）

> **推测（标注）**：这个 `out+8 len / out+9 key` 是 `receiveMessageFromPack` 反序列化**之后**的内存布局，不一定等于线缆上 RespKey 的原始字节偏移。线缆字节里 key 字段的精确 offset 需要抓一条真实 RespKey 验证（见"还差哪一步"）。但派生算法本身（=直接拷贝）已确认。

### 3. AES 模式与参数 —— AES-CFB128，固定 IV，已确认

`Encryption::encrypt` @0x8f5400 关键证据：

```asm
adrp   x9, #0x11f6000
add    x9, x9, #0x62c        ; x9 = 0x11f662c = 默认 IV 地址 (15ff0100...)
cmp    x4, #0                 ; x4 = 调用方传入的 IV 参数
csel   x8, x9, x4, eq        ; IV==0 → 用默认 IV;  否则用传入 IV
ldr    q0, [x8]              ; 加载 16 字节 IV/counter → 栈 [x29-0x50]
ldr    w8, [x0, #0x20]       ; w8 = key_len (字节)
lsl    w1, w8, #3            ; w1 = key_len*8 = key bits (128/192/256)
bl     #0x697f80            ; → AES_set_encrypt_key(key, bits, &AES_KEY@sp+8)
...
mov    w6, #1                ; enc = 1 (encrypt 方向)
mov    x0, x22               ; in
mov    x1, x21               ; out
mov    x2, x20               ; length
add    x3, sp, #8            ; &AES_KEY
sub    x4, x29, #0x50        ; ivec (栈上 IV 副本)
mov    x5, x19               ; *num
bl     #0x6a2810            ; → AES_cfb128_encrypt(in,out,len,&key,ivec,num,enc)
```

`0x6a2810` 和 `0x697f80` 是 PLT stub（`adrp+ldr+br [GOT]`）；解析 `.rela.plt` 重定位：

```
0x6a2810 → GOT 0x164f0f0 → AES_cfb128_encrypt
0x697f80 → GOT 0x1649ca8 → AES_set_encrypt_key
```

**已确认参数**：
- **Mode = AES-CFB128**（OpenSSL `AES_cfb128_encrypt`，按 bit 反馈的 CFB，stream-like，无需 padding）。
- **Key bits = key_len*8** → 默认 AES-256；RespKey 下发 24B 时变 AES-192，16B 变 AES-128。
- **IV** = 固定 `15ff010034ab4cd355fea122084f1307`（@0x11f662c），调用方未传 IV 时用它。CFB 的 `num` 初值 0（`str wzr,[x19,#0x28]`，即每个新 Encryption 周期从 IV 起算）。
- CFB 的 `AES_set_encrypt_key`（而非 decrypt key）对加解密都成立——CFB 解密也只用 forward cipher，符合 OpenSSL CFB 约定。

> **重要纠正**：当前 `remote/srs_spectator/crypto.py` 用的是 **AES-CTR**，这是**错的**，真实是 **CFB128**。CTR 和 CFB 的 keystream 完全不同，用 CTR 解不出来。

### 4. transformStr 语义 —— hex 编码（snprintf "%02x"），已确认

`Encryption::transformStr(in, in_flag, len, **out, *outlen)` @0x8f5794：

```asm
csel   x22, xzr, x2, eq      ; x22 = len (in_flag==0 时清零)
lsl    x8, x22, #1           ; out_byte_len = len*2  ← hex 每字节占2字符
str    x8, [x4]              ; *outlen = len*2
bl     #0x68e620            ; malloc(len*2 + 1)
...
loop:
  ldrb w3, [x21, x8]         ; 取一个输入字节
  add  x0, x0, w23           ; out + i*2
  mov  x1, #-1
  bl   #0x8f5828            ; snprintf-style: 写 "%02x"
  add  w23, w23, #2          ; 输出游标 +2
  ...
strb   wzr, [x0, x8]         ; 末尾补 '\0'
```

`0x8f5828` 是变参 sprintf/snprintf 风格函数（prologue 保存 q0-q7 + x3-x7，典型 AArch64 varargs）。

**结论（已确认）**：`transformStr` = **把字节数组转成小写 hex ASCII 字符串**（每字节 2 字符），输出长度 = 输入长度*2，末尾带 `\0`。等价 Python `data.hex().encode("ascii")`。

> 作用时机/范围：从 frida `hook_key.js` 注释看 `transformStr` 在加密链路里把数据 hex 化。**是在加密之前还是之后未在本次静态分析中完全锁定**——`encrypt` 函数体内没有调用 `transformStr`，二者是独立函数，由上层（`GuoPengFei::sendMessage`/`encryptStr`）串联。需要抓真实流量确认 hex 在 AES 前还是后（推测：先 hex 再 AES，即 `AES_cfb( hex_ascii(payload) )`，与现有 crypto.py 的 `transform_and_encrypt` 假设一致，但**待真流验证**）。

### 5. RespKey 报文结构

- 解析入口 `GuoPengFei::receiveMessageFromPack<SRS::RespKey>` @0x678a40（C++ 模板，按 SRS::RespKey 的字段定义反序列化）。
- onRespKey 读 `ZhouLuJun*` 消息头：frida 脚本用的偏移是 `+0x10 processid`、`+0x14 appid`、`+0x18 msgid`、`+0x20 payload_len`、`+0x30 payload` —— 这是**内存里的 ZhouLuJun 对象布局**，可信。
- 反序列化后内存：`key_len` @out+0x08 (1B)，`key` @out+0x09。

> RespKey 在**线缆字节**里的精确 offset 未静态确定（被 `receiveMessageFromPack` 模板解析吞掉了）。需要一条真实 RespKey 抓包对照。

---

## Caveats / Not Found（区分已确认 vs 待定）

**已确认（带反汇编/地址证据）**：
- 默认 key = 32B `f362…448b` @0x11f660c，AES-256。
- IV = `15ff…1307` @0x11f662c，固定。
- Mode = AES-CFB128（OpenSSL，GOT 重定位实锤）。
- key bits = key_len*8。
- key 派生 = RespKey 直接下发，**无 KDF/XOR/变换**。
- transformStr = hex 编码（len*2，snprintf %02x）。

**待定（需真实流量/动态验证，不可编）**：
1. RespKey 在 TCP 线缆字节中的精确字段 offset（receiveMessageFromPack 模板把布局藏起来了）。
2. hex 化（transformStr）相对 AES 的先后顺序——静态看是两个独立函数，未见 encrypt 内部调用 transformStr。
3. RespKey 之前的握手报文是否真用默认 key 加密、第一条加密消息的 num/IV 是否 reset。
4. 服务端是否**每会话都下发新 key**，还是某些场景直接用默认 key（onRespKey 有 flag 判断 `[x19,#0x459]`/`[x0,#0x4a0]`，可能存在跳过分支）。

---

## Python crypto.py 该怎么改（具体清单）

当前 `remote/srs_spectator/crypto.py` 三个错误，逐条修：

1. **模式：CTR → CFB128**。删掉 `modes.CTR`，改用 `modes.CFB`（OpenSSL CFB128 = 全反馈，cryptography 库的 `CFB` 即 CFB128）：
   ```python
   from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
   Cipher(algorithms.AES(key), modes.CFB(iv))   # CFB128, NOT CTR
   ```
2. **默认 key：用 32B AES-256，别用 24B 全零**：
   ```python
   SRS_DEFAULT_KEY = bytes.fromhex(
       "f362120513e389ff2311d7360123100705a210007acc023c3901da2ecb12448b")  # 32B
   SRS_IV = bytes.fromhex("15ff010034ab4cd355fea122084f1307")               # 16B 固定
   ```
   （Frida 的"24字节全零"是反篡改清零的假值，丢弃。）
3. **会话 key：从 RespKey 取，长度任意 16/24/32 都支持**。`set_key(key)` 里据 `len(key)` 自动选 AES-128/192/256（AES 算法自适应），保持 IV 不变。
4. **CFB 是流式**：每个 Encryption 周期从 IV 起算、`num=0`；同一周期内 `encryptor.update` 连续调用即可保持反馈链。换 key（RespKey 到达）时必须 `_reset()` 重建 cipher。
5. **transformStr**：保留 `transform_and_encrypt = AES_cfb( hex_ascii(payload) )` 假设，但加 TODO 待真流验证 hex/AES 先后；解密侧对应 `bytes.fromhex(cfb_decrypt(ct).decode('ascii'))`。
6. （可选健壮性）保留对默认 key 的解密尝试：握手早期报文用默认 key+CFB 解，RespKey 之后切会话 key。

参考骨架：
```python
class SRSCrypto:
    def __init__(self, key=SRS_DEFAULT_KEY, iv=SRS_IV):
        self.key, self.iv = bytes(key), bytes(iv)
        self._reset()
    def _reset(self):
        self._enc = Cipher(algorithms.AES(self.key), modes.CFB(self.iv)).encryptor()
        self._dec = Cipher(algorithms.AES(self.key), modes.CFB(self.iv)).decryptor()
    def set_key(self, key):           # key 来自 RespKey, len ∈ {16,24,32}
        self.key = bytes(key); self._reset()
    def decrypt(self, ct):  return self._dec.update(ct)
    def encrypt(self, pt):  return self._enc.update(pt)
```

---

## 还差哪一步才能被动解密

1. **抓一条真实 RespKey + 紧随其后的一条已知明文报文**（用 `hook_srs.js` 的 `tcp_recv`/`wire_send` 在真机抓，或被动嗅探流量）。
2. 用上面 CFB + 从 RespKey 取出的 key 解那条报文，**比对是否得到合法的 ZhouLuJun/protobuf 结构**——成功即闭环。
3. 同时确定：RespKey 线缆字段 offset（坑1）+ hex/AES 顺序（坑2）。这两点只能靠一条对照样本敲定，静态到此为止。
