# Anti-Crawler Phase 2 Resilience and Dynamic Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add bounded recovery, cookie-consent handling, `Load more`, infinite scrolling, internal scrolling, and virtual-list snapshot merging.

**Architecture:** Pure policy functions decide when to retry. A Playwright adapter performs safe browser actions and returns immutable action traces; `FacultyCrawler` parses each accepted snapshot and merges records using existing deduplication.

**Tech Stack:** Python 3.11, Playwright sync API, existing parser contracts, `unittest` fakes.

## Global Constraints

- One active task per hostname; no proxy or fingerprint manipulation.
- Network retry limit is 3; honor `Retry-After` when valid.
- Stop `Load more` after 2 unchanged clicks and scrolling after 3 unchanged rounds.
- All action loops also have explicit maximum rounds and elapsed-time limits.
- Never click generic “more” controls outside a trusted people-directory scope.

---

## File Map

- Create `crawler/access_policy.py`: retry and hostname cooldown decisions.
- Create `crawler/dynamic_loader.py`: browser action adapter and snapshot collection.
- Create `crawler/consent.py`: conservative Cookie dialog actions.
- Modify `crawler/faculty_crawler.py`: integrate assessments, retries, consent, and snapshots.
- Modify `crawler/models.py`: `DynamicTrace` and retry metadata.
- Create `tests/test_access_policy.py`, `tests/test_dynamic_loader.py`, and `tests/test_consent.py`.
- Modify `tests/test_crawler_diagnostics.py`.

### Task 1: Bounded retry policy

**Files:**
- Create: `crawler/access_policy.py`
- Test: `tests/test_access_policy.py`

**Interfaces:**
- Produces: `RetryDecision(should_retry: bool, delay_seconds: float, reason: str)`.
- Produces: `retry_decision(*, attempt: int, assessment: PageAssessment, retry_after: str | None, now: datetime) -> RetryDecision`.

- [ ] **Step 1: Write retry tests**

```python
import unittest
from datetime import datetime, timezone

from crawler.access_policy import retry_decision
from crawler.models import PageAssessment, PageKind, RecommendedAction


class RetryPolicyTests(unittest.TestCase):
    def test_honors_retry_after_seconds(self):
        assessment = PageAssessment(PageKind.RATE_LIMITED, RecommendedAction.RETRY_LATER)
        result = retry_decision(attempt=1, assessment=assessment, retry_after="12", now=datetime.now(timezone.utc))
        self.assertTrue(result.should_retry)
        self.assertEqual(result.delay_seconds, 12)

    def test_stops_after_three_attempts(self):
        assessment = PageAssessment(PageKind.TEMPORARY_FAILURE, RecommendedAction.RETRY_LATER)
        result = retry_decision(attempt=3, assessment=assessment, retry_after=None, now=datetime.now(timezone.utc))
        self.assertFalse(result.should_retry)

    def test_never_retries_human_verification(self):
        assessment = PageAssessment(PageKind.HUMAN_VERIFICATION, RecommendedAction.QUEUE_VERIFICATION)
        result = retry_decision(attempt=0, assessment=assessment, retry_after=None, now=datetime.now(timezone.utc))
        self.assertFalse(result.should_retry)
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.test_access_policy -v`

Expected: missing-module failure.

- [ ] **Step 3: Implement the policy**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

from crawler.models import PageAssessment, RecommendedAction


@dataclass(frozen=True)
class RetryDecision:
    should_retry: bool
    delay_seconds: float
    reason: str


def retry_decision(*, attempt: int, assessment: PageAssessment, retry_after: str | None, now: datetime) -> RetryDecision:
    if assessment.action is not RecommendedAction.RETRY_LATER:
        return RetryDecision(False, 0, assessment.action.value)
    if attempt >= 3:
        return RetryDecision(False, 0, "retry_limit")
    delay = float(2 ** attempt)
    if retry_after:
        try:
            delay = max(delay, float(retry_after))
        except ValueError:
            parsed = parsedate_to_datetime(retry_after)
            delay = max(delay, (parsed - now).total_seconds())
    return RetryDecision(True, max(0, delay), "bounded_retry")
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m unittest tests.test_access_policy -v`

Expected: 3 tests pass.

```bash
git add crawler/access_policy.py tests/test_access_policy.py
git commit -m "feat: add bounded crawler retry policy"
```

### Task 2: Conservative Cookie-consent handling

**Files:**
- Create: `crawler/consent.py`
- Test: `tests/test_consent.py`

**Interfaces:**
- Produces: `dismiss_cookie_overlay(page: object) -> str | None`, returning the clicked accessible label.

- [ ] **Step 1: Write tests with a fake page**

```python
import unittest
from crawler.consent import dismiss_cookie_overlay


class FakePage:
    def __init__(self, result): self.result = result
    def evaluate(self, script): return self.result


class ConsentTests(unittest.TestCase):
    def test_returns_clicked_label(self):
        self.assertEqual(dismiss_cookie_overlay(FakePage("Accept necessary")), "Accept necessary")

    def test_returns_none_when_no_trusted_control_exists(self):
        self.assertIsNone(dismiss_cookie_overlay(FakePage(None)))
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.test_consent -v`

Expected: missing-module failure.

- [ ] **Step 3: Implement one DOM script**

```python
from __future__ import annotations


_DISMISS_SCRIPT = r"""
() => {
  const labels = ['accept necessary', 'necessary only', 'reject all', 'continue without accepting', '关闭'];
  for (const root of document.querySelectorAll('[role="dialog"], [class*="cookie" i], [id*="cookie" i], [class*="consent" i]')) {
    for (const button of root.querySelectorAll('button, [role="button"]')) {
      const text = (button.innerText || button.getAttribute('aria-label') || '').trim().toLowerCase();
      if (labels.includes(text) && !button.disabled) { button.click(); return text; }
    }
  }
  return null;
}
"""


def dismiss_cookie_overlay(page: object) -> str | None:
    return page.evaluate(_DISMISS_SCRIPT)
```

- [ ] **Step 4: Run tests and commit**

Run: `python -m unittest tests.test_consent -v`

Expected: 2 tests pass.

```bash
git add crawler/consent.py tests/test_consent.py
git commit -m "feat: dismiss trusted cookie overlays"
```

### Task 3: Dynamic snapshot collector

**Files:**
- Create: `crawler/dynamic_loader.py`
- Create: `tests/test_dynamic_loader.py`
- Modify: `crawler/models.py`

**Interfaces:**
- Produces: `DynamicTrace(action: str, rounds: int, additions: tuple[int, ...], stop_reason: str)`.
- Produces: `collect_dynamic_snapshots(page, base_url, initial_html, *, max_clicks=50, max_scrolls=50, timeout_ms=30000) -> tuple[list[str], list[DynamicTrace]]`.

- [ ] **Step 1: Write control-loop tests**

```python
import unittest
from crawler.dynamic_loader import collect_dynamic_snapshots


class FakeDynamicPage:
    def __init__(self, events): self.events = iter(events)
    def dynamic_step(self, action): return next(self.events, None)


class DynamicLoaderTests(unittest.TestCase):
    def test_load_more_stops_after_two_unchanged_rounds(self):
        page = FakeDynamicPage([("load_more", "<a href='/people/a'>A</a>"), ("load_more", "<a href='/people/a'>A</a>"), ("load_more", "<a href='/people/a'>A</a>")])
        snapshots, traces = collect_dynamic_snapshots(page, "https://example.edu", "<main></main>", max_clicks=10, max_scrolls=0)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(traces[0].stop_reason, "two_unchanged_clicks")

    def test_virtual_list_keeps_each_changed_snapshot(self):
        page = FakeDynamicPage([("scroll", "<a href='/people/a'>A</a>"), ("scroll", "<a href='/people/b'>B</a>"), None])
        snapshots, traces = collect_dynamic_snapshots(page, "https://example.edu", "<main></main>", max_clicks=0, max_scrolls=10)
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(traces[-1].stop_reason, "control_exhausted")
```

- [ ] **Step 2: Run and verify failure**

Run: `python -m unittest tests.test_dynamic_loader -v`

Expected: missing-module failure.

- [ ] **Step 3: Add `DynamicTrace` to `crawler/models.py`**

```python
@dataclass(frozen=True)
class DynamicTrace:
    action: str
    rounds: int
    additions: tuple[int, ...]
    stop_reason: str
```

- [ ] **Step 4: Implement the pure loop around an adapter method**

```python
from __future__ import annotations

from crawler.models import DynamicTrace
from crawler.parsers import normalized_person_profile_urls


def collect_dynamic_snapshots(page, base_url: str, initial_html: str, *, max_clicks: int = 50, max_scrolls: int = 50, timeout_ms: int = 30000):
    del timeout_ms
    seen = normalized_person_profile_urls(initial_html, base_url)
    snapshots: list[str] = []
    traces: list[DynamicTrace] = []
    for action, limit, unchanged_limit in (("load_more", max_clicks, 2), ("scroll", max_scrolls, 3)):
        additions: list[int] = []
        unchanged = 0
        stop_reason = "round_limit"
        for _ in range(limit):
            event = page.dynamic_step(action)
            if event is None:
                stop_reason = "control_exhausted"
                break
            _, html = event
            urls = normalized_person_profile_urls(html, base_url)
            new_count = len(urls - seen)
            additions.append(new_count)
            if new_count:
                snapshots.append(html)
                seen.update(urls)
                unchanged = 0
            else:
                unchanged += 1
            if unchanged >= unchanged_limit:
                stop_reason = "two_unchanged_clicks" if action == "load_more" else "three_unchanged_scrolls"
                break
        traces.append(DynamicTrace(action, len(additions), tuple(additions), stop_reason))
    return snapshots, traces
```

- [ ] **Step 5: Add Playwright-adapter contract tests**

```python
class EvaluatingPage:
    def __init__(self, values):
        self.values = iter(values)
        self.actions = []
    def evaluate(self, script, action):
        self.actions.append(action)
        return next(self.values)
    def content(self):
        return "<main><a href='/people/ada'>Ada</a></main>"
    def wait_for_timeout(self, milliseconds):
        self.waited = milliseconds

def test_adapter_uses_scoped_load_more_action(self):
    page = EvaluatingPage([{"acted": True, "kind": "load_more"}])
    adapter = _PlaywrightDynamicAdapter(page, timeout_ms=1000)
    event = adapter.dynamic_step("load_more")
    self.assertEqual(event[0], "load_more")
    self.assertEqual(page.actions, ["load_more"])

def test_adapter_distinguishes_internal_scroll(self):
    page = EvaluatingPage([{"acted": True, "kind": "internal_scroll"}])
    adapter = _PlaywrightDynamicAdapter(page, timeout_ms=1000)
    event = adapter.dynamic_step("scroll")
    self.assertEqual(event[0], "internal_scroll")
```

Implement the injected script so a `load_more` result is possible only when the control is inside an ancestor containing at least two normalized people links. The scroll branch must prefer a scrollable people-list ancestor and otherwise scroll the window.

- [ ] **Step 6: Run tests and commit**

Run: `python -m unittest tests.test_dynamic_loader -v`

Expected: all dynamic-loader tests pass.

```bash
git add crawler/models.py crawler/dynamic_loader.py tests/test_dynamic_loader.py
git commit -m "feat: collect load-more and scroll snapshots"
```

### Task 4: Integrate recovery and dynamic loading into `FacultyCrawler`

**Files:**
- Modify: `crawler/faculty_crawler.py`
- Modify: `tests/test_crawler_diagnostics.py`

**Interfaces:**
- Consumes: `classify_page`, `retry_decision`, `dismiss_cookie_overlay`, and `collect_dynamic_snapshots`.
- Produces diagnostics keys: `Page assessment`, `Retry attempts`, `Consent action`, `Dynamic traces`, and `Dynamic stop reason`.

- [ ] **Step 1: Add failing integration tests**

Add these tests with injected `load_attempt`, `sleep`, and `dynamic_collector` callables:

```python
def test_rate_limit_retries_then_succeeds_without_real_sleep(self):
    attempts = iter([(429, "Too many requests"), (200, self._person_page("Ada Lovelace", "ada"))])
    sleeps = []
    outcome = self._crawl_with_attempts(attempts, sleep=sleeps.append)
    self.assertEqual(outcome.status, TaskStatus.SUCCEEDED)
    self.assertEqual(len(sleeps), 1)

def test_challenge_returns_verification_required_without_retry(self):
    outcome = self._crawl_with_attempts(iter([(403, "<title>Just a moment</title>Verify you are human")]), sleep=lambda delay: self.fail("must not sleep"))
    self.assertEqual(outcome.status, TaskStatus.VERIFICATION_REQUIRED)

def test_dynamic_snapshots_are_all_parsed_and_deduplicated(self):
    snapshots = [self._person_page("Ada Lovelace", "ada"), self._person_page("Grace Hopper", "grace")]
    outcome = self._crawl_with_dynamic_snapshots(snapshots)
    self.assertEqual([record.name for record in outcome.records], ["Ada Lovelace", "Grace Hopper"])

def test_dynamic_trace_is_written_to_diagnostics(self):
    trace = DynamicTrace("load_more", 2, (20, 8), "control_exhausted")
    outcome = self._crawl_with_dynamic_trace(trace)
    self.assertEqual(outcome.diagnostics["Dynamic traces"][0]["additions"], [20, 8])
```

Inject `sleep: Callable[[float], None]` and the dynamic collector so tests do not use real time or a real browser.

- [ ] **Step 2: Run the focused tests and verify failures**

Run: `python -m unittest tests.test_crawler_diagnostics -v`

Expected: the four new tests fail for missing integration behavior.

- [ ] **Step 3: Integrate in one browser context**

Refactor the page load boundary to capture status, `Retry-After`, title, visible text, HTML, and parser candidate count. Classify before parsing, apply the bounded retry decision, dismiss trusted consent once, then collect dynamic snapshots. Parse and deduplicate each accepted snapshot immediately.

- [ ] **Step 4: Remove the old embedded dynamic-action JavaScript**

Delete `_DYNAMIC_RESULT_ACTION_SCRIPT` and `_interact_with_dynamic_result_page` only after the new adapter tests cover largest-page-size, next-page, `Load more`, window scroll, and internal scroll.

- [ ] **Step 5: Run the full suite**

Run: `python -m unittest discover -s tests -v`

Expected: zero failures and zero errors.

- [ ] **Step 6: Commit**

```bash
git add crawler/faculty_crawler.py tests/test_crawler_diagnostics.py
git commit -m "feat: recover and expand dynamic faculty pages"
```
