# 热点防火墙封锁：临时阻断手机重连为 ECS 双连让路

## 问题

RST 注入后，手机 TCP 层仍存活，一旦服务器关掉连接立刻重连（< 1s）。
ECS 和手机争同一 session 槽，互相踢对方，乒乓无限循环。

## 目标

在 ECS 连入并稳住 flag=0 期间，临时封锁手机→游服的 TCP 流量，
给 ECS 一个无竞争的 3~5 秒窗口建立双连后再放开。

## 方案

### 完整时序

```
T1: RST 注入 → 服务器关掉"手机"连接 → grace period 开始
T2: netsh advfirewall 加出站规则，封锁 phone_ip → 47.96.0.227:7777
    （手机流量被 PC 热点 NAT 丢弃，无法立即重连）
T3: 等 ECS continuous player 在 grace period 内 flag=0 连入（最多 5s）
T4: 删除防火墙规则 → 手机恢复重连
T5: 手机重连时，服务器已接受 ECS 双连 → 允许两条共存
T∞: 双连稳定，云端持续收手牌帧
```

### 实现位置

`remote/capture_credentials.py` 的 `_save_and_enter_phase2()` 流程：

```
_upload_creds()
  → sleep 3s（ECS 初始化）
  → _block_phone_traffic(phone_ip)       ← NEW: 加防火墙规则
  → _inject_rst_if_possible()            ← 已有
  → sleep 5s                            ← NEW: 等 ECS 连入
  → _unblock_phone_traffic(phone_ip)    ← NEW: 删防火墙规则
```

### 防火墙规则（netsh）

```python
# 加封锁
subprocess.run([
    "netsh", "advfirewall", "firewall", "add", "rule",
    "name=MahjongBlockPhone",
    "dir=out",
    "action=block",
    f"remoteip=47.96.0.227",
    f"remoteport=7777",
    f"localip={phone_ip}",   # 仅封锁该手机 IP
    "protocol=TCP",
    "enable=yes",
], check=True)

# 删除
subprocess.run([
    "netsh", "advfirewall", "firewall", "delete", "rule",
    "name=MahjongBlockPhone",
], check=True)
```

**说明**：
- `dir=out` 封锁的是从热点网卡出去的流量（手机→游服方向）
- `localip=phone_ip` 精确匹配手机来源，不影响其他流量
- 规则名固定为 `MahjongBlockPhone`，方便幂等删除
- 需要管理员权限（bat 已 UAC 提权）
- Linux ECS 不需要此逻辑（仅 Windows 热点场景）

### 错误处理

- netsh 失败（非管理员等）：打印警告，继续执行（降级为无防火墙模式）
- sleep 期间 Ctrl+C：finally 块确保删除规则

## 验收标准

- [ ] ECS 日志出现 flag=0 且连接保持 > 10s（不再 1s 被踢）
- [ ] 手机在 5s 封锁期间显示"连接中"，5s 后恢复正常
- [ ] 云端网页出现完整手牌（0x2BC0 帧持续到来）
- [ ] Ctrl+C 后防火墙规则被清理（不留残余封锁）

## Out of Scope

- Linux 支持
- 多手机场景
- 规则名冲突处理（同名规则会累积，幂等删除即可）

## 涉及文件

- `remote/capture_credentials.py`：主改动（加 block/unblock 方法）
