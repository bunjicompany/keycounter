# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ["keycounter_app.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("stats_viewer.html", "."),
        ("build_info.json", "."),
        ("vendor/chart.umd.min.js", "vendor"),
        ("vendor/html2canvas.min.js", "vendor"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KeyCounter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="KeyCounter",
)
