# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['C:/MahjongAI'],
    binaries=[],
    datas=[
        ('config/settings.yaml',   'config'),
        ('templates',              'templates'),
    ],
    hiddenimports=[
        'mss',
        'mss.windows',
        'cv2',
        'numpy',
        'yaml',
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'PIL'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 确保 PyQt6 Windows 平台插件被打包（否则 GUI 无法显示）
import os

try:
    import PyQt6
    qt6_root = os.path.dirname(PyQt6.__file__)
    platform_dll = os.path.join(qt6_root, 'Qt6', 'plugins', 'platforms', 'qwindows.dll')
    if os.path.isfile(platform_dll):
        a.datas += [(platform_dll, 'PyQt6/Qt6/plugins/platforms')]
except ImportError:
    pass

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='MahjongAI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,         # 隐藏黑框
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='ui/icons/app.ico',   # 有图标时取消注释
)
