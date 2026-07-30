# Official Evidence Fast Path Design

## Goal

Reduce repeated browser visits without lowering evidence quality or faculty coverage.

## Behavior

An official directory record may bypass its linked personal profile only when the directory evidence alone passes the existing candidate evaluator. That requires a grounded name, allowed title, explicit discipline relevance, a complete page-present official email, verified email ownership, and an official school URL. Records missing any required field continue through the existing personal-profile and research-portal workflow.

Successful persisted snapshots are reused for official email follow-up pages as well as directories and personal profiles. A missing, failed, non-200, or unreadable snapshot is fetched normally.

Profile discovery remains enabled for incomplete records so official laboratories, research centers, and portals can still expand coverage. A complete directory record is not downgraded merely because it has an optional profile link that was not visited.

## Data Flow

1. Parse and merge official directory records by exact normalized name.
2. Build the same directory-only extraction used for records without profile links.
3. Run title normalization and the existing candidate evaluator.
4. Mark records that already receive an `accepted` decision as directory-complete.
5. Skip profile prefetch, linked-source discovery, and profile extraction for those records; save the accepted directory extraction directly.
6. For incomplete records, keep the current profile and secondary-source flow.
7. When the email resolver requests an official follow-up URL, load a successful persisted source snapshot before making a network request.

## Safety Constraints

- Never infer an email address or domain.
- Search results remain discovery hints and never become evidence.
- Only official, page-present complete email addresses can pass.
- Emeritus and other policy exclusions run before the fast path.
- Cached evidence must have a successful fetch state, HTTP 2xx status, a content hash, and a readable snapshot.
- Existing accepted records and historical task data are not mutated by the code tests.

## Tests

- An integration test supplies an official directory card with complete evidence and a profile link whose fetch would fail; the result must be accepted with zero profile requests.
- A second integration test supplies an incomplete directory card; it must still fetch and use the profile.
- A cached email-follow-up test persists the page snapshot and verifies the resolver completes without a network request.
- Run the focused service tests, then the complete unit-test suite.
