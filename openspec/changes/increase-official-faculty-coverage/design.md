## Context

The local working baseline is the upstream 2.0.0 repository, which includes deterministic parsing, Windows workflows, offline multilingual title translation, diagnostics, and release packaging. A separate local handoff tree contains a task database, strict evidence gates, JLU split-email support, secondary official-source discovery, evidence merging, and review-only reprocessing that have been exercised on task `67e246112066`. See `proposal.md` for motivation and the capability specs for observable behavior.

The implementation must preserve the upstream translator and desktop behavior while importing only reusable evidence-workflow concepts. It must remain conservative about access controls and must not treat search content or predicted email formats as evidence.

## Goals / Non-Goals

**Goals:**

- Use the upstream 2.0.0 tree as the code baseline and integrate the evidence-first workflow without wholesale directory replacement.
- Separate directory enumeration, source discovery, page fetching, evidence extraction, identity merging, quality decisions, and reprocessing state behind explicit interfaces.
- Increase completed results only through additional official evidence while making directory coverage and unresolved reasons measurable.
- Preserve original multilingual titles and let local translation assist classification without changing evidence provenance.

**Non-Goals:**

- Guarantee completion for professors whose official pages do not expose a complete personal email.
- Crawl an entire university domain, bypass access controls, solve CAPTCHAs, use proxy evasion, or ignore robots policy.
- Treat third-party profiles, search snippets, or inferred address patterns as formal evidence.
- Push changes, create a pull request, migrate historical output files into Git, or package a release before verification succeeds.

## Decisions

### 1. Integrate into upstream by bounded modules, not tree overlay

The upstream checkout remains authoritative for translation, title classification, desktop behavior, and packaging. Evidence-workflow modules from the handoff are adapted behind upstream data models and tested individually. This avoids overwriting newer UI and release changes. The rejected alternative is copying the handoff tree over upstream, because that would silently discard the 2.0.0 translator and installer work.

### 2. Build a finite official-source graph

Each school run owns a queue of sources with URL, type, discovery parent, depth, official-boundary decision, fetch state, and stop reason. Directory and research pages can enqueue only supported source types, within configured depth and page limits. URL normalization and a visited set make the graph finite. The rejected alternative is recursive same-domain crawling, which is difficult to bound and would collect unrelated content.

### 3. Establish the directory baseline before enrichment

Directory traversal first emits a deduplicated person baseline with visible name, original title, profile URL, source, and coverage diagnostics. Evidence discovery enriches these people rather than determining whether they existed. This makes dropped-directory-person defects observable and prevents missing-email records from disappearing before review.

### 4. Use a staged discovery trust model

Direct official links are processed first. Unresolved people can then be passed to a discovery-provider interface that returns candidate URLs only. Every candidate is fetched through the normal page fetcher and must pass official-boundary validation before extraction. Search snippets are never stored as supported evidence. Keeping discovery provider output separate from evidence prevents accidental promotion of unverified text and allows university site search or a configured search service without changing quality rules.

### 5. Represent evidence as source-scoped facts

Every supported field records value, quote or deterministic markup representation, source URL, extraction method, and status. JavaScript or attribute-split emails are allowed only when all address components are present in the delivered page. Generic addresses and conflicting personal addresses cannot satisfy completion. Evidence remains attached to its source when records are merged.

### 6. Merge people with conservative identity keys

Primary merge signals are normalized full name plus an unambiguous normalized profile identity. Exact normalized name can bridge a directory record to a secondary official card when there is only one match. Transliteration-only or fuzzy matching may propose a review link but cannot automatically merge. Any collision produces an explicit review reason instead of a winner.

### 7. Apply translation before role policy, never before provenance capture

The official title is stored first. The upstream local title pipeline classifies the original title and invokes local translation only when its existing rules require it. The normalized role may use the translated classification, but exports and evidence retain the original title, translation result, language, engine, and status. Translation failure is review-safe.

### 8. Make review-only reprocessing a database generation

Starting reprocessing atomically supersedes only active review candidates and requeues only their schools. Completed candidates are protected by status and accepted-identity guards. Page/source cache entries remain reusable. A generation identifier and decision note make interruption recovery idempotent and auditable. Repeating initialization of the same active generation is rejected or resumed rather than resetting rows again.

### 9. Verify with fixtures before live pilots

Tests use minimal saved HTML fixtures for directory exhaustion, dynamic states, JLU-style split emails, research links, search candidate revalidation, merge conflicts, translator integration, and reprocessing. Live JLU/TSU/UCR runs report baseline people, completed records, reviews, failures, and evidence-source types. Live outcomes supplement but do not replace deterministic tests.

### 10. Keep parser validity separate from workflow completion

The upstream generic crawler keeps its established record contract: a valid directory record requires Name, Title, and Profile_URL, while Email remains optional. The evidence workflow consumes those valid records and applies the stricter completion gate only when deciding whether a candidate enters the final evidence-backed output. This preserves existing parser exports and fixtures while allowing email-less professors to remain visible for enrichment and review. The rejected alternative is making Email mandatory inside `crawler/parsers.py`, because that would drop valid directory people and violate the existing parser contract.

## Risks / Trade-offs

- [More official pages increase runtime and load] → Enforce per-domain serialization, rate limits, finite source depth, page budgets, caching, and clear stop reasons.
- [Exact-name merging misses legitimate variants] → Prefer reviewable false negatives over false merges; add explicit alias evidence only when a validated profile connects the names.
- [Search providers change or block automation] → Keep discovery optional and provider-isolated; direct official links and school site search remain usable without weakening completion gates.
- [Upstream and handoff models differ] → Port behavior behind adapters and tests instead of copying database or UI files wholesale.
- [Translation can alter title meaning] → Retain original title and require the existing conservative classifier; translation is classification assistance, not identity or email evidence.
- [A directory can hide an unknown number of dynamic results] → Report interaction history and coverage-incomplete states rather than claiming completeness after a safety cutoff.

## Migration Plan

1. Establish a clean upstream 2.0.0 test baseline and inventory the handoff-only modules and tests.
2. Add task/source/evidence persistence with schema initialization that does not modify existing upstream user settings or translation cache.
3. Port directory enumeration and split-email regression behavior behind upstream parsers.
4. Add the bounded source graph, official-boundary validation, conservative merging, and strict completion gate.
5. Add review-only reprocessing and exports, then run all unit and integration tests.
6. Copy a task database before any migration rehearsal; validate on the copy and retain the original handoff database as rollback.
7. Run JLU/TSU/UCR pilots and compare coverage and status counts. Build a Windows release only after local acceptance.

Rollback consists of using the untouched upstream checkout or reverting local implementation commits; historical task data remains outside the repository and is never overwritten during development.
