"""Entrypoint for the LibreTranslate process bundled with the desktop app."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    service_root = Path(sys.executable).resolve().parent
    package_root = Path(getattr(sys, "_MEIPASS", service_root)).resolve()
    os.environ.setdefault("ARGOS_PACKAGES_DIR", str(package_root / "models"))
    os.environ.setdefault("ARGOS_DEVICE_TYPE", "cpu")
    os.environ.setdefault("ARGOS_CHUNK_TYPE", "MINISBD")
    # The desktop installer already carries the supported Argos models.  Do
    # not let LibreTranslate contact the model index or add every available
    # language pair during application startup.
    from libretranslate import init as libretranslate_init

    libretranslate_init.boot = lambda *args, **kwargs: None
    from libretranslate.main import main as libretranslate_main

    libretranslate_main()


if __name__ == "__main__":
    main()
