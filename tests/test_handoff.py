from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from build_handoff import build_handoff_archive, collect_handoff_files, create_git_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class HandoffFileSelectionTests(unittest.TestCase):
    def test_collects_development_files_and_outputs_but_excludes_local_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            included = [
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
                "crawler/parsers.py",
                "desktop_ui/app.py",
                "desktop_ui/theme.qss",
                "tests/test_parsers.py",
                "docs/architecture.md",
                "output/faculty.xlsx",
                "output/pending_title/faculty_title_pending.xlsx",
            ]
            excluded = [
                ".venv/Lib/site.py",
                ".git/config",
                "dist/old.zip",
                "crawler/__pycache__/parsers.cpython-312.pyc",
                "tests/test_parsers.pyc",
                "output/__pycache__/ignored.txt",
                "unrelated.tmp",
            ]
            for relative in included + excluded:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(relative, encoding="utf-8")

            selected = [path.as_posix() for path in collect_handoff_files(root)]

        self.assertEqual(selected, sorted(included))


class HandoffArchiveTests(unittest.TestCase):
    def test_git_bundle_only_exports_normal_branches_and_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("build_handoff.subprocess.run") as run:
                create_git_bundle(root, root / "repository.bundle")

        command = run.call_args.args[0]
        self.assertIn("--branches", command)
        self.assertIn("--tags", command)
        self.assertNotIn("--all", command)

    def test_archive_contains_selected_files_and_portable_git_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            dist = Path(temp_dir) / "dist"
            for relative in (
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
                "crawler/__init__.py",
                "tests/test_example.py",
                "output/result.xlsx",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(relative.encode("utf-8"))

            def fake_bundle(_project_root: Path, bundle_path: Path) -> None:
                bundle_path.write_bytes(b"portable git history")

            with patch("build_handoff.create_git_bundle", side_effect=fake_bundle):
                archive_path = build_handoff_archive(root, dist, date_stamp="20260722")

            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                prefix = "faculty-crawler-project-handoff-20260722/"
                self.assertIn(prefix + "repository.bundle", names)
                self.assertIn(prefix + "tests/test_example.py", names)
                self.assertIn(prefix + "output/result.xlsx", names)
                self.assertNotIn(prefix + "dist/old.zip", names)
                self.assertEqual(archive.read(prefix + "repository.bundle"), b"portable git history")
                self.assertEqual(len({entry.date_time for entry in archive.infolist()}), 1)


class HandoffGuideTests(unittest.TestCase):
    def test_guide_contains_every_section_needed_by_the_next_developer(self) -> None:
        guide = (PROJECT_ROOT / "任务转接说明.md").read_text(encoding="utf-8")

        required_text = (
            "# 高校教师数据采集项目任务转接说明",
            "## 1. 转接快照",
            "## 2. 项目目标",
            "## 3. 代码结构",
            "## 4. 环境与首次安装",
            "## 5. 运行方式",
            "## 6. 测试与修改纪律",
            "## 7. 输出与日志",
            "## 8. 当前能力",
            "## 9. 已知限制",
            "## 10. 后续优化建议",
            "## 11. Git 历史",
            "d80f108",
            "CODEX_PARSER_RULES.md",
            "python -m unittest discover -s tests -v",
            "output/pending_title",
            "repository.bundle",
            "build_handoff.py",
        )
        for text in required_text:
            with self.subTest(text=text):
                self.assertIn(text, guide)


if __name__ == "__main__":
    unittest.main()
