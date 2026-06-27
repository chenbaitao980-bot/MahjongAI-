"""netconf_patch.py — 解密 / 改写 / 重加密 游戏的 NetConf.luac。

游戏的 Lua 资源格式（已逆向坐实，见 task PRD / 记忆 hotupdate-mitm-netconf-overlay）：

    assets/src/app/Config/NetConf.luac = SIGN + XXTEA(明文 Lua 源码)

    SIGN = b"devaguopeifei"
    KEY  = b"03f1fdcbf5215b45"   (16 字节，作为 XXTEA 128bit key)

XXTEA 这里不在密文里存长度（to_u32 inc=False），解密时用密文字节长作为明文长度，
因此明文长度 == 密文长度，**改成不同长度的 IP 也能完美往返**。

本模块职责（设置期，离线）：
  1. 从 APK 取出 NetConf.luac
  2. 解密 → 明文 Lua 源码
  3. 只把 **台州 LOCAL_TCP_LIST[5045]** 块里的真服 IP 换成 ECS IP（端口保留）
  4. 重新 XXTEA 加密 + 加 SIGN → 新 NetConf.luac（投递给热更）
  5. 往返自测：解密新 luac，确认 5045 指向 ECS 且其余字节不变

隔离：纯离线工具，不依赖 noconfig 运行时，不碰 vpn/hotspot。
"""
from __future__ import annotations

import argparse
import logging
import re
import zipfile
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ─── XXTEA（与 apk_research/_decrypt_lua.py 同源，补上 encrypt）──────────────

_DELTA = 0x9E3779B9
SIGN = b"devaguopeifei"
KEY = b"03f1fdcbf5215b45"

# 游戏 APK 内 NetConf 落点
APK_NETCONF_ENTRY = "assets/src/app/Config/NetConf.luac"

# 台州区：srsGroupID = 5045（areaID=7109）。真服大厅 IP 与端口见 NetConf.lua。
TAIZHOU_GROUP_ID = 5045
REAL_LOBBY_IP = "47.96.101.155"
# 台州 5045 区大厅端口（LOCAL_TCP_LIST[5045] 两个条目 id=9074/9075）。
TAIZHOU_LOBBY_PORTS = (5748, 5749)

# LOCAL_TCP_LIST_50 表里**硬编码真服游服**（金币局等）的重定向表。
# 根因：getTcpConnectInfoByGroupId 对 _50 里的 groupId 是最高优先级「直接 return」，
# 完全绕过 RespSRSAddr 改写和 srslist 缓存。金币局牌局游服 groupId=5067(正式)/5167(DEBUG)，
# _50 里写死真服:7777 → 手机直连真服游服、绕过 ECS。必须把它们也改写指向 ECS，
# 由 ECS 在对应监听端口起代理转发到原真服 7777（端口用 5700-5799 已放行段）。
# {groupId: (real_host, real_port, ecs_listen_port)}。tcp_proxy.main 据此建金币游服代理。
SRS50_REMAP = {
    5067: ("srs-zj.tt2kj.com", 7777, 5767),   # 金币局 正式服
    5167: ("60.205.203.7", 7777, 5768),       # 金币局 DEBUG 服
}


def _to_u32(data: bytes) -> tuple[list[int], int]:
    n = len(data)
    arr = [0] * ((n + 3) // 4)
    for i in range(n):
        arr[i >> 2] |= data[i] << ((i & 3) << 3)
    return arr, n


def _to_bytes(arr: list[int], n: int) -> bytes:
    out = bytearray(n)
    for i in range(n):
        out[i] = (arr[i >> 2] >> ((i & 3) << 3)) & 0xFF
    return bytes(out)


def _mx(s: int, y: int, z: int, p: int, e: int, k: list[int]) -> int:
    return (
        (((z >> 5) ^ ((y << 2) & 0xFFFFFFFF)) + ((y >> 3) ^ ((z << 4) & 0xFFFFFFFF)))
        ^ (((s ^ y) & 0xFFFFFFFF) + ((k[(p & 3) ^ e] ^ z) & 0xFFFFFFFF))
    ) & 0xFFFFFFFF


def _key_words(key: bytes) -> list[int]:
    k, _ = _to_u32(key)
    while len(k) < 4:
        k.append(0)
    return k


def xxtea_decrypt(data: bytes, key: bytes = KEY) -> bytes:
    if not data:
        return b""
    v, vn = _to_u32(data)
    k = _key_words(key)
    n = len(v)
    if n < 2:
        return data
    s = ((6 + 52 // n) * _DELTA) & 0xFFFFFFFF
    y = v[0]
    while s != 0:
        e = (s >> 2) & 3
        for p in range(n - 1, 0, -1):
            z = v[p - 1]
            v[p] = (v[p] - _mx(s, y, z, p, e, k)) & 0xFFFFFFFF
            y = v[p]
        z = v[n - 1]
        v[0] = (v[0] - _mx(s, y, z, 0, e, k)) & 0xFFFFFFFF
        y = v[0]
        s = (s - _DELTA) & 0xFFFFFFFF
    return _to_bytes(v, vn)


def xxtea_encrypt(data: bytes, key: bytes = KEY) -> bytes:
    """XXTEA 加密 — decrypt 的精确逆，保持明文/密文等长。"""
    if not data:
        return b""
    v, vn = _to_u32(data)
    k = _key_words(key)
    n = len(v)
    if n < 2:
        return data
    s = 0
    rounds = 6 + 52 // n
    z = v[n - 1]
    for _ in range(rounds):
        s = (s + _DELTA) & 0xFFFFFFFF
        e = (s >> 2) & 3
        for p in range(n - 1):
            y = v[p + 1]
            v[p] = (v[p] + _mx(s, y, z, p, e, k)) & 0xFFFFFFFF
            z = v[p]
        y = v[0]
        v[n - 1] = (v[n - 1] + _mx(s, y, z, n - 1, e, k)) & 0xFFFFFFFF
        z = v[n - 1]
    return _to_bytes(v, vn)


# ─── luac 封包 / 解包 ───────────────────────────────────────────────────────

def unwrap_luac(raw: bytes, key: bytes = KEY) -> str:
    """SIGN + XXTEA(源码) → 明文 Lua 源码字符串。

    cocos XXTEA 格式（inc=True）：明文块 = 源码字节(补0到4字节对齐) + 4字节长度尾(小端=源码长度)。
    游戏解密后**读末尾长度字，只取前 N 字节作真正源码**。因此这里也必须剥掉长度尾，
    否则会把 \\x9c4\\x00\\x00 这种长度字当成源码内容，wrap 回去后长度字错位 → 游戏截取错误 → luaLoadBuffer 崩溃。

    用 latin-1 解码（字节↔字符 1:1 无损）：NetConf 含 GBK 中文注释，utf-8 会损坏字节。
    """
    body = raw[len(SIGN):] if raw.startswith(SIGN) else raw
    full = xxtea_decrypt(body, key)
    if len(full) >= 4:
        n = int.from_bytes(full[-4:], "little")
        if 0 <= n <= len(full) - 4:
            return full[:n].decode("latin-1")
    return full.decode("latin-1")


def wrap_luac(source: str, key: bytes = KEY) -> bytes:
    """明文 Lua 源码 → SIGN + XXTEA(块)，与游戏加载格式一致。

    cocos XXTEA 格式（inc=True）：明文块 = 源码字节(补0到4字节对齐) + 4字节长度尾(小端=源码长度)。
    游戏解密读末尾长度字、取前 N 字节作源码。改写后源码长度可能变化，长度尾必须按新长度写，
    否则游戏按旧长度截取会切到半句 Lua → luaLoadBuffer 崩溃。
    """
    data = source.encode("latin-1")  # 与 unwrap_luac 对称，字节级无损
    n = len(data)
    pad = (-n) % 4
    block = data + b"\x00" * pad + n.to_bytes(4, "little")
    return SIGN + xxtea_encrypt(block, key)


# ─── NetConf 改写 ───────────────────────────────────────────────────────────

@dataclass
class PatchResult:
    source_before: str
    source_after: str
    replacements: int
    new_luac: bytes


def _patch_taizhou_block(source: str, ecs_ip: str, group_id: int = TAIZHOU_GROUP_ID,
                         real_ip: str = REAL_LOBBY_IP,
                         ports: tuple[int, ...] = TAIZHOU_LOBBY_PORTS) -> tuple[str, int]:
    """在 LOCAL_TCP_LIST[<group_id>] = { ... } 这一块里**就地把真服 IP 改写为 ECS**。

    降级形态（2026-06-19，记忆 ecs-failover-path-y）：原 Path Y "追加 ECS 保留真服"
    导致 NetEngine 普通路径 `math.random(1, len)` 在 [真服, 真服, ECS, ECS] 里 ~50%
    抽中真服 → 手机直连 7777 绕开 ECS tcp_proxy → relay 抓不到 0x2bc0、admin 看不到
    登录态。抓牌依赖 ECS 全程在线，与"ECS 整机宕机用户能玩"互斥；选抓牌，5045
    回滚为 ECS 单点：把块里所有 real_ip 改成 ecs_ip，端口与 id 字段保持原状，
    列表只剩两个 ECS 条目（端口 5748/5749 用 ECS 监听复用真服端口号）。

    NetConf.lua 里 47.96.101.155 出现在多个区（5045/5027/5070 等），必须只动台州块。
    幂等：若块内 real_ip 已经全部被替换为 ecs_ip，返回 (source, 0)。
    """
    # 用花括号配平精确框住整个 [group_id] = { ... } 表块（含嵌套 {id=...} 条目）。
    # 注意 NetConf 顶部有**被注释掉**的同号块（用别的 IP）；只改**含真服 IP 的真块**。
    start, end = _find_real_block_span(source, group_id, real_ip)
    if start is None:
        return source, 0
    block = source[start:end]
    if real_ip not in block:
        return source, 0  # 幂等：已 in-place 替换过
    # in-place 把真服 IP 改写为 ECS IP；端口与 id 字段保持，避免触动 LOCAL_TCP_LIST
    # 其他区（块外的 real_ip 由 _find_real_block_span 已隔离）。
    new_block = block.replace(real_ip, ecs_ip)
    n = block.count(real_ip)
    new_source = source[:start] + new_block + source[end:]
    return new_source, n


def _find_real_block_span(source: str, group_id: int, must_contain: str):
    """返回 [group_id] = { ... } 真块（含 must_contain）在 source 中的 [start,end) 区间。

    用花括号配平找到与 '{' 匹配的 '}'，跳过被注释或不含 must_contain 的同号块。
    """
    for m in re.finditer(r"\[\s*%d\s*\]\s*=\s*" % group_id, source):
        brace = source.find("{", m.end())
        if brace < 0:
            continue
        depth = 0
        i = brace
        while i < len(source):
            c = source[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        end = i + 1
        span = source[m.start():end]
        if must_contain in span:
            return m.start(), end
    return None, None


def _inject_srs50_block(source: str, ecs_ip: str, group_id: int = TAIZHOU_GROUP_ID,
                        ports: tuple[int, ...] = TAIZHOU_LOBBY_PORTS) -> tuple[str, int]:
    """往 LOCAL_TCP_LIST_50 表里注入 [group_id] = ECS 大厅条目。

    根因（NetEngine.getTcpConnectInfoByGroupId）：该区 isSupportSRS50()=true 时，
    若 LOCAL_TCP_LIST_50[groupId] 存在且非空 → **直接 return list[1]**，
    完全跳过「LOCAL_TCP_LIST + srslist{groupId}.json 缓存混合后随机选」的逻辑。
    线上 _50 表只有 [5167][5067]，没有 5045，所以 5045 大厅被动态 srslist 缓存
    稀释、随机连真服。注入 [5045]=ECS 后，大厅地址被确定性钉到 ECS。

    幂等：已存在 [group_id] 则不重复注入。
    """
    # 已注入则跳过（在 _50 表块内找 [group_id]）
    m50 = re.search(r"LOCAL_TCP_LIST_50\s*=\s*\{", source)
    if not m50:
        return source, 0
    # 截出 _50 表块（花括号配平）
    brace = source.find("{", m50.start())
    depth = 0
    i = brace
    while i < len(source):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    blk = source[brace:i + 1]
    if re.search(r"\[\s*%d\s*\]" % group_id, blk):
        return source, 0  # 幂等
    entries = ", ".join('{id = 0, ip = "%s", port = %d}' % (ecs_ip, p) for p in ports)
    inject = "\n        [%d] = { %s }," % (group_id, entries)
    pos = m50.end()
    return source[:pos] + inject + source[pos:], 1


def _patch_srs50_realservers(source: str, ecs_ip: str) -> tuple[str, int]:
    """把 LOCAL_TCP_LIST_50 里硬编码真服游服（SRS50_REMAP 的 groupId）改成 ECS 单点单条。

    降级形态（2026-06-19，记忆 ecs-failover-path-y）：原 Path Y 写成 [ECS, 真服] 两项 +
    NetEngine `_50` 分支轮询，希望 ECS 挂时切真服恢复金币局。但抓牌依赖 ECS tcp_proxy
    全程在线，与"切真服恢复"互斥（切了真服就抓不到 0x2bc0），同样不需要真服兜底。
    每个金币游服 [groupId] 改写为单项 list[1] = ECS:ecs_listen_port，由 ECS 代理转发。
    幂等：若 list 已经只含 ECS 单条且不含真服则跳过。
    """
    # 先框定 LOCAL_TCP_LIST_50 表自身的范围（[5167]/[5067] 在别的表也出现，必须限定）。
    m50 = re.search(r"LOCAL_TCP_LIST_50\s*=\s*\{", source)
    if not m50:
        return source, 0
    t_brace = source.find("{", m50.start())
    depth = 0
    j = t_brace
    while j < len(source):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    table_start, table_end = t_brace, j + 1
    table = source[table_start:table_end]

    total = 0
    for gid, (real_host, _real_port, ecs_port) in SRS50_REMAP.items():
        m = re.search(r"\[\s*%d\s*\]\s*=\s*\{" % gid, table)
        if not m:
            continue
        brace = table.find("{", m.start())
        d = 0
        i = brace
        while i < len(table):
            if table[i] == "{":
                d += 1
            elif table[i] == "}":
                d -= 1
                if d == 0:
                    break
            i += 1
        block = table[brace:i + 1]
        # 幂等：块里只含 ECS、不含真服，跳过
        if ecs_ip in block and real_host not in block:
            continue
        # 重写为单项 [ECS_entry]；保留外层缩进风格
        new_block = (
            "{\n"
            '        {id = 0, ip = "%s", port = %d}\n'
            "    }"
        ) % (ecs_ip, ecs_port)
        if new_block != block:
            table = table[:brace] + new_block + table[i + 1:]
            total += 1
    if total:
        source = source[:table_start] + table + source[table_end:]
    return source, total


def patch_netconf(raw_luac: bytes, ecs_ip: str, *, key: bytes = KEY,
                  group_id: int = TAIZHOU_GROUP_ID,
                  real_ip: str = REAL_LOBBY_IP) -> PatchResult:
    """主入口：原始 NetConf.luac + ECS IP → 改写后的 NetConf.luac（含往返校验）。

    降级形态（2026-06-19，记忆 ecs-failover-path-y）：抓牌依赖 ECS tcp_proxy 全程在线，
    与"ECS 整机宕机切真服兜底"互斥，全部回滚为 ECS 单点：

    1) LOCAL_TCP_LIST[group_id] 大厅块：in-place 把真服 47.96.101.155:5748/5749
       改写为 ECS:5748/5749，块里**不再含真服**。
    2) **注入** LOCAL_TCP_LIST_50[group_id]=ECS——让 NetEngine.getTcpConnectInfoByGroupId
       的 `_50` 分支命中 `return list[1]`，**确定性返回 ECS、跳过 getSRSConfigListFromFile
       的 srslist 缓存混入与 math.random**（见 06-19-noconfig-ecs-intermittent-routing
       实机根因：srslist{5045}.json 把真服条目追加进 list，random 会抽中真服绕过 ECS，
       表现为"重进几次才连上 ECS"）。
    3) LOCAL_TCP_LIST_50[5067/5167] 金币游服：改写为单项 list[1] = ECS:ecs_listen_port，
       由 ECS 代理转发到原真服 7777，块里**不再含真服**。
    """
    source = unwrap_luac(raw_luac, key)
    new_source, n = _patch_taizhou_block(source, ecs_ip, group_id, real_ip)
    if n == 0:
        # 已 in-place 改写过则视为幂等成功（块里已只含 ecs_ip、不含 real_ip）
        if ecs_ip not in source:
            raise ValueError(
                f"未在 LOCAL_TCP_LIST[{group_id}] 块中找到真服 IP {real_ip}，"
                "请确认 NetConf 结构或 group_id"
            )
    # 注入 LOCAL_TCP_LIST_50[group_id]=ECS：钉死 _50 分支，跳过 srslist 随机污染。
    new_source, ninj = _inject_srs50_block(new_source, ecs_ip, group_id, TAIZHOU_LOBBY_PORTS)
    logger.info("[netconf] _50 注入 [5045]=ECS x%d -> %s", ninj, ecs_ip)
    # 把 _50 里硬编码真服游服（金币局 5067/5167）改成 ECS 单点单条。
    new_source, nrs = _patch_srs50_realservers(new_source, ecs_ip)
    logger.info("[netconf] _50 真服游服改写 %d 个 -> ECS 单点 %s", nrs, ecs_ip)
    new_luac = wrap_luac(new_source, key)

    # 往返校验：解密新 luac 必须等于我们写入的源码（容忍末尾 4 字节对齐补的 \n）
    roundtrip = unwrap_luac(new_luac, key)
    if roundtrip.rstrip("\n") != new_source.rstrip("\n"):
        raise AssertionError("XXTEA 往返校验失败：解密新 luac 与改写源码不一致")
    ecs_block = _extract_block(roundtrip, group_id, prefer_ip=ecs_ip)
    # 降级形态：块里**只含 ECS、不含真服**
    if real_ip in ecs_block:
        raise AssertionError(
            f"改写后 {group_id} 块仍含真服 IP {real_ip}（降级形态要求 ECS 单点）"
        )
    if ecs_ip not in ecs_block:
        raise AssertionError(f"改写后 {group_id} 块未含 ECS IP")
    # 校验：LOCAL_TCP_LIST_50[group_id] **必须**存在且只含 ECS（钉死 _50 分支，跳过 srslist 随机）
    m50 = re.search(r"LOCAL_TCP_LIST_50\s*=\s*\{", roundtrip)
    if not m50:
        raise AssertionError("LOCAL_TCP_LIST_50 表缺失，无法注入 [group_id]=ECS")
    # 取 _50 表整体范围（花括号配平），仅在表内检查
    brace = roundtrip.find("{", m50.start())
    depth = 0
    j = brace
    while j < len(roundtrip):
        if roundtrip[j] == "{":
            depth += 1
        elif roundtrip[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    seg = roundtrip[brace:j + 1]
    # [group_id] 必须存在
    mblk = re.search(r"\[\s*%d\s*\]\s*=\s*\{" % group_id, seg)
    if not mblk:
        raise AssertionError(
            f"LOCAL_TCP_LIST_50[{group_id}] 未注入（_50 分支不会命中，仍走 srslist 随机）"
        )
    # 校验 [group_id] 块只含 ECS、不含真服
    sub_brace = seg.find("{", mblk.end() - 1)
    d = 0
    k = sub_brace
    while k < len(seg):
        c = seg[k]
        if c == "{":
            d += 1
        elif c == "}":
            d -= 1
            if d == 0:
                break
        k += 1
    g_block = seg[sub_brace:k + 1]
    if ecs_ip not in g_block:
        raise AssertionError(f"LOCAL_TCP_LIST_50[{group_id}] 必须含 ECS")
    if real_ip in g_block:
        raise AssertionError(
            f"LOCAL_TCP_LIST_50[{group_id}] 不应含真服 {real_ip}（必须 ECS 单点）"
        )
    # 校验：5067/5167 列表只含 ECS、不含真服
    for gid, (real_host, _real_port, _ecs_port) in SRS50_REMAP.items():
        mblk = re.search(r"\[\s*%d\s*\]\s*=\s*\{" % gid, seg)
        if not mblk:
            continue
        sub_brace = seg.find("{", mblk.end() - 1)
        d = 0
        k = sub_brace
        while k < len(seg):
            c = seg[k]
            if c == "{":
                d += 1
            elif c == "}":
                d -= 1
                if d == 0:
                    break
            k += 1
        block_body = seg[sub_brace:k + 1]
        if ecs_ip not in block_body:
            raise AssertionError(
                f"LOCAL_TCP_LIST_50[{gid}] 必须含 ECS"
            )
        if real_host in block_body:
            raise AssertionError(
                f"LOCAL_TCP_LIST_50[{gid}] 不应再含真服 {real_host}（降级形态：ECS 单点）"
            )
    logger.info("[netconf] patched (ECS-only): LOCAL_TCP_LIST[%d] in-place x%d + _50 注入x%d + _50 真服游服x%d -> %s",
                group_id, n, ninj, nrs, ecs_ip)

    return PatchResult(source, new_source, n + ninj + nrs, new_luac)


def _extract_block(source: str, group_id: int, prefer_ip: str | None = None) -> str:
    """返回 [group_id] 表块体（花括号配平，含嵌套 {id=...} 条目）。

    prefer_ip 给定时，优先返回**包含该 IP** 的块；否则返回**第一个非注释**块
    （注释块以 -- 开头）。注释块虽然也会被语法上找到，但通常 IP 与现行真服不同。
    """
    out = []
    for m in re.finditer(r"\[\s*%d\s*\]\s*=\s*" % group_id, source):
        # 跳过整行被 `--` 注释掉的块
        line_start = source.rfind("\n", 0, m.start()) + 1
        line_prefix = source[line_start:m.start()]
        if line_prefix.lstrip().startswith("--"):
            continue
        brace = source.find("{", m.end())
        if brace < 0:
            continue
        depth = 0
        i = brace
        while i < len(source):
            c = source[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = source[brace + 1:i]
        out.append(body)
    if prefer_ip is not None:
        for body in out:
            if prefer_ip in body:
                return body
    return out[0] if out else ""


def patch_from_file(luac_path: str, ecs_ip: str, **kw) -> PatchResult:
    with open(luac_path, "rb") as f:
        raw = f.read()
    return patch_netconf(raw, ecs_ip, **kw)


def patch_from_apk(apk_path: str, ecs_ip: str, **kw) -> PatchResult:
    with zipfile.ZipFile(apk_path) as z:
        raw = z.read(APK_NETCONF_ENTRY)
    return patch_netconf(raw, ecs_ip, **kw)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="解密/改写/重加密 NetConf.luac，把台州 5045 指向 ECS")
    ap.add_argument("--apk", required=True, help="原始游戏 APK 路径")
    ap.add_argument("--ecs-ip", required=True, help="ECS 公网 IP（替换真服大厅 IP）")
    ap.add_argument("--out", required=True, help="输出的新 NetConf.luac 路径")
    ap.add_argument("--group-id", type=int, default=TAIZHOU_GROUP_ID)
    ap.add_argument("--real-ip", default=REAL_LOBBY_IP)
    ap.add_argument("--dump-source", help="可选：把改写后的源码也写到此路径，便于核对")
    args = ap.parse_args()

    res = patch_from_apk(args.apk, args.ecs_ip, group_id=args.group_id, real_ip=args.real_ip)
    with open(args.out, "wb") as f:
        f.write(res.new_luac)
    if args.dump_source:
        with open(args.dump_source, "w", encoding="utf-8") as f:
            f.write(res.source_after)

    print(f"[OK] 替换 {res.replacements} 处 {args.real_ip} -> {args.ecs_ip}（仅 [{args.group_id}] 块）")
    print(f"[OK] 新 NetConf.luac 写入 {args.out}（{len(res.new_luac)} 字节）")
    print(f"[OK] 台州块: {_extract_block(res.source_after, args.group_id).strip()[:160]}")


if __name__ == "__main__":
    main()
