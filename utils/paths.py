import os
import sys


def resource_path(relative: str) -> str:
    """打包后从 _MEIPASS 读只读资源（模板、配置初始文件）。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    # _MEIPASS 指向解压临时目录；开发时指向 utils/ 的父目录
    if getattr(sys, "frozen", False):
        return os.path.join(base, relative)
    return os.path.join(os.path.dirname(base), relative)


def data_path(relative: str = "") -> str:
    """用户数据目录（可写），始终在 exe 同级目录。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base, relative) if relative else base
    os.makedirs(path, exist_ok=True)
    return path


def template_dir(subdir: str = "") -> str:
    """模板目录：优先用 exe 同级的可写 templates/，fallback 到只读资源。"""
    writable = data_path(os.path.join("templates", subdir))
    if os.path.isdir(writable):
        return writable
    return resource_path(os.path.join("templates", subdir))
