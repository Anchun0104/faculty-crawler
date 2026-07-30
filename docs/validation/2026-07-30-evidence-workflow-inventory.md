# Evidence Workflow Integration Inventory

## Baseline

- Upstream commit: `5e04a28` on local branch `feature/increase-official-faculty-coverage`.
- Python: 3.13.3 in the isolated `.venv`.
- Command: `.venv\\Scripts\\python.exe -m unittest discover -s tests -v`.
- Result: 486 tests passed in 25.444 seconds, with zero failures or errors.

## Upstream 2.0.0 remains authoritative

| Area | Upstream files | Integration rule |
|---|---|---|
| Generic parsing and dynamic traversal | `crawler/parsers.py`, `crawler/dynamic_loader.py`, `crawler/faculty_crawler.py` | Extend additively; do not replace the parser or make Email mandatory. |
| Title classification and translation | `crawler/title_classifier.py`, `crawler/title_pipeline.py`, `crawler/translation.py`, `crawler/translation_settings.py` | Reuse unchanged public contracts; original title is captured before translation. |
| Desktop and batch workflows | `desktop_app.py`, `ui/`, `crawler/batch.py`, `crawler/task_store.py` | Preserve existing URL-task behavior and add the evidence workflow as a separate entry path. |
| Session, privacy, and diagnostics | `crawler/session_store.py`, `crawler/diagnostics.py`, `crawler/verification.py` | Keep upstream privacy and access-control boundaries. |
| Packaging | `build_release.py`, `build_installer.ps1`, `installer/` | Do not package until local verification is complete and separately authorized. |

## Handoff behavior to port as a bounded package

| Capability | Handoff source | Destination decision |
|---|---|---|
| Task/school/source/candidate/evidence persistence | `faculty_workflow/database.py`, `faculty_workflow/models.py` | Add `faculty_workflow/` to upstream; extend schema only for source graph and generation metadata. |
| Fetching and protected workflow sessions | `faculty_workflow/fetcher.py`, `faculty_workflow/session_store.py` | Adapt to upstream privacy vocabulary; do not replace upstream crawler sessions. |
| Directory adapters and official email resolution | `faculty_workflow/directory_adapters.py`, `faculty_workflow/email_resolver.py`, `faculty_workflow/adapters.py` | Port generic behavior and tests, including deterministic split-email decoding. |
| Evidence extraction and strict completion | `faculty_workflow/providers.py`, `faculty_workflow/quality.py`, `faculty_workflow/service.py` | Port behind workflow-only quality gates; inject upstream `TitlePipeline`. |
| Review-only reprocessing | `faculty_workflow/database.py`, `faculty_workflow/service.py` | Preserve completed candidates and cached sources; add generation audit metadata. |
| Exports and CLI | `faculty_workflow/exporter.py`, `workflow.py` | Add optional workflow CLI and evidence exports without changing existing `main.py` columns. |

## Parser compatibility decision

The handoff parser file is not copied over upstream. Only generic, test-proven capabilities missing upstream are ported: linked official research-source discovery and deterministic page-present split-email decoding. All existing upstream parser strategies, translation fields, and fixtures remain authoritative.

## Test-first port order

1. Copy workflow tests without production modules and verify import failures.
2. Add the bounded workflow package until those tests pass.
3. Add new failing tests for source graph metadata, translation integration, search re-fetch trust, and reprocessing generations.
4. Implement the minimum behavior for each failing test.
5. Run focused suites, then all 486 upstream tests plus the new workflow tests.
