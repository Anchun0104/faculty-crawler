from __future__ import annotations

import os
import sys
from pathlib import Path


bundle_root = Path(sys._MEIPASS)  # type: ignore[attr-defined]
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(bundle_root / "ms-playwright")
