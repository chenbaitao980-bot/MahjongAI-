#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_official_tiles.py — 抓取浙江游戏大厅官方台州麻将牌面，切成 34 张 {tile}.png。

一键复跑：

    python scripts/fetch_official_tiles.py

链路（公网 curl 直接可下，无需 MITM）：

    1. GET hotfix_update?appid=1233&engine_ver=3.13&channel=7109&version=1.0.0.0
         -> manifest_url  (oss / cos 双源)
    2. GET manifest_url   -> file_list（md5 分桶存储名）+ file_url 基址
         file_list 含两条：
           res/mahface/7109/mahlayer_mah_face_2.plist
           res/mahface/7109/mahlayer_mah_face_2.png
    3. GET file_url + name -> 原样字节，按 file_list[*].md5 校验
    4. 解析 plist 图集 -> 按 nibble 帧号映射 -> 切 34 张 140x158 牌面
         frame 号 = nibble 十六进制的十进制值：
           0x11-0x19 (17-25) = 1-9 万(m)
           0x21-0x29 (33-41) = 1-9 条(s)   <-- 已按真机牌面像素核对(非筒)
           0x31-0x39 (49-57) = 1-9 筒(p)
           0x41-0x44 (65-68) = 东南西北 (1-4z)
           0x51-0x53 (81-83) = 中发白 (5-7z)
           0x6x (97+)        = 花牌/财神，跳过
         rotated:true 的帧在图集里旋转存放，crop 后 rotate(90, expand) 还原
         （一在上、萬在下，与真机牌面方向一致）。
    5. 输出 34 张 {tile}.png 到 remote/relay/static/tiles/（保留透明通道）。

牌面台州套（areaid 7109，GlobalDefine.lua:169，独立皮肤）。前端 tileEl() 已是
<img src="tiles/{n}{suit}.png">，替换图片即可，零代码改动。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import urllib.request
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("缺少 Pillow：pip install Pillow")

# ---------------------------------------------------------------------------
# 热更端点（默认台州 7109）
# ---------------------------------------------------------------------------
HOTFIX_BASE = "https://gxb-api.imeete.com/hotfix_update"
DEFAULT_APPID = 1233
DEFAULT_ENGINE_VER = "3.13"
DEFAULT_CHANNEL = "7109"           # 台州麻将牌面套
DEFAULT_QUERY_VERSION = "1.0.0.0"  # 起查版本，服务器回当前最新
USER_AGENT = "Mozilla/5.0 (fetch_official_tiles)"
HTTP_TIMEOUT = 30

# file_list 里要抓的两条目标（plist 图集 + 贴图）
PLIST_KEY = "res/mahface/{channel}/mahlayer_mah_face_2.plist"
PNG_KEY = "res/mahface/{channel}/mahlayer_mah_face_2.png"

# 默认输出目录（noconfig web 后台读牌网页的牌面资源）
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "remote" / "relay" / "static" / "tiles"

EXPECTED_TILE_SIZE = (140, 158)


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def _http_get_multi(urls: list[str], *, expect_md5: str | None = None) -> bytes:
    """oss / cos 双源依次尝试，可选 md5 校验。"""
    last_err: Exception | None = None
    for url in urls:
        try:
            data = _http_get(url)
        except Exception as exc:  # noqa: BLE001 — 换下一个源
            last_err = exc
            print(f"  ! 源失败 {url}: {exc}")
            continue
        if expect_md5:
            got = hashlib.md5(data).hexdigest()
            if got != expect_md5:
                last_err = ValueError(f"md5 不匹配 got={got} want={expect_md5}")
                print(f"  ! md5 校验失败 {url}: {last_err}")
                continue
        print(f"  + {url}  ({len(data)} bytes, md5 ok)")
        return data
    raise RuntimeError(f"全部源失败: {last_err}")


def fetch_manifest(appid: int, engine_ver: str, channel: str, query_version: str) -> dict:
    """走 hotfix_update -> manifest_url -> 返回完整 manifest dict。"""
    hotfix_url = (
        f"{HOTFIX_BASE}?env=1&appid={appid}&engine_ver={engine_ver}"
        f"&channel={channel}&version={query_version}"
    )
    print(f"[1] hotfix_update: {hotfix_url}")
    hotfix = json.loads(_http_get(hotfix_url).decode("utf-8"))
    manifest_urls = hotfix.get("manifest_url") or []
    if not manifest_urls:
        raise RuntimeError(f"hotfix_update 无 manifest_url: {hotfix}")
    print(f"    最新版本 {hotfix.get('version')}, manifest 源 {len(manifest_urls)} 个")
    print("[2] manifest")
    manifest = json.loads(_http_get_multi(manifest_urls).decode("utf-8"))
    return manifest


def download_atlas(manifest: dict, channel: str) -> tuple[bytes, bytes]:
    """从 manifest.file_list 取 plist + png（md5 校验）。返回 (plist_bytes, png_bytes)。"""
    file_list = manifest.get("file_list")
    file_url = manifest.get("file_url") or []
    if not isinstance(file_list, dict) or not file_url:
        raise RuntimeError("manifest 缺少 file_list / file_url")

    plist_key = PLIST_KEY.format(channel=channel)
    png_key = PNG_KEY.format(channel=channel)
    for key in (plist_key, png_key):
        if key not in file_list:
            raise RuntimeError(f"file_list 缺少 {key}（实际键: {list(file_list)}）")

    print("[3] download atlas")
    out: list[bytes] = []
    for key in (plist_key, png_key):
        entry = file_list[key]
        name = entry["name"]
        md5 = entry.get("md5")
        urls = [base.rstrip("/") + "/" + name for base in file_url]
        print(f"  {key} -> {name} ({entry.get('size')} bytes)")
        out.append(_http_get_multi(urls, expect_md5=md5))
    return out[0], out[1]


# ---------------------------------------------------------------------------
# plist 图集解析 + 切图
# ---------------------------------------------------------------------------
_PAIR_RE = re.compile(r"\{\s*\{(-?\d+)\s*,\s*(-?\d+)\}\s*,\s*\{(-?\d+)\s*,\s*(-?\d+)\}\s*\}")
_FRAME_NUM_RE = re.compile(r"_(\d+)\.png$")


def parse_plist_frames(plist_bytes: bytes) -> dict[str, dict]:
    """解析 cocos plist 图集，返回 {frame_name: {frame:(x,y,w,h), rotated:bool}}。

    只用 stdlib plistlib，避免额外依赖。
    """
    import plistlib

    root = plistlib.loads(plist_bytes)
    frames_raw = root.get("frames", {})
    result: dict[str, dict] = {}
    for fname, meta in frames_raw.items():
        frame_str = meta.get("frame", "")
        m = _PAIR_RE.search(frame_str)
        if not m:
            continue
        x, y, w, h = (int(v) for v in m.groups())
        result[fname] = {
            "frame": (x, y, w, h),
            "rotated": bool(meta.get("rotated", False)),
        }
    return result


def _frame_num_to_tile(num: int) -> str | None:
    """nibble 帧号 -> tile 字符串。非 34 标准牌（花/财神）返回 None。"""
    hi, lo = num >> 4, num & 0xF
    if hi == 1 and 1 <= lo <= 9:
        return f"{lo}m"
    if hi == 2 and 1 <= lo <= 9:       # 0x2x = 条(s)，已按真机牌面像素核对
        return f"{lo}s"
    if hi == 3 and 1 <= lo <= 9:       # 0x3x = 筒(p)
        return f"{lo}p"
    if hi == 4 and 1 <= lo <= 4:       # 东南西北
        return f"{lo}z"
    if hi == 5 and 1 <= lo <= 3:       # 中发白 -> 5z 6z 7z
        return f"{lo + 4}z"
    return None  # 0x6x 花牌/财神等


def slice_tiles(plist_bytes: bytes, png_bytes: bytes) -> dict[str, Image.Image]:
    """切出 {tile: PIL.Image}，统一 140x158 RGBA，rotated 帧已还原。"""
    frames = parse_plist_frames(plist_bytes)
    atlas = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    tiles: dict[str, Image.Image] = {}
    for fname, info in frames.items():
        m = _FRAME_NUM_RE.search(fname)
        if not m:
            continue
        tile = _frame_num_to_tile(int(m.group(1)))
        if tile is None:
            continue
        x, y, w, h = info["frame"]
        if info["rotated"]:
            # 图集里旋转存放：占位区域宽高互换，crop 后 rotate(90) 还原成 w×h
            # （正确方向：一在上、萬在下，与真机牌面一致）。
            box = (x, y, x + h, y + w)
            img = atlas.crop(box).rotate(90, expand=True)
        else:
            box = (x, y, x + w, y + h)
            img = atlas.crop(box)
        tiles[tile] = img
    return tiles


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
ALL_34 = (
    [f"{n}{s}" for s in "mps" for n in range(1, 10)] + [f"{n}z" for n in range(1, 8)]
)


def main() -> int:
    ap = argparse.ArgumentParser(description="抓取官方台州麻将牌面切成 34 张 PNG")
    ap.add_argument("--channel", default=DEFAULT_CHANNEL, help="MahFace areaid (默认 7109 台州)")
    ap.add_argument("--appid", type=int, default=DEFAULT_APPID)
    ap.add_argument("--engine-ver", default=DEFAULT_ENGINE_VER)
    ap.add_argument("--query-version", default=DEFAULT_QUERY_VERSION)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="输出目录")
    ap.add_argument("--dry-run", action="store_true", help="只切图不写盘，打印校验结果")
    args = ap.parse_args()

    manifest = fetch_manifest(args.appid, args.engine_ver, args.channel, args.query_version)
    plist_bytes, png_bytes = download_atlas(manifest, args.channel)

    print("[4] slice")
    tiles = slice_tiles(plist_bytes, png_bytes)

    # 完整性 + 尺寸校验
    missing = [t for t in ALL_34 if t not in tiles]
    if missing:
        print(f"  ! 缺失牌面: {missing}")
        return 2
    bad_size = [t for t in ALL_34 if tiles[t].size != EXPECTED_TILE_SIZE]
    if bad_size:
        print(f"  ! 尺寸异常 (应 {EXPECTED_TILE_SIZE}): "
              + ", ".join(f"{t}={tiles[t].size}" for t in bad_size))
        return 2
    print(f"  + 34 张牌面齐全，统一 {EXPECTED_TILE_SIZE}")

    if args.dry_run:
        print("[dry-run] 不写盘")
        return 0

    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[5] write -> {out_dir}")
    for tile in ALL_34:
        tiles[tile].save(out_dir / f"{tile}.png")
    print(f"  + 写入 {len(ALL_34)} 张")
    print("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
