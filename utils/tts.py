from __future__ import annotations

import threading

_engine = None
_lock = threading.Lock()


def _get_engine():
    global _engine
    if _engine is None:
        import pyttsx3
        _engine = pyttsx3.init()
        _engine.setProperty("rate", 150)
        for voice in _engine.getProperty("voices"):
            vid = voice.id.lower() if voice.id else ""
            vname = voice.name.lower() if voice.name else ""
            if "zh" in vid or "chinese" in vname or "huihui" in vname or "yaoyao" in vname:
                _engine.setProperty("voice", voice.id)
                break
    return _engine


def speak_discard(tile_chinese_name: str) -> None:
    """在后台线程播报推荐出牌，不阻塞UI主线程。"""
    def _speak() -> None:
        with _lock:
            try:
                engine = _get_engine()
                engine.say(f"打{tile_chinese_name}")
                engine.runAndWait()
            except Exception:
                pass
    threading.Thread(target=_speak, daemon=True).start()
