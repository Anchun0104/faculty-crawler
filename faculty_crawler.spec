# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


project_root = Path(SPECPATH).resolve()
browser_source = Path(os.environ["FACULTY_CRAWLER_BROWSER_SOURCE"]).resolve()
if not browser_source.is_dir():
    raise SystemExit(f"Bundled Chromium source is missing: {browser_source}")
version_file = Path(os.environ["FACULTY_CRAWLER_VERSION_FILE"]).resolve()
if not version_file.is_file():
    raise SystemExit(f"Generated version resource is missing: {version_file}")

hiddenimports = (
    collect_submodules("desktop_ui")
    + collect_submodules("ui")
    + collect_submodules("crawler")
    + collect_submodules("faculty_workflow")
)
datas = [
    (str(browser_source), "ms-playwright"),
    (str(project_root / "desktop_ui" / "theme.qss"), "desktop_ui"),
    (str(project_root / "使用说明.txt"), "."),
]

a = Analysis(
    [str(project_root / "desktop_app.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_root / "pyinstaller_runtime_hook.py")],
    excludes=["tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FacultyCrawler",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    version=str(version_file),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FacultyCrawler",
)
