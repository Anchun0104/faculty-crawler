# Local Translation Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, persistent local LibreTranslate settings for desktop and CLI usage.

**Architecture:** A focused `TranslationSettings` value object validates loopback-only settings and creates the existing `LibreTranslateClient`. Existing app settings persist the value object fields with backwards-compatible migration; `FacultyCrawler` consumes the settings only when no explicit pipeline is injected.

**Tech Stack:** Python dataclasses, pathlib, existing JSON settings store, argparse, unittest.

## Global Constraints

- Endpoint must only use `localhost`, `127.0.0.1`, or `::1`.
- Do not add DeepSeek, remote AI services, credentials, or API keys.
- Keep `TitlePipeline` dependency injection unchanged.
- Preserve existing uncommitted changes; do not commit or push.

### Task 1: Translation configuration value object

**Files:**
- Create: `crawler/translation_settings.py`
- Create: `tests/test_translation_settings.py`

**Interfaces:**
- Produces: `TranslationSettings(endpoint, cache_path, connect_timeout, response_timeout, retries, target_language)` and `create_client()`.

- [ ] Write failing tests for defaults, accepted loopback endpoints, rejected remote/authenticated endpoints, numeric bounds and cache path handling.
- [ ] Run `python -m unittest tests.test_translation_settings -v`; expect import failure.
- [ ] Implement immutable validation and client construction using `TranslationCache` and `LibreTranslateClient`.
- [ ] Re-run the test module; expect pass.

### Task 2: Persistent settings migration

**Files:**
- Modify: `crawler/settings_store.py`
- Modify: `tests/test_settings_store.py`

**Interfaces:**
- Consumes: old three-field JSON or new JSON settings.
- Produces: `AppSettings` with `translation: TranslationSettings` and backward-compatible `load()`.

- [ ] Write failing tests that load legacy JSON into default translation settings and round-trip a custom local configuration.
- [ ] Run focused settings tests; expect failure.
- [ ] Add validated translation fields with legacy migration, preserving atomic writes and sensitive-key rejection.
- [ ] Re-run focused settings tests; expect pass.

### Task 3: Crawler and CLI wiring

**Files:**
- Modify: `crawler/faculty_crawler.py`
- Modify: `main.py`
- Modify: `tests/test_crawler_diagnostics.py`
- Modify: `tests/test_cli.py`

**Interfaces:**
- `FacultyCrawler(..., translation_settings: TranslationSettings | None = None)`.
- CLI flags: `--translation-endpoint`, `--translation-cache-path`, `--translation-connect-timeout`, `--translation-response-timeout`, `--translation-retries`.

- [ ] Write failing tests proving injected settings build the default title pipeline, explicit pipeline wins, and CLI options reach crawler construction.
- [ ] Run focused tests; expect failure.
- [ ] Implement only the configuration plumbing and error reporting; do not start a service.
- [ ] Re-run focused tests; expect pass.

### Task 4: Desktop advanced settings

**Files:**
- Modify: `ui/controller.py`
- Modify: `ui/settings_page.py`
- Modify: `desktop_app.py`
- Modify: `tests/test_ui_workflows.py`
- Modify: `tests/test_desktop_app.py`

**Interfaces:**
- Settings page displays and saves local endpoint, cache path, timeouts and retries.
- Batch crawler factories receive the current `TranslationSettings`.

- [ ] Write failing controller/UI tests for displaying, validating and applying settings.
- [ ] Run focused UI tests; expect failure.
- [ ] Implement field binding and pass the saved settings into all default crawler factories.
- [ ] Re-run focused UI tests; expect pass.

### Task 5: Regression verification

**Files:**
- No production changes expected.

- [ ] Run all translation/settings/CLI/UI tests that do not require unavailable dependencies.
- [ ] Run `python -m py_compile` for touched modules and `git diff --check`.
- [ ] Run a local LibreTranslate smoke test using custom cache and timeout configuration.
