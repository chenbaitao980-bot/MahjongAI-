"""test_win_dns_divert.py — Windows WinDivert DNS 劫持的纯逻辑自测（不碰 pydivert）。

只验"收回到 windows 包"后的 DNS 解析/应答构造与源过滤逻辑仍正确，
pydivert/WinDivert 驱动相关只能在 Windows 管理员真机验，不入单测。

运行:
  cd apps/router_runtime
  python -m pytest tests/ -v
"""
from __future__ import annotations

import os
import socket
import sys

_RUNTIME_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNTIME_ROOT not in sys.path:
    sys.path.insert(0, _RUNTIME_ROOT)

from mahjong_mitm.setup_mitm import HIJACK_DOMAINS, _build_dns_query
from windows.win_dns_divert import DnsDivert, build_a_response, parse_qname


def test_parse_qname_roundtrip():
    q = _build_dns_query("gxb-oss.hzxuanming.com")
    name, _ = parse_qname(q)
    assert name == "gxb-oss.hzxuanming.com"


def test_build_a_response_points_to_self_ip():
    q = _build_dns_query("gxb-api.hzxuanming.com")
    resp = build_a_response(q, "192.168.137.1")
    # 末 4 字节 = rdata = A 记录 IP
    assert socket.inet_ntoa(resp[-4:]) == "192.168.137.1"
    # 同一 tid（前 2 字节）回带，问题区保留
    assert resp[:2] == q[:2]


def test_hijack_domains_shared_with_kernel():
    # 收回后仍复用内核同一份劫持域名集合（避免两处漂移）
    d = DnsDivert("192.168.137.1")
    assert d.hijack == {x.lower() for x in HIJACK_DOMAINS}


def test_phone_src_filter_dynamic_subnet():
    """默认按热点网段自动识别手机；PC 本机(self_ip)与网段外源放行。"""
    d = DnsDivert("192.168.137.1")
    assert d._is_phone_src("192.168.137.42") is True   # 热点内手机
    assert d._is_phone_src("192.168.137.1") is False   # PC 本机不劫持
    assert d._is_phone_src("8.8.8.8") is False          # 网段外（PC 回源查询）放行


def test_phone_src_filter_explicit_phone_ip():
    """显式 phone_ip 时只认它（向后兼容）。"""
    d = DnsDivert("192.168.137.1", phone_ip="192.168.137.99")
    assert d._is_phone_src("192.168.137.99") is True
    assert d._is_phone_src("192.168.137.42") is False
