# Official PDF Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download, extract, cache, and evaluate text-layer official PDFs while preserving strict literal-email evidence rules.

**Architecture:** `PageFetcher` routes PDF URLs through a bounded direct HTTP downloader and a focused PDF extractor, returning the existing `FetchedPage` interface. The workflow cache loader rehydrates raw PDF snapshots, while seed merging and directory parsing preserve multiple real people per shared PDF and reject laboratory labels.

**Tech Stack:** Python 3, standard-library `urllib`, `pypdf>=5.0.0`, SQLite, `unittest`, existing workflow evidence evaluator.

## Global Constraints

- Text-layer PDFs only; no OCR.
- Maximum PDF response size is 20 MB.
- Preserve raw PDF bytes for audit.
- Never reconstruct `{a}`, `[at]`, `(a)`, `#`, or similar email substitutions.
- Search results remain discovery-only.
- Rerun only the review generation for task `6257cee3e0f2` after verification.
- Do not commit or push.

---

### Task 1: PDF extraction boundary

**Files:**
- Create: `faculty_workflow/pdf_documents.py`
- Create: `tests/test_workflow_pdf_documents.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `extract_pdf_text(data: bytes, *, max_text_characters: int = 500_000) -> tuple[str, str]`, returning `(title, text)` and raising `PdfDocumentError` for invalid, encrypted, or empty-text PDFs.

- [ ] Write a failing test using an in-memory text PDF fixture and assert literal email extraction and bounded text.
- [ ] Run the focused test and verify failure because the module does not exist.
- [ ] Add `pypdf>=5.0.0`, install it in `.venv`, and implement the minimal extractor.
- [ ] Add failing cases for invalid signature, unreadable/encrypted data, and no extractable text; implement fail-closed errors.
- [ ] Run `tests.test_workflow_pdf_documents` and verify all cases pass.

### Task 2: Bounded direct PDF fetch

**Files:**
- Modify: `faculty_workflow/fetcher.py`
- Modify: `tests/test_workflow_fetcher.py`

**Interfaces:**
- Consumes: `extract_pdf_text` and existing robots/throttle behavior.
- Produces: `PageFetcher.fetch(...) -> FetchedPage` with raw `.pdf` snapshot, extracted `text`, empty `html`, response status/final URL, and SHA-256 hash.

- [ ] Write a failing test with a local HTTP server returning a real PDF; patch browser launch to fail if called.
- [ ] Verify RED because the current fetcher invokes Playwright.
- [ ] Implement `.pdf` URL direct download with the existing user agent, timeout, redirects, 2xx check, PDF signature/content type validation, and 20 MB cap.
- [ ] Add and verify rejection tests for non-PDF bodies, HTTP errors, oversized responses, and empty-text PDFs.
- [ ] Run all workflow fetcher tests.

### Task 3: Persisted PDF cache reuse

**Files:**
- Modify: `faculty_workflow/service.py`
- Modify: `tests/test_workflow_service.py`

**Interfaces:**
- Consumes: raw `.pdf` snapshots and `extract_pdf_text`.
- Produces: `_load_cached_source_page(...)` support for `.pdf` alongside `.html.gz`.

- [ ] Write a failing service test that persists a successful PDF source and uses a fetcher that raises on network access.
- [ ] Verify RED because the current loader assumes gzip HTML.
- [ ] Detect `.pdf`, validate size/signature, extract text, and return a `FetchedPage`; invalid snapshots return `None`.
- [ ] Run cached HTML and PDF reuse tests together.

### Task 4: Shared PDF identities and lab-label filtering

**Files:**
- Modify: `faculty_workflow/service.py`
- Modify: `faculty_workflow/directory_adapters.py`
- Modify: `tests/test_workflow_service.py`
- Modify: `tests/test_workflow_adapters.py`

**Interfaces:**
- Consumes: directory seed dictionaries with name and profile URL.
- Produces: independent seeds for different real names sharing one PDF, and no `* Lab` person records.

- [ ] Write a failing seed test with Ada and Grace sharing one PDF URL; assert two seeds survive.
- [ ] Implement collision-safe keys only when the existing and incoming normalized names differ.
- [ ] Write a failing adapter test containing `A Lab` and `Ada Lovelace`; assert only Ada is emitted.
- [ ] Extend person-name plausibility checks to reject normalized laboratory labels without rejecting real names containing the word Laboratory in surrounding text.
- [ ] Run focused seed and adapter tests.

### Task 5: Evidence safety and complete verification

**Files:**
- Modify if required by a demonstrated regression: `faculty_workflow/email_resolver.py`, related tests.

**Interfaces:**
- Consumes: PDF-backed `FetchedPage.text`.
- Produces: acceptance only for literal complete official addresses.

- [ ] Add a PDF-backed resolver test proving `ada@example.edu` is accepted and `ada{a}example.edu` is not reconstructed.
- [ ] Run workflow PDF, fetcher, adapter, resolver, and service tests.
- [ ] Run `.venv\Scripts\python.exe -m unittest discover -s tests` and require zero failures.

### Task 6: Nagoya review-only rerun

**Files:**
- Data only: `workflow_data/nagoya-physics-20260730/workflow.db`
- Export: `workflow_data/nagoya-physics-20260730/output/`

**Interfaces:**
- Consumes: task `6257cee3e0f2` and its persisted main-directory snapshot.
- Produces: one completed review generation and updated completed/review/audit exports.

- [ ] Start or resume exactly one `reprocess-reviews` generation for task `6257cee3e0f2`.
- [ ] Run with official network access; PDF snapshots must be reused after their first successful download.
- [ ] Export completed, review, and audit files.
- [ ] Run `scripts.validate_task_acceptance` and inspect names/reasons; require zero lab-label candidates and zero email violations.
- [ ] Report discovered, completed, remaining review, rejected, runtime, and output paths without modifying task `67e246112066`.
