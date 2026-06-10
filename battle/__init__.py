from .state import BattleAdvice, BattleState

# BattleService 依赖 cv2/numpy（vision 链）。为了让轻量消费方（如软路由上的
# remote/extractor，只需要 BattleState/tracker）不被动拉进 OpenCV，这里改用
# PEP 562 懒加载：`from battle import BattleService` 仍可用，但只有真正访问时
# 才导入 service 模块。
__all__ = ["BattleAdvice", "BattleState", "BattleService"]


def __getattr__(name):
    if name == "BattleService":
        from .service import BattleService
        return BattleService
    raise AttributeError("module {!r} has no attribute {!r}".format(__name__, name))
