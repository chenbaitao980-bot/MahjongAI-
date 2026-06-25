# -*- mode: python ; coding: utf-8 -*-
"""mahjong_mitm_win.spec — Windows 托盘全自动版 exe 打包配置。

输出：dist/MahjongMITM/ 单文件夹（含 MahjongMITM.exe）。复制整个文件夹到任意
未装 Python 的 Win10/11 x64 即可双击运行（exe 经 UAC manifest 自动提权）。

关键收集项：
  - WinDivert 驱动：pydivert 自带 WinDivert.dll + WinDivert64.sys（微软交叉签名），
    用 collect_data_files + collect_dynamic_libs('pydivert') 收进 bundle，运行时
    pydivert 按其包内相对路径加载。
  - WinRT：winsdk 投影含大量动态子模块/二进制，用 collect_all('winsdk') 全收。
  - 托盘：pystray 的后端子模块 + Pillow。
  - 内嵌资源：assets/game_base.apk 放到 _RUNTIME_ROOT/assets（与 mahjong_mitm 同级，
    使 setup_mitm.DEFAULT_APK = _RUNTIME_ROOT/assets/game_base.apk 在冻结态命中）。

构建：cd interface && winpack\\build_win.bat
"""
import os

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

# spec 执行时 cwd = interface（build_win.bat 切到此处再调）
_ROOT = os.path.abspath(os.getcwd())

datas = []
binaries = []
hiddenimports = []

# 1) 内嵌 APK（资源源：XXTEA key / SIGN / 原始 luac 取自此）
datas += [(os.path.join(_ROOT, "assets", "game_base.apk"), "assets")]

# 2) WinDivert 驱动（pydivert 自带 dll/sys，微软签名，免手动装驱动）
datas += collect_data_files("pydivert")
binaries += collect_dynamic_libs("pydivert")

# 3) WinRT（winsdk 全量：移动热点 NetworkOperatorTetheringManager 等）
_wd, _wb, _wh = collect_all("winsdk")
datas += _wd
binaries += _wb
hiddenimports += _wh

# 4) 托盘后端 + 图像
hiddenimports += collect_submodules("pystray")
hiddenimports += ["PIL.Image", "PIL.ImageDraw"]

# 5) 内核回源依赖（一般自动，显式列出兜底）
hiddenimports += ["requests", "urllib3", "cryptography"]


a = Analysis(
    [os.path.join(_ROOT, "winpack", "tray_entry.py")],
    pathex=[_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "PyQt6", "cv2", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MahjongMITM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # WinDivert 驱动/winrt 二进制 upx 压缩易出问题，关掉
    console=True,              # v1 保留控制台便于真机验证；验证稳定后可改 False（纯托盘）
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,            # ★ manifest 自动提权（绑 53/443 + WinDivert + 写 icssvc 注册表）
    # icon="...",              # 可选自定义图标
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MahjongMITM",
)
