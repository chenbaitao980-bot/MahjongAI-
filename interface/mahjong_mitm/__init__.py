"""mahjong_mitm — setup-period 热更 MITM（路由器/PC 双模）。

抽取自 remote/noconfig/hijack/ 的最小子集，只保留 setup-period 一刀：
  - DNS 响应器（劫持热更域名 → 本机）
  - 自签 HTTPS server（回源真实 manifest + 只改 NetConf 一条）
  - NetConf XXTEA 解密改 IP（台州 5045 → ECS）

不含 ECS 侧 tcp_proxy / 多用户后台 / relay；那些单独部署。

入口：`python -m mahjong_mitm --host-ip <网关IP> --ecs-ip <ECS公网IP>`
"""
from __future__ import annotations

# ── OpenWrt python3-light 兼容 shim：注入 fake `logging` 到 sys.modules ──
# python3-light 不带 `logging`/`requests`，子模块全部统一从这里拿。
import sys as _sys
try:
    import logging  # noqa: F401
except ImportError:
    import types as _types

    class _FakeLogger:
        def __init__(self, name: str = "") -> None:
            self.name = name

        def _emit(self, level: str, msg, *args) -> None:
            try:
                text = msg % args if args else msg
            except Exception:
                text = str(msg)
            print(f"[{level}] {self.name}: {text}", flush=True)

        def info(self, msg, *args, **kw):    self._emit("INFO", msg, *args)
        def warning(self, msg, *args, **kw): self._emit("WARN", msg, *args)
        def warn(self, msg, *args, **kw):    self._emit("WARN", msg, *args)
        def error(self, msg, *args, **kw):   self._emit("ERR", msg, *args)
        def exception(self, msg, *args, **kw): self._emit("ERR", msg, *args)
        def critical(self, msg, *args, **kw): self._emit("CRIT", msg, *args)
        def debug(self, msg, *args, **kw):   pass
        def setLevel(self, *a, **kw):        pass
        def addHandler(self, *a, **kw):      pass

    _fake = _types.ModuleType("logging")
    _fake.getLogger = lambda name="": _FakeLogger(name)
    _fake.basicConfig = lambda *a, **kw: None
    _fake.Logger = _FakeLogger
    _fake.INFO = 20
    _fake.WARNING = 30
    _fake.ERROR = 40
    _fake.DEBUG = 10
    _fake.CRITICAL = 50
    _fake.NOTSET = 0
    _sys.modules["logging"] = _fake

# python3-light 还可能剥 `idna` codec，让 http.server.server_bind() 调
# socket.getfqdn() 或 urllib.request 解析主机名时抛 LookupError。
# 我们的全部主机名都是 ASCII，注册一个回退到 ascii 的 idna codec 即可。
try:
    "x".encode("idna")
except (LookupError, UnicodeError):
    import codecs as _codecs
    import socket as _socket

    def _idna_search(name: str):
        if name != "idna":
            return None
        def _encode(s: str, errors: str = "strict") -> tuple[bytes, int]:
            return s.encode("ascii", errors), len(s)
        def _decode(b: bytes, errors: str = "strict") -> tuple[str, int]:
            return bytes(b).decode("ascii", errors), len(b)
        return _codecs.CodecInfo(name="idna", encode=_encode, decode=_decode)

    _codecs.register(_idna_search)
    # 兜底：socket.getfqdn() 在某些路径仍可能直接走 C 层 IDN，留这个 monkey-patch。
    _socket.getfqdn = lambda name="": name or _socket.gethostname()

__all__ = ["run", "main", "DEFAULT_ECS_IP", "DEFAULT_APK"]

from .setup_mitm import DEFAULT_APK, DEFAULT_ECS_IP, main, run
