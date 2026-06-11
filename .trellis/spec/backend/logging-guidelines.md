# Logging Guidelines

> How logging is done in this project.

---

## Overview

<!--
Document your project's logging conventions here.

Questions to answer:
- What logging library do you use?
- What are the log levels and when to use each?
- What should be logged?
- What should NOT be logged (PII, secrets)?
-->

(To be filled by the team)

---

## Log Levels

<!-- When to use each level: debug, info, warn, error -->

(To be filled by the team)

---

## Structured Logging

<!-- Log format, required fields -->

(To be filled by the team)

---

## What to Log

<!-- Important events to log -->

(To be filled by the team)

---

## What NOT to Log

<!-- Sensitive data, PII, secrets -->

(To be filled by the team)

---

## Side-Path Isolation（旁路日志绝不能破坏核心数据链路）

**Convention**: 取证日志、调试 dump、统计计数等**旁路**逻辑，若挂在每条消息必经的热路径上
（如 `TokenExtractor.feed()`、`MJProtocol._decode_frame()`），**必须**用 `try/except Exception`
包裹、字段读取用 `getattr(obj, "field", default)`，失败时 `logger.warning` 记一笔即可，
**绝不向上抛**。

**Why**: 旁路失败（磁盘满、权限、异常帧、对象缺字段）绝不应该连带把核心数据提取
（token / handshake / roomid）一起带崩。

**真实回归（2026-06）**: 给 `feed()` 加旁观帧取证捕获时，无条件读取了 `message.extra`，
导致一旦该字段缺失/异常就抛出，把同一次调用里的 token/room 提取一起拖垮——4 个
`TokenExtractor` 单元测试全挂（`AttributeError: 'FakeMsg' object has no attribute 'extra'`）。

### Wrong

```python
def feed(self, message):
    # 取证写盘直接挂在热路径上，无保护
    rec = {"extra": message.extra, "sub": message.sub_type}   # ← 缺字段即抛
    self._forensic_file.write(json.dumps(rec) + "\n")
    self._extract_from_cs(message)   # ← 上面一抛，核心提取永远到不了
```

### Correct

```python
def feed(self, message):
    try:
        rec = {
            "extra": getattr(message, "extra", ""),
            "sub":   getattr(message, "sub_type", 0),
        }
        self._forensic_file.write(json.dumps(rec) + "\n")
    except Exception as exc:               # 旁路失败只记不抛
        self._logger.warning("forensic dump skipped: %s", exc)
    self._extract_from_cs(message)         # 核心提取始终执行
```

> **Note**: 核心提取自身的字段访问（`_extract_from_cs` 里的 `message.msg_type` 等）**保留直接
> 访问**——那是真实契约，其失败不应被静默吞掉；只隔离取证/日志这类旁路。测试 mock（`FakeMsg`）
> 应补齐真实 `ProtocolMessage` 接口字段（`extra`/`ts` 等），让契约真实可测。
