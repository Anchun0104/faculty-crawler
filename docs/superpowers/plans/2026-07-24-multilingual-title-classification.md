# Multilingual Academic Title Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an auditable post-parse title classification layer that preserves known English behavior, uses local LibreTranslate only as a fallback, and exports included, excluded, and review records without silently losing unknown non-English academics.

**Architecture:** HTML parsing remains synchronous and network-free. A pure `TitleClassifier` applies deterministic original-language and English rules; a separate `LibreTranslateClient` performs optional localhost translation with SQLite caching; `FacultyCrawler` coordinates both after parsing and retains backward compatibility by returning included `FacultyRecord` objects. Exporters add review, exclusion, and run-summary sheets while CLI, batch, and desktop entry points expose translation configuration and status.

**Tech Stack:** Python 3.14 main application, standard-library `dataclasses`, `enum`, `sqlite3`, `urllib.request`, `unittest`, OpenPyXL, Playwright, Docker Compose with a pinned LibreTranslate image.

## Global Constraints

- Keep the official source title unchanged in `FacultyRecord.title`; translated text is auxiliary.
- Translation is a fallback only and must never run inside `crawler/parsers.py`.
- Only `http://127.0.0.1:5000` is enabled by default; no hosted translation fallback.
- LibreTranslate failure must produce `review`, never crawler failure or automatic exclusion.
- `Emeritus`, `Emerita`, `Honorary`, `Retired`, and `Former` have unconditional exclusion priority.
- `Doctoral Researcher` alone is included; any co-occurring Student, Candidate, Teaching Assistant, or Research Assistant phrase excludes it.
- Librarians, IT, data/software, laboratory technical, administrative, student-service, finance, HR, communications, facilities, and research professional-support roles are excluded by full phrases, not broad single words.
- Do not commit people data, translation caches, Docker volumes/models, virtual environments, browser caches, credentials, cookies, or logs.
- Minimize C-drive use: install only required translation models, report local cache paths/sizes, and keep cleanup gated on successful new-computer verification.
- Every parser change follows `CODEX_PARSER_RULES.md`: positive, regression, and negative coverage.

---

## File Structure

- Create `crawler/title_classifier.py`: pure normalization, rule tables, classification enums and result types.
- Create `crawler/translation.py`: localhost client, `/languages` capability check, `/translate`, SQLite cache and structured statuses.
- Create `crawler/title_pipeline.py`: coordinates original classification, optional translation and second classification.
- Modify `crawler/parsers.py`: extend `FacultyRecord` with backward-compatible metadata defaults and relax only proven premature title filtering.
- Modify `crawler/faculty_crawler.py`: run the post-parse pipeline, retain review/excluded records and export a multi-sheet workbook.
- Modify `crawler/batch.py`: pass translation configuration and all classification outputs to the exporter.
- Modify `main.py`: add CLI flags and logging.
- Modify `desktop_app.py`: add local-translation toggle, service status and worker plumbing.
- Create `tests/test_title_classifier.py`, `tests/test_translation.py`, `tests/test_title_pipeline.py`.
- Modify `tests/test_parsers.py`, `tests/test_crawler_diagnostics.py`, `tests/test_export.py`, `tests/test_batch.py`, `tests/test_cli.py`, `tests/test_desktop_app.py`, `tests/test_release.py`, `tests/test_handoff.py`.
- Create `docker-compose.translate.yml`.
- Modify `.gitignore`, `README.md`, `使用说明.txt`, `build_release.py`, `build_handoff.py`, `任务转接说明.md`.

---

### Task 1: Classification Data Contract and Normalization

**Files:**
- Create: `crawler/title_classifier.py`
- Create: `tests/test_title_classifier.py`

**Interfaces:**
- Produces: `StaffClassification`, `AcademicTrack`, `AffiliationStatus`, `ConfidenceTier`, `ClassificationResult`.
- Produces: `normalize_title(value: str) -> str`.
- Produces: `TitleClassifier.classify(value: str, *, translated: bool = False) -> ClassificationResult`.

- [ ] **Step 1: Write failing contract and normalization tests**

```python
import unittest

from crawler.title_classifier import (
    AcademicTrack,
    AffiliationStatus,
    ClassificationResult,
    ConfidenceTier,
    StaffClassification,
    normalize_title,
)


class TitleClassifierContractTests(unittest.TestCase):
    def test_normalize_title_preserves_unicode_and_normalizes_spacing(self) -> None:
        self.assertEqual(normalize_title("  أستاذ\u00a0 مشارك  "), "أستاذ مشارك")

    def test_result_exposes_auditable_fields(self) -> None:
        result = ClassificationResult(
            classification=StaffClassification.INCLUDE,
            academic_track=AcademicTrack.RESEARCH,
            affiliation_status=AffiliationStatus.CURRENT,
            reason="academic_phrase:research fellow",
            matched_rule="research fellow",
            confidence=ConfidenceTier.HIGH,
        )
        self.assertEqual(result.classification.value, "include")
        self.assertEqual(result.reason, "academic_phrase:research fellow")
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run:

```powershell
python -m unittest tests.test_title_classifier -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'crawler.title_classifier'`.

- [ ] **Step 3: Implement the minimal data contract**

```python
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class StaffClassification(str, Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    REVIEW = "review"


class AcademicTrack(str, Enum):
    TEACHING_AND_RESEARCH = "teaching_and_research"
    RESEARCH = "research"
    TEACHING = "teaching"
    CLINICAL = "clinical"
    PROFESSIONAL_PRACTICE = "professional_practice"
    VISITING = "visiting"
    ADJUNCT = "adjunct"
    POSTDOCTORAL = "postdoctoral"
    DOCTORAL_RESEARCHER = "doctoral_researcher"
    UNKNOWN = "unknown"


class AffiliationStatus(str, Enum):
    CURRENT = "current"
    VISITING = "visiting"
    ADJUNCT = "adjunct"
    INACTIVE_OR_HONORARY = "inactive_or_honorary"
    UNKNOWN = "unknown"


class ConfidenceTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class ClassificationResult:
    classification: StaffClassification
    academic_track: AcademicTrack = AcademicTrack.UNKNOWN
    affiliation_status: AffiliationStatus = AffiliationStatus.UNKNOWN
    reason: str = "no_rule_matched"
    matched_rule: str = ""
    confidence: ConfidenceTier = ConfidenceTier.LOW


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


class TitleClassifier:
    def classify(self, value: str, *, translated: bool = False) -> ClassificationResult:
        return ClassificationResult(classification=StaffClassification.REVIEW)
```

- [ ] **Step 4: Run the focused tests**

Run:

```powershell
python -m unittest tests.test_title_classifier -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add crawler/title_classifier.py tests/test_title_classifier.py
git commit -m "feat: add title classification data contract"
```

---

### Task 2: Deterministic Inclusion, Exclusion and Ambiguity Rules

**Files:**
- Modify: `crawler/title_classifier.py`
- Modify: `tests/test_title_classifier.py`

**Interfaces:**
- Consumes: `normalize_title()` and classification types from Task 1.
- Produces: deterministic, network-free `TitleClassifier.classify()`.

- [ ] **Step 1: Add failing priority and scope tests**

Add table-driven tests covering the exact policy:

```python
class TitleClassifierRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = TitleClassifier()

    def assert_classification(self, title: str, expected: StaffClassification) -> None:
        self.assertEqual(self.classifier.classify(title).classification, expected)

    def test_confirmed_inclusions(self) -> None:
        for title in (
            "Reader",
            "Associate Lecturer",
            "Research Fellow",
            "Postdoctoral Researcher",
            "Clinical Lecturer",
            "Professor of Practice",
            "Visiting Professor",
            "Adjunct Professor",
            "Doctoral Researcher",
            "أستاذ مشارك",
        ):
            with self.subTest(title=title):
                self.assert_classification(title, StaffClassification.INCLUDE)

    def test_status_exclusions_override_academic_titles(self) -> None:
        for title in (
            "Emeritus Professor and Research Director",
            "Honorary Clinical Professor",
            "Former Professor, Senior Research Fellow",
            "Retired Reader",
        ):
            with self.subTest(title=title):
                self.assert_classification(title, StaffClassification.EXCLUDE)

    def test_student_and_assistant_exclusions_override_doctoral_researcher(self) -> None:
        for title in (
            "Doctoral Researcher / PhD Candidate",
            "Doctoral Researcher and Teaching Assistant",
            "Research Assistant",
            "PhD Student",
        ):
            with self.subTest(title=title):
                self.assert_classification(title, StaffClassification.EXCLUDE)

    def test_professional_services_are_excluded_without_broad_word_false_positives(self) -> None:
        excluded = (
            "Academic Librarian",
            "IT Technologist",
            "Research Software Engineer",
            "Bioinformatician",
            "Laboratory Technician",
            "Research Support Officer",
            "Teaching Administrator",
            "Communications Officer",
            "Facilities Manager",
        )
        included = (
            "Professor of Library Science",
            "Assistant Professor",
            "Research Scientist",
            "Professor of Information Technology",
        )
        for title in excluded:
            with self.subTest(title=title):
                self.assert_classification(title, StaffClassification.EXCLUDE)
        for title in included:
            with self.subTest(title=title):
                self.assert_classification(title, StaffClassification.INCLUDE)

    def test_ambiguous_titles_require_review(self) -> None:
        for title in ("Researcher", "Director", "Consultant Cardiologist", "Program Coordinator"):
            with self.subTest(title=title):
                self.assert_classification(title, StaffClassification.REVIEW)
```

- [ ] **Step 2: Run tests and verify rule failures**

Run:

```powershell
python -m unittest tests.test_title_classifier -v
```

Expected: rule tests FAIL because every title is currently `review`.

- [ ] **Step 3: Implement ordered phrase rules**

Implement rule sets as normalized complete phrases and boundary-aware regular expressions. The first version must include all titles approved in the design document. Use the following evaluation skeleton:

```python
RULES_VERSION = "2026.07.1"


def _contains_phrase(title: str, phrase: str) -> bool:
    pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
    return re.search(pattern, title, flags=re.IGNORECASE) is not None


class TitleClassifier:
    def classify(self, value: str, *, translated: bool = False) -> ClassificationResult:
        title = normalize_title(value)
        if not title:
            return ClassificationResult(
                classification=StaffClassification.REVIEW,
                reason="missing_title",
            )

        folded = title.casefold()
        for phrase in STATUS_EXCLUSIONS:
            if _contains_phrase(folded, phrase):
                return _excluded("inactive_or_honorary", phrase)

        for phrase in STUDENT_AND_ASSISTANT_EXCLUSIONS:
            if _contains_phrase(folded, phrase):
                return _excluded("student_or_assistant", phrase)

        for category, phrases in PROFESSIONAL_STAFF_EXCLUSIONS.items():
            for phrase in phrases:
                if _contains_phrase(folded, phrase):
                    return _excluded(category, phrase)

        for phrase, track, status in ACADEMIC_INCLUSIONS:
            if _contains_phrase(folded, phrase):
                return ClassificationResult(
                    classification=StaffClassification.INCLUDE,
                    academic_track=track,
                    affiliation_status=status,
                    reason=f"academic_phrase:{phrase}",
                    matched_rule=phrase,
                    confidence=ConfidenceTier.MEDIUM if translated else ConfidenceTier.HIGH,
                )

        for phrase in AMBIGUOUS_TITLES:
            if _contains_phrase(folded, phrase):
                return ClassificationResult(
                    classification=StaffClassification.REVIEW,
                    reason=f"ambiguous_phrase:{phrase}",
                    matched_rule=phrase,
                    confidence=ConfidenceTier.LOW,
                )

        return ClassificationResult(
            classification=StaffClassification.REVIEW,
            reason="no_rule_matched",
        )
```

Include correct Unicode source phrases such as `أستاذ`, `أستاذ مشارك`, `أستاذ مساعد`, `محاضر`, `محاضر أول`, `مدرس`, `عضو هيئة تدريس`, `باحث مشارك`, `باحث رئيسي`, `أستاذ زائر`, `أستاذ ممارس`, `catedràtic`, `catedrática`, `professeur des universités`, `maître de conférences`, `privatdozent`, `universitair docent`, and `hoogleraar`.

- [ ] **Step 4: Run classifier tests**

Run:

```powershell
python -m unittest tests.test_title_classifier -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add crawler/title_classifier.py tests/test_title_classifier.py
git commit -m "feat: classify academic and professional staff titles"
```

---

### Task 3: Local LibreTranslate Client and SQLite Cache

**Files:**
- Create: `crawler/translation.py`
- Create: `tests/test_translation.py`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `TranslationStatus`, `TranslationResult`, `LanguageCapability`.
- Produces: `TranslationCache.get(...)`, `TranslationCache.put(...)`, `TranslationCache.size_bytes`.
- Produces: `LibreTranslateClient.check_capabilities() -> tuple[LanguageCapability, ...]`.
- Produces: `LibreTranslateClient.translate(title: str, source_language: str = "auto") -> TranslationResult`.

- [ ] **Step 1: Write failing cache and client tests**

Use a dependency-injected transport so unit tests never require Docker:

```python
import tempfile
import unittest
from pathlib import Path

from crawler.translation import (
    LibreTranslateClient,
    TranslationCache,
    TranslationStatus,
)


class TranslationTests(unittest.TestCase):
    def test_successful_translation_is_cached(self) -> None:
        calls = []

        def transport(method: str, path: str, payload: dict | None, timeout: float):
            calls.append((method, path, payload))
            if path == "/languages":
                return [{"code": "ar", "name": "Arabic", "targets": ["en"]}]
            return {"translatedText": "Associate Professor", "detectedLanguage": {"language": "ar"}}

        with tempfile.TemporaryDirectory() as temp_dir:
            cache = TranslationCache(Path(temp_dir) / "translations.sqlite3")
            client = LibreTranslateClient(transport=transport, cache=cache)
            first = client.translate("أستاذ مشارك", source_language="ar")
            second = client.translate("أستاذ مشارك", source_language="ar")

        self.assertEqual(first.status, TranslationStatus.SUCCESS)
        self.assertEqual(second.status, TranslationStatus.CACHE_HIT)
        self.assertEqual(second.translated_text, "Associate Professor")
        self.assertEqual(sum(path == "/translate" for _, path, _ in calls), 1)

    def test_service_failure_returns_status_instead_of_raising(self) -> None:
        def failing_transport(method: str, path: str, payload: dict | None, timeout: float):
            raise TimeoutError("offline")

        client = LibreTranslateClient(transport=failing_transport)
        result = client.translate("أستاذ", source_language="ar")
        self.assertEqual(result.status, TranslationStatus.TIMEOUT)
        self.assertEqual(result.translated_text, "")
```

- [ ] **Step 2: Run tests and verify the module is missing**

Run:

```powershell
python -m unittest tests.test_translation -v
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement cache, statuses and localhost-only client**

Use `urllib.request` for JSON requests and `sqlite3` for cache storage. Constructor defaults:

```python
LibreTranslateClient(
    endpoint="http://127.0.0.1:5000",
    connect_timeout=2.0,
    response_timeout=10.0,
    retries=1,
    cache=TranslationCache(default_cache_path()),
)
```

Reject non-loopback defaults using parsed hostname validation. Return, rather than raise, these statuses:

```python
class TranslationStatus(str, Enum):
    SUCCESS = "translation_success"
    CACHE_HIT = "cache_hit"
    NOT_NEEDED = "not_needed"
    SERVICE_UNAVAILABLE = "service_unavailable"
    TIMEOUT = "timeout"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    INVALID_RESPONSE = "invalid_response"
    FAILED = "translation_failed"
```

Create the cache table with:

```sql
CREATE TABLE IF NOT EXISTS translations (
    cache_key TEXT PRIMARY KEY,
    original_title TEXT NOT NULL,
    translated_title TEXT NOT NULL,
    source_language TEXT NOT NULL,
    target_language TEXT NOT NULL,
    engine TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL
)
```

- [ ] **Step 4: Ignore local runtime artifacts**

Add:

```gitignore
.pytest_cache/
**/__pycache__/
translation_cache.sqlite3
*.sqlite3-wal
*.sqlite3-shm
handoff/reviewed_titles.xlsx
handoff/custom_title_rules.json
handoff/translation_cache.sqlite3
handoff/handoff-cleanup-manifest.json
```

Do not add a rule that hides all `.xlsx` files because existing release and test expectations may rely on tracked spreadsheet fixtures or outputs.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
python -m unittest tests.test_translation -v
```

Expected: PASS without Docker or network.

- [ ] **Step 6: Commit**

```powershell
git add crawler/translation.py tests/test_translation.py .gitignore
git commit -m "feat: add local translation client and cache"
```

---

### Task 4: Original-First Translation Pipeline

**Files:**
- Create: `crawler/title_pipeline.py`
- Create: `tests/test_title_pipeline.py`

**Interfaces:**
- Consumes: `TitleClassifier`, `LibreTranslateClient`.
- Produces: `ProcessedTitle`.
- Produces: `TitlePipeline.process(title_original: str, *, language_hint: str = "") -> ProcessedTitle`.

- [ ] **Step 1: Write failing pipeline tests**

```python
import unittest

from crawler.title_classifier import StaffClassification, TitleClassifier
from crawler.title_pipeline import TitlePipeline
from crawler.translation import TranslationResult, TranslationStatus


class FakeTranslator:
    def __init__(self, result: TranslationResult):
        self.result = result
        self.calls = []

    def translate(self, title: str, source_language: str = "auto") -> TranslationResult:
        self.calls.append((title, source_language))
        return self.result


class TitlePipelineTests(unittest.TestCase):
    def test_known_original_title_does_not_call_translation(self) -> None:
        translator = FakeTranslator(
            TranslationResult(status=TranslationStatus.SUCCESS, translated_text="unused")
        )
        result = TitlePipeline(TitleClassifier(), translator).process("أستاذ مشارك")
        self.assertEqual(result.classification.classification, StaffClassification.INCLUDE)
        self.assertEqual(translator.calls, [])

    def test_unknown_non_english_title_uses_translation(self) -> None:
        translator = FakeTranslator(
            TranslationResult(
                status=TranslationStatus.SUCCESS,
                translated_text="Associate Professor",
                detected_language="ar",
            )
        )
        result = TitlePipeline(TitleClassifier(), translator).process("لقب أكاديمي")
        self.assertEqual(result.classification.classification, StaffClassification.INCLUDE)
        self.assertEqual(result.title_translated, "Associate Professor")

    def test_translation_failure_is_review(self) -> None:
        translator = FakeTranslator(
            TranslationResult(status=TranslationStatus.SERVICE_UNAVAILABLE)
        )
        result = TitlePipeline(TitleClassifier(), translator).process("لقب غير معروف")
        self.assertEqual(result.classification.classification, StaffClassification.REVIEW)
        self.assertEqual(result.translation_status, "service_unavailable")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```powershell
python -m unittest tests.test_title_pipeline -v
```

Expected: FAIL because `crawler.title_pipeline` does not exist.

- [ ] **Step 3: Implement the pipeline**

Use a frozen result:

```python
@dataclass(frozen=True)
class ProcessedTitle:
    title_original: str
    title_translated: str
    title_language: str
    classification: ClassificationResult
    translation_status: str
    translation_engine: str = ""
    rules_version: str = RULES_VERSION
```

Processing rules:

1. Classify original text.
2. Return immediately for deterministic include/exclude.
3. If the title is empty, return review without translation.
4. If translation is disabled or unavailable, return review.
5. Translate once.
6. Classify translated text with `translated=True`.
7. Preserve the original review reason if translation fails.

Use a lightweight `contains_non_ascii_letters()` helper plus optional `language_hint`; do not add a language-detection dependency.

- [ ] **Step 4: Run pipeline and classifier tests**

Run:

```powershell
python -m unittest tests.test_title_pipeline tests.test_title_classifier tests.test_translation -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add crawler/title_pipeline.py tests/test_title_pipeline.py
git commit -m "feat: add original-first title processing pipeline"
```

---

### Task 5: Integrate Classification After Parsing

**Files:**
- Modify: `crawler/parsers.py`
- Modify: `crawler/faculty_crawler.py`
- Modify: `tests/test_parsers.py`
- Modify: `tests/test_crawler_diagnostics.py`

**Interfaces:**
- Keeps: `FacultyCrawler.crawl(url: str) -> list[FacultyRecord]`, returning only included records.
- Adds: `FacultyCrawler.review_records`, `FacultyCrawler.excluded_records`, `FacultyCrawler.classification_summary`.
- Extends: `FacultyRecord` with defaulted classification metadata so all current positional constructors remain valid.

- [ ] **Step 1: Write failing crawler integration tests**

Add a test that passes parsed records through an injected pipeline:

```python
def test_post_parse_pipeline_keeps_include_and_audits_review_and_exclude(self):
    crawler = FacultyCrawler(title_pipeline=FakeTitlePipeline({
        "Professor": processed_include("Professor"),
        "IT Technologist": processed_exclude("IT Technologist"),
        "لقب غير معروف": processed_review("لقب غير معروف"),
    }))
    html = """
    <main><h2>Faculty and Staff</h2>
      <div class="person"><a href="/people/a">Ada</a><p>Professor</p></div>
      <div class="person"><a href="/people/b">Bob</a><p>IT Technologist</p></div>
      <div class="person"><a href="/people/c">Cora</a><p>لقب غير معروف</p></div>
    </main>
    """
    records = crawler._parse_fetched_html("https://example.edu/people", html, 200)
    self.assertEqual([record.name for record in records], ["Ada"])
    self.assertEqual([record.name for record in crawler.excluded_records], ["Bob"])
    self.assertEqual([record.name for record in crawler.review_records], ["Cora"])
```

Add parser regression coverage proving:

- a known English faculty card still parses;
- a reliable linked card with an Arabic title reaches the candidate list;
- an administrative navigation block does not become a person.

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```powershell
python -m unittest tests.test_crawler_diagnostics tests.test_parsers -v
```

Expected: new integration tests FAIL; existing tests remain green.

- [ ] **Step 3: Extend `FacultyRecord` compatibly**

Append defaulted fields after `email`:

```python
title_translated: str = ""
title_language: str = ""
staff_classification: str = "include"
academic_track: str = "unknown"
affiliation_status: str = "unknown"
classification_reason: str = "legacy_parser_acceptance"
matched_rule: str = ""
confidence_tier: str = "high"
translation_status: str = "not_needed"
translation_engine: str = ""
classification_rules_version: str = ""
source_url: str = ""
```

Do not rename or reorder the existing first four fields.

- [ ] **Step 4: Inject and run the pipeline in `FacultyCrawler`**

Extend the constructor:

```python
def __init__(
    self,
    timeout: int = 30000,
    headless: bool = True,
    title_pipeline: TitlePipeline | None = None,
) -> None:
```

Initialize review and excluded collections at each crawl. Convert each parsed record with `dataclasses.replace()`. Keep included records in the return value; append the others to their audit collections. Add diagnostic counts without removing existing keys.

- [ ] **Step 5: Relax only the tested premature filters**

Where `_is_title_text()` or `_is_non_faculty_member_title()` currently rejects a reliable person block solely because an unknown non-English title misses `ACADEMIC_TITLE_PATTERNS`, allow the record to reach the pipeline only when existing person and profile-URL evidence is already sufficient.

Do not loosen:

- name validation;
- individual profile URL requirements;
- navigation/header exclusions;
- candidate boundaries;
- explicit excluded directory sections.

Fix corrupted Unicode entries such as `catedr脿tic` to valid source text and add an exact regression assertion.

- [ ] **Step 6: Run parser and crawler tests**

Run:

```powershell
python -m unittest tests.test_parsers tests.test_crawler_diagnostics -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add crawler/parsers.py crawler/faculty_crawler.py tests/test_parsers.py tests/test_crawler_diagnostics.py
git commit -m "feat: classify titles after faculty parsing"
```

---

### Task 6: Multi-Sheet Excel Export

**Files:**
- Modify: `crawler/faculty_crawler.py`
- Modify: `tests/test_export.py`

**Interfaces:**
- Extends: `export_to_excel(records, output_path, *, review_records=(), excluded_records=(), summary=None)`.
- Keeps: existing two-positional-argument calls valid.

- [ ] **Step 1: Write failing workbook tests**

Create include, review and excluded `FacultyRecord` fixtures and assert:

```python
workbook = load_workbook(output_path)
self.assertEqual(
    workbook.sheetnames,
    ["Faculty", "Review", "Excluded", "Run Summary"],
)
self.assertEqual(workbook["Faculty"]["B2"].value, "أستاذ مشارك")
self.assertEqual(workbook["Faculty"]["C2"].value, "Associate Professor")
self.assertEqual(workbook["Review"]["A2"].value, "Needs Review")
self.assertEqual(workbook["Excluded"]["A2"].value, "Library Person")
self.assertEqual(workbook["Run Summary"]["A2"].value, "included_count")
```

Retain a compatibility assertion that `export_to_excel(records, output_path)` still succeeds.

- [ ] **Step 2: Run tests and verify missing sheets**

Run:

```powershell
python -m unittest tests.test_export -v
```

Expected: new test FAIL because only `Faculty` exists.

- [ ] **Step 3: Implement the sheets**

Use these `Faculty` columns:

```python
[
    "Name", "Title", "Title_Translated", "Title_Language",
    "Academic_Track", "Profile_URL", "Email",
    "Classification_Reason", "Translation_Status", "Source_URL",
]
```

Use these `Review` columns:

```python
[
    "Name", "Title_Original", "Title_Translated", "Title_Language",
    "Profile_URL", "Email", "Review_Reason", "Translation_Status",
    "Suggested_Action", "Manual_Decision", "Manual_Note", "Source_URL",
]
```

Use these `Excluded` columns:

```python
[
    "Name", "Title_Original", "Title_Translated", "Profile_URL",
    "Exclusion_Category", "Classification_Reason", "Source_URL",
]
```

Use key/value rows for `Run Summary`. Preserve `export_title_pending_to_excel()` for truly missing or honorific-only source titles.

- [ ] **Step 4: Run export tests**

Run:

```powershell
python -m unittest tests.test_export -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add crawler/faculty_crawler.py tests/test_export.py
git commit -m "feat: export title classification audit sheets"
```

---

### Task 7: CLI, Batch and Desktop Configuration

**Files:**
- Modify: `main.py`
- Modify: `crawler/batch.py`
- Modify: `desktop_app.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_batch.py`
- Modify: `tests/test_desktop_app.py`

**Interfaces:**
- Adds CLI: `--no-local-translation`.
- Adds CLI: `--translation-endpoint`, default `http://127.0.0.1:5000`, validated as loopback.
- Batch factory receives `enable_translation` and `translation_endpoint`.
- Desktop adds a BooleanVar toggle and non-blocking status label/check action.

- [ ] **Step 1: Write failing CLI tests**

Assert:

```python
exit_code = main([
    "https://example.edu/faculty",
    "--output", "output/result.xlsx",
    "--no-local-translation",
])
self.assertEqual(exit_code, 0)
FacultyCrawler.assert_called_once()
self.assertIsNone(FacultyCrawler.call_args.kwargs["title_pipeline"].translator)
```

Also assert a non-loopback endpoint returns exit code 2:

```python
main([
    "https://example.edu/faculty",
    "--translation-endpoint", "https://libretranslate.com",
])
```

- [ ] **Step 2: Write failing batch and desktop tests**

Verify worker plumbing passes the toggle and endpoint to `run_tasks`, and status-check failures enqueue/display a non-fatal message.

- [ ] **Step 3: Run entry-point tests and verify failure**

Run:

```powershell
python -m unittest tests.test_cli tests.test_batch tests.test_desktop_app -v
```

Expected: FAIL for missing options and arguments.

- [ ] **Step 4: Implement CLI and batch plumbing**

Build the default pipeline in one helper:

```python
def build_title_pipeline(
    enabled: bool,
    endpoint: str = "http://127.0.0.1:5000",
) -> TitlePipeline:
    translator = LibreTranslateClient(endpoint=endpoint) if enabled else None
    return TitlePipeline(TitleClassifier(), translator)
```

After crawling, call:

```python
export_to_excel(
    records,
    args.output,
    review_records=crawler.review_records,
    excluded_records=crawler.excluded_records,
    summary=crawler.classification_summary,
)
```

Do the equivalent inside `run_tasks()` without changing per-task isolation.

- [ ] **Step 5: Add desktop controls**

Add:

```text
☑ 启用本地职位翻译
本地翻译：未检查 / 已连接 / 未启动 / 缺少语言模型
[检查服务]
```

The check action must run off the Tk main thread and report through the existing event queue. It must not install Docker, download models, or block task preparation.

- [ ] **Step 6: Run entry-point tests**

Run:

```powershell
python -m unittest tests.test_cli tests.test_batch tests.test_desktop_app -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add main.py crawler/batch.py desktop_app.py tests/test_cli.py tests/test_batch.py tests/test_desktop_app.py
git commit -m "feat: expose local title translation controls"
```

---

### Task 8: Docker, Documentation, Release and Handoff Portability

**Files:**
- Create: `docker-compose.translate.yml`
- Modify: `README.md`
- Modify: `使用说明.txt`
- Modify: `build_release.py`
- Modify: `build_handoff.py`
- Modify: `任务转接说明.md`
- Modify: `tests/test_release.py`
- Modify: `tests/test_handoff.py`

**Interfaces:**
- Produces: pinned local-only LibreTranslate service configuration.
- Produces: repeatable new-computer setup and C-drive-conscious cleanup instructions.

- [ ] **Step 1: Write failing package tests**

Require release and handoff archives to include:

```text
docker-compose.translate.yml
docs/superpowers/specs/2026-07-23-multilingual-title-classification-design.md
docs/superpowers/plans/2026-07-24-multilingual-title-classification.md
```

Require them to exclude:

```text
translation_cache.sqlite3
.venv
__pycache__
.pytest_cache
*.log
reviewed_titles.xlsx
Docker model or volume directories
```

- [ ] **Step 2: Run package tests and verify failure**

Run:

```powershell
python -m unittest tests.test_release tests.test_handoff -v
```

Expected: FAIL because Docker configuration is not yet packaged.

- [ ] **Step 3: Add pinned Docker Compose configuration**

Bind only loopback:

```yaml
services:
  libretranslate:
    image: libretranslate/libretranslate:1.9.6
    ports:
      - "127.0.0.1:5000:5000"
    restart: unless-stopped
```

Before implementation locks this tag, verify it exists in the official registry. If the exact tag is unavailable, replace it with the newest verified immutable official version and record that exact value in README and the handoff file; never use `latest`.

- [ ] **Step 4: Document setup and failure behavior**

Document exact user flow:

```powershell
docker compose -f docker-compose.translate.yml up -d
python -m unittest discover -s tests -v
python main.py https://example.edu/faculty --output output/faculty.xlsx
```

Explain:

- only required language models should be installed;
- Docker/model storage can consume C-drive space;
- moving Docker's global storage is a manual Docker Desktop operation, not performed by this project;
- no local service means unknown titles go to Review;
- hosted API endpoints are disabled by default.

- [ ] **Step 5: Document new-computer handoff**

Record:

1. branch `codex/translation`;
2. design and plan file paths;
3. Python, Playwright and Docker setup;
4. full tests;
5. one real crawl and translation smoke test;
6. only then permit old-computer cleanup.

Define `handoff-cleanup-manifest.json` fields:

```json
{
  "generated_at": "ISO-8601 timestamp",
  "items": [
    {
      "target": "absolute path or exact Docker resource name",
      "purpose": "translation cache",
      "size_bytes": 0,
      "migrated": true,
      "rebuildable": true,
      "recommendation": "delete_after_new_machine_verification",
      "cleaned_at": null
    }
  ]
}
```

Do not implement automatic deletion in this feature. Cleanup remains a later, separately confirmed operation.

- [ ] **Step 6: Run package tests**

Run:

```powershell
python -m unittest tests.test_release tests.test_handoff -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add docker-compose.translate.yml README.md 使用说明.txt build_release.py build_handoff.py 任务转接说明.md tests/test_release.py tests/test_handoff.py
git commit -m "docs: add portable local translation setup"
```

---

### Task 9: Full Verification, Real Local Smoke Test and Handoff Snapshot

**Files:**
- Modify only if verification reveals a directly related defect.
- Generate locally: release ZIP and handoff ZIP.
- Do not commit: generated caches, people data, smoke-test output or cleanup manifest.

**Interfaces:**
- Produces: verified branch state, exact test evidence, portable handoff archive and GitHub-ready commits.

- [ ] **Step 1: Run static whitespace and repository checks**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors; only intentional files appear.

- [ ] **Step 2: Run the complete automated suite**

Run:

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests PASS.

- [ ] **Step 3: Verify no-service degradation**

With the local container stopped, run a fixture-driven or controlled crawl containing an unknown Arabic title.

Expected:

- task completes;
- unknown title appears in Review;
- no title is silently excluded because translation is unavailable;
- English fixtures retain their expected counts.

- [ ] **Step 4: Verify local translation**

Start the pinned service:

```powershell
docker compose -f docker-compose.translate.yml up -d
```

Check:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/languages
```

Run the approved small smoke sample. Expected:

- a supported unknown source title is translated;
- the original title remains in Excel;
- the translated title, reason and status are populated;
- a repeated title produces a cache hit.

Stop here and report if the required model is unavailable; do not silently download every language model.

- [ ] **Step 5: Measure project-specific C-drive artifacts**

Enumerate only exact project-owned locations:

```text
%LOCALAPPDATA%\FacultyCrawler
this project's .venv
the named LibreTranslate container/image/volume
generated release and handoff archives
```

Record sizes in the handoff notes. Do not delete anything during this task.

- [ ] **Step 6: Build and test archives**

Run:

```powershell
python build_release.py
python build_handoff.py
python -m unittest tests.test_release tests.test_handoff -v
```

Expected: archives are created and package tests PASS.

- [ ] **Step 7: Update the handoff status**

Record:

- current branch;
- exact HEAD commit SHA;
- last full-test command and result;
- Docker image tag;
- installed languages;
- completed and remaining tasks;
- C-drive artifact locations and sizes;
- new-computer verification checklist;
- old-computer cleanup remains blocked until verification.

- [ ] **Step 8: Final verification before GitHub publication**

Run:

```powershell
git status --short
git log -10 --oneline --decorate
python -m unittest discover -s tests -v
```

Expected: clean or fully explained working tree, intended commits present, all tests PASS.

- [ ] **Step 9: Publish only with user authorization**

Use the GitHub publish workflow to:

1. push `codex/translation`;
2. create a draft PR;
3. include test evidence, Docker/local-only behavior, privacy exclusions, migration steps and remaining cleanup gate.

Do not merge the PR automatically.

---

## Final Success Criteria

- Known English pages preserve their existing successful extraction behavior.
- Reliable non-English titles can reach the post-parse classifier.
- Deterministic original-language rules avoid unnecessary translation.
- Local translation is optional, cached and limited to loopback by default.
- Translation failure yields Review and never deletes a person.
- Confirmed academic, research, teaching, clinical, practice, visiting, adjunct, postdoctoral and standalone Doctoral Researcher roles are included.
- Inactive/honorary states, students/assistants and approved professional-service families are excluded with auditable reasons.
- Excel contains Faculty, Review, Excluded and Run Summary without overwriting source titles.
- GitHub and handoff archives contain code and instructions but no people data, caches, models, credentials or logs.
- C-drive artifacts are measured and documented; cleanup happens only after the new computer passes tests and a real smoke run, and only after separate user confirmation.

