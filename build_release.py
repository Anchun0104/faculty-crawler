from __future__ import annotations

import zipfile
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent
_ROOT_RELEASE_FILES = (
    Path("VERSION"),
    Path("README.md"),
    Path("CHANGELOG.md"),
    Path("README_WORKFLOW_AI.md"),
    Path("RELEASE_NOTES_2.1.0.md"),
    Path("build_installer.ps1"),
    Path("build_release.py"),
    Path("desktop_app.py"),
    Path("faculty_crawler.spec"),
    Path("installer/faculty-crawler.iss"),
    Path("main.py"),
    Path("pyinstaller_runtime_hook.py"),
    Path("requirements-build.txt"),
    Path("requirements.txt"),
    Path("setup.bat"),
    Path("start.bat"),
    Path("THIRD_PARTY_NOTICES.md"),
    Path("tools/install_translation_models.py"),
    Path("translation_service_entry.py"),
    Path("translation_service.spec"),
    Path("workflow.py"),
    Path("workflow_desktop.py"),
    Path("使用说明.txt"),
)
_SOURCE_PACKAGES = ("crawler", "faculty_workflow", "scripts", "tests", "ui")
RELEASE_FILES = _ROOT_RELEASE_FILES + tuple(
    sorted(
        path.relative_to(_PROJECT_ROOT)
        for package in _SOURCE_PACKAGES
        for path in (_PROJECT_ROOT / package).rglob("*.py")
    )
)
ARCHIVE_NAME = "faculty-crawler-windows.zip"
ARCHIVE_ROOT = "faculty-crawler-windows"


def build_archive(project_root: Path, dist_dir: Path) -> Path:
    missing = [str(path) for path in RELEASE_FILES if not (project_root / path).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing release files: {', '.join(missing)}")

    dist_dir.mkdir(parents=True, exist_ok=True)
    archive_path = dist_dir / ARCHIVE_NAME
    with zipfile.ZipFile(
        archive_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for relative_path in RELEASE_FILES:
            archive_name = f"{ARCHIVE_ROOT}/{relative_path.as_posix()}"
            info = zipfile.ZipInfo(archive_name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(
                info,
                (project_root / relative_path).read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return archive_path


def main() -> None:
    project_root = Path(__file__).resolve().parent
    archive_path = build_archive(project_root, project_root / "dist")
    print(f"Created {archive_path}")


if __name__ == "__main__":
    main()
