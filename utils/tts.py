from __future__ import annotations

import queue
import threading

_q: queue.Queue[str | None] = queue.Queue()
_thread: threading.Thread | None = None

# SAPI flags
_SVSFlagsAsync = 1
_SVSFIsXML = 0x20


def _tts_worker() -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    speaker.Volume = 100
    speaker.Rate = -2   # 稍慢，吐字更清晰

    # 优先选中文语音
    voices = speaker.GetVoices()
    for i in range(voices.Count):
        desc = voices.Item(i).GetDescription()
        if "Chinese" in desc or "Huihui" in desc or "Yaoyao" in desc:
            speaker.Voice = voices.Item(i)
            break

    # 预热音频设备：播一段静音，避免第一次真正播报时被硬件丢开头
    speaker.Speak('<silence msec="300"/>', _SVSFIsXML)
    speaker.WaitUntilDone(-1)

    while True:
        text = _q.get()
        if text is None:
            break
        try:
            # 每条前加 80ms 静音垫片，防止音频设备省电后截断开头
            xml = f'<silence msec="80"/>{text}'
            speaker.Speak(xml, _SVSFlagsAsync | _SVSFIsXML)
            speaker.WaitUntilDone(-1)
        except Exception:
            pass


def _ensure_thread() -> None:
    global _thread
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_tts_worker, daemon=True)
        _thread.start()


def speak_discard(tile_chinese_name: str) -> None:
    """异步播报推荐出牌，不阻塞UI主线程。"""
    _ensure_thread()
    _q.put(f"打{tile_chinese_name}")
