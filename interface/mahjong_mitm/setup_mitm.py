"""setup_mitm.py — 设置期一次性服务（PC 热点端，手机在热点上开游戏触发热更时跑）。

组成：
  1. DNS 响应器（UDP:53）：把游戏热更域名解析到 PC 热点 IP，其余转发上游/返回空。
     劫持域名：gxb-api / gxb-api-tx / gxb-oss / gxb-cos . hzxuanming.com。
  2. HTTPS 服务（自签证书，CN 随便——热更下载器 VERIFYPEER=0 接受任何证书）：
     - GET /hotfix_update?...        → **回源真实 version.manifest**（透传含 query 的 raw_path，
       自带 appid）+ 最小改写（顶高 version + 清空 project_md5 + 删 zip，**保留真实
       manifest_url/file_url**）。同时记下真实 manifest_url 的 host+path 供 project handler 用。
     - GET <真实 manifest_url path>  → **回源真实线上 project.manifest**（即上面记下的 path），
       只 patch NetConf 一条（顶高版本 + forbid_zip + NetConf md5/size/name 指 PC），
       file_url 保持真实（被劫持的 gxb 域名）。回源/patch 失败 → 502（**不回退 APK 静态**）。
     - GET /yj/files/<served_name>   → netconf_patch 生成的改过的 NetConf.luac（原始 luac 字节）
     - GET 其它文件（.manifest/.png/.luac 等）→ **透明回源真实 CDN 原样返回**（兜底）。

— 为何「回源真实 version.manifest」（2026-06-14 真机修正）—
此前 version.manifest 是**伪造**的，manifest_url 用自编路径 `/yj/Lobby/project.manifest`，真实
CDN 没有此路径 → project handler 回源 404 → 回退 APK 旧版静态 → 游戏 diff 出 91 个线上新版文件
→ 全 404 → 热更失败「加载网络失败」。根因：游戏 genDiffList 用「我们 serve 的 project.manifest」
比对「游戏本地 localManifest（已热更到线上新版）」。要只 diff 出 NetConf，我们 serve 的
project.manifest 必须 = 线上新版 + 只改 NetConf，而线上真实 project.manifest 的位置 =
**真实 version.manifest 的 manifest_url**。故 version.manifest 必须回源真实、保留 manifest_url。

— 为何「透明回源」（2026-06-14）—
APK(`apk/game_base.apk`) 内置 manifest 是旧版 1.0.0.50，手机线上跑的是更新版。基于 APK 旧版
forge 会让游戏 diff 出 91 个本不在 PC 的文件 → 全 404 → 热更整体失败回滚 → 「加载网络失败」。
正解：project.manifest 回源**手机线上真实跑的版本**做底，只改 NetConf 一条 → diff 只剩 NetConf。
回源用固定公共 DNS（119.29.29.29，不依赖系统 DNS、不被 dns_divert 影响）解析真实 CDN IP，
以「同 Host + 同 path」直连回源（verify=False）；DNS 劫持后到达 PC 的 path 即原本要请求的真实路径。

复用：netconf_patch.patch_from_apk + manifest_forge.forge_manifest_full / load_real_manifest。
ECS IP 参数化（默认 8.136.37.136）。

— 工作原理（为何不用改手机）—
PC 做热点网关时通过 DHCP 下发 DNS=PC 自己。手机用 PC 的 DNS → 本 DNS 器把游戏域名
解析到 PC → 游戏 HTTPS 请求落到本 HTTP 服务 → 自签证书被 VERIFYPEER=0 接受。
手机无需改任何设置。

— Windows 绑 53 端口注意 —
- 需以管理员权限运行（绑 <1024 端口）。
- Windows「Internet 连接共享(ICS)」或自带热点会占用 UDP:53 → 先停掉系统 DNS 代理，
  或把 DHCP 下发的 DNS 指向本机另起的 53。若 53 被占，可用 --dns-port 改端口并在
  路由/热点侧把 DNS 指过来（高级用法）。
- 防火墙需放行 UDP:53 与 TLS 端口（默认 443）。

⚠ 需真机/抓包确认（见 research/hotfix-download-verify.md §2）：
  - CDN 对 .luac 是否返回 gzip 且引擎 gunzip。本服务默认 serve 原始 luac 字节
    （逆向判定通用下载路径无解压）。若真机抓包发现需 gzip，把 served bytes 换成
    gzip(luac) 并让 manifest_forge 用 gzip 字节算 md5（两处一致即可）。

隔离：全新文件；不碰 vpn/hotspot/noconfig 现有端点。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import logging
import os
import socket
import struct
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 包根目录（interface/）——assets/game_base.apk 与默认证书目录据此定位。
# 抽取自 remote/noconfig/hijack/，已去除对仓库根的依赖（原 _REPO_ROOT + sys.path 注入）。
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNTIME_ROOT = os.path.dirname(_PKG_DIR)  # interface/

from .manifest_forge import forge_manifest_full
from .netconf_patch import patch_from_apk, wrap_luac, KEY

logger = logging.getLogger("mahjong_mitm.setup_mitm")

# 被劫持的热更域名（hzxuanming.com = 旧域名，imeete.com = 线上真实 CDN 域名）
HIJACK_DOMAINS = {
    "gxb-api.hzxuanming.com",
    "gxb-api-tx.hzxuanming.com",
    "gxb-oss.hzxuanming.com",
    "gxb-cos.hzxuanming.com",
    # 线上真实 CDN（2026-06-14 真机发现：version.manifest 的 manifest_url/file_url
    # 指向 gxb-oss.imeete.com / gxb-cos.imeete.com 而非 hzxuanming.com）
    "gxb-oss.imeete.com",
    "gxb-cos.imeete.com",
}

DEFAULT_ECS_IP = "8.136.32.137"
DEFAULT_APK = os.path.join(_RUNTIME_ROOT, "assets", "game_base.apk")
APK_RESCHECKER_ENTRY = "assets/src/app/hotupdate/lobby/ResChecker.luac"

# ─── 官方上游硬编码 host（PR2：4G 永久指向 ECS）────────────────────────────────
# 4G 下没有 DNS 劫持，进来的 Host 头 = ECS IP（手机直连 ECS），不能再靠 Host 头
# 判断回源目标。回源官方资源时必须用这里硬编码的官方真实域名。
#
# - OFFICIAL_UPDATE_HOSTS：hotfix_update / version.manifest 端点（实测真机用
#   gxb-api[-tx].hzxuanming.com，见 hijack_live.err 回源解析记录）。第一个为主、
#   失败回退第二个。
# - OFFICIAL_MANIFEST_HOST：project.manifest 回源兜底 host（正常用运行时捕获的
#   real_manifest_host；首个请求尚未捕获时用此兜底）。线上真实 manifest 指向 imeete CDN。
# - OFFICIAL_FILE_HOST：官方文件字节回源 host（仅 --file-url-mode ecs 验收模式用）。
OFFICIAL_UPDATE_HOSTS = (
    "gxb-api.hzxuanming.com",
    "gxb-api-tx.hzxuanming.com",
)
OFFICIAL_MANIFEST_HOST = "gxb-oss.imeete.com"
OFFICIAL_FILE_HOST = "gxb-oss.imeete.com"

# file_url 改写模式：
#   "official"（默认/生产）：project.manifest 的 file_url 保持官方原样，官方文件字节
#       4G 下直连官方 CDN，不经 ECS（NetConf 因 md5 恒定永不被请求，覆盖绝对安全）。
#   "ecs"（验收用）：file_url 改写为 ECS file base，所有官方文件经 ECS 透传，日志全可见。
FILE_URL_MODE_OFFICIAL = "official"
FILE_URL_MODE_ECS = "ecs"
MANIFEST_URL_MODE_LOCAL = "local"
MANIFEST_URL_MODE_ECS = "ecs"

# 路由路径（HTTPS）
PATH_VERSION = "/hotfix_update"            # update_url 落点
PATH_PROJECT = "/yj/Lobby/project.manifest"  # 伪 project.manifest 落点
FILE_URL_PREFIXES = ("/yj/files/", "/other/files/")  # file_url 基址（旧 CDN + 线上真实 CDN）

# 回源用的固定公共 DNS（手机硬编码同款；不依赖系统 DNS，也不被 dns_divert 影响）
ORIGIN_DNS = "119.29.29.29"
ORIGIN_TIMEOUT = 8.0
# NetConf 在 manifest file_list 里的 key。实测真实线上 manifest 用小写
# `src/app/config/NetConf.luac`（与 APK 内置 project.manifest 一致），游戏按此 key
# 落盘并加载，故覆盖也必须用同一 key。注入兜底用此小写默认值；改写优先按
# case-insensitive 命中线上 manifest 里的现有 key（保留其原始大小写）。
NETCONF_FILE_KEY_DEFAULT = "src/app/config/NetConf.luac"
# 兼容旧引用名
NETCONF_FILE_KEY = NETCONF_FILE_KEY_DEFAULT

# ResEnsure.luac 在 manifest file_list 里的 key（用于注入跳过校验版本）
RESENSURE_FILE_KEY = "src/app/hotupdate/lobby/ResEnsure.luac"
RESCHECKER_FILE_KEY = "src/app/hotupdate/lobby/ResChecker.luac"

# 是否注入修改版 ResEnsure/ResChecker（跳过 clean_res 的「快速」热更）。
# 默认 False —— 2026-06-15 排查「热更后黑屏」定位到：跳过 clean_res 会在
# 手机本地版本回落到 APK 基线（1.0.0.59，与线上 1.0.1.1776 差几千文件）时，
# 在残留/混合的 harbor 目录上做增量合并，导致大厅资源状态不一致 → 黑屏。
# 原版 ResEnsure 在版本 tag 不匹配时会 clean_res（清空 harbor）后全量重做，
# 全量下载已被证实可完整成功（origin 200 ×16495，0 失败），结果一致、不黑屏。
# 只注入 NetConf（指向 ECS）即可，这也是 2026-06-14 真机成功时的配置。
# 仅当确认手机本地已是线上最新版（diff 极小）且原版 ResChecker 确实卡住时，
# 才考虑临时置 True 走跳过路径。
INJECT_LOBBY_CHECKER = False

# 跳过校验版本的 ResEnsure.lua 源码（替换原始版本，直接跳过 clean_res）
SKIP_CHECK_RESENSURE_SOURCE = '''local cjson = require("cjson")

local ResEnsure = {}

local CWD = un.FileSystem.getWritePath() .. "hotfix/"

-- Skip validation, go directly to hotupdate flow
function ResEnsure.start(mainKey, isForce, listener)
    listener.onFinish(false, mainKey)
end

return ResEnsure
'''

def _find_netconf_key(file_list: dict) -> str | None:
    """在 file_list 里 case-insensitive 找到 NetConf 条目的实际 key（保留原始大小写）。"""
    want = NETCONF_FILE_KEY_DEFAULT.lower()
    for k in file_list:
        if k.lower() == want:
            return k
    return None


def _load_apk_entry_bytes(apk_path: str, entry_name: str) -> bytes:
    """Load an original asset directly from the APK so hotfix patches can restore it byte-for-byte."""
    with zipfile.ZipFile(apk_path, "r") as zf:
        with zf.open(entry_name, "r") as fh:
            return fh.read()

# host → real IP 解析缓存（同一 host 只解析一次）
_resolve_cache: dict[str, str] = {}


# ─── 回源辅助：用固定公共 DNS 解析真实 CDN，并透明回源 ───────────────────────

def _resolve_real_ip(host: str) -> str | None:
    """用固定公共 DNS（119.29.29.29）解析 host 的真实 A 记录 IP。

    不依赖系统 DNS（避免被 dns_divert 把自己劫持回 PC），用裸 UDP DNS 查询。
    带缓存：同一 host 只解析一次。失败返回 None。
    """
    cached = _resolve_cache.get(host)
    if cached:
        return cached
    try:
        query = _build_dns_query(host)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3.0)
        try:
            sock.sendto(query, (ORIGIN_DNS, 53))
            resp, _ = sock.recvfrom(2048)
        finally:
            sock.close()
        ip = _parse_first_a(resp)
        if ip:
            _resolve_cache[host] = ip
            logger.info("[origin] resolved %s -> %s (via %s)", host, ip, ORIGIN_DNS)
        else:
            logger.warning("[origin] resolve %s: no A record in response", host)
        return ip
    except Exception as exc:
        logger.warning("[origin] resolve %s failed: %s", host, exc)
        return None


def _parse_first_a(resp: bytes) -> str | None:
    """从 DNS 响应里取第一条 A 记录的 IPv4。失败返回 None。"""
    try:
        if len(resp) < 12:
            return None
        qd = struct.unpack_from(">H", resp, 4)[0]
        an = struct.unpack_from(">H", resp, 6)[0]
        if an == 0:
            return None
        off = 12
        # 跳过 question 区
        for _ in range(qd):
            while True:
                ln = resp[off]; off += 1
                if ln == 0:
                    break
                off += ln
            off += 4  # qtype + qclass
        # 解析 answer 区
        for _ in range(an):
            # name（可能是指针 0xc0xx，2 字节；或普通 labels）
            if resp[off] & 0xC0 == 0xC0:
                off += 2
            else:
                while True:
                    ln = resp[off]; off += 1
                    if ln == 0:
                        break
                    off += ln
            rtype = struct.unpack_from(">H", resp, off)[0]
            rdlen = struct.unpack_from(">H", resp, off + 8)[0]
            rdata_off = off + 10
            if rtype == 1 and rdlen == 4:  # A
                return socket.inet_ntoa(resp[rdata_off:rdata_off + 4])
            off = rdata_off + rdlen
        return None
    except Exception:
        return None


def _origin_fetch(host: str, path: str) -> tuple[int, bytes, str]:
    """透明回源真实 CDN：用固定公共 DNS 解析 host → https://{real_ip}{path}（Host 头=host）。

    ⚠ path 必须是游戏请求的**完整 raw path（含 query）**，例如
    `/hotfix_update?appid=...&version=...`。否则真实服务器会因缺 appid 等参数报错
    （"appid can not be nil"）。调用方应传 `self.path`（BaseHTTPRequestHandler 的 raw path），
    而不是 split("?") 后的纯 path。

    返回 (status_code, body, content_type)。失败/异常返回 (502, b"", "")。
    """
    import urllib3
    urllib3.disable_warnings()

    real_ip = _resolve_real_ip(host)
    if not real_ip:
        return 502, b"", ""
    url = f"https://{real_ip}{path}"
    try:
        import requests

        session = requests.Session()
        # Ignore host/system proxy settings so hotspot MITM origin fetches
        # always go straight to the real CDN.
        session.trust_env = False
        r = session.get(
            url,
            headers={"Host": host},
            verify=False,
            timeout=ORIGIN_TIMEOUT,
        )
        ctype = r.headers.get("Content-Type", "application/octet-stream")
        return r.status_code, r.content, ctype
    except Exception as exc:
        logger.warning("[origin] fetch %s%s failed: %s", host, path, exc)
        return 502, b"", ""


# ─── 资产构建（manifest + 改过的 NetConf）────────────────────────────────────

class MitmAssets:
    """一次性构建并缓存：改过的 NetConf.luac + 伪 project.manifest + 伪 version.manifest。"""

    def __init__(self, apk_path: str, ecs_ip: str, self_host: str, tls_port: int = 443,
                 bump_version: str = "9.9.9.103",
                 file_url_mode: str = FILE_URL_MODE_OFFICIAL,
                 manifest_url_mode: str = MANIFEST_URL_MODE_ECS):
        self.apk_path = apk_path
        self.ecs_ip = ecs_ip
        self.self_host = self_host        # 手机看到的我们的主机名（被劫持域名，如 gxb-oss.hzxuanming.com）
        self.tls_port = tls_port
        self.bump_version = bump_version
        # file_url 改写模式（"official" 默认 / "ecs" 验收）。见 FILE_URL_MODE_* 常量。
        self.file_url_mode = file_url_mode
        # manifest_url 改写模式："ecs" 写到 ECS；"local" 保留官方 host 走热点本地 MITM。
        self.manifest_url_mode = manifest_url_mode
        # 真实线上版本号（从回源到的真实 version.manifest 的 version 字段 / manifest_url
        # 文件名动态捕获）。对外下发的版本号优先用它，而非伪造的 bump_version——
        # 否则手机本地版本被写成"未来版本"(9.9.9.103)，切到 4G 用本地版本请求真服
        # hotfix_update API，真服无法处理未知版本 → 热更管理器拿不到结果 → 永远卡在
        # "正在校验本地资源中"。用真实线上版本则 4G 下「本地==真服」→ API 答已最新 →
        # 不再重下、NetConf 覆盖保留指向 ECS。见 _served_version()。
        # 启动时为 None；首个 version.manifest 回源请求时被赋值。
        self.real_online_version: str | None = None
        # 真实线上 project.manifest 的 path（含 query，从回源到的真实 version.manifest 的
        # manifest_url 里解析得到）。project handler 据此识别 project.manifest 请求并回源。
        # 在 patch_real_version_manifest 成功时被赋值；启动时为 None。
        self.real_manifest_path: str | None = None
        self.real_manifest_host: str | None = None
        self.real_manifest_paths: set[str] = set()
        self.real_manifest_hosts_by_path: dict[str, str] = {}
        # 当真实 API 返回"无需更新"（只有 version）时，从请求参数推断 manifest_url。
        # 由 handler 在每次请求时解析 hotfix_update query 参数并更新。
        self._inferred_manifest_url: str | None = None
        # Serve a minimal lobby manifest so the setup-period hotfix only downloads
        # the files we intentionally changed instead of replaying the full upstream patch set.
        self.hotfix_only_manifest = True
        self._build()

    def _base_url(self, host: str) -> str:
        # VERIFYPEER=0，CN 随便；URL 用被劫持域名，DNS 已指向 PC。
        port = "" if self.tls_port == 443 else f":{self.tls_port}"
        return f"https://{host}{port}"

    def _ecs_base(self) -> str:
        """ECS 回写基址 = ECS 公网 IP（self.ecs_ip），手机 4G 下据此 IP 直连，无需 DNS。

        关键：写进 harbor 的永久 manifest_url / update_url（以及 ecs 模式 file_url）必须是
        ECS 公网 IP，因为热更完成后 HotFixProcessor._updateLocalManifest 把它整体存进
        harbor，手机切 4G 后据此地址直连。这与"设置期由谁 serve manifest"(self_host：
        PC 热点=热点网关 IP / ECS 常驻=公网 IP) 无关——PC 热点设置时 self_host=192.168.137.1
        是热点网关，4G 够不着，绝不能用作 update_url/manifest_url 的写入值。
        """
        return self._base_url(self.ecs_ip)

    # 下发版本策略：4 段缓冲支配版本——在真实线上版本的每个分量上加小幅缓冲偏移，
    # 分量数与官方一致（同为 4 段），避免 5 段方案触发手机端热更中断（见下方说明）。
    #
    # 为什么不用 5 段（曾经尝试过的 official_plus_segment）：5 段版本虽能靠 versionLessThan
    # 段数短路"永久支配"，但真机实测手机热更下完文件后中断、version 写不进 harbor（界面
    # 不显示）。回滚到 4 段 +100000 后恢复正常。5 段中断的精确机理在手机端 native/UI 层，
    # 服务器端日志与 Lua 反编译全链路均未发现原因，故放弃 5 段，回到与官方同段数的 4 段。
    #
    # 4 段缓冲：每段加一个"略高于官方"的偏移，保证每段都 > 官方可预见未来的对应段
    # （versionLessThan 逐段只判 <，每段都 >= 即永久支配），同时位数贴近官方、不像
    # +100000 那样多一位显得像盗版。
    #   major(+1) minor(+5) patch(+9) build(+2000)
    #
    # build 段偏移历史:
    #   +1000 (06-14~06-18) 初始 Path Y 版 NetConf 部署
    #   +2000 (06-19) 5045/5067/5167 全回滚为 ECS 单点(取消真服 fallback);bump 让
    #         已经热更过 +1000 版本的手机重下新 NetConf,否则手机本地 NOUPDATE 不重下、
    #         继续用 Path Y 版 NetConf(真服+ECS 并存)、~50% 抽真服绕过 ECS tcp_proxy。
    #   +3000 (06-19) 注入 LOCAL_TCP_LIST_50[5045]=ECS,钉死 NetEngine _50 分支跳过
    #         srslist{5045}.json 缓存随机污染(实机根因:重进几次才连上 ECS);bump 让
    #         已热更过 +2000 版本的手机重下新 NetConf,否则本地 NOUPDATE 继续被 srslist 污染。
    #   +3001 (06-25) scenario3 真机验证后定版为当前支配偏移(零漏更); NetConf 内容未变, 仅作版本支配基准
    #   未来 NetConf 内容变化时必须再 bump build 偏移,否则手机感知不到。
    _VERSION_SEGMENT_OFFSETS = (1, 5, 9, 3001)
    # 拿不到真实线上版本时的静态兜底支配版本（4 段、每段都远大于任何现实版本）。
    _FALLBACK_DOMINATE_VERSION = "99.99.99.9999"

    @staticmethod
    def _build_offset() -> int:
        """build 段（第 4 段）偏移，默认 3001，可被环境变量 MITM_BUILD_OFFSET 覆盖。

        用途：scenario 3 真机验证后定版的当前生产支配偏移（零漏更）。临时设其它值
        可让下发版本比 harbor 高/低以触发或抑制更新检查。
        非法值（无法 int 解析）回退默认 3001。call-time 读取，便于 systemd 进程级
        env 生效及单测在 import 后改 env。
        """
        import os
        try:
            return int(os.environ.get("MITM_BUILD_OFFSET", "3001"))
        except ValueError:
            return 3001

    def _served_version(self) -> str:
        """对外下发 / 写进 harbor 的版本号：4 段缓冲支配版本（与官方同段数，每段略高）。

        必须同时满足两个看似矛盾的需求：
        - 热点：手机本地版本 < 下发版本 → 触发热更并注入 NetConf（连已是线上最新版、
          从未注入过的手机也必须触发——靠首分量大于真实主版本号实现）。
        - 4G：手机切自己网络后 HotFixProcessor 用 harbor 本地版本与真服真实 version.manifest
          比较，必须判 NOUPDATE，否则会重下覆盖我们的 NetConf 或卡在"正在校验本地资源中"。

        关键：游戏 `Manifest.versionLessThan` 逐分量只检查 `a[i] < b[i]` 就返回 true，
        不会因前面 `a[j] > b[j]` 提前判否。所以下发版本在**每一个分量**上都 >= 真实线上版本
        即可永久支配。这里取每段 +小幅缓冲（(1,5,9,3001)），分量数与官方一致（4 段），
        位数贴近官方；拿不到真实版才回退静态支配版本。
        """
        real = self.real_online_version
        if not real:
            return self._FALLBACK_DOMINATE_VERSION
        comps = self._parse_version_components(real)
        if not comps:
            return self._FALLBACK_DOMINATE_VERSION
        # 前 N 段叠加缓冲偏移（分量数不足时只对已有分量加偏移）。
        # 前 3 段（major+1/minor+5/patch+9）固定用 _VERSION_SEGMENT_OFFSETS[:3]，
        # 保持支配语义不变；第 4 段（build）改用 _build_offset()——默认 3001（scenario 3
        # 真机验证后定版的当前生产支配偏移，零漏更）；临时设其它值可调触发/抑制更新检查。
        offsets = list(self._VERSION_SEGMENT_OFFSETS[:3]) + [self._build_offset()]
        bumped = [
            c + offsets[i]
            for i, c in enumerate(comps[:len(offsets)])
        ]
        # 官方若超过 4 段（理论上不会），原样保留多余分量
        bumped.extend(comps[len(self._VERSION_SEGMENT_OFFSETS):])
        return ".".join(str(c) for c in bumped)

    @staticmethod
    def _parse_version_components(version: str) -> list[int]:
        import re
        return [int(x) for x in re.findall(r"\d+", version or "")]

    @staticmethod
    def _extract_version_from_manifest_url(url: str) -> str | None:
        """从 manifest_url 文件名 project-<VER>.manifest 提取版本号（更可靠的兜底来源）。"""
        import re
        m = re.search(r"project-([0-9]+(?:\.[0-9]+)+)\.manifest", url or "")
        return m.group(1) if m else None

    def _build(self) -> None:
        # 1) 改过的 NetConf.luac（台州 5045 → ECS）
        patch = patch_from_apk(self.apk_path, self.ecs_ip)
        self.netconf_luac = patch.new_luac

        # 2)+3) 修改版 ResEnsure/ResChecker（跳过 clean_res）——仅在 INJECT_LOBBY_CHECKER
        #       为 True 时构建并注入。默认关闭：见 INJECT_LOBBY_CHECKER 常量处的黑屏说明。
        self.resensure_luac = b""
        self.resensure_md5 = self.resensure_size = self.resensure_name = None
        self.reschecker_luac = b""
        self.reschecker_md5 = self.reschecker_size = self.reschecker_name = None
        if INJECT_LOBBY_CHECKER:
            # 2) 改过的 ResEnsure.luac（跳过校验本地资源）
            self.resensure_luac = wrap_luac(SKIP_CHECK_RESENSURE_SOURCE, KEY)
            self.resensure_md5 = hashlib.md5(self.resensure_luac).hexdigest()
            self.resensure_size = len(self.resensure_luac)
            self.resensure_name = f"{self.resensure_md5[:2]}/{self.resensure_md5}.luac"

            # 3) 跳过校验的 ResChecker.luac（第一次热更就不卡）
            # 修改 _ensureRes 直接调用 ResEnsureListener.onFinish，跳过资源校验
            reschecker_modified_path = os.path.join(os.path.dirname(__file__), "reschecker_modified.luac")
            if os.path.exists(reschecker_modified_path):
                with open(reschecker_modified_path, "rb") as f:
                    self.reschecker_luac = f.read()
                logger.info("Using modified ResChecker (skips validation): %s", reschecker_modified_path)
            else:
                # Fallback to official version if modified file not found
                self.reschecker_luac = _load_apk_entry_bytes(self.apk_path, APK_RESCHECKER_ENTRY)
                logger.warning("Modified ResChecker not found at %s, using official version (will cause first-run stall)", reschecker_modified_path)
            self.reschecker_md5 = hashlib.md5(self.reschecker_luac).hexdigest()
            self.reschecker_size = len(self.reschecker_luac)
            self.reschecker_name = f"{self.reschecker_md5[:2]}/{self.reschecker_md5}.luac"
        else:
            logger.info("Lobby ResEnsure/ResChecker injection DISABLED (INJECT_LOBBY_CHECKER=False); "
                        "serving original from CDN to keep clean_res — avoids post-hotfix black screen")

        # 4) file_url 基址（NetConf / ResEnsure / ResChecker 从这里下）；用 gxb-oss 域名（已劫持）
        file_base = self._base_url("gxb-oss.hzxuanming.com") + FILE_URL_PREFIXES[0]

        # 5) 伪 project.manifest（只改 NetConf 一条 + 顶高版本 + forbid_zip）
        forge = forge_manifest_full(
            self.apk_path, self.netconf_luac, file_base,
            bump_version=self.bump_version,
        )
        self.served_name = forge.served_name          # 如 "fe/feb4....luac"
        self.served_md5 = forge.served_md5
        self.served_size = forge.served_size          # = len(netconf_luac)
        self.version = forge.version
        self.project_manifest = self.patch_real_project_manifest(forge.manifest_json_bytes)

        # 6) 伪 version.manifest（version 顶高 + manifest_url 指我们的 project.manifest）
        manifest_url = self._base_url("gxb-api.hzxuanming.com") + PATH_PROJECT
        import json
        self.version_manifest = json.dumps({
            "version": self._served_version(),
            "update_type": 1,           # NORMAL（非 FORCE，避免「请退出应用」弹窗）
            "tip_msg": "",
            "manifest_url": [manifest_url],
            "project_md5": "",          # 空串 → 下载器不校验 project.manifest md5
            "file_url": [file_base],
            # 故意不带 diff_zip / zip_url → 强制通用逐文件下载
        }, ensure_ascii=False).encode("utf-8")

        # 7) NetConf / ResEnsure / ResChecker 文件下载基址（回源 patch 时写进 project.manifest 的 file_url）
        self.file_base = file_base

        logger.info("MITM assets built: version=%s netconf=%dB md5=%s inject_checker=%s resensure=%dB md5=%s reschecker=%dB md5=%s",
                    self.version, len(self.netconf_luac), self.served_md5, INJECT_LOBBY_CHECKER,
                    len(self.resensure_luac), self.resensure_md5,
                    len(self.reschecker_luac), self.reschecker_md5)

    def patch_real_version_manifest(self, real_version_bytes: bytes) -> bytes:
        """对回源到的真实线上 version.manifest 做最小 patch（透明回源 + 最小改写）。

        关键：**保留真实的 manifest_url / file_url 原样**——这才是线上真实 project.manifest
        的位置。同时把真实 manifest_url 的 path（含 query）+ host 记到 self.real_manifest_path /
        self.real_manifest_host，供 project handler 识别 project.manifest 请求并回源。

        只改三处：
          ① version = 顶高（触发热更，逐段数字比较远超官方）
          ② project_md5 = ""（清空——我们会 patch project.manifest 改其 md5，清空让 d2 跳过校验）
          ③ 删 diff_zip / zip_url（强制通用逐文件下载）

        当真实 API 返回"无需更新"的极简响应（只有 version，没有 manifest_url）时，
        从请求参数里推断 appid/engine_ver/channel，构造一个 manifest_url 指向线上真实 CDN。
        这确保即使手机已是最新版，我们也能触发一次"更新"来注入 NetConf。
        """
        import json
        from urllib.parse import urlsplit

        vm = json.loads(real_version_bytes.decode("utf-8"))

        manifest_url = vm.get("manifest_url")
        # manifest_url 可能是字符串或字符串数组（游戏侧 getManifestUrl 取 [i]）
        if isinstance(manifest_url, list):
            manifest_urls = [u for u in manifest_url if isinstance(u, str) and u]
        elif isinstance(manifest_url, str) and manifest_url:
            manifest_urls = [manifest_url]
        else:
            manifest_urls = []
        first_url = manifest_urls[0] if manifest_urls else None
        if not first_url:
            # 真实 API 返回"无需更新"的极简响应（只有 version）——
            # 我们必须注入 manifest_url，否则游戏不会下载 project.manifest。
            # 从已解析的 appid 等参数构造（见 _parse_update_params）。
            if self._inferred_manifest_url:
                vm["manifest_url"] = [self._inferred_manifest_url]
                manifest_urls = [self._inferred_manifest_url]
                first_url = self._inferred_manifest_url
                logger.info("[patch] 注入 manifest_url=%s (API 未返回)", first_url)
            else:
                raise KeyError("线上 version.manifest 缺少 manifest_url，且无法推断")

        # 记下所有真实 manifest_url 的 path + host，供 project handler 精确匹配。
        # 多个 appid 会并发请求 hotfix_update，单值缓存会互相覆盖，导致部分 project
        # manifest 被当成普通文件透传，进而触发大批资源下载或卡在本地校验。
        for url in manifest_urls:
            parts = urlsplit(url)
            if not parts.hostname:
                continue
            manifest_path = parts.path + (("?" + parts.query) if parts.query else "")
            manifest_path_only = parts.path
            self.real_manifest_paths.add(manifest_path_only)
            self.real_manifest_hosts_by_path[manifest_path_only] = parts.hostname
            if url == first_url:
                self.real_manifest_host = parts.hostname
                self.real_manifest_path = manifest_path

        # ★ 捕获真实线上版本（覆盖前）：优先 vm["version"]，兜底从 manifest_url 文件名提取。
        #    用于对外下发版本号，避免把手机本地写成"未来版本"导致 4G 卡校验。
        captured = vm.get("version") if isinstance(vm.get("version"), str) else None
        if not captured:
            for u in manifest_urls:
                captured = self._extract_version_from_manifest_url(u)
                if captured:
                    break
        if captured and captured != self.real_online_version:
            self.real_online_version = captured
            logger.info("[origin] captured real online version=%s → served dominating version=%s",
                        captured, self._served_version())

        # ① 下发版本（用真实线上版本触发热更且 4G 不卡；拿不到才回退 bump_version）
        vm["version"] = self._served_version()
        # ② 清空 project_md5（我们会 patch project.manifest 导致其 md5 变）
        vm["project_md5"] = ""
        # ③ 删 zip 差分/整包（强制通用逐文件下载）
        vm.pop("diff_zip", None)
        vm.pop("zip_url", None)
        # ④ ★PR2：把 manifest_url 改写到 ECS（保留官方 path+query，host 换 ECS）。
        #    热更完成后 _updateLocalManifest 整体替换 harbor → 手机下次（含 4G）取
        #    project.manifest 时直接打到 ECS，而非真官方（避免官方 NetConf md5≠harbor
        #    导致重下官方 NetConf 把覆盖冲掉）。
        #    path 保持官方原样 → 仍命中 real_manifest_paths → project handler 据此回源官方。
        rewritten_manifest_urls = None
        if self.manifest_url_mode == MANIFEST_URL_MODE_LOCAL:
            vm["manifest_url"] = manifest_urls
            logger.info("[patch] keep manifest_url on official hosts for local hotspot bootstrap")
        else:
            ecs_base = self._ecs_base()
            rewritten_manifest_urls = []
            for url in manifest_urls:
                parts = urlsplit(url)
                path_q = parts.path + (("?" + parts.query) if parts.query else "")
                rewritten_manifest_urls.append(ecs_base + path_q)
            vm["manifest_url"] = rewritten_manifest_urls
        # 若 file_url 缺失（"无需更新"响应），也注入一个官方原样兜底
        if not vm.get("file_url"):
            vm["file_url"] = [
                "https://gxb-oss.imeete.com/other/files/",
                "https://gxb-cos.imeete.com/other/files/",
            ]
            logger.info("[patch] 注入 file_url (API 未返回)")

        logger.info("[origin] real version.manifest manifest_url=%s (host=%s path=%s all=%d) "
                    "→ECS=%s",
                    first_url, self.real_manifest_host, self.real_manifest_path,
                    len(manifest_urls), rewritten_manifest_urls[0] if rewritten_manifest_urls else None)

        return json.dumps(vm, ensure_ascii=False).encode("utf-8")

    def patch_real_project_manifest(self, real_manifest_bytes: bytes) -> bytes:
        """对回源到的真实线上 project.manifest 做最小 patch：注入/改写 NetConf + ResEnsure 条目 + 顶高版本。

        相比基于 APK 旧版 forge，这里用手机线上真实跑的版本做底，diff 只剩 NetConf + ResEnsure，
        游戏不会再去请求那 91 个本不属于 PC 的文件。

        NetConf.luac 在线上 project.manifest 的 file_list 里**确实存在**（实测真实
        manifest 含 key `src/app/config/NetConf.luac`，小写 config）。游戏的 genDiffList
        按 file_list 的 **key** 比对 md5、并按 **key** 决定落盘路径，故必须原地改写
        游戏已在追踪的那个 key（大小写要与线上一致），而不是注入一个不同大小写的新 key
        ——否则真正的条目没动、幽灵条目落到错路径，diff 出错 / 覆盖落空 → 卡"校验资源"。

        ResEnsure.luac 同样在 file_list 里存在（key `src/app/hotupdate/lobby/ResEnsure.luac`），
        注入跳过校验版本后，游戏下次启动直接跳过 clean_res()，不再卡「校验本地资源」。

        file_url 保持真实原样（指向被劫持的 gxb 域名）→ NetConf/ResEnsure 从 PC 下、其余文件回源。

        失败（非 JSON）时抛异常，由调用方处理（project handler 不再回退静态）。
        """
        import json

        forged = json.loads(real_manifest_bytes.decode("utf-8"))
        file_list = forged.get("file_list")
        if not isinstance(file_list, dict):
            raise KeyError("线上 manifest 缺少 file_list")

        # ① 顶高版本（游戏据此判定有新版且之后不回滚）
        target_key = _find_netconf_key(file_list)
        has_lobby_checker = INJECT_LOBBY_CHECKER and (
            RESENSURE_FILE_KEY in file_list or RESCHECKER_FILE_KEY in file_list
        )
        if not (target_key or has_lobby_checker):
            logger.info("[patch] project.manifest has no lobby hotfix targets; pass through unchanged")
            return real_manifest_bytes

        forged["version"] = self._served_version()

        # ② ★PR2：把 update_url 改写到 ECS（host 换 ECS，path=/hotfix_update，保留原 query
        #    里的 appid/engine_ver/channel/version）。原 update_url 是 list（gxb-api[-tx]
        #    两条），逐条改写。热更完成后 _updateLocalManifest 整体替换 harbor →
        #    getUpdateUrl() 永久指向 ECS，4G 直连 IP 无需 DNS。
        forged_update_url = self._rewrite_update_url(forged.get("update_url"))
        if forged_update_url is not None:
            forged["update_url"] = forged_update_url

        # ③ file_url：official 模式保持官方原样（官方文件 4G 直连官方 CDN，ECS 零带宽）；
        #    ecs 模式（验收）改写为 ECS file base，所有官方文件经 ECS 透传、日志全可见。
        if self.file_url_mode == FILE_URL_MODE_ECS:
            forged["file_url"] = [self._ecs_base() + FILE_URL_PREFIXES[1]]

        # ④ 强制通用逐文件下载，规避 zip 差分/整包压缩
        forged["forbid_zip"] = True
        forged.pop("diff_zip", None)
        forged.pop("zip_url", None)

        # ④ 原地改写 NetConf 条目 → md5/size/name 指向 PC 改写版。
        #    线上 manifest 的 NetConf key 大小写可能与常量不同，按 case-insensitive
        #    找到现有 key 原地改写（保留其原始大小写）；找不到才按小写约定注入。
        if target_key:
            entry = dict(file_list[target_key])
            entry["md5"] = self.served_md5
            entry["size"] = self.served_size
            entry["name"] = self.served_name
            file_list[target_key] = entry

        # ⑤ 注入/改写 ResEnsure / ResChecker 条目 → 跳过校验本地资源（默认关闭）。
        #    INJECT_LOBBY_CHECKER=False 时保持线上原版条目不动，手机从 CDN 回源取回
        #    原版 ResEnsure/ResChecker，原版 clean_res 正常清理 harbor，避免黑屏。
        if INJECT_LOBBY_CHECKER:
            if RESENSURE_FILE_KEY in file_list:
                resensure_entry = dict(file_list[RESENSURE_FILE_KEY])
                resensure_entry["md5"] = self.resensure_md5
                resensure_entry["size"] = self.resensure_size
                resensure_entry["name"] = self.resensure_name
                file_list[RESENSURE_FILE_KEY] = resensure_entry

            if RESCHECKER_FILE_KEY in file_list:
                reschecker_entry = dict(file_list[RESCHECKER_FILE_KEY])
                reschecker_entry["md5"] = self.reschecker_md5
                reschecker_entry["size"] = self.reschecker_size
                reschecker_entry["name"] = self.reschecker_name
                file_list[RESCHECKER_FILE_KEY] = reschecker_entry

        # hotfix_only_manifest 已禁用：file_list 必须保持完整。
        # 只修改 NetConf/ResEnsure/ResChecker 的 md5，其余条目保留线上原样。
        # 游戏的 genDiffList 只会 diff 出 md5 不同的 3 个文件，不会下载其他资源。
        # 若缩减 file_list 会导致游戏找不到其他资源而黑屏。
        # if self.hotfix_only_manifest:
        #     keep_keys = []
        #     for key in (target_key, RESENSURE_FILE_KEY, RESCHECKER_FILE_KEY):
        #         if key and key in file_list and key not in keep_keys:
        #             keep_keys.append(key)
        #     forged["file_list"] = {key: file_list[key] for key in keep_keys}
        #     file_list = forged["file_list"]

        logger.info(
            "[patch] project.manifest: NetConf=%s inject_checker=%s ResEnsure=%s ResChecker=%s "
            "keys=%d update_url→ECS=%s file_url_mode=%s",
            target_key or "-",
            INJECT_LOBBY_CHECKER,
            INJECT_LOBBY_CHECKER and RESENSURE_FILE_KEY in file_list,
            INJECT_LOBBY_CHECKER and RESCHECKER_FILE_KEY in file_list,
            len(file_list),
            (forged_update_url[0] if isinstance(forged_update_url, list) and forged_update_url
             else forged_update_url),
            self.file_url_mode,
        )

        return json.dumps(forged, ensure_ascii=False).encode("utf-8")

    def _rewrite_update_url(self, update_url):
        """把 project.manifest 的 update_url（更新检查端点）改写到 ECS。

        host 换为本服务（ECS）、path 统一为 PATH_VERSION（/hotfix_update）、保留原 query
        里的 appid/engine_ver/channel/version 等参数。原 update_url 可能是 list（gxb-api[-tx]
        两条）或单个字符串，逐条改写，保持 list 条数。无 update_url 时返回 None（不注入）。
        """
        from urllib.parse import urlsplit

        if isinstance(update_url, list):
            urls = [u for u in update_url if isinstance(u, str) and u]
            was_list = True
        elif isinstance(update_url, str) and update_url:
            urls = [update_url]
            was_list = False
        else:
            return None

        ecs_base = self._ecs_base()
        rewritten = []
        for u in urls:
            parts = urlsplit(u)
            # path 统一为 ECS 的 /hotfix_update 端点；保留原 query（appid 等）
            q = ("?" + parts.query) if parts.query else ""
            rewritten.append(ecs_base + PATH_VERSION + q)
        return rewritten if was_list else rewritten[0]


# ─── 从 hotfix_update 请求参数推断 manifest_url ───────────────────────────────

def _infer_manifest_url_from_query(assets: MitmAssets, raw_path: str) -> None:
    """解析 hotfix_update?appid=...&engine_ver=...&channel=...&version=... 参数，
    推断线上 project.manifest 的 URL，存入 assets._inferred_manifest_url。

    当真实 API 返回"无需更新"的极简响应（只有 version）时，patch_real_version_manifest
    用此推断值注入 manifest_url，确保游戏会下载 project.manifest。

    推断规则：线上 CDN URL 格式为
      https://gxb-oss.hzxuanming.com/yj/manifests/{appid}/{engine_ver}/{channel}/project-{version}.manifest
    """
    from urllib.parse import parse_qs
    try:
        qs = raw_path.split("?", 1)[1] if "?" in raw_path else ""
        params = parse_qs(qs)
        appid = params.get("appid", [None])[0]
        engine_ver = params.get("engine_ver", [None])[0]
        channel = params.get("channel", [None])[0]
        version = params.get("version", [None])[0]
        if not all([appid, engine_ver, channel, version]):
            return
        # 线上 CDN 格式（hzxuanming.com 路径，观察自真实 API 响应）
        inferred = (
            f"https://gxb-oss.hzxuanming.com/yj/manifests/"
            f"{appid}/{engine_ver}/{channel}/project-{version}.manifest"
        )
        assets._inferred_manifest_url = inferred
        logger.info("[infer] manifest_url from query: %s (appid=%s engine=%s channel=%s ver=%s)",
                    inferred, appid, engine_ver, channel, version)
    except Exception as exc:
        logger.debug("[infer] parse query failed: %s", exc)


def _downgrade_version_in_path(raw_path: str) -> str:
    """把 hotfix_update URL 中的 version 参数降级为 1.0.0.0。

    手机已是最新版时，API 对当前版本返回 {"version":"xxx"}（极简"无需更新"响应），
    不带 manifest_url。降级 version 让 API 认为手机是旧版，返回完整的 manifest_url +
    file_url + project_md5 + zip_url，我们的 patcher 才能正常工作。
    """
    from urllib.parse import parse_qs, urlencode, urlsplit
    parts = raw_path.split("?", 1)
    if len(parts) < 2:
        return raw_path
    path, qs = parts
    params = parse_qs(qs, keep_blank_values=True)
    if "version" in params:
        params["version"] = ["1.0.0.0"]
    # 重建 query string（保持原始参数顺序不重要）
    new_qs = urlencode(params, doseq=True)
    return f"{path}?{new_qs}"


# ─── HTTPS 处理器 ────────────────────────────────────────────────────────────

def make_http_handler(assets: MitmAssets, enable_origin: bool = True):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass  # 由 do_GET 统一打日志，避免重复

        def _send(self, body: bytes, ctype="application/octet-stream", code=200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _req_host(self) -> str:
            return self.headers.get("Host", "").split(":")[0]

        def do_GET(self):
            client_ip = self.address_string()
            host = self._req_host()
            raw_path = self.path
            path = raw_path.split("?", 1)[0]

            # 1) version.manifest / hotfix_update → 回源真实 version.manifest + 最小改写
            if path == PATH_VERSION or path.endswith("/hotfix_update"):
                self._handle_version_manifest(client_ip, host, raw_path)
                return

            # 2) project.manifest → 回源真实线上 manifest，只 patch NetConf 一条
            #    识别依据：path 命中步骤1记下的真实 manifest_url 的 path（精确）；
            #    兜底弱匹配 PATH_PROJECT / 以 .manifest 结尾。
            if self._is_project_manifest_request(path):
                self._handle_project_manifest(client_ip, host, raw_path)
                return

            # 3) NetConf / ResEnsure / ResChecker 文件请求 → 返回改写后的 luac
            #    支持多种 file_url 前缀（旧 CDN /yj/files/ 和线上真实 /other/files/）
            matched_prefix = None
            for prefix in FILE_URL_PREFIXES:
                if prefix in path:
                    matched_prefix = prefix
                    break
            if matched_prefix:
                rel = path.split(matched_prefix, 1)[1]
                # NetConf 文件
                if rel == assets.served_name or rel.endswith(assets.served_name):
                    logger.info("[mitm] %s host=%s → NetConf.luac (%dB md5=%s)",
                                client_ip, host, len(assets.netconf_luac), assets.served_md5)
                    # ★PR2：NetConf 真被请求 = 首次注入（正常）；官方更新流程中本不应
                    #    出现（md5 恒定→不进 diff），出现=覆盖被误重下，反向告警可 grep。
                    logger.info("[REINJECT] client=%s NetConf.luac re-served md5=%s",
                                client_ip, assets.served_md5)
                    self._send(assets.netconf_luac, "application/octet-stream")
                    return
                # ResEnsure 文件（跳过校验版本）——仅在注入开启时由 PC 提供，
                # 关闭时 name 为 None，跳过这两个分支，走回源取回原版。
                if assets.resensure_name and (rel == assets.resensure_name or rel.endswith(assets.resensure_name)):
                    logger.info("[mitm] %s host=%s → ResEnsure.luac (skip-check, %dB md5=%s)",
                                client_ip, host, len(assets.resensure_luac), assets.resensure_md5)
                    self._send(assets.resensure_luac, "application/octet-stream")
                    return
                # ResChecker 文件（跳过可见的本地资源校验流程）
                if assets.reschecker_name and (rel == assets.reschecker_name or rel.endswith(assets.reschecker_name)):
                    logger.info("[mitm] %s host=%s → ResChecker.luac (official restore, %dB md5=%s)",
                                client_ip, host, len(assets.reschecker_luac), assets.reschecker_md5)
                    self._send(assets.reschecker_luac, "application/octet-stream")
                    return
                # 其余文件 → 回源兜底（透传含 query 的 raw_path）
                self._handle_origin_passthrough(client_ip, host, raw_path)
                return

            # 4) 其它所有文件请求（.manifest/.png/.luac 等）→ 回源真实 CDN 兜底
            self._handle_origin_passthrough(client_ip, host, raw_path)

        def _is_project_manifest_request(self, path: str) -> bool:
            """识别 project.manifest 请求。

            优先用步骤1从真实 version.manifest 记下的 manifest_url path（精确匹配，
            真实存在于线上 CDN）。兜底弱匹配自编 PATH_PROJECT / 以 .manifest 结尾，
            但排除 version.manifest 自身（已在前面 return）。
            """
            if path in assets.real_manifest_paths:
                return True
            real_path = assets.real_manifest_path
            if real_path:
                real_path_only = real_path.split("?", 1)[0]
                if path == real_path_only:
                    return True
            # 兜底弱匹配（真实 manifest_url 尚未记下时；或异常路径）
            if path == PATH_PROJECT or path.endswith("/project.manifest"):
                return True
            filename = path.rsplit("/", 1)[-1]
            if "/manifests/" in path and filename.startswith("project-") and filename.endswith(".manifest"):
                return True
            return False

        def _handle_version_manifest(self, client_ip: str, host: str, raw_path: str):
            """回源真实 version.manifest（透传含 query 的 raw_path，自带 appid 等）→
            最小改写（顶高 version + 清空 project_md5 + 删 zip，保留真实 manifest_url/file_url）。
            回源失败/非 JSON → 回退现有伪 version.manifest（绝不挂请求）。
            """
            logger.info("[mitm] %s host=%s path=%s → version.manifest (origin fetch...)",
                        client_ip, host, raw_path)
            # 从请求参数推断 manifest_url（当 API 返回"无需更新"时备用）
            _infer_manifest_url_from_query(assets, raw_path)
            # 回源时把 version 降级为 1.0.0.0，确保真实 API 返回完整的 manifest_url
            # （否则手机已是最新版时 API 只返回 {"version":"xxx"}，不带 manifest_url）
            origin_path = _downgrade_version_in_path(raw_path)
            if not enable_origin:
                logger.info("[mitm] %s host=%s → version.manifest (static, v=%s)",
                            client_ip, host, assets.version)
                self._send(assets.version_manifest, "application/json")
                return
            # ★PR2：回源官方 version.manifest 改用硬编码官方 update host（不依赖进来的
            #    Host 头——4G 下 Host=ECS IP）。主 host 失败回退备 host。
            status, body = 502, b""
            used_host = None
            for official_host in OFFICIAL_UPDATE_HOSTS:
                status, body, _ = _origin_fetch(official_host, origin_path)
                if status == 200 and body:
                    used_host = official_host
                    break
            if status == 200 and body:
                # 调试：打印回源响应前200字节
                logger.info("[mitm] %s host=%s version.manifest origin body(200B): %s",
                            client_ip, used_host, body[:200])
                try:
                    patched = assets.patch_real_version_manifest(body)
                    served = assets._served_version()
                    manifest_url_to_ecs = None
                    try:
                        import json as _json
                        _vm = _json.loads(patched.decode("utf-8"))
                        _mu = _vm.get("manifest_url")
                        manifest_url_to_ecs = _mu[0] if isinstance(_mu, list) and _mu else _mu
                    except Exception:
                        pass
                    logger.info("[CHAIN-VER] client=%s real_online=%s served=%s manifest_url→ECS=%s",
                                client_ip, assets.real_online_version, served, manifest_url_to_ecs)
                    self._send(patched, "application/json")
                    return
                except Exception as exc:
                    logger.warning("[mitm] %s host=%s version.manifest patch failed: %s "
                                   "→ fallback static", client_ip, used_host, exc)
            else:
                logger.warning("[mitm] %s host=%s version.manifest origin fetch status=%s "
                               "→ fallback static", client_ip, host, status)
            # 兜底：回退到静态伪 version.manifest（绝不挂请求）
            self._send(assets.version_manifest, "application/json")

        def _handle_project_manifest(self, client_ip: str, host: str, raw_path: str):
            """按真实 manifest_url 回源线上 project.manifest，失败时兜底静态 manifest。

            setup 阶段必须优先让客户端拿到可下载的最小热更包；回源失败只写日志，
            对手机返回已经 patch 过 NetConf / ResEnsure / ResChecker 的静态 manifest。
            """
            if not enable_origin:
                logger.info("[mitm] %s host=%s → project.manifest (static, %dB)",
                            client_ip, host, len(assets.project_manifest))
                self._send(assets.project_manifest, "application/json")
                return
            # ★PR2：回源官方 project.manifest 改用捕获的官方 manifest host（不依赖进来的
            #    Host 头——4G 下 Host=ECS IP）。优先按 path 命中的官方 host，再退 first-seen
            #    real_manifest_host，最后退硬编码 OFFICIAL_MANIFEST_HOST。
            path_only = raw_path.split("?", 1)[0]
            origin_host = (
                assets.real_manifest_hosts_by_path.get(path_only)
                or assets.real_manifest_host
                or OFFICIAL_MANIFEST_HOST
            )
            status, body, _ = _origin_fetch(origin_host, raw_path)
            if status == 200 and body:
                try:
                    patched = assets.patch_real_project_manifest(body)
                    served = assets._served_version()
                    update_url_to_ecs = None
                    file_count = 0
                    try:
                        import json as _json
                        _pm = _json.loads(patched.decode("utf-8"))
                        _uu = _pm.get("update_url")
                        update_url_to_ecs = _uu[0] if isinstance(_uu, list) and _uu else _uu
                        _fl = _pm.get("file_list")
                        file_count = len(_fl) if isinstance(_fl, dict) else 0
                    except Exception:
                        pass
                    logger.info("[CHAIN-PROJ] client=%s real_online=%s served=%s "
                                "netconf_md5=%s(const) update_url→ECS=%s file_count=%d",
                                client_ip, assets.real_online_version, served,
                                assets.served_md5, update_url_to_ecs, file_count)
                    self._send(patched, "application/json")
                    return
                except Exception as exc:
                    logger.error("[mitm] %s host=%s project.manifest patch failed: %s "
                                 "→ static fallback", client_ip, origin_host, exc)
                    self._send(assets.project_manifest, "application/json")
                    return
            logger.error("[mitm] %s host=%s project.manifest origin fetch status=%s "
                         "→ static fallback", client_ip, origin_host, status)
            self._send(assets.project_manifest, "application/json")

        def _handle_origin_passthrough(self, client_ip: str, host: str, path: str):
            if not enable_origin:
                logger.warning("[mitm] %s host=%s → %s (no-origin, 404)", client_ip, host, path)
                self._send(b"", code=404)
                return
            # ★PR2：official 模式维持现状（用进来的 Host 头回源——official 模式下文件
            #    请求本就直连官方、不经此路径，保持兼容）。ecs 模式（验收）下 4G 文件经
            #    ECS 透传，进来的 Host=ECS IP 不能用来回源，改用硬编码官方 file host。
            origin_host = host
            if assets.file_url_mode == FILE_URL_MODE_ECS:
                origin_host = OFFICIAL_FILE_HOST
            if not origin_host:
                logger.warning("[mitm] %s host=%s → %s (no-origin-host, 404)", client_ip, host, path)
                self._send(b"", code=404)
                return
            status, body, ctype = _origin_fetch(origin_host, path)
            if status and status != 502:
                logger.info("[mitm] %s host=%s → %s (origin %s, %dB)",
                            client_ip, origin_host, path, status, len(body))
                if assets.file_url_mode == FILE_URL_MODE_ECS:
                    name = path.split("?", 1)[0].rsplit("/", 1)[-1]
                    logger.info("[OFFICIAL-FILE] client=%s %s %dB", client_ip, name, len(body))
                self._send(body, ctype or "application/octet-stream", code=status)
                return
            logger.warning("[mitm] %s host=%s → %s (origin failed status=%s, 404)",
                           client_ip, origin_host, path, status)
            self._send(b"", code=404)

    return Handler


# ─── 自签证书 ────────────────────────────────────────────────────────────────

def generate_self_signed_cert(cert_path: str, key_path: str, cn: str = "gxb.hzxuanming.com") -> None:
    """生成自签 RSA 证书（CN 随便；VERIFYPEER=0 接受）。"""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    san = x509.SubjectAlternativeName([x509.DNSName(d) for d in HIJACK_DOMAINS])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject).issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )
    with open(key_path, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def start_https_server(assets: MitmAssets, host: str, port: int,
                       cert_path: str, key_path: str,
                       enable_origin: bool = True) -> ThreadingHTTPServer:
    import ssl
    if not (os.path.exists(cert_path) and os.path.exists(key_path)):
        generate_self_signed_cert(cert_path, key_path)
    httpd = ThreadingHTTPServer((host, port), make_http_handler(assets, enable_origin))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    logger.info("HTTPS MITM server on %s:%d", host, port)
    return httpd


# ─── 最小 DNS 响应器（UDP）───────────────────────────────────────────────────

class DnsResponder:
    """把 HIJACK_DOMAINS 的 A 查询解析到 self_ip；其余转发上游（或返回空）。"""

    def __init__(self, self_ip: str, listen_host: str | None = None, port: int = 53,
                 upstream: str = "223.5.5.5"):
        self.self_ip = self_ip
        # 绑定到热点适配器 IP 而非 0.0.0.0，避免和 ICS DNS 代理冲突
        # Windows ICS 绑 0.0.0.0:53，我们绑 192.168.137.1:53 优先收包
        self.listen_host = listen_host or self_ip
        self.port = port
        self.upstream = upstream
        self._sock = None
        self._running = False

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.listen_host, self.port))
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        logger.info("DNS responder on %s:%d -> hijack %s as %s",
                    self.listen_host, self.port, sorted(HIJACK_DOMAINS), self.self_ip)

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass

    def _loop(self) -> None:
        while self._running:
            try:
                data, addr = self._sock.recvfrom(2048)
            except OSError:
                break
            try:
                resp = self._handle(data)
                if resp:
                    self._sock.sendto(resp, addr)
            except Exception as e:
                logger.debug("DNS handle error: %s", e)

    @staticmethod
    def _parse_qname(data: bytes) -> tuple[str, int]:
        """解析 DNS question 的 qname，返回 (name, offset_after_qname_qtype_qclass)。"""
        off = 12  # header
        labels = []
        while True:
            length = data[off]; off += 1
            if length == 0:
                break
            labels.append(data[off:off + length].decode("ascii", errors="replace"))
            off += length
        name = ".".join(labels)
        off += 4  # qtype(2) + qclass(2)
        return name, off

    def _handle(self, data: bytes) -> bytes | None:
        if len(data) < 12:
            return None
        name, qend = self._parse_qname(data)
        qtype = struct.unpack_from(">H", data, qend - 4)[0]

        if name.lower() in HIJACK_DOMAINS and qtype == 1:  # A record
            return self._build_a_response(data, qend, self.self_ip)

        # 非劫持域名：转发上游（保持手机正常上网）
        return self._forward_upstream(data)

    def _build_a_response(self, query: bytes, qend: int, ip: str) -> bytes:
        tid = query[:2]
        flags = b"\x81\x80"  # response, recursion available, no error
        qdcount = b"\x00\x01"
        ancount = b"\x00\x01"
        header = tid + flags + qdcount + ancount + b"\x00\x00\x00\x00"
        question = query[12:qend]
        answer = (
            b"\xc0\x0c"            # name pointer to question
            + b"\x00\x01"          # type A
            + b"\x00\x01"          # class IN
            + b"\x00\x00\x00\x3c"  # TTL 60s
            + b"\x00\x04"          # rdlength 4
            + socket.inet_aton(ip)
        )
        return header + question + answer

    def _forward_upstream(self, query: bytes) -> bytes | None:
        try:
            up = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            up.settimeout(2.0)
            up.sendto(query, (self.upstream, 53))
            resp, _ = up.recvfrom(2048)
            up.close()
            return resp
        except Exception:
            return None


# ─── 顶层启动 ────────────────────────────────────────────────────────────────

def run(host_ip: str, ecs_ip: str = DEFAULT_ECS_IP, apk_path: str = DEFAULT_APK,
        tls_port: int = 443, dns_port: int = 53, no_dns: bool = False,
        cert_dir: str = None, enable_origin: bool = True,
        bump_version: str = "9.9.9.103", dns_listen_host: str | None = None,
        file_url_mode: str = FILE_URL_MODE_OFFICIAL,
        manifest_url_mode: str = MANIFEST_URL_MODE_ECS):
    """启动热更 MITM（HTTPS manifest 服务 + DNS 劫持）。

    host_ip: 写进 DNS 应答 / NetConf / manifest 的地址（手机据此连本服务的 443）。
             PC 热点场景 = 热点网关 IP；ECS 场景 = ECS 公网 IP。
    dns_listen_host: DNS 响应器实际 bind 的本机地址。None 时默认 = host_ip。
             ECS 在 NAT 后，公网 IP 不是本机网卡可绑地址，需显式传 eth0 私网 IP
             （如 172.16.x.x），应答里仍返回 host_ip(公网)。
    """
    cert_dir = cert_dir or os.path.join(_RUNTIME_ROOT, "data", "mitm")
    os.makedirs(cert_dir, exist_ok=True)
    cert_path = os.path.join(cert_dir, "mitm_cert.pem")
    key_path = os.path.join(cert_dir, "mitm_key.pem")

    assets = MitmAssets(apk_path, ecs_ip, host_ip, tls_port=tls_port, bump_version=bump_version,
                        file_url_mode=file_url_mode, manifest_url_mode=manifest_url_mode)
    httpd = start_https_server(assets, "0.0.0.0", tls_port, cert_path, key_path,
                               enable_origin=enable_origin)

    dns = None
    if not no_dns:
        # self_ip=host_ip（应答里返回的地址=公网），listen_host=实际 bind 地址
        dns = DnsResponder(host_ip, listen_host=dns_listen_host, port=dns_port)
        dns.start()

    return assets, httpd, dns


# ─── 离线自测 ────────────────────────────────────────────────────────────────

def _selftest() -> None:
    import hashlib
    import json
    import time

    import requests
    import urllib3
    urllib3.disable_warnings()

    print("=== setup_mitm 离线自测 ===")
    # 用 127.0.0.1 + 高端口（免管理员），关 DNS（本地用 IP 直连测路由）
    # enable_origin=False：本地无回源，project.manifest 回退静态、文件请求回 404/静态
    assets, httpd, _ = run("127.0.0.1", tls_port=8443, no_dns=True, enable_origin=False)
    time.sleep(0.4)
    base = "https://127.0.0.1:8443"

    # 1) version.manifest
    r = requests.get(base + PATH_VERSION + "?env=1&version=1.0.0.50", verify=False, timeout=5)
    assert r.status_code == 200, r.status_code
    vm = json.loads(r.content)
    assert vm["version"] == assets._served_version(), vm["version"]
    assert vm["manifest_url"] and vm["file_url"]
    print(f"[OK] /hotfix_update → version={vm['version']} manifest_url={vm['manifest_url'][0]}")

    # 2) project.manifest
    r = requests.get(base + PATH_PROJECT, verify=False, timeout=5)
    assert r.status_code == 200
    pm = json.loads(r.content)
    assert pm["version"] == assets._served_version(), pm["version"]
    assert pm["forbid_zip"] is True
    nc = pm["file_list"]["src/app/config/NetConf.luac"]
    assert nc["md5"] == assets.served_md5
    re_entry = pm["file_list"]["src/app/hotupdate/lobby/ResEnsure.luac"]
    rc_entry = pm["file_list"]["src/app/hotupdate/lobby/ResChecker.luac"]
    if INJECT_LOBBY_CHECKER:
        assert re_entry["md5"] == assets.resensure_md5
        assert rc_entry["md5"] == assets.reschecker_md5
    print(f"[OK] project.manifest → version={pm['version']} forbid_zip={pm['forbid_zip']} "
          f"inject_checker={INJECT_LOBBY_CHECKER} NetConf.md5={nc['md5']} "
          f"ResEnsure.md5={re_entry['md5']} ResChecker.md5={rc_entry['md5']}")

    # 3) NetConf.luac 文件下载 + md5 校验
    file_url = base + FILE_URL_PREFIXES[0] + assets.served_name
    r = requests.get(file_url, verify=False, timeout=5)
    assert r.status_code == 200, r.status_code
    got_md5 = hashlib.md5(r.content).hexdigest()
    assert got_md5 == nc["md5"], (got_md5, nc["md5"])
    assert got_md5 == assets.served_md5
    assert r.content[:13] == b"devaguopeifei", r.content[:13]
    print(f"[OK] GET {assets.served_name} → {len(r.content)}B md5={got_md5} (== manifest md5)")

    # 4) ResEnsure / ResChecker 文件下载 + md5 校验（仅在注入开启时由 PC 提供）
    if INJECT_LOBBY_CHECKER:
        for label, entry, expected_md5, expected_prefix in [
            ("ResEnsure", re_entry, assets.resensure_md5, b"devaguopeifei"),
            ("ResChecker", rc_entry, assets.reschecker_md5, b"devaguopeifei"),
        ]:
            file_url = base + FILE_URL_PREFIXES[0] + entry["name"]
            r = requests.get(file_url, verify=False, timeout=5)
            assert r.status_code == 200, (label, r.status_code)
            got_md5 = hashlib.md5(r.content).hexdigest()
            assert got_md5 == expected_md5, (label, got_md5, expected_md5)
            assert r.content[:13] == expected_prefix, (label, r.content[:13])
            print(f"[OK] GET {entry['name']} → {label} {len(r.content)}B md5={got_md5}")
    else:
        print("[OK] ResEnsure/ResChecker 注入已禁用，跳过其文件下载自测（由 CDN 回源原版）")

    # 5) DNS 响应器单元测试（构造一个 A 查询，断言返回 host_ip）
    # listen_host 显式绑 127.0.0.1（self_ip=10.0.0.1 仅作为应答里返回的地址，
    # 不一定是本机可绑地址）。
    dns = DnsResponder("10.0.0.1", listen_host="127.0.0.1", port=15353)
    dns.start()
    time.sleep(0.2)
    q = _build_dns_query("gxb-oss.hzxuanming.com")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2.0)
    s.sendto(q, ("127.0.0.1", 15353))
    resp, _ = s.recvfrom(2048)
    s.close()
    dns.stop()
    ip = socket.inet_ntoa(resp[-4:])
    assert ip == "10.0.0.1", ip
    print(f"[OK] DNS gxb-oss.hzxuanming.com → {ip}")

    # 6) _parse_first_a：构造一个含 A 记录的 DNS 响应，断言能取到 IP（不联网）
    fake_resp = _build_a_dns_response("gxb-oss.hzxuanming.com", "1.2.3.4")
    parsed = _parse_first_a(fake_resp)
    assert parsed == "1.2.3.4", parsed
    print(f"[OK] _parse_first_a → {parsed}")

    # 7) patch_real_project_manifest：用真实 APK 的 manifest 当「线上版」回源样本，
    #    断言只 patch lobby 相关条目 + 顶高版本 + forbid_zip（不联网）
    #    注意：hotfix_only_manifest 已禁用，file_list 保持完整，只改 3 个条目的 md5
    from .manifest_forge import load_real_manifest
    real_manifest = load_real_manifest(assets.apk_path)
    real_bytes = json.dumps(real_manifest, ensure_ascii=False).encode("utf-8")
    patched_bytes = assets.patch_real_project_manifest(real_bytes)
    patched = json.loads(patched_bytes.decode("utf-8"))
    real_fl = real_manifest["file_list"]
    patched_fl = patched["file_list"]
    assert patched["version"] == assets._served_version(), patched["version"]
    assert patched["forbid_zip"] is True
    assert "diff_zip" not in patched and "zip_url" not in patched
    # ★PR2：official 模式 file_url 保持真实原样（官方文件 4G 直连官方 CDN）
    assert patched.get("file_url") == real_manifest.get("file_url"), patched.get("file_url")
    # ★PR2：update_url 改写到 ECS（host 换 ECS、path=/hotfix_update、保留原 query）
    real_uu = real_manifest.get("update_url")
    if real_uu:
        from urllib.parse import urlsplit as _urlsplit
        ecs_base = assets._ecs_base()
        patched_uu = patched.get("update_url")
        assert isinstance(patched_uu, list) and len(patched_uu) == len(real_uu), patched_uu
        for orig, new in zip(real_uu, patched_uu):
            assert new.startswith(ecs_base + PATH_VERSION), new
            assert _urlsplit(new).query == _urlsplit(orig).query, (new, orig)
            assert "appid=" in new, new
        print(f"[OK] update_url → ECS: {patched_uu[0]}")
    nc = patched_fl["src/app/config/NetConf.luac"]
    assert nc["md5"] == assets.served_md5 and nc["size"] == assets.served_size
    assert nc["name"] == assets.served_name
    # ResEnsure/ResChecker：注入开启时被改写；关闭时保持线上原版（不动）
    re_entry = patched_fl.get("src/app/hotupdate/lobby/ResEnsure.luac")
    rc_entry = patched_fl.get("src/app/hotupdate/lobby/ResChecker.luac")
    if INJECT_LOBBY_CHECKER:
        assert re_entry and re_entry["md5"] == assets.resensure_md5
        assert rc_entry and rc_entry["md5"] == assets.reschecker_md5
    else:
        # 关闭时不得改写：md5 应与线上原版一致
        if "src/app/hotupdate/lobby/ResEnsure.luac" in real_fl:
            assert re_entry["md5"] == real_fl["src/app/hotupdate/lobby/ResEnsure.luac"]["md5"]
        if "src/app/hotupdate/lobby/ResChecker.luac" in real_fl:
            assert rc_entry["md5"] == real_fl["src/app/hotupdate/lobby/ResChecker.luac"]["md5"]
    # hotfix_only_manifest 已禁用：file_list 保持完整，只断言 3 个关键条目被修改
    assert len(patched_fl) == len(real_fl), (len(patched_fl), len(real_fl))
    print(f"[OK] patch_real_project_manifest → 热更条目已修改: NetConf/ResEnsure/ResChecker, "
          f"version={patched['version']}, forbid_zip={patched['forbid_zip']}, "
          f"file_url 保持真实 {patched.get('file_url')}, total_keys={len(patched_fl)}")

    # 8) 非 lobby / 非主包 manifest 不应被注入 lobby 条目，避免多 appid 并发时误改小游戏 manifest。
    non_lobby_bytes = json.dumps({
        "version": "1.0.0.1",
        "file_list": {
            "subgame/main.luac": {"md5": "abc", "size": 3, "name": "aa/abc.luac"}
        },
    }, ensure_ascii=False).encode("utf-8")
    assert assets.patch_real_project_manifest(non_lobby_bytes) == non_lobby_bytes
    print("[OK] patch_real_project_manifest → 非 lobby manifest 原样透传")

    # 9) patch_real_version_manifest：构造一个真实样式 version.manifest，断言最小改写 +
    #    多个 real_manifest_path/host 都被记下（不联网）
    fake_vm = json.dumps({
        "version": "1.0.0.51",
        "update_type": 1,
        "manifest_url": [
            "https://gxb-oss.hzxuanming.com/yj/proj/project_10001.manifest?appid=10001",
            "https://gxb-cos.hzxuanming.com/yj/manifests/1073/1.0.0.16/198/project-1.0.0.16.manifest",
        ],
        "file_url": ["https://gxb-oss.hzxuanming.com/yj/files/"],
        "project_md5": "deadbeef",
        "diff_zip": {"url": "x"},
        "zip_url": ["y"],
    }, ensure_ascii=False).encode("utf-8")
    patched_vm = json.loads(assets.patch_real_version_manifest(fake_vm).decode("utf-8"))
    # 下发版本 = 4 段缓冲支配版本：真实线上版每段 +缓冲偏移(1,5,9,3001)，段数与官方一致
    assert assets.real_online_version == "1.0.0.51", assets.real_online_version
    assert patched_vm["version"] == "2.5.9.3052", patched_vm["version"]  # 1.0.0.51 → 2.5.9.3052
    _sv = [int(x) for x in patched_vm["version"].split(".")]
    _rv = [int(x) for x in "1.0.0.51".split(".")]
    assert len(_sv) == len(_rv) and all(a >= b for a, b in zip(_sv, _rv)) and any(a > b for a, b in zip(_sv, _rv)), patched_vm["version"]
    assert patched_vm["project_md5"] == ""
    assert "diff_zip" not in patched_vm and "zip_url" not in patched_vm
    # ★PR2：manifest_url 已改写到 ECS（保留官方 path+query，host 换 ECS）
    _ecs = assets._ecs_base()
    assert patched_vm["manifest_url"] == [
        _ecs + "/yj/proj/project_10001.manifest?appid=10001",
        _ecs + "/yj/manifests/1073/1.0.0.16/198/project-1.0.0.16.manifest",
    ], patched_vm["manifest_url"]
    assert patched_vm["file_url"] == ["https://gxb-oss.hzxuanming.com/yj/files/"]
    # 仍记下真实官方 manifest_url 的 host + path（含 query），供 project handler 回源
    assert assets.real_manifest_host == "gxb-oss.hzxuanming.com", assets.real_manifest_host
    assert assets.real_manifest_path == "/yj/proj/project_10001.manifest?appid=10001", assets.real_manifest_path
    assert "/yj/proj/project_10001.manifest" in assets.real_manifest_paths
    assert "/yj/manifests/1073/1.0.0.16/198/project-1.0.0.16.manifest" in assets.real_manifest_paths
    print(f"[OK] patch_real_version_manifest → version={patched_vm['version']} "
          f"project_md5='' real_manifest_host={assets.real_manifest_host} "
          f"real_manifest_path={assets.real_manifest_path} all_paths={len(assets.real_manifest_paths)}")

    httpd.shutdown()
    print("\n[ALL PASS] setup_mitm 离线自测全部通过")


def _build_dns_query(name: str) -> bytes:
    tid = b"\xab\xcd"
    flags = b"\x01\x00"  # standard query, recursion desired
    counts = b"\x00\x01\x00\x00\x00\x00\x00\x00"
    q = b""
    for label in name.split("."):
        q += bytes([len(label)]) + label.encode("ascii")
    q += b"\x00"
    q += b"\x00\x01\x00\x01"  # type A, class IN
    return tid + flags + counts + q


def _build_a_dns_response(name: str, ip: str) -> bytes:
    """构造一个含单条 A 记录的 DNS 响应（仅供 _parse_first_a 自测用）。"""
    tid = b"\xab\xcd"
    flags = b"\x81\x80"
    counts = b"\x00\x01\x00\x01\x00\x00\x00\x00"  # qd=1, an=1
    q = b""
    for label in name.split("."):
        q += bytes([len(label)]) + label.encode("ascii")
    q += b"\x00" + b"\x00\x01\x00\x01"  # type A, class IN
    answer = (
        b"\xc0\x0c"            # name pointer
        + b"\x00\x01"          # type A
        + b"\x00\x01"          # class IN
        + b"\x00\x00\x00\x3c"  # TTL
        + b"\x00\x04"          # rdlength
        + socket.inet_aton(ip)
    )
    return tid + flags + counts + q + answer


def main() -> None:
    ap = argparse.ArgumentParser(description="热更 MITM 设置期服务（DNS + 自签 HTTPS + 伪 manifest）")
    ap.add_argument("--host-ip", help="PC 热点 IP（手机看到的网关 IP），DNS 把游戏域名解析到它")
    ap.add_argument("--ecs-ip", default=DEFAULT_ECS_IP, help="ECS 公网 IP（写进 NetConf）")
    ap.add_argument("--apk", default=DEFAULT_APK)
    ap.add_argument("--tls-port", type=int, default=443)
    ap.add_argument("--dns-port", type=int, default=53)
    ap.add_argument("--dns-listen-host", default=None,
                    help="DNS 响应器实际 bind 地址（ECS NAT 场景传 eth0 私网 IP，"
                         "如 172.16.x.x；应答仍返回 --host-ip）。默认 = --host-ip")
    ap.add_argument("--no-dns", action="store_true", help="只起 HTTPS，不起 DNS")
    ap.add_argument("--no-origin", action="store_true",
                    help="禁用透明回源（project.manifest 回退静态、文件请求 404；调试用）")
    ap.add_argument("--file-url-mode", choices=[FILE_URL_MODE_OFFICIAL, FILE_URL_MODE_ECS],
                    default=FILE_URL_MODE_OFFICIAL,
                    help="file_url 改写模式：official（默认/生产，官方文件 4G 直连官方 CDN）"
                         " / ecs（验收，官方文件经 ECS 透传、日志全可见）")
    ap.add_argument("--selftest", action="store_true", help="跑离线自测后退出")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.selftest:
        _selftest()
        return

    if not args.host_ip:
        ap.error("--host-ip 必填（除非 --selftest）")

    run(args.host_ip, ecs_ip=args.ecs_ip, apk_path=args.apk,
        tls_port=args.tls_port, dns_port=args.dns_port, no_dns=args.no_dns,
        enable_origin=not args.no_origin, dns_listen_host=args.dns_listen_host,
        file_url_mode=args.file_url_mode)
    logger.info("MITM 设置期服务已启动；手机连热点开游戏触发热更即可。Ctrl+C 退出。")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
