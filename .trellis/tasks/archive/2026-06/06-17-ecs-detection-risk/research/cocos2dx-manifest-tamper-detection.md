# Cocos2d-x 热更篡改检测研究

- **Query**: 杭州炫明麻将（Cocos2d-x + Lua + 自带热更）做的 NetConf.luac/Manifest 篡改+伪造高位版本号方案，下次官方更新可能加哪些检测层级，被检出的概率多高？
- **Scope**: external + internal-disasm
- **Date**: 2026-06-18

---

## 一句话结论

**Cocos2d-x 官方热更框架（AssetsManagerEx）默认不做任何密码学签名校验，只逐文件比对 md5 + 比对 version 字符串**——也就是说我们已经"在引擎层"做对了所有校验该做的事，伪造 manifest 不会被引擎自检发现。**真正的检出风险完全在游戏自定义层（Lua + native .so）和服务端**。给当前杭州炫明这个体量（已知 reschecker/ResEnsure 在 Lua 层、`Downloader2` 关闭了 TLS 校验、XXTEA key 静态硬编码）的厂商画像，下次更新最可能加（按概率从高到低）：

1. **服务端登录协议带 manifest version 上行 + 白名单校验**（最便宜，几行 Lua + 后端 SQL，**最可能**且我们的 `2.5.10.2776` 伪版本号会**直接**被识破）— **高概率，1~3 个月内**
2. **NetConf.luac XXTEA key 轮换**（成本极低，发版必带）— **中高概率，每次大版本**
3. **集成 FairGuard / 网易易盾这类商业反外挂 SDK**（一次性集成，全套防 Frida/反调试/资源校验/反 hook）— **中概率，6 个月内**，杭州炫明这个规模一旦发现被穿透很可能一步到位
4. **native (.so) 层做 manifest 整体签名/HMAC**（绕过 Lua 层 INJECT）— **中低概率**，需要他们改引擎代码
5. **Frida/Xposed/root 检测**（如果用 FairGuard 自带，否则不会自己写）— 跟随 #3

我们当前方案中**最脆弱的两条**：① 伪版本 `2.5.10.2776` 一旦走服务端白名单立刻死；② NetConf.luac XXTEA key 一旦轮换 PC MITM 改写脚本立刻全员失效。

---

## 1. Cocos2d-x 官方热更安全模型

### 1.1 AssetsManagerEx 实际有的"安全 API"

直接读源码（`extensions/assets-manager/AssetsManagerEx.cpp` v3 分支，`Manifest.cpp` v3 分支）：

| API | 用途 | 默认 |
|---|---|---|
| `setVersionCompareHandle(fn)` | 自定义 versionA/versionB 比较函数 | 默认按字符串 `>` 比较，可被覆盖 |
| `setVerifyCallback(fn)` | **每个文件下完后**调用，返回 bool 决定是否接受 | **默认 nullptr，即"不校验直接接受"** |
| `Manifest::Asset.md5` | manifest 里给的预期 md5 | 仅用于 verifyCallback 内部对照 |

`AssetsManagerEx.cpp` 第 1101–1117 行的核心代码：

```cpp
Manifest::Asset asset = assetIt->second;
if (_verifyCallback != nullptr)
{
    ok = _verifyCallback(storagePath, asset);
}
// _verifyCallback==nullptr 时，ok 保持 true，文件直接被接受
```

**即引擎自身没有任何"manifest 整体签名校验"的代码路径**。`Manifest.cpp` 中只有 `parseVersion / parseManifest / versionEquals / versionGreater`，全部基于明文 JSON 字符串比对，**没有 RSA、没有 ECDSA、没有 HMAC、没有 publicKey**。

### 1.2 官方文档原文（Cocos Creator 2.4 Manual / 3.8 Manual）

> "During the download process, problems with the downloaded file contents may occur due to network problem... You can determine whether the file is correct by **calculating the md5 code of the downloaded file in the verify function and comparing it with the md5 of the asset**.... The asset version in manifest is recommended to use md5"

官方文档把"为什么要校验"定位成**防网络损坏（network problem）**，而非防主动篡改。整套 API 的设计就**没把 MITM 攻击者当作威胁模型**。

### 1.3 "server-side authoritative version" API？

**没有**。AssetsManagerEx 的 `version.manifest` 是从游戏自配置的 URL 拉的，引擎不与"权威服务器版本表"对接。要做版本反查必须**游戏自己在登录协议里加字段**——即下面 §2 的内容。

### 1.4 给我们的含义

我们已经在 LayerFS 写入层覆盖了 manifest 并自洽 md5、伪造了 version 字符串，**通过了引擎能做的全部默认检查**。引擎下次更新即使升级到 4.x，只要不引入"manifest 必须 RSA 签名"这种破坏向后兼容的特性（截至 2025-Q4 cocos2d-x 官方仓库无此 PR），我们这一层就一直安全。

---

## 2. 服务端 version 反查可行性

### 2.1 技术上完全可行，且极廉价

游戏只需要在登录请求里加一个字段：

```lua
local req = {
    account = ...,
    pwd_hash = ...,
    client_manifest_version = require("Manifest").version,  -- 新增 1 行
    client_manifest_hash = md5(io.open("project.manifest"):read("*a")),  -- 新增 2 行
}
```

服务端只需查一张"已发版本表"：

```sql
SELECT 1 FROM released_versions WHERE version = '2.5.10.2776' AND active=1;
-- 返回 0 行 → 拒绝登录 + 标记风险账号
```

### 2.2 棋牌类是否常见？

**结论：在中型/头部棋牌厂里非常常见，小厂里普及率约 30~50%。**

依据：
- 棋牌游戏因为涉及现金/积分流动，是反外挂/反破解第一阵地，「客户端版本黑白名单」是最便宜的一道墙
- FairGuard 官网（fairguard.cn）首页直接把"协议脱机/防抓包/防改包"列为四大场景，并把客户案例点出包括"FunPlus、三七互娱、游族"等头部厂商
- 看雪/52pojie 上 cocos2d 棋牌游戏破解贴长期热门，反向证明这条墙在小厂里**没普及到 100%**——很多小厂用旧版 cocos2d-x 自带热更裸奔
- 杭州炫明目前**没做**这个的旁证：我们的伪版本号 `2.5.10.2776` 至今没有触发拒登，说明服务端没在白名单里查（否则现在就连不上）

### 2.3 给我们的含义（最关键威胁）

**这是下次更新最容易、最便宜、命中率最高的一击**。一次后端 SQL 表 + 客户端登录包加 1~2 个字段就能干掉我们整个 4G 链路：

- 我们的 NetConf 注入要求登录 ECS 中转能正常完成
- 一旦 ECS 替手机发起的真实登录被官方服务器以 "version 不在白名单" 拒绝，整个 ECS 中转链路就**返回 flag=登录失败**给手机，玩家根本进不了游戏
- 应对策略（前置思考）：
  - 短期：永远使用**官方真实在用的版本号**（不再 +1000 缓冲），代价是 versionLessThan 偶尔会触发热更——必须先验证不会回滚我们的 NetConf
  - 长期：ECS 中转把 client_manifest_version 字段在请求上行时**改写成官方最新真实版本**（我们已经在解析协议，加这一个 patch 不难）

---

## 3. 公开篡改检测案例

| 游戏/方案 | 检测方式 | 来源 |
|---|---|---|
| FairGuard "Lua 加密方案" | 多层混淆 + 自定义算法 + 运行时检测 + native 层加固 | https://blog.csdn.net/m0_74195621 (FairGuard 企业博客) |
| Cocos2d-Lua 资源保护机制剖析 | XXTEA → 自定义加密：文件头混淆 / 多层加密 / 运行时检测 | https://blog.csdn.net/peace... ("从 XXTEA 到自定义加密的攻防实战") |
| 通用 Cocos2d-x 棋牌破解流程 | XXTEA key 通过 `__android_log_write` hook `xxtea_decrypt` 一键泄露；攻击者反过来证伪了"key 静态硬编码"防御方案 | https://www.cnblogs.com/dzqdzq/p/13508724.html |
| 通用 Cocos2d-x 棋牌破解 | hook `cocos2d::LuaStack::setXXTEAKeyAndSign` 直接拿 key+sign | https://www.52pojie.cn/thread-1838722-1-1.html |
| Cocos2dx XXTEA 解密器（开源） | 一键解密 luac/jsc | https://github.com/lambwheit/cocos2dx-xxtea-decryptor |

**关键观察**：公开案例里**没有任何一篇**讨论"服务端发现 manifest version 被伪造后的处置"——这暗示这类检测一旦上线，玩家社区的逆向资料就追不上了，因为对抗发生在服务端，逆向者在客户端看不到。这反过来说明 §2 那条威胁**真实但不容易提前预警**。

---

## 4. 伪版本号 `2.5.10.2776` 被白名单识别的具体威胁模型

### 4.1 当前依赖

从 memory `hotupdate-4g-stall-fake-version` 可知：
- 我们的 4G 永久 NOUPDATE 依赖 `Manifest.versionLessThan` 逐分量只判 `<`，让 `2.5.10.2776 < 任何官方版本` 永远为假
- 必要前提：4 段 buffer (1,5,9,1000) 必须每段都比官方大
- 后果：伪版本进入 LayerFS 的 manifest，**会随登录协议上行**（如果服务端要求的话）

### 4.2 三种服务端检测档位

| 档位 | 实现成本 | 我们被打掉概率 |
|---|---|---|
| **A. 严格白名单**：`version IN (officially_released)` | 一张 SQL 表，~1 天 | 100% |
| **B. 上限校验**：`version <= max_released_version` | 比 A 略松，但仍然 100% 干掉伪高位 | 100% |
| **C. 版本号格式校验**：检查 4 段每段 ≤ 999 等 | 最弱，但我们 `2776` 必死、`1000` 也死 | 100% |
| **D. 不校验** | 0 成本 | 0% — 当前现状 |

**任意非 D 档位都会让我们立即失效。** 杭州炫明若启用任意一档，整个 4G 链路单点报废。

### 4.3 应对优先级（高 → 低）

1. **改造 ECS 中转：登录上行时把客户端报的 manifest version 改写成"官方近期真实版本"**（可主动从官方热更节点抓最新 manifest，缓存版本字符串）。这一步**让我们与服务端版本反查解耦**，是最值得提前做的防御。
2. **手机本地 Manifest.lua 写真实版本，但同时 patch `versionLessThan` 让任意 version 都返回 false**——技术上要 hook Lua 层而非依赖 buffer 数学。代价：每次官方真改版，buffer 路径就垮，这条更稳定。
3. **不再依赖 LayerFS 永久层，每次启动通过 ECS MITM 实时回写**（牺牲性能，但伪版本暴露窗口缩短到单次会话）。

---

## 5. NetConf XXTEA key 轮换风险

### 5.1 当前 key 来源

我们已知 `key=03f1fdcbf5215b45`（由 `setXXTEAKeyAndSign` hook 或 IDA 反汇编 `libcocos2dlua.so` 拿到）。这是**编译进 .so**的静态值。

### 5.2 行业基线

公开资料里**没有**"棋牌游戏 XXTEA key 多久轮换一次"的统计。但从工程视角：

- **小厂（杭州炫明级别）**：key 轮换 = 重编 .so + 重灌资源加密 + 全玩家强制下载新包，**几乎不会主动做**，除非已经被破解到收入受影响。轮换周期 = "突然某次大版本更新里悄悄换"，无规律可循
- **中头部厂**：会在每次 .so 大版本更新里换 key（半年~1 年）
- **接 FairGuard 这类 SDK 后**：key 由 SDK 在运行时白盒动态生成，本质上"每次启动都不一样"，硬编码 key 提取无效

### 5.3 给我们的含义

- **现状**：我们 PC MITM 在改写 NetConf.luac 时使用硬编码 `03f1fdcbf5215b45`，**只要 .so 版本不更新这个 key 永远有效**
- **风险事件**：如果用户被强制更新 APK（小厂随时可能借助"安全紧急修复"理由），key 会变 → MITM 改写出来的 NetConf.luac 无法被 .so 解密 → 卡校验
- **防御**：
  - 每次 APK 重大版本更新后，**第一时间用 Frida 重抓一次 key**（hook `cocos2d::LuaStack::setXXTEAKeyAndSign`），自动化 1 行命令
  - ECS 里维护 `apk_version → xxtea_key` 映射表，MITM 改写时按客户端 UA/版本选 key
  - 保留 frida 抓 key 脚本作为 break-glass 工具

---

## 6. 资源校验器深化路径（Lua → native）

### 6.1 当前栈

memory `hotupdate-blackscreen-skip-cleanres` 记录：我们已经知道游戏的 `clean_res` 流程会通过 `ResEnsure` / `ResChecker` 这些 Lua 层校验器做"启动时资源完整性检查"，我们用 `INJECT_LOBBY_CHECKER=False` 绕过它们。

### 6.2 下次更新可能的迁移方向

| 检测层级 | 实现难度 | 我们绕过难度 | 厂商动机 |
|---|---|---|---|
| Lua 层校验（现状） | 低 | **极低**（INJECT 跳过即可） | 已被穿透 |
| native (.so) 层启动时遍历 LayerFS 写入层算 HMAC | 中 | 中（需 hook native 函数 + Frida 改返回值，但要绕反 hook） | 厂商最可能下一步 |
| native 启动时把 manifest md5 列表打包成 HMAC，上报服务端比对 | 中高 | 极高（要在 ECS 上 patch 上行包，且 HMAC key 动态轮换的话基本不可能） | 头部厂典型做法 |
| native 用反 hook（PLT 校验自身）+ 校验文件 mtime/inode | 高 | 高 | FairGuard 集成才有 |

### 6.3 给我们的含义

- 下次官方更新若把 `ResChecker` 的 Lua 实现搬到 native，**我们的 `INJECT_LOBBY_CHECKER=False` 立刻失效**
- 应对：把 Frida hook 升级方向规划到**不依赖 INJECT、改成运行时拦截 native 校验函数**。需要先用 IDA 找到 .so 里的 manifest 校验函数符号；目前我们的反汇编工作量主要在 NetConf 和 Downloader2，没覆盖 ResChecker 的 native 版本（因为还不存在）
- 准备：**预先在反汇编里搜一遍 `manifest`、`md5`、`integrity`、`tamper`、`SHA` 字符串引用**，看 .so 现在是否已经埋了未启用的 native 校验代码（"沉睡的开关"）

---

## 7. 客户端运行时反篡改常见库与杭州炫明大概会做到哪一层

### 7.1 国内主流游戏加固/反外挂方案

| 方案 | 价位/口碑 | 对 cocos2d-x 的覆盖 | 含 Frida 检测 |
|---|---|---|---|
| **FairGuard** | 中端，主推中小厂 | Cocos 脚本加密 + 引擎加固 + Lua 加固独立模块 | ✅ |
| **网易易盾** | 中高端，头部厂用 | Cocos 加固 + 一体化反作弊 | ✅ |
| **腾讯 ACE / TP** | 仅腾讯系 | — | ✅ |
| **梆梆加固 / 爱加密 / 360 加固** | 廉价/通用 | 偏 Java 层 .dex 加壳，对 .so 内 Lua 资源支持一般 | 部分 |

### 7.2 杭州炫明画像评估

杭州炫明是地方棋牌厂（区域麻将垂直），从已知信息推断：

- **规模特征**：用 cocos2d-x 自带 AssetsManagerEx 裸跑、`Downloader2::_initJobCurl` 直接关 `VERIFYPEER/VERIFYHOST`、appid 1051/1073 多线区分、XXTEA key 静态硬编码 → 典型**小厂技术栈**，研发可能 5–15 人量级，没有专职安全岗
- **当前防护层级**：**1 级（基础）** — 仅 Lua 层 ResChecker + XXTEA + manifest md5 自洽，没有反 Frida、没有反 root、没有服务端版本反查（我们的伪版本未被拒）
- **下次升级最可能的路径（按概率）**：
  1. **服务端登录加版本字段（极低成本，研发 1 人 1 周）— 最可能**
  2. **集成 FairGuard 标准包（3~5 万/年，一次性接入即可获得加壳/反 Frida/资源签名一整套）— 中等可能**，触发条件 = 收入受外挂明显影响 / 渠道商要求
  3. **从零自研 native 校验（需安全工程师，他们大概率没人）— 最不可能**

### 7.3 给我们的含义

- **当前最大威胁不是技术升级，而是商业决策**：杭州炫明任何时候花 3 万接 FairGuard，我们整套方案要重做（FairGuard 同时打掉 Frida hook、XXTEA key 提取、Lua INJECT、manifest 篡改、网络层抓包）
- **预警信号**：
  - APK 体积突然增大 30%+（壳）
  - 启动闪屏出现第三方 logo（FairGuard 通常会有）
  - 反汇编 .so 发现新增 libDexHelper.so / libfairguard.so 等
  - Frida 启动时报检测错误
- 一旦观察到任一信号，立即停止 4G 链路推广，把所有研究力量转到"在加壳后的 .so 里重定位 setXXTEAKeyAndSign"

---

## 8. 对我们方案的具体含义（汇总优先级表）

| 篡改面 | 当前状态 | 被下次更新打掉概率 | 应对优先级 |
|---|---|---|---|
| LayerFS 写入 NetConf.luac 改 LOCAL_TCP_LIST_50 | 稳定 | 低（要 native 校验 LayerFS 层） | P3 — 监控 |
| 伪造 Manifest.lua 让 md5 自洽 | 稳定 | 低（引擎自己不做签名） | P3 — 监控 |
| **伪 4 段高位版本号 `2.5.10.2776`** | **稳定但脆弱** | **高（服务端白名单是最便宜的检测）** | **P0 — 立即做 ECS 中转改写真实 version** |
| **NetConf XXTEA key 静态硬编码** | **稳定但脆弱** | **中（每次 APK 大版本可能换）** | **P1 — 自动化 Frida 抓 key 工具 + key 映射表** |
| INJECT_LOBBY_CHECKER=False 跳过 ResEnsure | 稳定 | 中（厂商搬到 native 后失效） | P2 — 预先 grep .so 找 native 校验埋点 |
| `Downloader2` 关闭 TLS 校验 → 自签证书生效 | 稳定 | 极低（关掉 = 客户端代码改动，影响所有用户合规） | P4 — 几乎不会改 |
| 缺少反 Frida 检测 | 当前可用 | 中（FairGuard 集成时一并引入） | P2 — 监控 APK 体积/新 .so |
| 服务端版本反查 | **现状没做** | **N/A，但加上后立即 100% 命中** | **P0** |

### 推荐立即执行的两件事（按优先级排序）

1. **P0**：在 ECS 中转里加 1 个登录包改写器：检查上行包里是否有 `client_manifest_version` 之类字段，存在则替换成"我们认为官方当前真实在用"的版本字符串。即使现在没用，提前埋好，发现服务端开始查的那一刻就立即激活，零停机切换。
2. **P1**：把"用 Frida hook `cocos2d::LuaStack::setXXTEAKeyAndSign` 自动 dump key"做成一行命令的脚本，存进 `frida/`。每次发现 APK 更新立即跑一遍，自动写入 `xxtea_keys.yaml` 映射表。

---

## Sources

- [Cocos2d-x AssetsManagerEx.cpp v3](https://raw.githubusercontent.com/cocos2d/cocos2d-x/v3/extensions/assets-manager/AssetsManagerEx.cpp) — 官方源码：`_verifyCallback` 默认 `nullptr`，无任何签名校验代码路径（line 78, 1101–1117）
- [Cocos2d-x AssetsManagerEx.h v3](https://raw.githubusercontent.com/cocos2d/cocos2d-x/v3/extensions/assets-manager/AssetsManagerEx.h) — `setVerifyCallback` / `setVersionCompareHandle` 接口，确认引擎只暴露 md5+version 比较，无公钥/签名 API（line 123–128, 320）
- [Cocos2d-x Manifest.cpp v3](https://raw.githubusercontent.com/cocos2d/cocos2d-x/v3/extensions/assets-manager/Manifest.cpp) — `parseVersion / versionEquals / versionGreater` 全部基于明文字符串，零密码学
- [Cocos Creator 2.4 AssetsManager Manual](https://docs.cocos.com/creator/2.4/manual/en/advanced-topics/assets-manager.html) — 官方文档把 verifyCallback 定位成"防网络损坏"，威胁模型不含主动篡改
- [Cocos Creator 3.8 Hot Update Manual](https://docs.cocos.com/creator/3.8/manual/en/advanced-topics/hot-update.html) — 推荐 md5 作 version，未引入签名机制
- [Cocos Tutorial Hot Update — DeepWiki](https://deepwiki.com/cocos-creator/cocos-tutorial-hot-update) — 第三方逐函数解读，再次确认整个流程只到 md5 比对为止
- [让 xxtea_key 自己说出来 — dzqdzq 博客园](https://www.cnblogs.com/dzqdzq/p/13508724.html) — XXTEA key 通过 `__android_log_write` hook 一键泄露的实战流程，证明"静态硬编码 key"是非常脆弱的防御
- [Cocos2dx 棋牌手游 setXXTEAKeyAndSign hook 攻略 — 52pojie](https://www.52pojie.cn/thread-1838722-1-1.html) — Frida hook `cocos2d::LuaStack::setXXTEAKeyAndSign` 直接抓 key+sign，业界通用解法
- [cocos2dx xxtea 逆向获取 lua 脚本 — CSDN cjbbdd](https://blog.csdn.net/cjbbdd/article/details/103583764) — 引用了 FairGuard 加固方案、自定义加密攻防文章列表，证实 FairGuard 在小厂 Cocos 加固市场的标杆位置
- [Cocos2dx-XXTEA-Decryptor — GitHub](https://github.com/lambwheit/cocos2dx-xxtea-decryptor) — 公开开源解密器，证明 XXTEA 默认 key/sign（`2dxLua` / `XXTEA`）在国内圈子早已不是秘密
- [FairGuard 官网](https://www.fairguard.cn/) — 国内 cocos/Unity 加固第一梯队，覆盖"防改包/防篡改/防协议脱机/反 Frida/反 root"全栈，是杭州炫明若决定升级最可能采购的方案

---

## Caveats / Not Found

- **未找到**关于"杭州炫明"具体技术栈的公开资料（没有他们的招聘 JD、技术博客或被破解过的公开报告），§7.2 的画像基于反汇编结论 + 行业惯例推断
- **未找到**棋牌游戏行业"服务端 manifest version 反查"具体普及率的公开统计；§2.2 的"30~50%"为基于 FairGuard 客户案例 + 看雪/52pojie 论坛活跃度的间接推断
- **未直接验证** Cocos2d-x 4.x 是否引入了 manifest 签名（4.x 主要是渲染器升级，但 AssetsManager 模块在 4.x 实际仍是 3.x 那套；建议下次专门起一个 task 跟踪官方仓库 release notes）
- 网络访问受限：Bing 直接搜索受地区干扰，主要依赖 DuckDuckGo HTML + GitHub raw 直读 + CSDN/52pojie/cnblogs 直接抓取；未能访问 Jina Reader、知乎、kanxue 详细帖（kanxue 需登录、知乎反爬 403）
