"""test_win_admin.py — UAC/自启工具的纯逻辑自测（不写注册表、不提权）。

提权与注册表写入有副作用，只能真机验；这里只测无副作用的命令行拼接逻辑。

运行:
  cd apps/router_runtime
  python -m pytest tests/ -v
"""
from __future__ import annotations

import os
import sys

_RUNTIME_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNTIME_ROOT not in sys.path:
    sys.path.insert(0, _RUNTIME_ROOT)

from windows.win_admin import subprocess_list_to_str


def test_quote_args_with_spaces():
    assert subprocess_list_to_str(["C:/Program Files/x.exe", "--ip", "1.2.3.4"]) == \
        '"C:/Program Files/x.exe" --ip 1.2.3.4'


def test_no_quote_when_no_space():
    assert subprocess_list_to_str(["a", "b", "c"]) == "a b c"


def test_empty_list():
    assert subprocess_list_to_str([]) == ""
