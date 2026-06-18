"""dns_divert.py — WinDivert 网络层 DNS 劫持（突破游戏硬编码公共 DNS）。

背景（见 .trellis/tasks/06-14-noconfig-netconf-respsrsaddr/research/diagnosis-2026-06-14.md）:
  游戏客户端把热更域名 gxb-api.hzxuanming.com 的 DNS 查询**硬编码**发往公共 DNS
  119.29.29.29 / 223.5.5.5，绕过 PC 热点 DHCP 下发的 DNS。setup_mitm 的 DnsResponder
  (绑 PC:53) 因此永远收不到游戏的热更查询 → 热更链路从未生效。

方案:
  手机经 PC 热点上网，其**所有** DNS 查询（含发往 119.29.29.29:53 的）必经 PC 网关转发。
  用 WinDivert 拦截转发路径上的 UDP:53：
    - qname 命中 HIJACK_DOMAINS → 就地伪造 A 响应指向 PC（self_ip），注入回手机，丢弃原查询。
    - 其余查询原样放行（不影响手机正常上网）。
  这样无论游戏把查询发给谁，gxb-* 都会被解析到 PC → 落到 setup_mitm 的 443 热更服务。

前提:
  - pip install pydivert；以管理员权限运行（WinDivert 驱动）。
  - 与 setup_mitm（443 + 可选 DnsResponder）配合：dns_divert 负责"抢"硬编码 DNS 的查询，
    setup_mitm 的 443 负责回热更内容。二者 self_ip 一致（PC 热点 IP）。

隔离: 全新文件；复用 setup_mitm.HIJACK_DOMAINS（不改其源码）。
"""
from __future__ import annotations

import argparse
import ipaddress
import logging
import os
import socket
import struct
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from remote.noconfig.hijack.setup_mitm import HIJACK_DOMAINS

logger = logging.getLogger("remote.noconfig.hijack.dns_divert")


# ─── DNS 解析 / 响应构造（与 setup_mitm.DnsResponder 同规则）──────────────────

def parse_qname(dns: bytes) -> tuple[str, int]:
    """解析 DNS question 的 qname，返回 (name_lower, offset_after_question)。"""
    off = 12  # header
    labels = []
    while True:
        length = dns[off]; off += 1
        if length == 0:
            break
        labels.append(dns[off:off + length].decode("ascii", errors="replace"))
        off += length
    name = ".".join(labels)
    off += 4  # qtype(2) + qclass(2)
    return name.lower(), off


def build_a_response(query: bytes, ip: str) -> bytes:
    """基于原 query 构造一条 A 记录响应，answer 指向 ip。"""
    name, qend = parse_qname(query)
    tid = query[:2]
    flags = b"\x81\x80"            # response, recursion available, no error
    counts = b"\x00\x01\x00\x01\x00\x00\x00\x00"  # qd=1 an=1 ns=0 ar=0
    header = tid + flags + counts
    question = query[12:qend]
    answer = (
        b"\xc0\x0c"               # name pointer to question
        + b"\x00\x01"             # type A
        + b"\x00\x01"             # class IN
        + b"\x00\x00\x00\x3c"     # TTL 60s
        + b"\x00\x04"             # rdlength 4
        + socket.inet_aton(ip)
    )
    return header + question + answer


# ─── WinDivert 拦截器 ────────────────────────────────────────────────────────

class DnsDivert:
    """拦截手机转发的 UDP:53，劫持 HIJACK_DOMAINS → self_ip，其余放行。"""

    def __init__(self, self_ip: str, hijack_domains=None, phone_ip: str | None = None,
                 hotspot_cidr: str | None = None):
        self.self_ip = self_ip
        self.hijack = {d.lower() for d in (hijack_domains or HIJACK_DOMAINS)}
        self.phone_ip = phone_ip            # 可选：显式只劫持该手机 IP（优先级最高，向后兼容）
        # 动态识别：默认劫持"热点网段内、非本机"的任意源，手机 IP 变了也自动适配。
        # 从 self_ip 推 /24（192.168.137.1 → 192.168.137.0/24），可用 hotspot_cidr 覆盖。
        self.hotspot_net = ipaddress.ip_network(hotspot_cidr or f"{self_ip}/24", strict=False)
        self._running = False
        self._hits = 0
        self._seen_phones: set[str] = set()  # 已劫持过的手机 IP（仅用于日志可视化）

    def run(self) -> None:
        import pydivert
        # 只看转发出去的 DNS 查询（outbound）。本机自身查询也会匹配，但 qname 不命中即放行。
        flt = "udp.DstPort == 53 and outbound"
        scope = (f"仅手机 {self.phone_ip}" if self.phone_ip
                 else f"热点网段 {self.hotspot_net}（自动识别任意手机）")
        logger.info("DnsDivert 启动: filter=%r 劫持 %s -> %s  范围: %s",
                    flt, sorted(self.hijack), self.self_ip, scope)
        self._running = True
        with pydivert.WinDivert(flt) as w:
            for pkt in w:
                if not self._running:
                    break
                try:
                    self._handle(w, pkt)
                except Exception as e:
                    logger.debug("handle error (放行兜底): %s", e)
                    try:
                        w.send(pkt)
                    except Exception:
                        pass

    def stop(self) -> None:
        self._running = False

    def _is_phone_src(self, src: str) -> bool:
        """判断 DNS 查询源是否为手机（需劫持）。

        - 显式 phone_ip：只认它（向后兼容）。
        - 否则：源在热点网段内、且不是 PC 本机(self_ip) → 视为手机（动态适配任意 IP）。
        PC 自身回源查询（主网卡 IP，不在热点网段）一律放行，保证 setup_mitm 回源不被自劫持。
        """
        if self.phone_ip:
            return src == self.phone_ip
        if src == self.self_ip:
            return False
        try:
            return ipaddress.ip_address(src) in self.hotspot_net
        except ValueError:
            return False

    def _handle(self, w, pkt) -> None:
        payload = pkt.payload
        if not payload or len(payload) < 13:
            w.send(pkt); return
        # 源过滤：只劫持手机的查询，放行 PC 自身回源查询（setup_mitm 用 119.29.29.29 回源）。
        if not self._is_phone_src(pkt.src_addr):
            w.send(pkt); return
        try:
            name, _ = parse_qname(payload)
        except Exception:
            w.send(pkt); return

        if name not in self.hijack:
            w.send(pkt)  # 非目标域名，原样放行
            return

        # 命中：伪造 A 响应，交换 src/dst + 端口，反转方向，注入回手机
        resp = build_a_response(payload, self.self_ip)
        src_addr, dst_addr = pkt.src_addr, pkt.dst_addr
        src_port, dst_port = pkt.src_port, pkt.dst_port
        pkt.src_addr, pkt.dst_addr = dst_addr, src_addr     # 响应来自"被查询的 DNS 服务器"
        pkt.src_port, pkt.dst_port = dst_port, src_port
        pkt.direction = 1  # INBOUND：注入回内网（手机）方向
        pkt.payload = resp
        w.send(pkt, recalculate_checksum=True)
        self._hits += 1
        if src_addr not in self._seen_phones:
            self._seen_phones.add(src_addr)
            logger.info("[divert] 新手机上线: %s（自动识别）", src_addr)
        logger.info("[divert] %s (asked %s) from %s -> %s  [hit#%d]",
                    name, dst_addr, src_addr, self.self_ip, self._hits)


# ─── 入口 ────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="WinDivert DNS 劫持 — 突破游戏硬编码公共 DNS，把热更域名劫持到 PC")
    ap.add_argument("--self-ip", required=True,
                    help="PC 热点 IP（热更域名解析到它，须与 setup_mitm 一致，如 192.168.137.1）")
    ap.add_argument("--phone-ip", default=None,
                    help="显式只劫持该手机 IP（默认按热点网段自动识别任意手机，IP 变了也适配）")
    ap.add_argument("--hotspot-cidr", default=None,
                    help="热点网段（默认从 --self-ip 推 /24，如 192.168.137.0/24）")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    d = DnsDivert(args.self_ip, phone_ip=args.phone_ip, hotspot_cidr=args.hotspot_cidr)
    try:
        d.run()
    except KeyboardInterrupt:
        d.stop()
        print(f"\n停止。累计劫持 {d._hits} 次。")


if __name__ == "__main__":
    main()
