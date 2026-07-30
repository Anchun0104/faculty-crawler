# Local acceptance report — official faculty coverage

Date: 2026-07-30
Change: `increase-official-faculty-coverage`
Historical task: `67e246112066`

## Verification

- Upstream baseline before integration: 486 tests passed.
- Final local regression suite: 538 tests passed in 22.278 seconds.
- OpenSpec strict validation: `Change 'increase-official-faculty-coverage' is valid`.
- The historical database was copied before migration. Original and copy initially had SHA-256 `1F29204F664FEFE23C0666DC27BD525DE4982483ACD31E03D2000AEF5F49C9A1`.
- After migration, two review-only generations, and export against the copy, the original database retained the same SHA-256.

## Implemented behavior

- JLU-style split JavaScript/attribute email reconstruction requires every component to be present in official page markup; no domain or address pattern is guessed.
- Directory, profile-linked research unit, research portal, and URL-only search discovery all pass through the official-domain boundary and normal page fetcher.
- Search hints contain URL and query only; snippets cannot become evidence.
- Original title text is retained before local translation. Translation metadata is stored and translation never becomes official page evidence.
- Field evidence is persisted separately with value, quote/markup, source URL, extraction method, and support status.
- Active person/profile identities are normalized and unique. Accepted identity guards prevent review-only reruns from replacing completed rows.
- `reprocess-reviews` creates or resumes a generation, supersedes only active review rows, requeues only affected schools, reuses successful snapshots, and audits its scope.
- The evidence-workflow desktop app exposes the same review-only generation action; CLI and desktop share one service implementation.
- The final import workbook retains its original eight columns. A completed-evidence workbook and extended review workbook contain translation and evidence metadata.

## Historical-task rehearsal

Baseline: 58 accepted, 174 review, 559 rejected; 3 completed schools and 2 review schools.

Only the 174 review records were superseded and only Tomsk State University and Universidad de Costa Rica were requeued. The 58 accepted records remained unchanged. Two review-only generations completed on the copied database.

Final active result: 58 accepted and 174 review. No review row could be promoted under the strict evidence gate because the available official TSU/UCR pages still did not show complete personal official email addresses; 136 TSU rows lacked email evidence and 38 UCR rows lacked email and role/title evidence. They correctly remained in review instead of receiving guessed addresses.

The acceptance validator found zero email violations among the 58 preserved accepted rows: every address is complete, non-generic, on the configured official domain, and printed in supported evidence. Ten preserved legacy rows carry role/title-gate warnings from the older run; review-only processing intentionally did not demote or rewrite those completed rows.

The saved profile snapshots do expose many profile-linked official research sources for JLU and the University of Jyväskylä, validating the new discovery path. The saved TSU/UCR snapshots expose no currently supported profile-linked research source, so this rehearsal did not manufacture additional evidence.

## Local artifacts

- Migrated task copy: `workflow_data/migration-rehearsal-20260730/workflow-task-67e246112066.db`
- Acceptance exports: `workflow_data/migration-rehearsal-20260730/acceptance-output/`
- Original database was not modified.

Packaging, commits, pushes, and pull requests were intentionally not performed.
