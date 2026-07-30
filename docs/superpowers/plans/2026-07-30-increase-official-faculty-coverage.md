# Increase Official Faculty Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the proven evidence-first workflow into the upstream 2.0.0 crawler so every visible eligible directory person is retained, official secondary evidence can raise completion counts, and only unresolved records are reprocessed.

**Architecture:** Keep the upstream parser, translator, UI, session, and packaging code authoritative. Add `faculty_workflow/` as an optional evidence layer that consumes upstream parser records, traverses a finite official-source graph, stores source-scoped evidence in SQLite, applies strict completion gates, and exposes a separate `workflow.py` CLI. Port only additive parser helpers and inject the existing local `TitlePipeline`; never make Email mandatory in the generic parser.

**Tech Stack:** Python 3.13, standard-library SQLite/HTML/URL modules, Playwright, openpyxl, upstream title translation pipeline, `unittest`, OpenSpec 1.7.0.

## Global Constraints

- Work only in `faculty-crawler-coverage-worktree` on local branch `feature/increase-official-faculty-coverage`.
- Do not push, open a pull request, package a release, or modify the remote repository.
- Do not commit during this local implementation unless the user separately authorizes commits.
- Follow `CODEX_PARSER_RULES.md`: generic parser validity remains Name + Title + Profile_URL; Email is optional at that layer.
- The evidence-workflow completed output requires a complete, non-generic personal email visibly present on a validated official page.
- Search output is URL discovery only; snippets and cached search content can never become supported evidence.
- Do not infer email formats, add university-specific extraction branches, bypass access controls, or crawl an unbounded university site.
- Every production behavior change follows RED-GREEN-REFACTOR and the complete upstream suite must remain green.

---

### Task 1: Protect the Upstream Baseline and Port Workflow Contracts

**Files:**
- Create: `tests/test_workflow_adapters.py`
- Create: `tests/test_workflow_database.py`
- Create: `tests/test_workflow_provider.py`
- Create: `tests/test_workflow_service.py`
- Create: `docs/validation/2026-07-30-evidence-workflow-inventory.md`
- Modify: `openspec/changes/increase-official-faculty-coverage/tasks.md`

**Interfaces:**
- Consumes: upstream `crawler.parsers.FacultyRecord`, `crawler.title_pipeline.TitlePipeline`, and existing translation/settings contracts.
- Produces: executable contract tests for `faculty_workflow` and a recorded 486-test baseline.

- [x] **Step 1: Run the untouched upstream test suite**

Run: `.venv\Scripts\python.exe -m unittest discover -s tests -v`

Expected: `Ran 486 tests` and `OK`.

- [x] **Step 2: Record the module inventory and parser/workflow boundary**

Record the baseline, upstream authority, handoff source mapping, and test-first port order in `docs/validation/2026-07-30-evidence-workflow-inventory.md`.

- [ ] **Step 3: Add workflow contract tests before production modules**

Port the four `test_workflow_*.py` files from the handoff tree, then add this upstream-preservation test to `tests/test_workflow_service.py`:

```python
from crawler.title_classifier import TitleClassifier
from crawler.title_pipeline import TitlePipeline

def test_workflow_title_pipeline_preserves_official_original():
    processed = TitlePipeline(TitleClassifier()).process("Professor")
    assert processed.title_original == "Professor"
    assert processed.title_translated == ""
```

- [ ] **Step 4: Verify RED**

Run: `.venv\Scripts\python.exe -m unittest tests.test_workflow_adapters tests.test_workflow_database tests.test_workflow_provider tests.test_workflow_service -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'faculty_workflow'`; the upstream title-pipeline assertion itself must pass.

- [ ] **Step 5: Mark OpenSpec baseline tasks complete after the contract test failure is captured**

Change OpenSpec task 1.3 to checked only after the expected import failure is observed.

### Task 2: Add the Evidence Workflow Core Without Replacing Upstream Modules

**Files:**
- Create: `faculty_workflow/__init__.py`
- Create: `faculty_workflow/models.py`
- Create: `faculty_workflow/database.py`
- Create: `faculty_workflow/adapters.py`
- Create: `faculty_workflow/directory_adapters.py`
- Create: `faculty_workflow/email_resolver.py`
- Create: `faculty_workflow/fetcher.py`
- Create: `faculty_workflow/session_store.py`
- Create: `faculty_workflow/importers.py`
- Create: `faculty_workflow/providers.py`
- Create: `faculty_workflow/quality.py`
- Create: `faculty_workflow/exporter.py`
- Create: `faculty_workflow/service.py`
- Create: `workflow.py`
- Test: `tests/test_workflow_adapters.py`
- Test: `tests/test_workflow_database.py`
- Test: `tests/test_workflow_provider.py`
- Test: `tests/test_workflow_service.py`

**Interfaces:**
- Produces: `WorkflowDatabase(path)`, `WorkflowService(database, ..., title_pipeline=None, discovery_provider=None)`, `CandidateExtraction`, `Evidence`, `evaluate_candidate()`, and the `workflow.py` subcommands `new`, `policy`, `run`, `status`, `review`, `export`.
- Consumes: upstream `FacultyCrawler`, `FacultyRecord`, `TitlePendingRecord`, and later `find_linked_directory_sources()`.

- [ ] **Step 1: Port the bounded package skeleton and existing tested behavior**

Create the package using the handoff modules as the behavior source. Keep imports package-local except for these upstream-facing imports:

```python
from crawler.faculty_crawler import FacultyCrawler
from crawler.parsers import FacultyRecord, TitlePendingRecord
from crawler.title_pipeline import TitlePipeline
```

- [ ] **Step 2: Add the title-pipeline dependency explicitly**

Extend `WorkflowService.__init__` with:

```python
def __init__(
    self,
    database: WorkflowDatabase,
    *,
    provider: ModelProvider | None = None,
    fetcher: PageFetcher | None = None,
    crawler_factory: Callable[[int], FacultyCrawler] | None = None,
    email_resolver: OfficialEmailResolver | None = None,
    directory_adapter: UniversalDirectoryAdapter | None = None,
    title_pipeline: TitlePipeline | None = None,
    discovery_provider: "DiscoveryProvider | None" = None,
    timeout_ms: int = 30000,
) -> None:
```

Store both dependencies but do not invoke search or translation until their focused tests exist.

- [ ] **Step 3: Verify GREEN for the imported contracts**

Run the four workflow test modules. Expected: all ported tests pass, except tests deliberately waiting on Tasks 3-6.

- [ ] **Step 4: Run upstream translation and parser regression tests**

Run: `.venv\Scripts\python.exe -m unittest tests.test_parsers tests.test_title_classifier tests.test_title_pipeline tests.test_translation tests.test_translation_settings -v`

Expected: PASS with no output-schema changes.

- [ ] **Step 5: Mark OpenSpec persistence tasks that are already proven by tests**

Check tasks 2.1, 2.3, and the existing portions of 2.4 only when their database tests pass; leave new source-graph/generation metadata unchecked.

### Task 3: Add Finite Official-Source Discovery and Enumeration Diagnostics

**Files:**
- Modify: `crawler/parsers.py`
- Modify: `faculty_workflow/models.py`
- Modify: `faculty_workflow/database.py`
- Modify: `faculty_workflow/service.py`
- Create: `faculty_workflow/discovery.py`
- Modify: `tests/test_parsers.py`
- Modify: `tests/test_workflow_database.py`
- Modify: `tests/test_workflow_service.py`

**Interfaces:**
- Produces: `LinkedDirectorySource`, `DiscoveryLimits`, `OfficialSourceGraph`, and `find_linked_directory_sources(html, base_url, official_domain)`.
- Consumes: normalized URLs and source persistence from Task 2.

- [ ] **Step 1: Write failing linked-source tests**

Add a parser test whose official directory contains links to a team page, laboratory, research center, institutional portal, unrelated news page, and third-party profile. Assert only supported official sources are returned with types `faculty_directory`, `research_unit`, and `research_portal`.

- [ ] **Step 2: Verify RED for missing source discovery**

Run the exact parser test. Expected: import or assertion failure because linked-source discovery is absent or incomplete.

- [ ] **Step 3: Implement the additive parser helper**

Add these public types without altering existing record parsing:

```python
@dataclass(frozen=True)
class LinkedDirectorySource:
    url: str
    source_type: str

def find_linked_directory_sources(
    html: str,
    base_url: str,
    official_domain: str = "",
) -> list[LinkedDirectorySource]:
    ...
```

Use same-institution hostname validation plus structural/label signals for people, research units, and official research portals. Do not add university names, domains, or selectors.

- [ ] **Step 4: Write and fail source-graph boundary tests**

Target this API in `faculty_workflow/discovery.py`:

```python
@dataclass(frozen=True)
class DiscoveryLimits:
    max_depth: int = 2
    max_pages: int = 50

class OfficialSourceGraph:
    def enqueue(self, url: str, source_type: str, discovered_from: str = "", depth: int = 0) -> bool: ...
    def pop(self) -> DirectorySource | None: ...
    @property
    def stop_reason(self) -> str: ...
```

Assert URL deduplication, page budget, depth rejection, and deterministic FIFO order.

- [ ] **Step 5: Implement the minimal graph and persist metadata**

Add `discovered_from`, `depth`, `official_boundary`, `fetch_state`, and `stop_reason` source columns through idempotent `ALTER TABLE` migrations guarded by `PRAGMA table_info`.

- [ ] **Step 6: Add enumeration diagnostics without changing parser validity**

Persist visited states, baseline unique count, duplicate count, and coverage stop reason on the school or generation summary. Email-less records remain in the baseline and generic parser export.

- [ ] **Step 7: Run focused and full parser tests**

Expected: new discovery/graph tests pass and all existing parser/dynamic-loader tests remain green.

### Task 4: Decode Page-Present Emails and Merge Source-Scoped Evidence

**Files:**
- Modify: `faculty_workflow/adapters.py`
- Modify: `faculty_workflow/email_resolver.py`
- Modify: `faculty_workflow/models.py`
- Modify: `faculty_workflow/service.py`
- Modify: `faculty_workflow/quality.py`
- Modify: `tests/test_workflow_adapters.py`
- Modify: `tests/test_workflow_service.py`
- Modify: `tests/test_workflow_database.py`

**Interfaces:**
- Produces: deterministic email preprocessing, `merge_official_evidence()`, and strict completion decisions.
- Consumes: source graph pages and upstream directory person baseline.

- [ ] **Step 1: Add RED tests for JLU-style split email**

Use synthetic markup, not a real person:

```html
<a class="jluint email-link" href="mailto:ada?subject=x" rel="physik.uni">E-Mail</a>
```

Assert the adapter reconstructs `ada@physik.uni` because both components are page-present. Add a negative test with only `ada` and no domain; assert no email.

- [ ] **Step 2: Implement deterministic attribute/JavaScript decoding**

Preprocess only syntactically complete component pairs and inject a normal `mailto:`/visible address for downstream extraction. Record extraction method `page_split_email`; never synthesize a domain from school configuration.

- [ ] **Step 3: Add RED tests for exact-name secondary evidence merging**

Create one directory seed without email and one official lab card with the same normalized name and a full email. Assert the merged candidate keeps both source evidence entries and the lab email. Add collision tests for duplicate normalized names and conflicting emails; assert review.

- [ ] **Step 4: Implement source-scoped evidence merging**

Use this pure interface:

```python
def merge_official_evidence(
    baseline: CandidateExtraction,
    additions: tuple[CandidateExtraction, ...],
) -> CandidateExtraction:
    ...
```

Merge only one unambiguous normalized identity. Retain each `Evidence(field, quote, source_url, extraction_method, status)` item and discard email evidence whose full normalized address is absent from its originating quote or deterministic markup representation.

- [ ] **Step 5: Add strict completion negative tests**

Assert guessed addresses, generic contacts, third-party sources, search snippets, missing evidence, and email conflicts return `review` or `rejected`, never `accepted`.

- [ ] **Step 6: Run adapter, service, quality, and database tests**

Expected: all new positive and negative evidence tests pass.

### Task 5: Integrate Local Title Translation Without Weakening Provenance

**Files:**
- Modify: `faculty_workflow/models.py`
- Modify: `faculty_workflow/service.py`
- Modify: `faculty_workflow/exporter.py`
- Modify: `tests/test_workflow_service.py`
- Modify: `tests/test_workflow_database.py`
- Modify: `tests/test_export.py`

**Interfaces:**
- Produces: persisted/exported `title_original`, `title_translated`, `title_language`, `translation_status`, `translation_engine`, and `classification_rules_version`.
- Consumes: `TitlePipeline.process(title_original, language_hint="") -> ProcessedTitle`.

- [ ] **Step 1: Write RED test for an unknown non-English official title**

Inject a fake `TitlePipeline` result that translates an official title to `Associate Professor`. Assert original title evidence remains unchanged and translated metadata assists normalized role classification.

- [ ] **Step 2: Add translation fields through forward-only migration**

Extend candidate storage and extraction JSON with empty/default-safe fields so old task databases load without migration data loss.

- [ ] **Step 3: Call translation only after original-title evidence exists**

Process directory/profile title once per merged candidate, and never treat translated text as an official quote.

- [ ] **Step 4: Add translation-failure test**

Assert `service_unavailable` or unknown translated classification keeps the person in review and never removes the baseline person.

- [ ] **Step 5: Verify upstream and workflow translation suites**

Run all translation/title/workflow service tests; expected all pass.

### Task 6: Add Search-Hint Re-fetch and Review-Only Generations

**Files:**
- Modify: `faculty_workflow/discovery.py`
- Modify: `faculty_workflow/database.py`
- Modify: `faculty_workflow/service.py`
- Modify: `faculty_workflow/exporter.py`
- Modify: `tests/test_workflow_database.py`
- Modify: `tests/test_workflow_service.py`

**Interfaces:**
- Produces: `DiscoveryProvider`, `DiscoveryHint`, `begin_review_generation()`, `resume_review_generation()`, and generation audit fields.
- Consumes: normal `PageFetcher` and strict evidence merge from Tasks 3-4.

- [ ] **Step 1: Write RED search trust tests**

Target this protocol:

```python
@dataclass(frozen=True)
class DiscoveryHint:
    url: str
    query: str

class DiscoveryProvider(Protocol):
    def discover(self, *, name: str, school: str, official_domain: str) -> tuple[DiscoveryHint, ...]: ...
```

Assert hint snippets are not accepted by the type, every hint URL is re-fetched, unofficial final URLs are rejected, and fetch failures leave review.

- [ ] **Step 2: Implement provider isolation and official re-fetch**

The default provider returns an empty tuple. Configured providers return URLs only. Feed validated official target pages through normal extraction and evidence merging.

- [ ] **Step 3: Write RED review-generation tests**

Create one completed and one review candidate, call `begin_review_generation(task_id)`, and assert only review rows are superseded/requeued. Call it again while active and assert resume/no second reset. Simulate interruption and assert recovery.

- [ ] **Step 4: Implement generation schema and atomic transitions**

Add a `reprocessing_generations` table with task ID, status, timestamps, superseded IDs JSON, requeued school IDs JSON, and summary JSON. Perform candidate superseding and school requeue in one transaction.

- [ ] **Step 5: Guard completed identities and reuse sources**

Skip candidates matching a completed normalized person identity or normalized homepage. Reuse successful source snapshots/fetch metadata when valid; do not re-fetch solely because a review generation resumed.

- [ ] **Step 6: Add audit assertions**

Verify audit JSON reports generation scope/counts and proves completed candidate IDs and values are unchanged.

### Task 7: Expose the Workflow Locally Without Breaking Existing CLI/UI

**Files:**
- Modify: `workflow.py`
- Modify: `faculty_workflow/exporter.py`
- Modify: `desktop_app.py`
- Modify: `ui/controller.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_desktop_app.py`
- Test: `tests/test_ui_controller.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Produces: `workflow.py reprocess-reviews --task TASK_ID`, evidence exports, and a desktop controller action that invokes review-only behavior.
- Preserves: existing `main.py`, URL batch flow, current Excel columns, and translation settings behavior.

- [ ] **Step 1: Add RED CLI test**

Assert `reprocess-reviews` calls only `WorkflowDatabase.begin_review_generation()` plus `WorkflowService.run_task()` and never calls whole-school reset.

- [ ] **Step 2: Implement CLI command and UTF-8-safe status output**

Add the subcommand with required `--task`; return the generation ID, requeued review count, and summary.

- [ ] **Step 3: Add export metadata without changing existing front columns**

Append evidence/translation/review columns only to the evidence-workflow workbooks. Keep existing generic crawler exports unchanged.

- [ ] **Step 4: Add RED controller test and minimal desktop action**

Expose a controller method for review-only reprocessing. Keep UI state transitions on the main thread and reuse existing worker/event patterns.

- [ ] **Step 5: Add privacy regression tests**

Assert audit/log/report output omits cookies, Authorization, tokens, session payloads, local browser state, and HTML bodies.

- [ ] **Step 6: Run CLI, export, desktop, and UI suites**

Expected: all existing and new tests pass.

### Task 8: Verify, Rehearse on a Copy, and Report

**Files:**
- Create: `docs/validation/2026-07-30-official-faculty-coverage-acceptance.md`
- Modify: `openspec/changes/increase-official-faculty-coverage/tasks.md`

**Interfaces:**
- Consumes: all code and tests from Tasks 1-7.
- Produces: local acceptance evidence and completed OpenSpec checkboxes; no release artifact.

- [ ] **Step 1: Run focused suites**

Run workflow adapters/database/provider/service, parser, dynamic-loader, translation, exporter, CLI, desktop, and UI tests. Expected: zero failures/errors.

- [ ] **Step 2: Run the complete suite**

Run `.venv\Scripts\python.exe -m unittest discover -s tests -v`. Expected: all 486 upstream tests plus every new workflow test pass.

- [ ] **Step 3: Rehearse database migration on a copy**

Compute SHA-256 of the original historical `workflow.db`, copy it to a temporary directory, open/migrate only the copy, and recompute the original hash. Expected: original hashes match exactly.

- [ ] **Step 4: Run JLU, TSU, and UCR pilots with bounded official access**

Record baseline person count, completed/review/rejected counts, failed sources, source-type counts, and discovery stop reason. Do not use search snippets as evidence and do not infer missing email addresses.

- [ ] **Step 5: Audit completion invariants**

Query every completed row and verify it has supported official name/title/department/relevance evidence plus a complete official personal email evidence item. Verify completed records from the prior generation are unchanged.

- [ ] **Step 6: Write local acceptance report and finish OpenSpec progress**

Record files/functions changed, old rules preserved, tests added, full results, pilot before/after counts, known review limitations, and the fact that no commit/push/package occurred. Check each OpenSpec task only when its evidence is present.
