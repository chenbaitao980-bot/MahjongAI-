from __future__ import annotations

import queue
import threading

_q: queue.Queue[str | None] = queue.Queue()
_thread: threading.Thread | None = None


def _tts_worker() -> None:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    speaker.Volume = 100   # 0-100
    speaker.Rate = -1      # -10(最慢) ~ +10(最快)，-1 接近正常语速

    # 优先选中文语音
    voices = speaker.GetVoices()
    for i in range(voices.Count):
        desc = voices.Item(i).GetDescription()
        if "Chinese" in desc or "Huihui" in desc or "Yaoyao" in desc:
            speaker.Voice = voices.Item(i)
            break

    while True:
        text = _q.get()
        if text is None:
            break
        try:
            speaker.Speak(text)   # 同步阻塞，说完再取下一条
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
