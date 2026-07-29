# Title Diagnostics Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export review and excluded faculty records to stable CSV/XLSX files for human review.

**Architecture:** Add a standalone `crawler/diagnostics_export.py` that serializes `FacultyRecord` fields with a fixed column order. Add two thin `FacultyCrawler` methods that delegate to it, leaving crawl and classification behavior unchanged.

**Tech Stack:** Python standard library `csv`, `pathlib`, `dataclasses`; existing `openpyxl`; unittest.

## Global Constraints

- Preserve all existing uncommitted multilingual classification and translation changes.
- CSV must be UTF-8 with BOM; XLSX must use the existing openpyxl dependency.
- Empty record lists still produce a header row.
- Unsupported formats raise `ValueError`; filesystem errors propagate.
- Do not commit, push, delete, or overwrite user files.

### Task 1: Standalone diagnostics exporter

**Files:**
- Create: `crawler/diagnostics_export.py`
- Create: `tests/test_diagnostics_export.py`

**Interfaces:**
- Consumes: `Iterable[FacultyRecord]`, output path, optional format string.
- Produces: `export_records(records, path, format=None) -> Path` and stable `EXPORT_COLUMNS`.

- [ ] **Step 1: Write failing tests** for fixed columns/values, Unicode CSV, empty headers, XLSX values, extension inference, explicit format override, and invalid format.
- [ ] **Step 2: Run** `python -m unittest tests.test_diagnostics_export -v`; expect failure because the exporter module does not exist.
- [ ] **Step 3: Implement** CSV and XLSX serialization using the fixed `FacultyRecord` field names; return the normalized `Path`.
- [ ] **Step 4: Run** the focused test module and confirm all exporter tests pass.

### Task 2: FacultyCrawler export facade

**Files:**
- Modify: `crawler/faculty_crawler.py`
- Modify: `tests/test_crawler_diagnostics.py`

**Interfaces:**
- Consumes: `self.review_records` and `self.excluded_records`.
- Produces: `export_review_records(path, format=None) -> Path` and `export_excluded_records(path, format=None) -> Path`.

- [ ] **Step 1: Write failing tests** that populate each list with distinct records and assert each facade writes only its corresponding record.
- [ ] **Step 2: Run** the focused test; expect failure because facade methods do not exist.
- [ ] **Step 3: Implement** two one-line delegating methods and import the standalone exporter.
- [ ] **Step 4: Run** both exporter and crawler diagnostic tests.

### Task 3: Regression verification

**Files:**
- No production changes expected.

- [ ] **Step 1: Run** `python -m unittest tests.test_diagnostics_export tests.test_crawler_diagnostics tests.test_title_classifier tests.test_title_pipeline tests.test_translation tests.test_parsers -v`.
- [ ] **Step 2: Run** `python -m compileall crawler` and `git diff --check`.
- [ ] **Step 3: Report** focused results and explicitly note the known Playwright dependency and pre-existing `tests/test_release.py` syntax issue if full-suite verification is attempted.
