# N6 Fuzzer Dry-Run Report

- **Date**: 2026-06-19
- **Script**: `.trellis/tasks/06-19-n6-hidden-protocol-scan/research/n6_fuzzer.py`
- **Goal**: 验证 fuzz 脚本骨架 dry-run 路径不联网、产物完整、wire frame 与 PoC v6 一致。

---

## §1 静态审查

### 网络调用 grep（关键字 `socket|connect|send|recv|create_connection`）

仅命中 14 处，分布全部安全：

| 行号 | 出处 | 是否被 `args.live` 守卫 |
|---|---|---|
| 13 | docstring "NEVER opens a network socket" | 文档，N/A |
| 162 | `confirm_live()` 警告文案 | 仅 live 路径调用 |
| 242 | `on_frame` docstring | 函数体在 `run_live` 内 |
| 249 | `"direction": "recv"` JSONL 字段 | `run_live` 内 |
| 254 | `"correlated_send": last` | `run_live` 内 |
| 283 | `client.connect(timeout=15.0)` | **真正的 socket 调用，`run_live` 内**，从 `main()` 出发只在 `args.live=True` + `confirm_live()=True` 时进入 |
| 284 | `connect failed` 错误日志 | `run_live` 内 |
| 321 | `"direction": "send"` JSONL | `run_live` 内 |
| 330, 351 | `client._send_raw(...)` | **真正的 socket 调用**，均在 `run_live` 内 |
| 332 | `send raised` 错误日志 | `run_live` 内 |
| 336 | `5 consecutive send failures (RST)` 文案 | `run_live` 内 |
| 400 | `--live` 参数 help | argparse 定义 |
| 416 | `=== DRY-RUN MODE === ...` 警告 | 顶层 main 控制流 |

补充扩展 grep（`socket\.|gethostby|getaddrinfo|create_connection|\.connect\(|\.send\(|\.recv\(|urlopen|requests\.|http\.`）：

```
13:  docstring (NEVER opens a network socket)
283: if not client.connect(timeout=15.0):    # run_live 内
```

**结论：网络 IO 完全被 `args.live` 守卫**。`SRSClient` 只在 `run_live()` 内 lazy-import（行 218），dry-run 路径连 `remote/srs_spectator/client.py` 都不加载，因此连 import 期间偶发的 socket 解析都不会发生。

### 默认行为

```python
p.add_argument("--live", action="store_true", ...)   # 默认 False
...
if not args.live:
    logger.warning("=== DRY-RUN MODE === ...")
    run_dry_run(args, msg_types, sub_types, out_path)
    return 0
```

未加 `--live` 时直接走 `run_dry_run` 后 return；`run_live` 永不被调用。dry-run 路径里 `SRSClient` 也不 import。

### Live 路径门槛

```python
if args.sessionid == "DRY_RUN_DUMMY_SID":
    logger.error("LIVE mode requires real --sessionid (副号 32-hex)")
    return 4
if not confirm_live():
    logger.error("LIVE mode aborted (user did not confirm)")
    return 4
```

`confirm_live()` 要求 stdin 输入精确字符串 `I HAVE READ THE WARNING` 才返回 True。strict equal，无任何旁路。✅ 符合任务约束。

### Wire frame 构造（vs PoC v5/v6）

```python
def pack_frame_v6(msg_type, payload, sub_type, extra):
    return struct.pack("<HHHHI", FLAG, len(payload), msg_type, sub_type, extra) + payload
```

12B header layout：`FLAG(u16=0x4001) | LEN(u16) | MSGTYPE(u16) | SUBTYPE(u16=processid) | EXTRA(u32=appid)`，与 `fuzz-strategy.md §4` / PoC v5 完全一致。✅

dry-run 抽样实测（见 §2）已验证字节位置正确。

### Body 加密（live 路径）

```python
if client._crypto.key:
    client._crypto.reset_cfb()        # fresh-from-IV per frame
    enc = client._crypto.encrypt_payload(body)
```

每帧 `reset_cfb()` 后 `encrypt_payload` —— AES-CFB128 fresh-from-IV with session key，与 stable/protocol.py 系统帧 / PoC v5 实证逻辑一致。✅ 注：dry-run **不加密**（无 session key 也无连接），rec 字段叫 `wire_hex_unencrypted`，明确语义。

### `--skip-known` 加载

```python
def load_skip_set(path: Path) -> set[int]:
    if not path.exists():
        logger.warning(... empty skip set ...)
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return {int(k) for k in data.keys()}
```

读 JSON top-level keys（已知 XY_ID）转 int，从 `expand_range` 结果集合做差。✅ 实测见 §2。

### sub_types 默认值

| 来源 | sub_types 集合 |
|---|---|
| `fuzz-strategy.md §4` 主要矩阵 | `{0, 1, 84, 92, 100, 1006}` (6 个) |
| `n6_fuzzer.py` 默认 `--sub-types` | `"100,84,1,1006"` (4 个) |
| 任务命令 `--sub-types` | `100,84,1,1006` (4 个) |
| go-live checklist Gate 3 | `100,84,1,1006,92,0` (6 个) |

**偏差 1**：脚本 default 缺 `0` 和 `92`，与 strategy/checklist 不符。任务此次明确传 `--sub-types 100,84,1,1006`，所以 dry-run 没问题；但 live 跑 round1 时如不显式传 6 个 sub_types，会少扫两个常见 processid（SRS 路由 0 / BagSysProtocol 92）—— 触发 `n6-go-live-checklist.md §1 Gate 3` 不合规。

**修复建议（live 前）**：把 default 改成 `"100,84,1,1006,92,0"`，与 checklist 对齐。本轮 dry-run 不必修改；任务允许的 trellis-implement 范围内可后续单独调整。

### Ctrl+C / KeyboardInterrupt 处理

`grep KeyboardInterrupt` → 0 命中。`run_live` 内有局部 `try/except`，但**没有顶层 try/finally** 保证 `client.close()` 被调用。

**偏差 2**：与 `n6-go-live-checklist.md Gate 4` 一致：「当前 n6_fuzzer.py 里 Ctrl+C 由 Python 默认 handler 处理 ... implement 阶段补 try/finally」。已在 checklist 中标记为 TODO，不阻塞 dry-run。

### dry-run 路径其他偏差

无。`run_dry_run` 仅做 `pack_frame_v6` + JSONL 写盘，无 `time.sleep` 之外的副作用，无文件系统写入除 `--out` 之外。

### 偏差汇总

| ID | 严重度 | 描述 | 建议修复 |
|---|---|---|---|
| Dev-1 | 中 | `--sub-types` default 4 个，与 strategy/checklist 6 个不符 | live 前改 default 或硬编码命令传 6 个 |
| Dev-2 | 中 | 无 KeyboardInterrupt 顶层 try/finally，Ctrl+C abort 不优雅 | live 前加 `try/finally` + 在 `client.close()` 上兜底 |
| Dev-3 | 低 | live 路径在 send 异常 abort 时 `consecutive_rst` 未在内层 break 后 reset；连续两轮 sub_type 各 4 次 RST 不会触发 abort（应用 5 阈值） | 边界 case，live 前可微调 |

---

## §2 实测 dry-run

### 命令

```bash
python .trellis/tasks/06-19-n6-hidden-protocol-scan/research/n6_fuzzer.py \
  --target lobby \
  --sessionid 0123456789abcdef0123456789abcdef \
  --userid newpt0000000000 \
  --range 1-5000 \
  --skip-known .trellis/tasks/06-19-n6-hidden-protocol-scan/research/xyid_closed_set.json \
  --sub-types 100,84,1,1006 \
  --rate 5 \
  --out .trellis/tasks/06-19-n6-hidden-protocol-scan/research/dryrun_log.jsonl
```

### stdout/stderr 末尾

```
2026-06-19 23:13:28,584 [INFO] n6_fuzzer: target=lobby host=None port=None
2026-06-19 23:13:28,584 [INFO] n6_fuzzer: msg_type total=5000 after-skip=4845 sub_types=[100, 84, 1, 1006] body_variants=False
2026-06-19 23:13:28,584 [INFO] n6_fuzzer: output=...\dryrun_log.jsonl
2026-06-19 23:13:28,584 [WARNING] n6_fuzzer: === DRY-RUN MODE === (use --live to actually send)
2026-06-19 23:13:28,872 [INFO] n6_fuzzer: dry-run: emitted 19380 frame records → ...\dryrun_log.jsonl
```

⏱️ 总耗时 ≈ **288 ms**（28.584s → 28.872s）。

**无任何 connection / connected / handshake / 0x4001 sent / SRSClient 字样**；进程结束零联网迹象。✅

### 总记录数 vs 期望

| 项 | 值 |
|---|---|
| `--range 1-5000` 展开 | 5000 个 msg_type |
| 闭集中落在 [1, 5000] 的条数 | 155（python 实测：`len([k for k in xyid_closed_set.json keys if 1 ≤ k ≤ 5000]) == 155`） |
| 扫描集大小 | 5000 - 155 = **4845** |
| sub_types 数 | 4 (`100, 84, 1, 1006`) |
| body templates | 1 (`empty`，未传 `--body-variants`) |
| **期望条数** | 4845 × 4 × 1 = **19380** |
| **实测条数** | `wc -l dryrun_log.jsonl` → **19380** ✅ |

### dryrun_log.jsonl 头 5 行（msg_type=22 起；前面 1-21 全在闭集中被剔除）

```json
{"ts": 1781882008.5857763, "mode": "dry-run", "msg_type": 22, "sub_type": 100, "extra": 0, "body_template": "empty", "body_hex": "", "wire_hex_unencrypted": "014000001600640000000000", "note": "..."}
{"ts": 1781882008.5857763, "mode": "dry-run", "msg_type": 22, "sub_type": 84, "extra": 0, "body_template": "empty", "body_hex": "", "wire_hex_unencrypted": "014000001600540000000000", "note": "..."}
{"ts": 1781882008.5857763, "mode": "dry-run", "msg_type": 22, "sub_type": 1, "extra": 0, "body_template": "empty", "body_hex": "", "wire_hex_unencrypted": "014000001600010000000000", "note": "..."}
{"ts": 1781882008.5857763, "mode": "dry-run", "msg_type": 22, "sub_type": 1006, "extra": 0, "body_template": "empty", "body_hex": "", "wire_hex_unencrypted": "014000001600ee0300000000", "note": "..."}
{"ts": 1781882008.5857763, "mode": "dry-run", "msg_type": 29, "sub_type": 100, "extra": 0, "body_template": "empty", "body_hex": "", "wire_hex_unencrypted": "014000001d00640000000000", "note": "..."}
```

### dryrun_log.jsonl 尾 5 行（msg_type=4999, 5000）

```json
{"ts": 1781882008.749441, "mode": "dry-run", "msg_type": 4999, "sub_type": 1006, "extra": 0, "body_template": "empty", "body_hex": "", "wire_hex_unencrypted": "014000008713ee0300000000", "note": "..."}
{"ts": 1781882008.749441, "mode": "dry-run", "msg_type": 5000, "sub_type": 100, "extra": 0, "body_template": "empty", "body_hex": "", "wire_hex_unencrypted": "014000008813640000000000", "note": "..."}
{"ts": 1781882008.749441, "mode": "dry-run", "msg_type": 5000, "sub_type": 84, "extra": 0, "body_template": "empty", "body_hex": "", "wire_hex_unencrypted": "014000008813540000000000", "note": "..."}
{"ts": 1781882008.749441, "mode": "dry-run", "msg_type": 5000, "sub_type": 1, "extra": 0, "body_template": "empty", "body_hex": "", "wire_hex_unencrypted": "014000008813010000000000", "note": "..."}
{"ts": 1781882008.749441, "mode": "dry-run", "msg_type": 5000, "sub_type": 1006, "extra": 0, "body_template": "empty", "body_hex": "", "wire_hex_unencrypted": "014000008813ee0300000000", "note": "..."}
```

### 抽样 frame_hex 拆解（`struct.unpack("<HHHHI", b[:12])`）

| sample wire_hex | FLAG | LEN | MSGTYPE | SUBTYPE | EXTRA | 备注 |
|---|---|---|---|---|---|---|
| `014000001600640000000000` | 0x4001 | 0 | 22 | 100 | 0 | mt=22 lua 闭集中没有 → 候选；sub=100=IM ✅ |
| `014000001600540000000000` | 0x4001 | 0 | 22 | 84 | 0 | sub=84=Room ✅ |
| `014000001d00640000000000` | 0x4001 | 0 | 29 | 100 | 0 | mt=29 候选 ✅ |
| `014000008813640000000000` | 0x4001 | 0 | 5000 | 100 | 0 | 区间末端 ✅ |
| `014000008713ee0300000000` | 0x4001 | 0 | 4999 | 1006 | 0 | 1006=MatchLink ✅ (0x03ee=1006 LE) |

5/5 样本字节序、字段顺序、值范围全部正确。`LEN=0` 因 round 1 默认 empty body，符合 strategy §4。✅

### 已知 (msg_type, sub_type) 不出现验证

```python
# 已知 mt 在 dryrun_log 中应为 0
records-with-known-mt: 0
sample known collisions: []
mt=306 occurrences: 0   # 306 in known set? True
```

闭集 207 个中所有 keys 没有任何一个在 dryrun_log.jsonl 出现。具体抽样 `mt=306`（IMProtocol.ReqKeepAlive，processid=100，已知 req）—— 为闭集 key，**0 次**出现 ✅。说明 `--skip-known` 正确生效。

### stderr/stdout 异常摘录

无异常、无 traceback、无 socket-related 日志。仅 4 行 INFO + 1 行 WARNING（DRY-RUN 自我标识）。✅

---

## §3 是否可上线（go/no-go）

参照 `n6-go-live-checklist.md §8 完成签收`。本轮只验证 Gate 4 中的 "n6_fuzzer.py dry-run 跑过一遍" 子项；其它运维 Gate (1-5) 由 main session 上线前补勾。

| Checklist 项 | 状态 | 备注 |
|---|---|---|
| 副号 sessionid 抓取，PoC v6 验证可用 | N/A 本轮不验 | 由运维侧 Gate 1 完成 |
| 副号 ≠ 主号 IP / 设备 | N/A | Gate 2 |
| ECS fuzz 出口已切 | N/A | Gate 2 |
| `xyid_closed_set.json` 同步到 fuzz 机 | ✅ | 已就位（207 keys） |
| **`n6_fuzzer.py` dry-run 跑过一遍（生成 ≥10000 行 jsonl）** | ✅ | **本轮：19380 行** |
| Ctrl+C abort 路径已测（脚本内 try/finally 已 implement） | ❌ | **Dev-2 偏差：无顶层 try/finally**，Ctrl+C 不一定 close conn |
| 监控终端开好（journalctl + 主 console） | N/A | Gate 4 |
| 用户在线，能即时回复 abort 指令 | N/A | Gate 5 |
| 备用副号 #2 sessionid 待命 | N/A | Gate 1 |

### 脚本侧硬阻塞

| 必须修复才能 live | 严重度 | 项 |
|---|---|---|
| **YES** | 中 | Dev-2：补 KeyboardInterrupt 顶层 try/finally（保证 Ctrl+C 时 `client.close()`），按 go-live checklist Gate 4 显式要求 implement 阶段处理 |
| **YES**（弱） | 中 | Dev-1：`--sub-types` default 与 checklist 6 个 sub_types 不符。**绕路修复也可**：live 命令显式传 `--sub-types 100,84,1,1006,92,0`。strict 一点：把 default 改了对齐 checklist |

### 判定：**🟡 NO-GO（脚本骨架本身需 1 处 implement 修复）**

- ✅ dry-run 路径**完全无网络 IO**，符合本轮零网络 IO 约束
- ✅ wire frame 与 PoC v5/v6 一致（FLAG/LEN/MSGTYPE/SUBTYPE/EXTRA 字节位置全对）
- ✅ `--skip-known` 正确剔除 155 个闭集 mt
- ✅ JSONL 输出 19380 = (5000-155)×4 完美匹配期望
- ❌ Ctrl+C 优雅 abort 未 implement（Dev-2，go-live checklist Gate 4 显式列出待办）
- ⚠️ sub_types default 与 checklist 不符（Dev-1，可通过命令行参数绕过）

**建议修复人**：trellis-implement 阶段 main session 处理；预计两处改动 ≤ 30 行 patch：

1. `main()` 把 `run_live(...)` 包到 `try: ... except KeyboardInterrupt: logger.warning("aborting"); finally: try: client.close() except: pass`（需把 `client` 提到 main 作用域 / 传出，或 `run_live` 自身负责）
2. `argparse` `--sub-types` default 改 `"100,84,1,1006,92,0"`

修完即可放行 live。dry-run 骨架 **本身已经 production-ready**，没有功能性 bug。

---

## §4 备注

- 验证产物：
  - `.trellis/tasks/06-19-n6-hidden-protocol-scan/research/dryrun_log.jsonl`（4.78 MB / 19380 行）
  - 本报告
- 未做（明确不做）：
  - 实际 `--live` 启动 / 任何 socket 调用 / DNS lookup
  - 修脚本（Dev-1 / Dev-2）。任务约束「改 n6_fuzzer.py 是允许的，但只为 dry-run 验证服务」—— dry-run 已通过，无需改动；若改 implement 阶段独立处理。
- `dryrun_log.jsonl` 含 `--out` 直传内容，**无 sessionid / userid 落盘**（`run_dry_run` 没引用 `args.sessionid` / `args.userid`，仅 `args.appid` / `args.roomid`），上 git 安全。但本任务约束「不要 commit」，留 working tree 即可。
- 闭集统计：207 unique keys 中 155 个落在 [1, 5000]，与 `lua-xyid-closed-set.md` 头注（"207 unique，155 in [1,5000]"）一致 ✅。
