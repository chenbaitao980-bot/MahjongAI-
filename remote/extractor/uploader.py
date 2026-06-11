"""
uploader.py — HTTP 客户端，向 relay 推送数据

提供：
- register(relay_url, api_token, handshake_blob, auth_token_12b) -> bool
- push(relay_url, api_token, snapshot) -> bool
"""
import logging

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

_LOGGER = logging.getLogger("remote.extractor.uploader")


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


def register(relay_url, api_token, handshake_blob, auth_token_12b):
    """
    向 relay 注册认证凭证。

    relay_url: str，如 "http://1.2.3.4:8000"
    api_token: str，鉴权密钥
    handshake_blob: bytes
    auth_token_12b: bytes
    返回 True 表示成功
    """
    url = relay_url.rstrip("/") + "/register"
    data = {
        "handshake_blob": handshake_blob.hex(),
        "auth_token_12b": auth_token_12b.hex(),
        "api_token": api_token,
    }
    success, code = _post(url, data)
    if success:
        print("[Uploader] Token 已注册到 relay ({})".format(url))
    return success


def register_room(relay_url, api_token, room_id, game_id):
    """
    向 relay 上报房间信息（通道B：零配置旁观）。

    relay_url: str，如 "http://1.2.3.4:8000"
    api_token: str，鉴权密钥
    room_id: int
    game_id: int
    返回 True 表示成功
    """
    url = relay_url.rstrip("/") + "/register-room"
    data = {
        "room_id": room_id,
        "game_id": game_id,
        "api_token": api_token,
    }
    success, code = _post(url, data)
    if success:
        print("[Uploader] 房间信息已上报到 relay (roomid={}, gameid={})".format(room_id, game_id))
    return success


def push(relay_url, api_token, snapshot):
    """
    向 relay 推送当前游戏状态快照。

    snapshot: dict，来自 PacketStateTracker.snapshot()
    返回 True 表示成功
    """
    url = relay_url.rstrip("/") + "/push"
    data = {
        "snapshot": snapshot,
        "api_token": api_token,
    }
    success, _code = _post(url, data, timeout=5)
    return success
