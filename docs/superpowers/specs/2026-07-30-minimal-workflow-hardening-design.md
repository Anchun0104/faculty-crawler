# Minimal Workflow Hardening Design

## Goal

Make the evidence-first workflow safe to release by preserving complete HTML snapshots, limiting review reprocessing to its recorded school scope, and reporting real active duplicate counts.

## Decisions

- HTML snapshots must be fully persisted. A configured size limit may reject a page with a clear fetch error, but it must never silently write a truncated snapshot that is later treated as deterministic input.
- Review-generation execution receives the exact school IDs recorded by the generation. It must not retry unrelated pending or failed schools.
- The audit computes duplicate counts from the same normalized person identity used for its unique-person count.

## Compatibility and Safety

- Existing PDF caching, output file names, and completed candidates remain unchanged.
- Existing task-wide `run_task` behavior remains available for normal runs.
- Tests use temporary files and SQLite databases only; no network access is required.

## Verification

- Add a regression test for a snapshot larger than the configured limit.
- Add a regression test showing review reprocessing excludes unrelated pending/failed schools.
- Add a regression test showing duplicate identities are reported in the audit.
- Run the focused regression tests and the full unittest suite.
