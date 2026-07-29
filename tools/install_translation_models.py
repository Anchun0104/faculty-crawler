"""Download the exact offline Argos models supported by FacultyCrawler."""

from __future__ import annotations

import os
from pathlib import Path


SOURCE_CODES = ("ar", "de", "es", "fr", "it", "ja", "nl", "pt", "zh", "zt")


def main() -> None:
    destination = Path(os.environ["ARGOS_PACKAGES_DIR"]).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    from argostranslate import package

    package.update_package_index()
    available = package.get_available_packages()
    for source in SOURCE_CODES:
        model = next(
            (item for item in available if item.from_code == source and item.to_code == "en"),
            None,
        )
        if model is None:
            raise RuntimeError(f"Argos model is unavailable: {source}->en")
        package.install_from_path(model.download())


if __name__ == "__main__":
    main()
