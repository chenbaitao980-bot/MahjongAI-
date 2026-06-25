"""tray_entry.py — PyInstaller 打包入口脚本。

单独的入口脚本（而非直接指向 windows/tray_app.py），保证冻结后 windows/mahjong_mitm
两个包都被 PyInstaller 收集且 import 路径稳定。源码态也可 `python packaging/tray_entry.py`。
"""
import os
import sys

# 源码态：把 interface/ 加进 sys.path，使 windows / mahjong_mitm 可导入。
# 冻结态：包已在 bundle 内，import 直接命中，这步无副作用。
_RUNTIME_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNTIME_ROOT not in sys.path:
    sys.path.insert(0, _RUNTIME_ROOT)

from windows.tray_app import main

if __name__ == "__main__":
    main()
