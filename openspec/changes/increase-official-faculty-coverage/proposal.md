## Why

The crawler can miss eligible faculty when an official directory uses pagination, dynamic rendering, or links out to research units and institutional portals. Records that are found often remain in review because the primary directory does not show a complete personal email, even when another official university page provides the missing evidence.

## What Changes

- Enumerate all eligible faculty displayed by an official directory across supported pagination and dynamic-loading patterns, with coverage diagnostics that make omissions visible.
- Discover bounded secondary official sources linked from directories, including personal profiles, research centers, laboratories, and institutional research portals.
- Use search results only to discover candidate entry points; re-fetch and validate the university's official page before accepting any evidence.
- Merge evidence from multiple official pages by a conservative person identity, retaining source provenance and routing name or email conflicts to review.
- Preserve the original title from the official page and use the bundled local translator only to assist title classification.
- Require a complete personal email visibly present on an official page before a record can be completed; never infer an email address or promote a generic contact address.
- Reprocess only review records while preserving previously completed records and cached successful source fetches.
- Add regression and live-pilot reporting for directory coverage, completion conversion, review reasons, and evidence sources.

## Capabilities

### New Capabilities

- `official-faculty-enumeration`: Complete, diagnosable enumeration of eligible people listed in official faculty directories.
- `official-evidence-discovery`: Bounded discovery, official-page revalidation, and conservative multi-page evidence merging.
- `review-only-reprocessing`: Idempotent reprocessing that targets review records without rerunning or altering completed records.

### Modified Capabilities

None.

## Impact

- Affects directory parsing and dynamic-page traversal in `crawler/`, plus task orchestration, source provenance, review state, and exports introduced from the local evidence-first workflow.
- Integrates with the existing multilingual title pipeline without changing the local-only translation trust boundary.
- Adds persistent source/discovery metadata and review-only reprocessing behavior to the local task database.
- Expands regression fixtures and workflow tests; live verification will initially cover JLU, TSU, and UCR.
- May increase bounded official-page requests per school, while retaining domain restrictions, robots compliance, rate limits, and access-control safeguards.
