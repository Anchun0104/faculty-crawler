# Official Faculty Coverage Design

## Approved outcome

Increase the number of completed faculty records by enumerating all eligible people visible in official directories and enriching them from official personal pages, research centers, laboratories, and institutional research portals. Search results may identify candidate URLs but cannot serve as evidence. A person without a complete official personal email remains in review.

## Architecture

Use the upstream 2.0.0 repository as the local baseline so the bundled offline translator, title classifier, desktop UI, and release packaging remain intact. Integrate the evidence-first workflow as bounded modules for directory enumeration, source discovery, fetching, evidence extraction, identity merging, quality decisions, and review-only reprocessing. Do not overlay the older handoff tree onto upstream.

Each school produces a directory baseline before enrichment. A finite official-source graph then follows supported links and, for unresolved people, accepts search-discovered candidate URLs. Candidate URLs must be fetched and validated as official university pages. Evidence is stored as source-scoped facts and merged only for an unambiguous person identity.

## Data and trust rules

- Preserve the official title before local translation and retain all translation metadata.
- Accept reconstructed emails only when the delivered page contains every address component in text, markup attributes, or JavaScript data.
- Never infer an email format or use a generic address as a person's email.
- Keep search snippets, third-party pages, and inaccessible targets out of supported evidence.
- Route name collisions, email conflicts, access failures, unknown titles, and missing emails to review.
- Complete records only when identity, included role, required official evidence, and a complete official personal email are all supported.

## Reprocessing

Review-only reprocessing supersedes only active review candidates, requeues only affected schools, protects completed candidates, reuses successful source state, and resumes an interrupted generation without resetting it again. Audit output must show scope and prove completed records were preserved.

## Verification

Regression fixtures must achieve 100 percent recall for their declared eligible directory population. Tests cover pagination, dynamic loading, split emails, official research-source discovery, search revalidation, conservative merging, translation, page-level failures, and review-only recovery. Live JLU, TSU, and UCR pilots report baseline population, completed count, review count, failures, and evidence sources. No record lacking a complete official personal email may be completed.

The full OpenSpec contract and technical decisions are in `openspec/changes/increase-official-faculty-coverage/`.
