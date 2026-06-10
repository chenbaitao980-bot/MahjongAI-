#!/usr/bin/env python3
"""
package_extractor.py — 在开发机上把 extractor 打包成软路由可独立运行的 bundle

产出 mahjong-extractor-bundle.tar.gz，内含 extractor 运行所需的最小模块集
（实测依赖链，不含 cv2/numpy/PyQt），以及安装脚本与服务文件。

用法（在项目根或 remote/extractor/ 下均可）：
    python remote/extractor/package_extractor.py [-o 输出路径.tar.gz]

bundle 解包后目录结构：
    mahjong-extractor/
      remote/extractor/*.py + config.yaml
      stable/{__init__,protocol,tracker,mapping}.py
      battle/{__init__,state}.py          # 不含 service.py(cv2)
      game/**                              # 整个 game 包(无 cv2)
      utils/{__init__,paths}.py
      install_linux.sh  install_openwrt.sh
      files/mahjong-extractor.service  files/mahjong-extractor.init
      selfcheck_capture.sh  DEPLOY.md

Python 3.7+，仅用标准库。
"""
import argparse
import io
import os
import sys
import tarfile

# 项目根 = 本文件上两级
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))

# extractor 运行时最小模块集（实测 stable.tracker 链 + 打包冗余安全项）
_INCLUDE_FILES = [
    # extractor 应用本身
    "remote/extractor/main.py",
    "remote/extractor/capture.py",
    "remote/extractor/token_extractor.py",
    "remote/extractor/uploader.py",
    "remote/extractor/config.yaml",
    # stable 协议/状态
    "stable/__init__.py",
    "stable/protocol.py",
    "stable/tracker.py",
    "stable/mapping.py",
    # battle：只要 state（懒加载后不再连带 service.py/cv2）
    "battle/__init__.py",
    "battle/state.py",
    # utils
    "utils/__init__.py",
    "utils/paths.py",
]

# 整目录纳入（game 包较小且全为纯 python，避免漏掉懒加载路径）
_INCLUDE_DIRS = [
    "game",
]

# 目录纳入时排除这些（heavy / 无关）
_DIR_EXCLUDE_SUFFIX = (".pyc",)
_DIR_EXCLUDE_PART = ("__pycache__", )

# bundle 内附带的部署资产（相对 remote/extractor/，打到 bundle 根）
_ASSET_FILES = [
    "install_linux.sh",
    "install_openwrt.sh",
    "selfcheck_capture.sh",
    "DEPLOY.md",
    "files/mahjong-extractor.service",
    "files/mahjong-extractor.init",
]

_TOP = "mahjong-extractor"  # bundle 顶层目录


def _iter_dir(rel_dir):
    base = os.path.join(_ROOT, rel_dir)
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in _DIR_EXCLUDE_PART]
        for fn in filenames:
            if fn.endswith(_DIR_EXCLUDE_SUFFIX):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, _ROOT).replace(os.sep, "/")
            yield rel


def _add(tar, abs_path, arcname):
    tar.add(abs_path, arcname=arcname, recursive=False)


def main():
    ap = argparse.ArgumentParser(description="Package extractor for soft-router deploy")
    ap.add_argument("-o", "--output", default=os.path.join(_ROOT, "mahjong-extractor-bundle.tar.gz"))
    args = ap.parse_args()

    # 收集模块文件
    rels = []
    missing = []
    for rel in _INCLUDE_FILES:
        if os.path.isfile(os.path.join(_ROOT, rel)):
            rels.append(rel)
        else:
            missing.append(rel)
    for d in _INCLUDE_DIRS:
        rels.extend(_iter_dir(d))

    if missing:
        print("[ERROR] 缺少必要文件，打包中止：")
        for m in missing:
            print("   -", m)
        return 1

    out = args.output
    with tarfile.open(out, "w:gz") as tar:
        # 1) 模块文件，保持包路径，放在 bundle 顶层目录下
        for rel in rels:
            _add(tar, os.path.join(_ROOT, rel), "{}/{}".format(_TOP, rel))
        # 2) 部署资产（从 remote/extractor/ 取，平铺到 bundle 顶层）
        for asset in _ASSET_FILES:
            src = os.path.join(_HERE, asset)
            if not os.path.isfile(src):
                print("[WARN] 部署资产缺失（跳过）:", asset)
                continue
            _add(tar, src, "{}/{}".format(_TOP, asset))
        # 3) 顶层 run 包装，便于 `python run.py`（设置 sys.path 到 bundle 顶层）
        run_py = (
            "import os, sys\n"
            "sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\n"
            "from remote.extractor.main import main\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )
        info = tarfile.TarInfo("{}/run.py".format(_TOP))
        data = run_py.encode("utf-8")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))

    size_kb = os.path.getsize(out) / 1024.0
    print("[ok] bundle 生成: {} ({:.1f} KB)".format(out, size_kb))
    print("[ok] 含模块 {} 个 + 部署脚本".format(len(rels)))
    print("下一步：scp {} 到路由器，解包后按 DEPLOY.md 执行 install_*.sh".format(os.path.basename(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
