"""
uploader.py — HTTP 客户端，向 relay 推送数据

提供：
- register(relay_urls, api_token, handshake_blob, auth_token_12b) -> bool
- push(relay_urls, api_token, snapshot) -> bool

支持多目标推送：relay_urls 可以是 str 或 list[str]，
列表时会向所有目标依次推送，任一成功即返回 True。
"""
import logging

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

_LOGGER = logging.getLogger("remote.extractor.uploader")


def _normalize_urls(relay_urls) -> list:
    """将 relay_urls 统一为列表形式。

    支持输入：
    - str: "http://1.2.3.4:8000" → ["http://1.2.3.4:8000"]
    - list[str]: ["http://1.2.3.4:8000", "http://1.2.3.4:8001"] → 不变
    """
    if isinstance(relay_urls, str):
        return [relay_urls]
    if isinstance(relay_urls, (list, tuple)):
        return list(relay_urls)
    return [str(relay_urls)]


def _post(url, data, timeout=10):
    """发送 POST 请求，返回 (success: bool, status_code: int)"""
    if not _HAS_REQUESTS:
        _LOGGER.error("requests 未安装，无法上传。请运行: pip install requests")
        return False, 0
    try:
        resp = requests.post(url, json=data, timeout=timeout)
        if resp.status_code == 200:
            return True, resp.status_code
        else:
            _LOGGER.warning("POST %s 返回 %s: %s", url, resp.status_code, resp.text[:200])
            return False, resp.status_code
    except Exception as exc:
        _LOGGER.error("POST %s 失败: %s", url, exc)
        return False, 0


def register(relay_urls, api_token, handshake_blob, auth_token_12b, srs_sessionid=None):
    """
    向 relay 注册认证凭证。

    relay_urls: str 或 list[str]，如 "http://1.2.3.4:8000" 或
                ["http://1.2.3.4:8000", "http://1.2.3.4:8001"]
    api_token: str，鉴权密钥
    handshake_blob: bytes
    auth_token_12b: bytes
    srs_sessionid: bytes or None，SRS 层 sessionid (16B)
    返回 True 表示至少一个目标成功
    """
    urls = _normalize_urls(relay_urls)
    any_success = False
    for relay_url in urls:
        url = relay_url.rstrip("/") + "/register"
        data = {
            "handshake_blob": handshake_blob.hex(),
            "auth_token_12b": auth_token_12b.hex(),
            "api_token": api_token,
        }
        if srs_sessionid:
            data["srs_sessionid"] = srs_sessionid.hex()
        success, code = _post(url, data)
        if success:
            print("[Uploader] Token 已注册到 relay ({})".format(url))
            any_success = True
        else:
            _LOGGER.warning("注册失败: %s", url)
    return any_success


def register_room(relay_urls, api_token, room_id, game_id):
    """
    向 relay 上报房间信息（通道B：零配置旁观）。

    relay_urls: str 或 list[str]
    api_token: str，鉴权密钥
    room_id: int
    game_id: int
    返回 True 表示至少一个目标成功
    """
    urls = _normalize_urls(relay_urls)
    any_success = False
    for relay_url in urls:
        url = relay_url.rstrip("/") + "/register-room"
        data = {
            "room_id": room_id,
            "game_id": game_id,
            "api_token": api_token,
        }
        success, code = _post(url, data)
        if success:
            print("[Uploader] 房间信息已上报到 relay (roomid={}, gameid={})".format(room_id, game_id))
            any_success = True
        else:
            _LOGGER.warning("房间信息上报失败: %s", url)
    return any_success


def push(relay_urls, api_token, snapshot):
    """
    向 relay 推送当前游戏状态快照。

    relay_urls: str 或 list[str]
    snapshot: dict，来自 PacketStateTracker.snapshot()
    返回 True 表示至少一个目标成功
    """
    urls = _normalize_urls(relay_urls)
    any_success = False
    for relay_url in urls:
        url = relay_url.rstrip("/") + "/push"
        data = {
            "snapshot": snapshot,
            "api_token": api_token,
        }
        success, _code = _post(url, data, timeout=5)
        if success:
            any_success = True
    return any_success
