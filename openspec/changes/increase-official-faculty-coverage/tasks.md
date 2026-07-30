## 1. Establish the Integration Baseline

- [x] 1.1 Run and record the upstream 2.0.0 unit-test baseline without changing dependencies or source files.
- [x] 1.2 Inventory handoff-only task, source, evidence, email-resolution, quality-gate, export, and reprocessing behavior against upstream modules.
- [x] 1.3 Add failing contract tests that protect the upstream translator, title pipeline, desktop settings, and release behavior during integration.

## 2. Add Persistent Evidence Workflow Models

- [x] 2.1 Add task, school, source, candidate, field-evidence, and reprocessing-generation persistence with forward-only schema initialization.
- [x] 2.2 Store source type, discovery parent, depth, official-boundary result, fetch state, snapshot metadata, and stop reason.
- [x] 2.3 Add normalized person and profile identities plus active-candidate uniqueness rules without changing the translation cache schema.
- [x] 2.4 Add database tests for restart recovery, uniqueness, completed-record protection, and rollback-safe initialization.

## 3. Complete Official Directory Enumeration

- [x] 3.1 Add minimal failing fixtures for missed pagination, page-size controls, load-more states, scrolling states, and duplicate dynamic snapshots.
- [x] 3.2 Refactor directory traversal to emit a stable person baseline before profile or email enrichment.
- [x] 3.3 Preserve displayed name, original title, profile URL, directory evidence, translation metadata, and eligibility state for email-less people.
- [x] 3.4 Record visited states, unique counts, duplicates, stop reason, failures, and coverage-incomplete safety bounds.
- [x] 3.5 Verify 100 percent eligible-person recall for every fixture with a declared population.

## 4. Discover and Validate Official Evidence Sources

- [x] 4.1 Add failing tests for directory-linked personal pages, research centers, laboratories, and institutional research portals.
- [x] 4.2 Implement a finite official-source queue with normalized URLs, visited-state deduplication, supported source types, depth limits, and page budgets.
- [x] 4.3 Implement official-boundary validation for configured university domains, subdomains, and officially linked institutional portals.
- [x] 4.4 Add a discovery-provider interface whose search output contains candidate URLs only and cannot create supported evidence.
- [x] 4.5 Re-fetch every search-discovered candidate through the normal fetcher and reject evidence from inaccessible, unofficial, or unvalidated targets.
- [x] 4.6 Isolate individual source failures with bounded retries and reviewable failure reasons while continuing other people and sources.

## 5. Merge Evidence and Enforce Completion

- [x] 5.1 Port generic split-email decoding tests, including JLU-style JavaScript and attribute components, without adding person-specific data or inferred formats.
- [x] 5.2 Store source-scoped field facts with value, supporting quote or deterministic markup, source URL, extraction method, and support status.
- [x] 5.3 Implement conservative exact-person merging by normalized name and profile identity, routing name and email conflicts to review.
- [x] 5.4 Integrate the existing local title translation pipeline after original-title capture and retain original, translated, language, engine, and status fields.
- [x] 5.5 Implement the strict completion gate for clear identity, included academic role, required official evidence, and a complete non-generic official personal email.
- [x] 5.6 Add negative tests proving guessed emails, generic contacts, third-party pages, search snippets, and conflicted identities never complete a record.

## 6. Implement Review-Only Reprocessing

- [x] 6.1 Add a failing database test in which completed and review records coexist and only review records are superseded and requeued.
- [x] 6.2 Implement atomic review-generation creation that requeues only affected schools and preserves completed candidates.
- [x] 6.3 Add completed-name/profile guards and source-cache reuse during revisited directory and profile processing.
- [x] 6.4 Implement interruption recovery that resumes the active generation without resetting review rows or duplicating candidates.
- [x] 6.5 Export generation scope, superseded record IDs, requeued schools, status counts, evidence sources, and preservation checks in the audit report.

## 7. Expose Results and Diagnostics

- [x] 7.1 Extend local CLI and desktop workflows to start or resume review-only processing without offering a whole-task rerun by default.
- [x] 7.2 Export completed and review workbooks with original title, translated title metadata, evidence URLs, and precise review reasons while preserving existing user-facing columns.
- [x] 7.3 Add per-school coverage and conversion summaries for directory baseline, completed, review, rejected, failed sources, and discovery stop reasons.
- [x] 7.4 Verify logs, audit files, and issue-report bundles do not expose cookies, tokens, session data, or unredacted sensitive diagnostics.

## 8. Verify Locally Before Release Work

- [x] 8.1 Run the focused parser, translation, database, service, exporter, CLI, and desktop regression suites.
- [x] 8.2 Run the complete upstream unit-test suite and resolve every regression before live crawling.
- [x] 8.3 Copy any historical task database before a migration rehearsal and verify the original remains byte-for-byte unchanged.
- [x] 8.4 Run JLU, TSU, and UCR pilots and compare baseline population, completed count, review count, failure reasons, and evidence-source types.
- [x] 8.5 Confirm no record without a complete official personal email was completed and no search summary became formal evidence.
- [x] 8.6 Produce a local acceptance report; defer Windows packaging, Git commits, pushes, and pull requests until separately authorized.
