"""test_netconf_patch.py — NetConf XXTEA 往返 + manifest 改写自测。

这是抽取后包的核心正确性保证：NetConf 解密改 IP 再加密必须字节级可逆，
否则手机热更下来的 NetConf 加载失败。复用 setup_mitm._selftest 的全链路断言。

运行:
  cd interface
  python -m pytest tests/ -v
  # 或直接: python -m mahjong_mitm --selftest
"""
from __future__ import annotations

import os
import sys

import pytest

_RUNTIME_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNTIME_ROOT not in sys.path:
    sys.path.insert(0, _RUNTIME_ROOT)

from mahjong_mitm.netconf_patch import (
    KEY,
    SIGN,
    patch_from_apk,
    unwrap_luac,
    wrap_luac,
    xxtea_decrypt,
    xxtea_encrypt,
)

_APK = os.path.join(_RUNTIME_ROOT, "assets", "game_base.apk")
_has_apk = os.path.isfile(_APK)


def test_xxtea_roundtrip():
    """XXTEA 加密→解密 字节级可逆（4 字节对齐明文——XXTEA inc=False 不存长度，
    真实 luac 密文均 4 字节对齐；非对齐输入不在契约内）。"""
    for plaintext in [b"abcd", b"a" * 8, b"a" * 100, b"x" * 256]:
        assert len(plaintext) % 4 == 0, "test input must be 4-byte aligned"
        enc = xxtea_encrypt(plaintext, KEY)
        dec = xxtea_decrypt(enc, KEY)
        assert dec == plaintext, (plaintext, dec)


def test_luac_wrap_roundtrip():
    """wrap_luac(SIGN+XXTEA) → unwrap_luac 还原源码。"""
    source = 'return {LOCAL_TCP_LIST = {[5045] = "1.2.3.4"}}'
    luac = wrap_luac(source, KEY)
    assert luac[: len(SIGN)] == SIGN, luac[: len(SIGN)]
    recovered = unwrap_luac(luac, KEY)
    assert recovered == source, recovered


@pytest.mark.skipif(not _has_apk, reason="assets/game_base.apk 不存在")
def test_patch_from_apk_points_to_ecs():
    """从 APK 取 NetConf → 改 5045 指向 ECS → 解密验证 IP 已替换、SIGN 完好。"""
    ecs_ip = "8.136.37.136"
    res = patch_from_apk(_APK, ecs_ip)
    assert res.new_luac[: len(SIGN)] == SIGN
    plaintext = unwrap_luac(res.new_luac, KEY)
    assert ecs_ip in plaintext, "ECS IP 未写入 NetConf 明文"


@pytest.mark.skipif(not _has_apk, reason="assets/game_base.apk 不存在")
def test_full_selftest_passes():
    """跑 setup_mitm 全链路离线自测（version/project manifest + DNS + 文件下载）。"""
    from mahjong_mitm.setup_mitm import _selftest
    _selftest()  # 内部全是 assert，抛异常即 fail
