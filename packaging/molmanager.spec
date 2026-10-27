# -*- mode: python ; coding: utf-8 -*-
# Starter PyInstaller spec — run from repo root:
#   pyinstaller packaging/molmanager.spec
# UPX is off. Packing fights code signing and is commonly flagged by scanners.
# codesign_identity stays unset until a signing certificate is available.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent

block_cipher = None

a = Analysis(
    [str(ROOT / "molmanager" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "molmanager" / "ui" / "static"), "molmanager/ui/static"),
        (str(ROOT / "molmanager" / "resources" / "README.md"), "molmanager/resources"),
        (str(ROOT / "molmanager" / "resources" / "fonts"), "molmanager/resources/fonts"),
    ],
    hiddenimports=[
        "rdkit",
        "rdkit.Chem",
        "rdkit.Chem.Draw",
        "rdkit.Chem.Draw.rdMolDraw2D",
        "PyQt5.QtWebEngineWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MolManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MolManager",
)
