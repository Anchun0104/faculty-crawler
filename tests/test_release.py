from __future__ import annotations

import tempfile
import unittest
import zipfile
import shutil
import os
import subprocess
import sys
from pathlib import Path

from build_release import RELEASE_FILES, build_archive


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _archive_subprocess_pythonpath(
    extracted: Path,
    inherited: str,
    source_cwd: Path,
) -> str:
    """Keep inherited dependency paths valid after the archive test changes CWD."""
    entries = [str(extracted)]
    for entry in filter(None, inherited.split(os.pathsep)):
        path = Path(entry)
        entries.append(str(path if path.is_absolute() else (source_cwd / path).resolve()))
    return os.pathsep.join(entries)


class ReleasePackageTests(unittest.TestCase):
    def test_archive_subprocess_normalizes_relative_pythonpath_entries(self) -> None:
        source_cwd = PROJECT_ROOT
        inherited = os.pathsep.join((".runtime-packages", "relative-tools"))

        pythonpath = _archive_subprocess_pythonpath(
            Path("C:/archive/faculty-crawler-windows"),
            inherited,
            source_cwd,
        )

        entries = pythonpath.split(os.pathsep)
        self.assertEqual(entries[0], "C:\\archive\\faculty-crawler-windows")
        self.assertEqual(entries[1], str((source_cwd / ".runtime-packages").resolve()))
        self.assertEqual(entries[2], str((source_cwd / "relative-tools").resolve()))

    def test_release_uses_single_version_source(self) -> None:
        version_path = PROJECT_ROOT / "VERSION"
        build_text = (PROJECT_ROOT / "build_installer.ps1").read_text(
            encoding="utf-8"
        )
        spec_text = (PROJECT_ROOT / "faculty_crawler.spec").read_text(
            encoding="utf-8"
        )
        inno_text = (
            PROJECT_ROOT / "installer" / "faculty-crawler.iss"
        ).read_text(encoding="utf-8")

        self.assertEqual(version_path.read_text(encoding="utf-8").strip(), "2.1.0")
        self.assertIn(Path("VERSION"), RELEASE_FILES)
        self.assertIn('Join-Path $ProjectRoot "VERSION"', build_text)
        self.assertIn('"FacultyCrawler-Setup-$Version.exe"', build_text)
        self.assertIn("FACULTY_CRAWLER_VERSION_FILE", build_text)
        self.assertIn("Get-FileHash", build_text)
        self.assertIn(
            "6auY5qCh5pWZ5biI55uu5b2V5om56YeP6YeH6ZuG5LiOIEV4Y2VsIOWvvOWHuuW3peWFtw==",
            build_text,
        )
        self.assertIn("version=str(version_file)", spec_text)
        self.assertIn("AppVersion={#AppVersion}", inno_text)
        self.assertIn(
            "OutputBaseFilename=FacultyCrawler-Setup-{#AppVersion}",
            inno_text,
        )

    def test_release_includes_offline_translation_service_sources(self) -> None:
        expected = {
            Path("translation_service_entry.py"),
            Path("translation_service.spec"),
            Path("tools/install_translation_models.py"),
            Path("THIRD_PARTY_NOTICES.md"),
        }

        self.assertTrue(expected.issubset(RELEASE_FILES))
        build_text = (PROJECT_ROOT / "build_installer.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("translation_service.spec", build_text)
        self.assertIn("install_translation_models.py", build_text)
        self.assertIn("LibreTranslate.exe", build_text)

    def test_installer_build_script_is_not_duplicated(self) -> None:
        build_text = (PROJECT_ROOT / "build_installer.ps1").read_text(
            encoding="utf-8"
        )

        self.assertTrue(build_text.startswith("param("))
        self.assertNotIn("\nparam(", build_text)
        self.assertEqual(
            build_text.count("function Remove-TaskBuildDirectory"),
            1,
        )
        self.assertEqual(build_text.count("Push-Location"), 1)
        self.assertIn("VERSION must contain exactly three numeric components", build_text)

    def test_installer_uses_short_temp_dist_path_and_passes_it_to_inno(self) -> None:
        build_text = (PROJECT_ROOT / "build_installer.ps1").read_text(
            encoding="utf-8"
        )
        inno_text = (
            PROJECT_ROOT / "installer" / "faculty-crawler.iss"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "ApplicationDistRoot = Join-Path",
            build_text,
        )
        self.assertIn("--distpath", build_text)
        self.assertIn("DApplicationRoot", build_text)
        self.assertNotIn("Remove-TaskBuildDirectory -Path $BuildRoot", build_text)
        self.assertIn(
            "Remove-TaskBuildDirectory -Path $BuildEnvironment",
            build_text,
        )
        self.assertIn(
            "Remove-TaskBuildDirectory -Path $ApplicationDistRoot",
            build_text,
        )
        self.assertIn("#ifndef ApplicationRoot", inno_text)
        self.assertIn("{#ApplicationRoot}", inno_text)

    def test_installer_build_sources_exist_and_use_explicit_inputs(self) -> None:
        paths = (
            PROJECT_ROOT / "requirements-build.txt",
            PROJECT_ROOT / "faculty_crawler.spec",
            PROJECT_ROOT / "build_installer.ps1",
            PROJECT_ROOT / "installer" / "faculty-crawler.iss",
            PROJECT_ROOT / "pyinstaller_runtime_hook.py",
        )
        self.assertTrue(all(path.is_file() for path in paths))
        combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
        for forbidden in (
            "output/*",
            "logs/*",
            "reports/*",
            "runs/*",
            "sessions/*",
            "tasks/*",
            ".venv/*",
        ):
            self.assertNotIn(forbidden, combined)

    def test_pyinstaller_spec_bundles_runtime_and_task_browser_assets(self) -> None:
        text = (PROJECT_ROOT / "faculty_crawler.spec").read_text(encoding="utf-8")
        self.assertIn('collect_submodules("desktop_ui")', text)
        self.assertIn('desktop_ui" / "theme.qss', text)
        self.assertIn('collect_submodules("ui")', text)
        self.assertIn('collect_submodules("crawler")', text)
        self.assertIn("FACULTY_CRAWLER_BROWSER_SOURCE", text)
        self.assertIn('"ms-playwright"', text)
        self.assertIn("pyinstaller_runtime_hook.py", text)

    def test_release_archive_includes_the_new_desktop_shell(self) -> None:
        self.assertIn(Path("desktop_ui/app.py"), RELEASE_FILES)
        self.assertIn(Path("desktop_ui/theme.qss"), RELEASE_FILES)

        hook = (PROJECT_ROOT / "pyinstaller_runtime_hook.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("sys._MEIPASS", hook)
        self.assertIn("PLAYWRIGHT_BROWSERS_PATH", hook)

    def test_build_script_is_clean_fail_fast_and_validates_artifacts(self) -> None:
        text = (PROJECT_ROOT / "build_installer.ps1").read_text(encoding="utf-8")
        self.assertIn('$ErrorActionPreference = "Stop"', text)
        self.assertIn('[IO.Path]::GetTempPath()', text)
        self.assertIn('"FacultyCrawler-installer-build"', text)
        self.assertIn("OrdinalIgnoreCase", text)
        self.assertIn("New-Item -ItemType Directory -Force -Path $BrowserRoot", text)
        self.assertNotIn('$BuildRoot = Join-Path $ProjectRoot', text)
        self.assertIn("--python", text)
        self.assertIn("Remove-TaskBuildDirectory", text)
        self.assertIn("PLAYWRIGHT_BROWSERS_PATH", text)
        self.assertIn("playwright install chromium", text)
        self.assertIn("--noconfirm", text)
        self.assertIn("--clean", text)
        self.assertIn("FacultyCrawler.exe", text)
        self.assertIn("chrome.exe", text)
        self.assertIn("FacultyCrawler-Setup-$Version.exe", text)
        self.assertIn("crawler.faculty_crawler", text)
        self.assertIn("ui.controller", text)
        self.assertNotIn("$HOME", text)

    def test_inno_installer_is_per_user_and_preserves_application_data(self) -> None:
        text = (PROJECT_ROOT / "installer" / "faculty-crawler.iss").read_text(
            encoding="utf-8"
        )
        self.assertIn("PrivilegesRequired=lowest", text)
        self.assertIn(r"DefaultDirName={localappdata}\Programs\FacultyCrawler", text)
        self.assertIn('Name: "{group}\\', text)
        self.assertIn("Flags: unchecked", text)
        self.assertIn('Name: "{userdesktop}\\', text)
        self.assertIn("Uninstallable=yes", text)
        self.assertIn("导出的 Excel", text)
        self.assertIn("本地应用数据", text)
        self.assertNotIn("[UninstallDelete]", text)

    def test_build_and_user_documentation_cover_zero_knowledge_workflow(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        guide_path = PROJECT_ROOT / "使用说明.txt"
        guide = guide_path.read_text(encoding="utf-8")
        version = (PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()

        self.assertTrue(guide_path.is_file())
        self.assertIn("requirements-build.txt", readme)
        self.assertIn("build_installer.ps1", readme)
        self.assertIn(
            f"releases/download/v{version}/FacultyCrawler-Setup-{version}.exe",
            readme,
        )
        self.assertIn("系统临时构建目录", readme)
        self.assertNotIn("GitHub 首版不保存", readme)
        for required in (
            "开始菜单",
            "批量采集",
            "自动翻页",
            "滚动到底部",
            "Load more",
            "人工验证",
            "清除保存状态",
            "30 天",
            "90 天",
            "问题报告 ZIP",
            "飞书",
            "标记为已提交",
            "Excel",
            "无需命令行",
            "无需 Python",
            "无需 AI",
            "无需飞书管理员",
        ):
            self.assertIn(required, guide)
        self.assertNotIn("浣跨敤璇存槑", readme + guide)

    def test_documentation_explains_ai_key_and_multi_url_batch_behavior(self) -> None:
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        guide = (PROJECT_ROOT / "使用说明.txt").read_text(encoding="utf-8")

        for document in (readme, guide):
            self.assertIn("AI 设置", document)
            self.assertIn("DPAPI", document)
            self.assertIn("1 个批次任务", document)

    def test_build_archive_contains_only_source_files_under_one_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = build_archive(PROJECT_ROOT, Path(temp_dir))
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                requirements = archive.read(
                    "faculty-crawler-windows/requirements.txt"
                ).decode("utf-8")

        expected = [f"faculty-crawler-windows/{path.as_posix()}" for path in RELEASE_FILES]
        self.assertEqual(names, expected)
        self.assertTrue(all("output/" not in name for name in names))
        self.assertTrue(all("__pycache__" not in name for name in names))
        self.assertTrue(all(".venv" not in name and ".git" not in name for name in names))
        self.assertIn("faculty-crawler-windows/crawler/task_store.py", names)
        self.assertIn("faculty-crawler-windows/crawler/verification.py", names)
        self.assertIn("faculty-crawler-windows/ui/start_page.py", names)
        self.assertIn("faculty-crawler-windows/使用说明.txt", names)
        self.assertIn("faculty-crawler-windows/faculty_crawler.spec", names)
        self.assertNotIn("faculty-crawler-windows/浣跨敤璇存槑.txt", names)
        self.assertIn("idna>=3.7", requirements)
        expected_modules = {
            f"faculty-crawler-windows/{path.relative_to(PROJECT_ROOT).as_posix()}"
            for package in ("crawler", "faculty_workflow", "scripts", "tests", "ui")
            for path in (PROJECT_ROOT / package).rglob("*.py")
        }
        self.assertTrue(expected_modules.issubset(names))
        forbidden_directories = {
            "sessions",
            "verification-queue",
            "tasks",
            "logs",
            "reports",
            ".installer-build",
        }
        self.assertFalse(
            any(
                any(part.casefold() in forbidden_directories for part in Path(name).parts)
                or "secret" in Path(name).name.casefold()
                for name in names
            )
        )

    def test_release_contains_evidence_workflow_and_excludes_runtime_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = build_archive(PROJECT_ROOT, Path(temp_dir))
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())

        required = {
            "faculty-crawler-windows/workflow.py",
            "faculty-crawler-windows/workflow_desktop.py",
            "faculty-crawler-windows/faculty_workflow/service.py",
            "faculty-crawler-windows/scripts/validate_task_acceptance.py",
            "faculty-crawler-windows/tests/test_workflow_service.py",
            "faculty-crawler-windows/RELEASE_NOTES_2.1.0.md",
        }
        self.assertTrue(required.issubset(names), required - names)
        forbidden_prefixes = (
            "faculty-crawler-windows/.git/",
            "faculty-crawler-windows/.venv/",
            "faculty-crawler-windows/.codex/",
            "faculty-crawler-windows/workflow_data/",
        )
        forbidden_suffixes = (".db", ".sqlite3", ".xlsx", ".log", ".pyc")
        self.assertFalse(any(name.startswith(forbidden_prefixes) for name in names))
        self.assertFalse(any(name.casefold().endswith(forbidden_suffixes) for name in names))

    def test_extracted_archive_imports_desktop_app_in_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = build_archive(PROJECT_ROOT, root / "dist")
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(root / "extract")
            extracted = root / "extract" / "faculty-crawler-windows"
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            environment["PYTHONPATH"] = _archive_subprocess_pythonpath(
                extracted,
                environment.get("PYTHONPATH", ""),
                Path.cwd(),
            )
            result = subprocess.run(
                [sys.executable, "-c", "import desktop_app"],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=15,
            )

        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        self.assertNotIn("SECRET", result.stdout + result.stderr)

    def test_source_archive_excludes_seeded_local_state_and_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_copy = root / "project"
            for relative_path in RELEASE_FILES:
                destination = project_copy / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(PROJECT_ROOT / relative_path, destination)

            seeded = (
                Path("output/faculty-secret.xlsx"),
                Path("logs/runtime-secret.log"),
                Path("reports/report-secret.zip"),
                Path("runs/run-secret.json"),
                Path("sessions/session-secret.bin"),
                Path("tasks/task-secret.json"),
                Path("settings/settings-secret.json"),
                Path(".venv/secret.txt"),
                Path(".git/secret.txt"),
                Path("crawler/__pycache__/secret.pyc"),
            )
            secret_marker = b"SEEDED-" + b"LOCAL-" + b"SECRET"
            for relative_path in seeded:
                path = project_copy / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(secret_marker)

            archive_path = build_archive(project_copy, root / "dist")
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                contents = b"".join(archive.read(name) for name in names)

        self.assertFalse(
            any(path.as_posix() in name for path in seeded for name in names)
        )
        self.assertNotIn(secret_marker, contents)

    def test_setup_and_start_scripts_cover_first_install_and_gui_launch(self) -> None:
        setup_text = (PROJECT_ROOT / "setup.bat").read_text(encoding="utf-8")
        start_text = (PROJECT_ROOT / "start.bat").read_text(encoding="utf-8")

        self.assertIn('py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"', setup_text)
        self.assertIn('python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"', setup_text)
        self.assertIn("sys.version_info >= (3, 11)", setup_text)
        self.assertIn("import tkinter", setup_text)
        self.assertIn("root = tkinter.Tk()", setup_text)
        self.assertIn(r'".venv\Scripts\python.exe" -c "import sys"', setup_text)
        self.assertIn(r'rmdir /s /q ".venv"', setup_text)
        self.assertIn("-m venv .venv", setup_text)
        self.assertIn("-m pip install -r requirements.txt", setup_text)
        self.assertIn("-m playwright install chromium", setup_text)
        self.assertIn(r".venv\Scripts\pythonw.exe", start_text)
        self.assertIn("desktop_app.py", start_text)

    def test_build_archive_is_byte_reproducible_when_source_mtimes_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            project_copy = temp_root / "project"
            for relative_path in RELEASE_FILES:
                destination = project_copy / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(PROJECT_ROOT / relative_path, destination)

            first_archive = build_archive(project_copy, temp_root / "first")
            first_bytes = first_archive.read_bytes()
            (project_copy / RELEASE_FILES[0]).touch()
            second_archive = build_archive(project_copy, temp_root / "second")
            second_bytes = second_archive.read_bytes()

        self.assertEqual(first_bytes, second_bytes)


if __name__ == "__main__":
    unittest.main()
