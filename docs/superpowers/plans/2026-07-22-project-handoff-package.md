# Project Handoff Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a complete developer handoff ZIP containing the current source, tests, all Excel results, operating documentation, and portable Git history.

**Architecture:** A standard-library Python builder selects an explicit set of root development files plus recursive `crawler`, `tests`, `docs`, and `output` content. It creates a temporary `repository.bundle` with Git, writes a deterministic ZIP under `dist`, and excludes virtual environments, caches, existing archives, and `.git` metadata.

**Tech Stack:** Python 3.11+, `zipfile`, `hashlib`, `subprocess`, Git bundle, `unittest`.

## Global Constraints

- Preserve all existing source and Excel files without modifying their content.
- Include every current file under `output`, including `output/pending_title`.
- Exclude `.venv`, `.git`, `__pycache__`, `.pyc`, and existing `dist` artifacts.
- The filesystem snapshot is authoritative for uncommitted files; `repository.bundle` contains committed history only.
- Do not commit, stage, or clean the user's existing working-tree changes.

---

### Task 1: Define and test the handoff archive contract

**Files:**
- Create: `tests/test_handoff.py`
- Create: `build_handoff.py`

**Interfaces:**
- Produces: `collect_handoff_files(project_root: Path) -> list[Path]`
- Produces: `build_handoff_archive(project_root: Path, dist_dir: Path) -> Path`

- [ ] Write failing tests that require source, tests, rules, documentation, and all output files while rejecting caches, `.venv`, `.git`, `dist`, and existing ZIP files.
- [ ] Run `python -m unittest tests.test_handoff -v` and confirm failure because `build_handoff` does not exist.
- [ ] Implement explicit selection, Git bundle generation, deterministic ZIP metadata, and archive creation.
- [ ] Re-run the focused tests and confirm they pass.

### Task 2: Write the colleague-facing transfer guide

**Files:**
- Create: `任务转接说明.md`
- Test: `tests/test_handoff.py`

**Interfaces:**
- The guide must document architecture, setup, GUI/CLI commands, tests, current commit, output layout, parser rules, known limits, and next optimization priorities.

- [ ] Add a failing content test for every required guide section.
- [ ] Write the concise Chinese handoff guide, explicitly separating committed Git history from the working-tree snapshot.
- [ ] Re-run `python -m unittest tests.test_handoff -v` and confirm it passes.

### Task 3: Build and verify the deliverable

**Files:**
- Create: `dist/faculty-crawler-project-handoff-20260722.zip`

- [ ] Run the full suite with `python -m unittest discover -s tests -v`.
- [ ] Run `python build_handoff.py` and confirm the archive is created.
- [ ] Verify every archived source/output byte matches the working tree, the Git bundle passes `git bundle verify`, excluded paths are absent, and the archive SHA-256 is reported.
