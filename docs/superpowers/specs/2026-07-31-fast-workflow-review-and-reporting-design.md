# Fast workflow, finite review, and diagnostic reporting

## Purpose

Preserve the evidence-first workflow's reliability while restoring the fast-path behaviour that made 2.0 useful for routine faculty directories.  A record with complete, literal directory evidence must not incur an unnecessary personal-page request.  Records that remain uncertain must have a bounded lifecycle rather than being retried indefinitely.

## Scope

This change covers the evidence workflow used by the unified desktop application and by `workflow.py`:

- fast-path eligibility for complete directory records;
- separate fetch policy for directory and personal pages;
- light, deterministic email deobfuscation on already fetched HTML;
- a single compact `run_report.json` for optimisation and troubleshooting;
- finite review generations and the terminal `unresolved` status;
- updated Chinese user documentation for the new outcomes and report.

It does not change the installer size or packaging layout, add AI directory discovery, guess email addresses, or automatically publish uncertain people as completed.

## Fast collection policy

The workflow evaluates every directory seed before any personal-page prefetch.  It immediately accepts a seed only when all of the following are present and grounded in the verified directory page:

- a person name;
- a non-generic email on the configured school domain;
- an accepted academic title under the task policy;
- supported name, email, and title evidence.

All other seeds remain eligible for a personal-page request.  Personal pages use a short, one-attempt policy (10 seconds by default); a failure becomes a review reason rather than holding up the school.  Directory pages retain the existing conservative timeout/retry behaviour so pagination and dynamic expansion remain reliable.

The workflow must not prefetch every personal profile merely to discover secondary sources.  It discovers profile-linked sources only while processing a seed that needs the profile.

## Deterministic email decoding

Email handling remains evidence-only: no generated address, name-to-address prediction, or third-party enrichment.  The resolver operates solely on HTML already fetched for the directory/profile/follow-up page.

New decoders normalise common literal representations before the existing identity and official-domain checks:

- JavaScript string concatenation such as `local + '@' + domain`;
- `data-*` attributes holding a local part and domain;
- HTML/Unicode escaped email literals;
- existing visible, `mailto:`, split `mailto:`, textual obfuscation, and Cloudflare support remain unchanged.

Decoded candidates are accepted only when their literal page context identifies the current person and the existing official-domain, generic-address, and score checks succeed.

## Reporting

Normal runs write one compact `run_report.json`; the prior final audit output and normal persistent text log are replaced by this report.  It contains:

- run metadata and mode;
- wall-clock timings by phase and source type;
- requested, fetched, cached, failed, and retried source counts;
- accepted/review/unresolved/rejected counts and top reasons;
- bounded diagnostic events for failures, retries, dynamic-stop conditions, and slow sources;
- deterministic optimisation signals, each with an evidence payload and suggested module to inspect;
- review-generation history.

The report stores at most 20 events per diagnostic category.  A verbose debugging option may still write an append-only text log, but is off by default.  The report contains URLs because they are required to reproduce crawler problems; it must never contain API keys, cookies, page bodies, or model prompts.

## Finite review lifecycle

Candidate statuses are `accepted`, `review`, `unresolved`, and `rejected`.

- `review` is active: a later evidence/rule change may resolve it.
- `unresolved` is terminal for automatic work: it is excluded from formal results but retained in `review_queue.xlsx` with the final reason and recommended next action.
- `rejected` is reserved for invalid/non-person and duplicate records.

The initial collection creates `review` records.  A candidate's school can be reprocessed at most twice after initial collection.  If the latest reprocess has the same source fingerprints, parser/email-rules version, and review-reason set as the preceding attempt, the record becomes `unresolved` immediately without consuming further automatic attempts.  On reaching the two-reprocess limit, remaining active review records become `unresolved`.

Accepted records are immutable during review-only reprocessing.  Superseded reviews remain in the database and report history.  A user can explicitly reopen unresolved records after a parser/email-rule upgrade, a corrected directory URL, or successful access verification; reopening starts a new review generation with an explicit reason.

## User-facing artifacts

- The formal result Excel contains accepted records only.
- `review_queue.xlsx` contains active review and unresolved records, the reason, source links, evidence links, retry count, terminal state, and recommended manual action.
- Internal field evidence and page snapshots remain in SQLite/output storage for deterministic decisions and later reprocessing, but `completed_evidence.xlsx` is not exported.
- Both `README.md` and `README_WORKFLOW_AI.md` explain fast mode, the evidence threshold, review/unresolved outcomes, how to reopen a record, and how Codex should use `run_report.json` to diagnose the next code improvement.

## Verification

Tests will cover:

- complete directory data avoids profile fetches;
- incomplete data uses the short personal-page policy and becomes review on fetch failure;
- each new decoder accepts only identity-bound, official addresses and rejects generic/out-of-domain addresses;
- report shape, event cap, and optimisation signals;
- unchanged review reprocessing becomes unresolved;
- two reprocesses cap further automatic work, preserve accepted records, and allow explicit reopening;
- exports omit completed-evidence workbooks and retain active/terminal queue items.

