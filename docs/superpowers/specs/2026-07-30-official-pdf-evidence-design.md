# Official PDF Evidence Design

## Goal

Treat text-layer PDFs on confirmed university domains as auditable official evidence without weakening email or identity requirements.

## Scope

The first version supports ordinary text-layer PDFs only. It does not perform OCR, infer missing characters, or reconstruct obfuscated addresses such as `name{a}domain`, `name[at]domain`, or `name@#domain`.

After implementation, only the review generation for Nagoya University task `6257cee3e0f2` is rerun. Accepted rows in unrelated tasks, including task `67e246112066`, are not reprocessed.

## PDF Fetching

`PageFetcher.fetch` detects a PDF from a `.pdf` URL or an HTTP response whose content type is `application/pdf`. PDF requests use a bounded direct HTTP download with the existing user agent, robots check, domain throttling, and timeout.

A response is accepted only when it is HTTP 2xx, has a PDF content type or begins with the `%PDF-` signature, and does not exceed 20 MB. Redirects are allowed only through the normal HTTP client and the final URL is persisted. Invalid, encrypted-without-readable-text, oversized, and network-failed PDFs raise `FetchError` with a bounded diagnostic.

The raw PDF bytes are hashed and stored as `<sha256>.pdf`. Text is extracted using `pypdf.PdfReader` and placed in `FetchedPage.text`; `FetchedPage.html` is empty. PDF metadata title is used when available, otherwise the filename is used. Extracted text is bounded for downstream processing, while the original raw snapshot remains available for audit.

## Cache Reuse

The persisted-source loader supports both existing `.html.gz` snapshots and new `.pdf` snapshots. A cached PDF is revalidated by file existence, size, `%PDF-` signature, and successful text extraction before it is returned as a `FetchedPage`. Corrupt or unreadable snapshots fail closed and are fetched again through the normal path.

## Evidence Rules

PDF text follows the same grounding rules as HTML text:

- The source and final URL must remain on the confirmed university domain.
- The candidate's name and allowed title must be supported by official evidence.
- An email is accepted only when the complete address with literal `@` appears in extracted PDF text.
- Search snippets and search-engine PDF text remain discovery-only; the crawler must download the official PDF itself.
- No replacement instruction is executed, even when the PDF explicitly says to replace `{a}`, `[at]`, `(a)`, `#`, or similar markers with `@`.

## Shared PDF and False-Person Handling

Multiple real people may legitimately share one laboratory PDF. Directory seed storage therefore does not merge two different non-empty names merely because their profile URLs are identical. Each real name remains an independent seed and may use the same cached PDF evidence.

Directory adapter candidates whose normalized names are laboratory labels, including forms ending in `Lab`, are rejected as non-person records. This does not block a real person's seed from linking to that laboratory PDF.

## Nagoya Review-Only Rerun

After tests pass, start one review generation for task `6257cee3e0f2`. The main directory is parsed again from its successful snapshot, bogus laboratory candidates from the prior generation are superseded, shared laboratory PDFs retain every real person name, and official PDFs are downloaded once then reused from cache.

Only rows satisfying all existing acceptance gates move to completed. Rows whose only email remains obfuscated are not accepted. The output must report discovered real people, completed rows, remaining review rows, rejected false-person rows, and email validation violations.

## Tests

- A direct PDF fetch test uses a local HTTP fixture and verifies raw snapshot persistence, text extraction, final URL, hash, and zero Playwright use.
- PDF signature, HTTP status, maximum size, corrupt file, and empty-text failures are covered.
- A cached PDF source is loaded without a second network request.
- A literal full official email in PDF text can pass the existing resolver and evidence gates.
- Obfuscated addresses are not reconstructed or accepted.
- Two people sharing one PDF URL remain two seeds.
- `A Lab` and `QG Lab` are not emitted as people.
- Focused tests and the full test suite pass before the Nagoya review-only rerun.
