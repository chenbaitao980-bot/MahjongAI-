# usertype 旁路测试结果 (2026-06-14)

## 测试目标

验证是否存在一种 usertype 能让云端以当前用户登录，同时不踢手机（绕过单连接限制）。

## 环境

- userid: `newpt1084306678` (1084306678)
- identify (from pcap): `b'020000000000'` (hex: `303230303030303030303030`)
- areaid: 7109
- 服务器: `47.96.0.227:7777`
- 测试时 sessionid `ae87a919015641c1b57324c6bc88556b` 已过期(>21小时)

## 关键发现 1: 真实 identify 值

从 `data/phone_srs.pcap` 和 `data/phone_full.pcap` 解密 PlayerConnect 明文，提取 identify 字段：

```
identify = b'020000000000'
identify (hex) = 303230303030303030303030
```

**结论**：之前测试用的 identify 值完全正确，不是 flag=48 的原因。

## 关键发现 2: 所有 usertype 结果

| usertype | 名称 | pwd | 结果 | 含义 |
|----------|------|-----|------|------|
| 0 | USERID | empty | ✅ flag=0 | 服务端接受空密码登录 |
| 1 | PTID | empty | ✅ flag=0 | 服务端接受空密码登录 |
| 2 | NMY | empty | ✅ flag=0 | 服务端接受空密码登录 |
| 3 | GLOBAL_ANONYMITY | empty | ✅ flag=0 | 服务端接受空密码登录 |
| 5 | IDENTIFY | `020000000000` | ❌ flag=48 | 服务端拒绝（原因未知）|
| 6 | DEVELOPER | empty | ❌ flag=147 | 开发者权限不足 |
| 7 | SESSION | `ae87a919...` (过期) | ❌ flag=72 | sessionid 过期 |
| 8 | REGISTER | empty | ✅ flag=0 | 服务端接受空密码登录 |
| 9 | PHONENUM | empty | ❌ flag=41 | 格式错误（需手机号） |

## 关键发现 3: usertype=3 的 PlayerData 响应

用 usertype=3 (GLOBAL_ANONYMITY) + empty pwd 连接后，PlayerData 响应：

```
flag = 0      ← 认证成功
areaid = 7109 ← 我们的区域
userid = 1084306678 ← 就是我们的真实 userid！
nickname = "LOLLAPALOO..." (截断)
```

**重大发现**：服务端用 usertype=3 + 空密码登录后，返回的是我们的**真实 userid**，不是匿名账号。

这意味着服务端直接接受了我们的账号，无需密码验证！

## flag=48 的真实含义

usertype=5 (IDENTIFY) 返回 flag=48，而 identify 值是正确的。

可能原因：
1. 该账号未绑定硬件码登录（从未用该方式登录过）
2. identify 值格式正确但内容不匹配（该设备标识符在服务端未注册）
3. flag=48 = 硬件码不匹配

## 待验证问题

**核心问题**：usertype=3/0/1/2/8 以 flag=0 登录后，手机在线打牌时，是否能收到 0x2bc0 手牌帧？

### 测试方法

1. 手机在线打牌（进入局中）
2. 云端用 usertype=3 + empty pwd 连接
3. 等待 30 秒，观察是否收到任何帧（尤其是 0x2bc0）
4. 同时观察手机是否被踢

### 测试脚本

```bash
PYTHONIOENCODING=utf-8 python scripts/test_all_usertypes.py
```

然后在 flag=0 后添加等待逻辑，监听后续帧。

## 最终结论（2026-06-14 实测完成）

| 状态 | 描述 |
|------|------|
| ✅ 已确认 | usertype=3 + 空密码 → flag=0，收到大量 0x2bc0 手牌帧 |
| ❌ 已确认 | usertype=3 登录 **同样踢手机** |
| ❌ 已确认 | usertype=5 (IDENTIFY) 硬件码登录 → flag=48 |
| ❌ 已排除 | **usertype 旁路方案彻底死路** |

## 核心发现：服务端单连接限制基于 userid，与 usertype 无关

服务端用 **userid（1084306678）** 做唯一标识来强制单连接限制。
无论用 usertype=3（空密码）还是 usertype=7（SESSION），
只要是同一个 userid，第二次连接必然踢掉第一个连接。

## 可行路径总结

| 方案 | 状态 | 说明 |
|------|------|------|
| usertype 旁路 | ❌ 死路 | 服务端按 userid 踢，与 usertype 无关 |
| 接管时间窗口 (方案一) | ⏸️ 待测 | 手机主动断网后，窗口期内云端重连 |
| WinDivert 旁路 | ⏸️ 待测 | 截获热点流量，不创建新连接 |
| Frida siphon | ✅ 理论可行 | 需要 PC 上有 Frida server |
