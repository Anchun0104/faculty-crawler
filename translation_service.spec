# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


project_root = Path(SPECPATH).resolve()
models_root = Path(os.environ["FACULTY_CRAWLER_TRANSLATION_MODELS"]).resolve()
if not models_root.is_dir():
    raise SystemExit(f"Bundled translation models are missing: {models_root}")

datas, binaries, hiddenimports = collect_all("libretranslate")
for package in ("argostranslate", "argostranslatefiles", "ctranslate2"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports
datas += [(str(models_root), "models")]

a = Analysis(
    [str(project_root / "translation_service_entry.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LibreTranslate",
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="LibreTranslate",
)
