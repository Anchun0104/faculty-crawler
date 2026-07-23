from __future__ import annotations

import subprocess
import tempfile
import zipfile
from datetime import date
from pathlib import Path


ROOT_FILES = {
    "README.md",
    "CODEX_PARSER_RULES.md",
    "main.py",
    "desktop_app.py",
    "build_release.py",
    "build_handoff.py",
    "requirements.txt",
    "setup.bat",
    "start.bat",
    "使用说明.txt",
    "任务转接说明.md",
}
INCLUDED_DIRECTORIES = ("crawler", "tests", "docs", "output")
EXCLUDED_PARTS = {".git", ".venv", "__pycache__", "dist"}
FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def collect_handoff_files(project_root: Path) -> list[Path]:
    selected: set[Path] = set()
    for filename in ROOT_FILES:
        path = project_root / filename
        if path.is_file():
            selected.add(Path(filename))

    for directory in INCLUDED_DIRECTORIES:
        base = project_root / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            relative = path.relative_to(project_root)
            if not path.is_file():
                continue
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            if path.suffix.lower() in {".pyc", ".zip"}:
                continue
            selected.add(relative)

    return sorted(selected, key=lambda path: path.as_posix())


def create_git_bundle(project_root: Path, bundle_path: Path) -> None:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={project_root.as_posix()}",
            "bundle",
            "create",
            str(bundle_path),
            "--branches",
            "--tags",
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )


def build_handoff_archive(
    project_root: Path,
    dist_dir: Path,
    *,
    date_stamp: str | None = None,
) -> Path:
    stamp = date_stamp or date.today().strftime("%Y%m%d")
    archive_root = f"faculty-crawler-project-handoff-{stamp}"
    archive_path = dist_dir / f"{archive_root}.zip"
    files = collect_handoff_files(project_root)

    dist_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        bundle_path = Path(temp_dir) / "repository.bundle"
        create_git_bundle(project_root, bundle_path)

        with zipfile.ZipFile(
            archive_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for relative_path in files:
                _write_archive_member(
                    archive,
                    f"{archive_root}/{relative_path.as_posix()}",
                    (project_root / relative_path).read_bytes(),
                )
            _write_archive_member(
                archive,
                f"{archive_root}/repository.bundle",
                bundle_path.read_bytes(),
            )

    return archive_path


def _write_archive_member(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    archive.writestr(
        info,
        data,
        compress_type=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    )


def main() -> None:
    project_root = Path(__file__).resolve().parent
    archive_path = build_handoff_archive(project_root, project_root / "dist")
    print(f"Created {archive_path}")


if __name__ == "__main__":
    main()
