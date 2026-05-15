from __future__ import annotations

import queue
import threading

_q: queue.Queue[str | None] = queue.Queue()
_thread: threading.Thread | None = None


def _tts_worker() -> None:
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", 150)
    for voice in engine.getProperty("voices"):
        vid = voice.id.lower() if voice.id else ""
        vname = voice.name.lower() if voice.name else ""
        if "zh" in vid or "chinese" in vname or "huihui" in vname or "yaoyao" in vname:
            engine.setProperty("voice", voice.id)
            break
    while True:
        text = _q.get()
        if text is None:
            break
        try:
            engine.say(text)
            engine.runAndWait()
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
