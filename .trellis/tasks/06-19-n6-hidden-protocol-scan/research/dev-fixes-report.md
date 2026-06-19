# N6 Fuzzer Dev-1/2/3 Fix Report

- **Date**: 2026-06-19
- **Script**: `.trellis/tasks/06-19-n6-hidden-protocol-scan/research/n6_fuzzer.py`
- **Scope**: 修复 dryrun-report.md §1 列出的 Dev-1 / Dev-2 / Dev-3 三处偏差，使脚本达到 live-ready。本轮**零网络 IO**（不 `--live`），仅改脚本 + 重跑 dry-run + 控制流仿真验证。

---

## §1 改动清单（diff 摘要）

只改了 `n6_fuzzer.py` 一个文件。

### Dev-1（中）— `--sub-types` default 4→6，与 strategy/checklist 对齐

`main()` argparse：

```python
# before
p.add_argument("--sub-types", default="100,84,1,1006",
               help="comma-separated sub_type (processid) values")
# after
p.add_argument("--sub-types", default="100,84,1,1006,92,0",
               help="comma-separated sub_type (processid) values; "
                    "default 6 sub_types {0,1,84,92,100,1006} per fuzz-strategy.md §4 "
                    "and go-live checklist Gate 3")
```

同步更新模块 docstring CLI 示例（`--sub-types 100,84,1,1006,92,0`），保证文案与 default 一致。命令行解析逻辑 (`expand_csv_ints`) 未动，只改 default 字符串 + help。

### Dev-2（中）— `run_live` 补顶层 `try/except KeyboardInterrupt / finally`，保证 `client.close()`

`run_live` 结构重排（不破坏现有 send 失败 abort 的 5-RST → 退出逻辑）：

1. 在 client 构造前提前声明 `client = None`（`SRSClient` lazy-import 失败的 `return 2` 仍在 try 外，此时 `client` 为 None，无需 close）。
2. 把「client 构造 → on_frame/on_handshake_done 注册 → connect → 握手等待 → send 主循环 → graceful drain → return」整体包进 `try:` 块（缩进 +4）。
3. `except KeyboardInterrupt:` → 记录 INFO `"abort: KeyboardInterrupt received, closing client"`，**不 re-raise**，`return 0`。
4. `finally:` → `if client is not None: try: client.close() except Exception as e: logger.warning(...)`，兜底吞异常，绝不 mask 真实退出码。
5. 原本散在 try 末尾的 `try: client.close() except: pass` 删除（由 finally 统一负责），避免重复 close。

正常 return（0/3）、`return 1`（connect/handshake fail）、`return 2`（import fail，try 外）、Ctrl+C 五条退出路径，`client.close()` 都被尝试调用（import-fail 路径因 `client is None` 跳过，符合预期）。

### Dev-3（低）— 5-RST abort 退出外层 `mt` 循环，不再只退内层 body 循环

原结构三层循环：外层 `for mt in msg_types` / 中层 `for st in sub_types` / 内层 `for tpl in templates`。

**Bug**：5-RST 在内层 `tpl` 循环里 `break`（退内层）→ 中层尾部 `if abort_flag["abort"]: break`（退中层）→ **外层 `mt` 循环头无 abort 检查**，于是 `mt` 继续推进，每个剩余 `mt` 重新进中层时头检查（原 line 303）再 break 一次并**重复打 ABORT 日志**，导致 abort 实际上「泄漏」到每个剩余 `mt` 迭代，会话无法真正终止（最坏遍历上千个 `mt`，每个都重复 log ABORT）。

**修法**（「set abort flag + break outer，flag 检查在每个循环头」）：

- 外层 `mt` 循环头新增 `if abort_flag["abort"]: logger.error("ABORT: ..."); break`（Dev-3 关键修复点）。
- 内层 `tpl` 循环头也新增 `if abort_flag["abort"]: break`，让 recv 回调里设置的 popup-abort（`on_frame` 内 `abort_flag["abort"]=True`）能在下一帧发送前被捕获，更快停手。
- 中层 `st` 循环头检查保留（原有）。
- RST 计数器 `consecutive_rst` 仍跨 (msg_type, sub_type) 累积（任务要求：跨 combo 累积、到 5 终止整个会话）——未改其语义，只补足外层退出路径。

现在 5-RST abort 路径：内层 break → 中层 break → 外层头检查 break → 会话终止，`return 3`。

---

## §2 dry-run 重验（6 sub_types）

### 命令（**不带 `--sub-types`**，用新 default）

```bash
python .trellis/tasks/06-19-n6-hidden-protocol-scan/research/n6_fuzzer.py \
  --target lobby \
  --sessionid 0123456789abcdef0123456789abcdef \
  --userid newpt0000000000 \
  --range 1-5000 \
  --skip-known .trellis/tasks/06-19-n6-hidden-protocol-scan/research/xyid_closed_set.json \
  --out .trellis/tasks/06-19-n6-hidden-protocol-scan/research/dryrun_log_v2.jsonl
```

### stdout 末尾（确认 default = 6 个 sub_types）

```
[INFO] msg_type total=5000 after-skip=4845 sub_types=[100, 84, 1, 1006, 92, 0] body_variants=False
[WARNING] === DRY-RUN MODE === (use --live to actually send)
[INFO] dry-run: emitted 29070 frame records → ...dryrun_log_v2.jsonl
```

### `wc -l` vs 期望

| 项 | 值 |
|---|---|
| `--range 1-5000` 展开 | 5000 |
| 闭集落在 [1, 5000] | 155 |
| 扫描集 | 5000 − 155 = **4845** |
| sub_types 数 | **6**（default `{0,1,84,92,100,1006}`） |
| body templates | 1（empty，未传 `--body-variants`） |
| **期望条数** | 4845 × 6 × 1 = **29070** |
| **`wc -l` 实测** | **29070** ✅ |

### sub_type 集合验证（python set）

```
sub_type set: [0, 1, 84, 92, 100, 1006]   # == 期望 6 集合 ✅
modes: {'dry-run'}                         # 纯 dry-run，无 live ✅
directions: {None}                         # dry-run rec 无 direction 字段 ✅
```

### dry-run 网络关键字扫（`connection|connected|handshake|socket|0x4001 sent|SRSClient`）

```
network-keyword hits in jsonl: 0   ✅ 仍零联网迹象
```

### 抽样 mt=22 行（6 个 sub_type 都有）

```json
{"msg_type":22,"sub_type":100,"wire_hex_unencrypted":"014000001600640000000000",...}
{"msg_type":22,"sub_type":84, "wire_hex_unencrypted":"014000001600540000000000",...}
{"msg_type":22,"sub_type":1,  "wire_hex_unencrypted":"014000001600010000000000",...}
{"msg_type":22,"sub_type":1006,"wire_hex_unencrypted":"014000001600ee0300000000",...}
{"msg_type":22,"sub_type":92, "wire_hex_unencrypted":"0140000016005c0000000000",...}   # 0x5c=92 LE ✅
{"msg_type":22,"sub_type":0,  "wire_hex_unencrypted":"014000001600000000000000",...}   # 0x0000 ✅
```

mt=22 共 6 行，6 个 sub_type 全覆盖。字节序/字段位置全部正确（FLAG=0x4001, LEN=0, MSGTYPE=22, SUBTYPE, EXTRA=0）。

---

## §3 静态验证

### KeyboardInterrupt grep

```
$ grep -n "KeyboardInterrupt" n6_fuzzer.py
375:    except KeyboardInterrupt:
377:        logger.info("abort: KeyboardInterrupt received, closing client")
```
≥1 命中 ✅

### finally grep

```
$ grep -n "finally" n6_fuzzer.py
379:    finally:
```
≥1 命中 ✅

### `run_live` Ctrl+C 路径 review

代码路径（line 375-378）：

```python
except KeyboardInterrupt:
    # Dev-2: Ctrl+C → graceful abort, close client in finally, do NOT re-raise
    logger.info("abort: KeyboardInterrupt received, closing client")
    return 0
```

- Ctrl+C 在 send 循环 / connect / 握手等待期间抛出 → 被捕获。
- 记 INFO 日志（按要求）。
- 不 re-raise（`return 0` 优雅退出）。
- `finally` 块 `if client is not None: try: client.close() except Exception` 兜底 close。

**仿真验证**（fake `SRSClient`，`_send_raw` 抛 `KeyboardInterrupt`）：

```
[INFO] abort: KeyboardInterrupt received, closing client
return code: 0
FakeClient closed (Dev-2 Ctrl+C path): True
```

Ctrl+C 路径确实调用 `client.close()`，无 traceback，return 0 ✅。

**附加验证 — connect-fail 提前 return 路径**：

```
[ERROR] connect failed
return code (connect-fail): 1
FakeClient closed (connect-fail path): True
```

`return 1` 在 try 内，finally 仍 close ✅。

**附加验证 — import-fail 路径**（`return 2` 在 try 外）：`client` 此时为 None，finally 不执行（根本进不去 try），无需 close，符合预期 ✅。

### abort 外层退出 review（Dev-3）

改动后三层循环头检查分布：

```
$ grep -n "if abort_flag\[.abort.\]" n6_fuzzer.py
306:            if abort_flag["abort"]:      # 外层 mt 循环头（Dev-3 新增）✅
310:                if abort_flag["abort"]:  # 中层 st 循环头（原有）
314:                    if abort_flag["abort"]:  # 内层 tpl 循环头（Dev-3 新增）✅
368:                if abort_flag["abort"]:  # 中层尾部 break（原有）
```

5-RST abort 路径（line 343-346）：`consecutive_rst >= 5` → set flag → `break`（退内层 tpl）→ line 368 `break`（退中层 st）→ 下一轮外层 `mt` 头检查 line 306 命中 → `break`（退外层 mt）→ 会话终止 → `return 3`。

**仿真验证**（fake `SRSClient`，`_send_raw` 永抛 `OSError('simulated RST')`，msg_types=100 × sub_types=6 = 600 帧上限）：

```
[ERROR] send raised: simulated RST / connection reset   ×5
[ERROR] ABORT: 5 consecutive send failures (RST)
[WARNING] === fuzz finished sent=4 abort={'abort': True, ...} ===
return code: 3
FakeClient closed: True
send records written: 5
```

- 第 5 次 RST 触发 abort，会话**立即终止** —— 仅写 5 条 send 记录，而非 600（100 mt × 6 st）。
- 若 Dev-3 未修，abort 只退内/中层，外层 `mt` 会继续遍历剩余 99 个 `mt`，每个进中层头检查再 break + 重复 log ABORT，最终写入远多于 5 条、且日志被 ABORT 刷屏。
- 实测写 5 条 = abort 干净退出外层 ✅。
- `return 3` 保持原 abort 退出码（未破坏现有逻辑）✅。
- `FakeClient closed: True` = Dev-2 finally 在 abort 路径也生效 ✅。

---

## §4 判定

### Dev 偏差修复状态

| ID | 严重度 | 修复 | 验证 |
|---|---|---|---|
| Dev-1 | 中 | `--sub-types` default → `"100,84,1,1006,92,0"`（6 个），docstring 同步 | dry-run default 输出 `[100,84,1,1006,92,0]`，sub_type 集合 == `{0,1,84,92,100,1006}` ✅ |
| Dev-2 | 中 | `run_live` 顶层 `try/except KeyboardInterrupt/finally`，`client = None` hoist，finally 兜底 `client.close()` | grep ≥1 / 仿真 Ctrl+C + connect-fail + abort 三路径均 `closed=True`，无 re-raise ✅ |
| Dev-3 | 低 | 外层 `mt` 循环头 + 内层 `tpl` 循环头补 abort 检查，5-RST abort 退外层 | 仿真 5-RST 仅写 5 帧非 600，会话干净终止，`return 3` 保留 ✅ |

### go-live checklist Gate 4 子项状态

| Gate 4 子项 | 状态 | 备注 |
|---|---|---|
| `n6_fuzzer.py` dry-run 跑过一遍（≥10000 行 jsonl） | ✅ | 29070 行，6 sub_types |
| Ctrl+C abort 路径已测（脚本内 try/finally 已 implement） | ✅ | **Dev-2 已修**；Ctrl+C / connect-fail / abort / normal 四路径仿真均 `client.close()` |
| 监控终端开好（journalctl + 主 console） | N/A | 运维侧 Gate 4，本轮不验 |
| 用户在线能即时回复 abort 指令 | N/A | 运维侧 Gate 5 |
| `--sub-types` default 与 checklist Gate 3 6 个一致 | ✅ | **Dev-1 已修**，default = `100,84,1,1006,92,0` |
| 5-RST abort 真正终止会话（不泄漏到剩余 mt） | ✅ | **Dev-3 已修**，仿真确认 |

### 判定：**GO for live（脚本侧）**

- ✅ Dev-1 / Dev-2 / Dev-3 三处偏差全部修复并通过 dry-run + 控制流仿真验证
- ✅ dry-run 路径仍**完全无网络 IO**（`network-keyword hits: 0`），符合本轮零网络 IO 约束
- ✅ dryrun_log_v2.jsonl = 29070 行 = (5000−155)×6 完美匹配期望，sub_type 6 集合正确
- ✅ Ctrl+C 优雅 abort + `client.close()`（Gate 4 硬阻塞已解除）
- ✅ 5-RST abort 干净退外层，不刷屏、不泄漏
- ✅ wire frame 与 PoC v5/v6 一致（未被本轮改动触碰）

**剩余 live 前阻塞**：均为运维侧 Gate（副号 sessionid 抓取 / ECS fuzz 出口 / 监控终端 / 用户在线 / 备用副号），不在脚本侧。脚本本身已 live-ready。

### 产出文件

- `.trellis/tasks/06-19-n6-hidden-protocol-scan/research/n6_fuzzer.py`（改动，working tree 未 commit）
- `.trellis/tasks/06-19-n6-hidden-protocol-scan/research/dryrun_log_v2.jsonl`（29070 行，新建）
- `.trellis/tasks/06-19-n6-hidden-protocol-scan/research/dev-fixes-report.md`（本报告，新建）
