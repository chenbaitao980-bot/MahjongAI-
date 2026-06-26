# Thinking Guides

> **Purpose**: Expand your thinking to catch things you might not have considered.

---

## Why Thinking Guides?

**Most bugs and tech debt come from "didn't think of that"**, not from lack of skill:

- Didn't think about what happens at layer boundaries → cross-layer bugs
- Didn't think about code patterns repeating → duplicated code everywhere
- Didn't think about edge cases → runtime errors
- Didn't think about future maintainers → unreadable code

These guides help you **ask the right questions before coding**.

---

## Available Guides

| Guide | Purpose | When to Use |
|-------|---------|-------------|
| [Code Reuse Thinking Guide](./code-reuse-thinking-guide.md) | Identify patterns and reduce duplication | When you notice repeated patterns |
| [Cross-Layer Thinking Guide](./cross-layer-thinking-guide.md) | Think through data flow across layers | Features spanning multiple layers |
| [Meta-System Testing Thinking Guide](./meta-system-testing-thinking-guide.md) | 监督/保护/恢复机制本身的故障注入测试 | 装 watchdog / circuit-breaker / retry / 限流 / 降级 |
| [MITM 连接稳定性与排查方法论](./mitm-connection-stability-guide.md) | noconfig 热更 MITM 7 条铁律 + 间歇性连接失败排查链 | 改 NetConf/大厅地址；排查 admin 丢用户、手机"重进几次才连上"、4G 卡校验 |

---

## Quick Reference: Thinking Triggers

### When to Think About Cross-Layer Issues

- [ ] Feature touches 3+ layers (API, Service, Component, Database)
- [ ] Data format changes between layers
- [ ] Multiple consumers need the same data
- [ ] You're not sure where to put some logic

→ Read [Cross-Layer Thinking Guide](./cross-layer-thinking-guide.md)

### When to Think About Code Reuse

- [ ] You're writing similar code to something that exists
- [ ] You see the same pattern repeated 3+ times
- [ ] You're adding a new field to multiple places
- [ ] **You're modifying any constant or config**
- [ ] **You're creating a new utility/helper function** ← Search first!

→ Read [Code Reuse Thinking Guide](./code-reuse-thinking-guide.md)

### When to Think About MITM Connection Stability

- [ ] You're modifying `netconf_patch.py` / `LOCAL_TCP_LIST` / `LOCAL_TCP_LIST_50`
- [ ] You're changing how the phone reaches ECS (lobby IP, port, DNS)
- [ ] Symptoms involve **"intermittent" / "重进几次才连上" / admin 偶发丢用户**
- [ ] You're touching `setup_mitm.py` version/build offset logic
- [ ] You're about to trust a "应该已经修了" comment without实机复现

→ Read [MITM 连接稳定性与排查方法论](./mitm-connection-stability-guide.md)

### When to Think About Meta-System Testing

- [ ] You're adding/modifying a **watchdog / circuit-breaker / retry / rate-limit / fallback**
- [ ] You're tempted to write "已部署" or "Restart=always" as Acceptance Criteria
- [ ] Your code's job is to "watch something and recover when it breaks"
- [ ] The code path you're adding lives in `scripts/*watchdog*` / `*/health*` / `*/retry*` / `*/circuit*`

→ Read [Meta-System Testing Thinking Guide](./meta-system-testing-thinking-guide.md)

---

## Pre-Modification Rule (CRITICAL)

> **Before changing ANY value, ALWAYS search first!**

```bash
# Search for the value you're about to change
grep -r "value_to_change" .
```

This single habit prevents most "forgot to update X" bugs.

---

## How to Use This Directory

1. **Before coding**: Skim the relevant thinking guide
2. **During coding**: If something feels repetitive or complex, check the guides
3. **After bugs**: Add new insights to the relevant guide (learn from mistakes)

---

## Contributing

Found a new "didn't think of that" moment? Add it to the relevant guide.

---

**Core Principle**: 30 minutes of thinking saves 3 hours of debugging.
