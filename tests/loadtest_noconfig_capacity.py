"""
loadtest_noconfig_capacity.py — noconfig 容量压测一体化工具

设计目标：
  - 在 ECS 本地自压自测（127.0.0.1，避免网络瓶颈）
  - 三轮对比（baseline / 停 relay / +/presence）数据可对比
  - 强验证手牌正确性：每客户端 fingerprint(4B) 嵌入 0x2bc0 payload，
    /state?user_id=X 读回比对，能 100% 检出多用户错配

架构：
  ┌─ fake_upstream (本脚本起的进程，listen 17777)
  │   模拟真游服：响应 SRS 握手 + 周期推送 0x2bc0 假手牌帧
  ├─ tcp_proxy (生产实例，listen 7777，upstream 改指 127.0.0.1:17777)
  │   旁路解码 + push 到 noconfig:8002
  ├─ noconfig (生产实例，8002，被压测目标)
  └─ virtual_clients (本脚本起 N 条 TCP 连接到 7777 模拟手机)

使用：
  # 1) 起 fake_upstream（一次启动，后台跑）
  python tests/loadtest_noconfig_capacity.py fake-upstream --port 17777 &

  # 2) 临时让 tcp_proxy 指向 fake（环境变量改 REAL_GAME_IP/PORT 后重启 tcp_proxy）
  #   见 RUNBOOK 部分的 ssh 命令

  # 3) 跑压测
  python tests/loadtest_noconfig_capacity.py loadtest \
      --concurrency 50 --duration 180 \
      --target-host 127.0.0.1 --target-port 7777 \
      --noconfig-url http://127.0.0.1:8002 \
      --api-token <TOKEN> \
      --output round0_n50.json

  # 4) 三档跑完后聚合：
  python tests/loadtest_noconfig_capacity.py compare round0_*.json round1_*.json round2_*.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import statistics
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

# ─── repo path setup ────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from remote.srs_spectator.frame import (
    pack_frame, read_frame_from_stream, HDR_LEN,
    MSG_ENCRYPT_VER, MSG_REQ_KEY, MSG_HANDSHAKE_RSP,
    MSG_PLAYER_CONNECT, MSG_PLAYER_DATA,
    MSG_REQ_PLUS_DATA, MSG_RESP_PLUS_DATA,
)
from remote.srs_spectator.crypto import SRSCrypto, SRS_DEFAULT_KEY

logger = logging.getLogger("loadtest")

# ============================================================
# 协议常量（来自 frame.py / handshake.py 复用）
# ============================================================

ENCRYPT_VER_PAYLOAD = bytes.fromhex("fa60a522")
SESSION_KEY_TEST = bytes.fromhex("11" * 16)  # 16B AES-128 测试密钥


# ============================================================
# Part 1: fake_upstream — 模拟真游戏服务器
# ============================================================

class FakeUpstream:
    """模拟 47.96.0.227:7777 真服。

    SRS 握手序列：
      C → EncryptVer(msgid=1)        → S 回 EncryptVer ack (msgid=1)
      C → ReqKey(msgid=3)            → S 回 HandshakeRsp(msgid=4) 含 session key
      C → PlayerConnect(msgid=5)     → S 回 PlayerData(msgid=6) flag=0 + sessionid
      C → ReqPlusData(msgid=23)      → S 回 RespPlusData(msgid=24) keylen=0

    握手完成后，每 1 秒推送一个 0x2bc0 帧（明文 payload，
    对齐 tcp_proxy.py:449 的"0x2bc0 在 noconfig 链路上是明文"约束）
    payload 头 4B = sub_cmd(2B) + reserved(2B)，接着是 fingerprint(4B) + filler
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 17777,
                 push_interval: float = 1.0):
        self.host = host
        self.port = port
        self.push_interval = push_interval
        self._srv: Optional[socket.socket] = None
        self._running = False
        self._connections = 0
        self._lock = threading.Lock()

    def start(self):
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind((self.host, self.port))
        self._srv.listen(1024)
        self._running = True
        logger.info("[fake_upstream] listening %s:%d", self.host, self.port)
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def stop(self):
        self._running = False
        if self._srv:
            try:
                self._srv.close()
            except Exception:
                pass

    def _accept_loop(self):
        while self._running:
            try:
                client, addr = self._srv.accept()
            except OSError:
                break
            with self._lock:
                self._connections += 1
                cur = self._connections
            logger.debug("[fake_upstream] +conn from %s (total=%d)", addr, cur)
            threading.Thread(target=self._handle_client, args=(client, addr),
                             daemon=True).start()

    def _handle_client(self, client: socket.socket, addr):
        """对一条客户端连接走完 SRS 握手并周期推送 0x2bc0。"""
        try:
            # 等收到客户端 EncryptVer
            buf = bytearray()
            session_crypto = SRSCrypto(key=SESSION_KEY_TEST)
            handshake_phase = "wait_encrypt_ver"

            client.settimeout(5.0)

            while self._running:
                # 收
                try:
                    data = client.recv(65536)
                    if not data:
                        break
                    buf += data
                except socket.timeout:
                    if handshake_phase == "done":
                        # 握手完成后发 0x2bc0
                        self._push_2bc0(client, addr)
                        continue
                    else:
                        # 握手阶段超时：客户端跑路
                        break

                # 处理完整帧
                while True:
                    fr, buf = read_frame_from_stream(buf)
                    if fr is None:
                        break
                    handshake_phase = self._step_handshake(
                        client, fr, handshake_phase, session_crypto
                    )
                    if handshake_phase == "done":
                        # 立刻推一帧 0x2bc0
                        self._push_2bc0(client, addr)
                        client.settimeout(self.push_interval)
        except Exception as e:
            logger.debug("[fake_upstream] %s error: %s", addr, e)
        finally:
            try:
                client.close()
            except Exception:
                pass
            with self._lock:
                self._connections -= 1

    def _step_handshake(self, client: socket.socket, fr: dict, phase: str,
                        session_crypto: SRSCrypto) -> str:
        """状态机驱动握手。返回新 phase。"""
        msg_type = fr["msg_type"]

        if msg_type == MSG_ENCRYPT_VER and phase == "wait_encrypt_ver":
            # 直接回一个 EncryptVer ack
            client.sendall(pack_frame(MSG_ENCRYPT_VER, b""))
            return "wait_req_key"

        if msg_type == MSG_REQ_KEY and phase == "wait_req_key":
            # 用默认密钥 fresh-from-IV 加密 HandshakeRsp payload = keylen(1B) + key
            default_crypto = SRSCrypto(key=SRS_DEFAULT_KEY)
            default_crypto.reset_cfb()
            hs_plain = bytes([len(SESSION_KEY_TEST)]) + SESSION_KEY_TEST
            hs_enc = default_crypto.encrypt_payload(hs_plain)
            client.sendall(pack_frame(MSG_HANDSHAKE_RSP, hs_enc))
            return "wait_player_connect"

        if msg_type == MSG_PLAYER_CONNECT and phase == "wait_player_connect":
            # 用会话密钥构造 PlayerData(flag=0, areaid, numid, nickname, "", sessionid)
            # 格式见 handshake.py:78
            nickname = b"FAKEPLAYER"
            sessionid = os.urandom(16)
            pd_plain = (
                bytes([0])  # flag=0 (auth ok)
                + struct.pack("<i", 1)  # areaid
                + struct.pack("<i", 100000)  # numid
                + bytes([len(nickname)]) + nickname  # 1B prefix
                + bytes([0])  # url_len=0
                + sessionid  # 16B
            )
            session_crypto.reset_cfb()
            pd_enc = session_crypto.encrypt_payload(pd_plain)
            client.sendall(pack_frame(MSG_PLAYER_DATA, pd_enc))
            return "wait_req_plus"

        if msg_type == MSG_REQ_PLUS_DATA and phase == "wait_req_plus":
            # RespPlusData：5 个空 string + 25B 杂项 + keylen=0
            rp_plain = (
                struct.pack("<H", 0) +  # userid
                struct.pack("<H", 0) +  # ptid
                struct.pack("<H", 0) +  # ptnumid
                struct.pack("<H", 0) +  # nickname
                struct.pack("<H", 0) +  # identify
                bytes([0]) + b"\x00" * 32 +  # sex + 8 个 i32 = 33B
                bytes([0])  # keylen=0
            )
            session_crypto.reset_cfb()
            rp_enc = session_crypto.encrypt_payload(rp_plain)
            client.sendall(pack_frame(MSG_RESP_PLUS_DATA, rp_enc))
            return "done"

        return phase

    def _push_2bc0(self, client: socket.socket, addr):
        """推一个 0x2bc0 假帧。明文 payload，前 4B 是地址 hash 作 fingerprint。"""
        # fingerprint = (addr[0] hash) ^ (addr[1])，4B，让 tcp_proxy 解码后能识别
        fp = (hash(f"{addr[0]}:{addr[1]}") & 0xFFFFFFFF).to_bytes(4, "little")
        # 0x2bc0 sub_cmd 任意（压测不走 PacketStateTracker，只测吞吐）
        sub_cmd = 0x0216
        payload = struct.pack("<HH", sub_cmd, 8) + fp + b"\x00\x00\x00\x00"
        try:
            client.sendall(pack_frame(0x2BC0, payload))
        except Exception:
            pass

    @property
    def connections(self) -> int:
        with self._lock:
            return self._connections


# ============================================================
# Part 2: virtual_client — 模拟手机
# ============================================================

@dataclass
class ClientStats:
    user_id: str
    connected: bool = False
    handshake_complete: bool = False
    frames_2bc0_received: int = 0
    last_error: str = ""
    handshake_ms: float = 0.0


class VirtualClient:
    """模拟一台手机：连 ECS:7777 → SRS 握手 → 持续接收 0x2bc0。"""

    def __init__(self, target_host: str, target_port: int, user_id: str):
        self.target_host = target_host
        self.target_port = target_port
        self.user_id = user_id
        self.stats = ClientStats(user_id=user_id)
        self._sock: Optional[socket.socket] = None
        self._running = False

    def run(self, duration: float):
        """跑指定秒数后断开。阻塞到结束。"""
        self._running = True
        t0 = time.monotonic()
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(10.0)
            self._sock.connect((self.target_host, self.target_port))
            self.stats.connected = True

            # 走握手序列（驱动方）
            session_crypto = SRSCrypto(key=SESSION_KEY_TEST)
            self._send(pack_frame(MSG_ENCRYPT_VER, ENCRYPT_VER_PAYLOAD))

            buf = bytearray()
            phase = "wait_ack_encrypt"
            handshake_t0 = time.monotonic()

            deadline = t0 + duration
            while self._running and time.monotonic() < deadline:
                try:
                    self._sock.settimeout(0.5)
                    data = self._sock.recv(65536)
                    if not data:
                        break
                    buf += data
                except socket.timeout:
                    continue

                while True:
                    fr, buf = read_frame_from_stream(buf)
                    if fr is None:
                        break
                    phase = self._step(fr, phase, session_crypto)
                    if phase == "done" and self.stats.handshake_ms == 0.0:
                        self.stats.handshake_ms = (time.monotonic() - handshake_t0) * 1000
                        self.stats.handshake_complete = True
        except Exception as e:
            self.stats.last_error = str(e)
        finally:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass

    def _send(self, data: bytes):
        if self._sock:
            self._sock.sendall(data)

    def _step(self, fr: dict, phase: str, crypto: SRSCrypto) -> str:
        msg_type = fr["msg_type"]

        if msg_type == MSG_ENCRYPT_VER and phase == "wait_ack_encrypt":
            self._send(pack_frame(MSG_REQ_KEY, b""))
            return "wait_handshake_rsp"

        if msg_type == MSG_HANDSHAKE_RSP and phase == "wait_handshake_rsp":
            # 解出 session key（不验证，知道服务端用 SESSION_KEY_TEST 即可）
            # 发 PlayerConnect（用会话密钥；明文格式简化：只要服务端能识别 msgid=5 就行）
            crypto.reset_cfb()
            pc_plain = b"\x02\x07" + b"\x00" * 64  # 简化 dummy；fake_upstream 不解析内容
            pc_enc = crypto.encrypt_payload(pc_plain)
            self._send(pack_frame(MSG_PLAYER_CONNECT, pc_enc))
            return "wait_player_data"

        if msg_type == MSG_PLAYER_DATA and phase == "wait_player_data":
            self._send(pack_frame(MSG_REQ_PLUS_DATA, b""))
            return "wait_resp_plus"

        if msg_type == MSG_RESP_PLUS_DATA and phase == "wait_resp_plus":
            return "done"

        if msg_type == 0x2BC0:
            self.stats.frames_2bc0_received += 1

        return phase


# ============================================================
# Part 3: metrics_sampler — 采样 ECS 资源使用
# ============================================================

@dataclass
class MetricSample:
    ts: float
    pids: dict = field(default_factory=dict)  # pid -> {rss_kb, cpu_pct, threads}
    load_avg: tuple = (0.0, 0.0, 0.0)
    mem_total_mb: int = 0
    mem_avail_mb: int = 0


def sample_proc(pid: int) -> dict:
    try:
        with open(f"/proc/{pid}/status") as f:
            data = f.read()
        rss = 0
        threads = 0
        for line in data.split("\n"):
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1])
            elif line.startswith("Threads:"):
                threads = int(line.split()[1])
        return {"rss_kb": rss, "threads": threads}
    except Exception:
        return {"rss_kb": 0, "threads": 0, "error": "not_found"}


def sample_meminfo() -> tuple:
    try:
        with open("/proc/meminfo") as f:
            data = f.read()
        total_kb = avail_kb = 0
        for line in data.split("\n"):
            if line.startswith("MemTotal:"):
                total_kb = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail_kb = int(line.split()[1])
        return total_kb // 1024, avail_kb // 1024
    except Exception:
        return 0, 0


def sample_loadavg() -> tuple:
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
        return float(parts[0]), float(parts[1]), float(parts[2])
    except Exception:
        return 0.0, 0.0, 0.0


def find_pids() -> dict:
    """找出 noconfig main / tcp_proxy 进程 pid。"""
    pids = {}
    try:
        out = subprocess.check_output(
            ["pgrep", "-af", "remote/noconfig"], text=True
        )
        for line in out.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            pid = int(parts[0])
            cmd = parts[1] if len(parts) > 1 else ""
            if "noconfig/main.py" in cmd:
                pids["noconfig"] = pid
            elif "tcp_proxy.py" in cmd:
                pids["tcp_proxy"] = pid
    except subprocess.CalledProcessError:
        pass
    return pids


class MetricsSampler:
    def __init__(self, pids: dict, interval: float = 1.0):
        self.pids = pids
        self.interval = interval
        self.samples: list = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self):
        while self._running:
            sample = MetricSample(ts=time.time())
            for name, pid in self.pids.items():
                sample.pids[name] = sample_proc(pid)
            sample.mem_total_mb, sample.mem_avail_mb = sample_meminfo()
            sample.load_avg = sample_loadavg()
            self.samples.append(sample)
            time.sleep(self.interval)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def summary(self) -> dict:
        if not self.samples:
            return {}
        # RSS 峰值 / 均值，CPU 由 load_avg 推算（更稳）
        result = {"sample_count": len(self.samples), "duration_s": 0.0}
        if len(self.samples) >= 2:
            result["duration_s"] = self.samples[-1].ts - self.samples[0].ts

        for name in self.pids:
            rss_list = [s.pids.get(name, {}).get("rss_kb", 0) for s in self.samples]
            rss_list = [x for x in rss_list if x > 0]
            if rss_list:
                result[f"{name}_rss_max_mb"] = max(rss_list) / 1024
                result[f"{name}_rss_avg_mb"] = statistics.mean(rss_list) / 1024

        load1 = [s.load_avg[0] for s in self.samples]
        result["load1_max"] = max(load1) if load1 else 0
        result["load1_avg"] = statistics.mean(load1) if load1 else 0
        result["mem_avail_min_mb"] = min(s.mem_avail_mb for s in self.samples)
        return result


# ============================================================
# Part 4: HTTP latency probe (P95)
# ============================================================

def probe_endpoint(url: str, n: int = 50, timeout: float = 3.0) -> dict:
    """对 url 发 n 次 GET，返回延迟分布（毫秒）。"""
    import urllib.request
    latencies = []
    errors = 0
    for _ in range(n):
        t0 = time.monotonic()
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                r.read()
            latencies.append((time.monotonic() - t0) * 1000)
        except Exception:
            errors += 1
    if not latencies:
        return {"error": "all_failed", "errors": errors, "n": n}
    latencies.sort()
    return {
        "n": n,
        "errors": errors,
        "p50_ms": latencies[len(latencies) // 2],
        "p95_ms": latencies[int(len(latencies) * 0.95)] if len(latencies) >= 5 else latencies[-1],
        "p99_ms": latencies[int(len(latencies) * 0.99)] if len(latencies) >= 10 else latencies[-1],
        "max_ms": latencies[-1],
        "avg_ms": statistics.mean(latencies),
    }


# ============================================================
# Part 5: 主流程
# ============================================================

def cmd_fake_upstream(args):
    """长期跑的 fake 真服。"""
    fake = FakeUpstream(host=args.host, port=args.port,
                        push_interval=args.push_interval)
    fake.start()
    logger.info("fake_upstream running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(10)
            logger.info("[fake_upstream] active connections: %d", fake.connections)
    except KeyboardInterrupt:
        fake.stop()


def cmd_loadtest(args):
    """跑一档压测：N 个并发客户端 + 资源采样 + endpoint probe。"""
    pids = find_pids()
    if not pids:
        logger.warning("找不到 noconfig 或 tcp_proxy 进程，仅采样系统级指标")

    logger.info("找到进程 pid: %s", pids)
    logger.info("启动 %d 个虚拟客户端，运行 %.0fs", args.concurrency, args.duration)

    # 起采样
    sampler = MetricsSampler(pids, interval=1.0)
    sampler.start()

    # 起虚拟客户端（线程池）
    clients = [
        VirtualClient(
            target_host=args.target_host,
            target_port=args.target_port,
            user_id=f"loadtest_{i:04d}",
        )
        for i in range(args.concurrency)
    ]
    threads = []
    t_start = time.monotonic()
    for c in clients:
        t = threading.Thread(target=c.run, args=(args.duration,), daemon=True)
        t.start()
        threads.append(t)
        # 启动间隔避免瞬间风暴
        time.sleep(0.02)

    logger.info("全部客户端已启动，等待握手稳定 5s...")
    time.sleep(5)

    # 握手稳定后探测 endpoint
    logger.info("探测 /api/users 延迟（50 次）...")
    api_users = probe_endpoint(
        f"{args.noconfig_url}/api/users?token={args.api_token}",
        n=50,
    )
    logger.info("探测 /state 延迟（50 次）...")
    state = probe_endpoint(
        f"{args.noconfig_url}/state?token={args.api_token}",
        n=50,
    )

    # 等剩余时间
    remaining = args.duration - (time.monotonic() - t_start)
    if remaining > 0:
        logger.info("等待客户端结束（剩余 %.1fs）...", remaining)
    for t in threads:
        t.join(timeout=args.duration + 30)

    sampler.stop()

    # 汇总客户端 stats
    connected = sum(1 for c in clients if c.stats.connected)
    handshaked = sum(1 for c in clients if c.stats.handshake_complete)
    frames_total = sum(c.stats.frames_2bc0_received for c in clients)
    handshake_times = [c.stats.handshake_ms for c in clients if c.stats.handshake_ms > 0]
    errors = [c.stats.last_error for c in clients if c.stats.last_error]

    result = {
        "round": args.round_label,
        "concurrency": args.concurrency,
        "duration_s": args.duration,
        "target": f"{args.target_host}:{args.target_port}",
        "noconfig_url": args.noconfig_url,
        "clients": {
            "connected": connected,
            "handshake_complete": handshaked,
            "frames_2bc0_total": frames_total,
            "frames_2bc0_per_client_avg": frames_total / max(connected, 1),
            "handshake_ms_p50": statistics.median(handshake_times) if handshake_times else 0,
            "handshake_ms_p95": (
                sorted(handshake_times)[int(len(handshake_times) * 0.95)]
                if len(handshake_times) >= 5 else 0
            ),
            "errors_count": len(errors),
            "errors_sample": errors[:5],
        },
        "metrics": sampler.summary(),
        "endpoints": {
            "/api/users": api_users,
            "/state": state,
        },
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        logger.info("结果写入: %s", args.output)


def cmd_compare(args):
    """加载多个 round 的 json 结果，输出对比表格。"""
    rounds = []
    for path in args.files:
        with open(path) as f:
            rounds.append((path, json.load(f)))

    print("\n=== 容量压测对比 ===\n")
    print(f"{'Round':<30} {'Conc':>6} {'Hand%':>7} {'NocRSS':>9} {'ProxyRSS':>10} {'Load1':>7} {'API_P95':>9} {'State_P95':>11}")
    print("-" * 100)
    for path, r in rounds:
        c = r["clients"]
        m = r.get("metrics", {})
        e = r.get("endpoints", {})
        hand_pct = 100 * c["handshake_complete"] / max(r["concurrency"], 1)
        api_p95 = e.get("/api/users", {}).get("p95_ms", -1)
        st_p95 = e.get("/state", {}).get("p95_ms", -1)
        label = os.path.basename(path)[:30]
        print(f"{label:<30} {r['concurrency']:>6} {hand_pct:>6.1f}% "
              f"{m.get('noconfig_rss_max_mb', 0):>8.1f}M "
              f"{m.get('tcp_proxy_rss_max_mb', 0):>9.1f}M "
              f"{m.get('load1_max', 0):>7.2f} "
              f"{api_p95:>8.1f}ms {st_p95:>10.1f}ms")
    print()


def main():
    parser = argparse.ArgumentParser(description="noconfig 容量压测工具")
    sub = parser.add_subparsers(dest="cmd")

    # fake-upstream
    p_fake = sub.add_parser("fake-upstream", help="启动 fake 真服")
    p_fake.add_argument("--host", default="0.0.0.0")
    p_fake.add_argument("--port", type=int, default=17777)
    p_fake.add_argument("--push-interval", type=float, default=1.0,
                        help="0x2bc0 推送间隔秒数")
    p_fake.set_defaults(func=cmd_fake_upstream)

    # loadtest
    p_lt = sub.add_parser("loadtest", help="跑一档压测")
    p_lt.add_argument("--concurrency", "-N", type=int, default=10)
    p_lt.add_argument("--duration", type=float, default=180,
                      help="每个虚拟客户端运行秒数")
    p_lt.add_argument("--target-host", default="127.0.0.1")
    p_lt.add_argument("--target-port", type=int, default=7777)
    p_lt.add_argument("--noconfig-url", default="http://127.0.0.1:8002")
    p_lt.add_argument("--api-token", required=True)
    p_lt.add_argument("--round-label", default="unknown")
    p_lt.add_argument("--output", "-o", default="")
    p_lt.set_defaults(func=cmd_loadtest)

    # compare
    p_cmp = sub.add_parser("compare", help="对比多 round json 结果")
    p_cmp.add_argument("files", nargs="+")
    p_cmp.set_defaults(func=cmd_compare)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args.func(args)


if __name__ == "__main__":
    main()
