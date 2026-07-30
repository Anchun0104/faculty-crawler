## Purpose

Increase completed records by finding and merging missing evidence from bounded official university pages without trusting search summaries or guessing personal email addresses.

## ADDED Requirements

### Requirement: Discover bounded official secondary sources
The system SHALL follow bounded links from an official directory to person profiles, research centers, laboratories, and institutional research portals that belong to the same university.

#### Scenario: Research laboratory linked from directory
- **WHEN** an official directory links to an official laboratory page containing faculty members
- **THEN** the laboratory page is fetched as a secondary source and its people are considered for conservative evidence merging

#### Scenario: Discovery bound is reached
- **WHEN** the configured source depth or page count is exhausted
- **THEN** discovery stops, records the bound as its stop reason, and does not continue into an unbounded site crawl

### Requirement: Treat search results as discovery hints only
The system MUST NOT use a search result title, snippet, cached text, or inferred URL as formal evidence.

#### Scenario: Search discovers an official profile
- **WHEN** a search result identifies a candidate URL for an unresolved person
- **THEN** the candidate URL is fetched and validated as an official university page before any field from it can support completion

#### Scenario: Search result cannot be re-fetched
- **WHEN** a search result appears relevant but its target official page cannot be fetched and validated
- **THEN** no search content is added as supported evidence and the person remains in review

### Requirement: Validate official source ownership
The system SHALL accept evidence only from the configured university domain, a validated university subdomain, or an institutional research portal whose ownership is established by an official university link.

#### Scenario: Unrelated third-party profile
- **WHEN** a candidate page is hosted outside the validated official source boundary
- **THEN** its fields cannot satisfy a completion gate

### Requirement: Decode complete emails without inference
The system SHALL reconstruct an email only when page text, markup attributes, or page-delivered JavaScript deterministically contains all components of the complete address.

#### Scenario: Email split across attributes
- **WHEN** a page contains a local part and official domain in separate attributes that deterministically form one complete address
- **THEN** the reconstructed address is accepted as page-present evidence with the originating page and extraction method recorded

#### Scenario: Only an email pattern is implied
- **WHEN** the page does not contain all components of a person's complete email address
- **THEN** the system does not guess the address and the missing-email completion gate remains unsatisfied

### Requirement: Merge evidence conservatively by identity
The system SHALL merge secondary-page evidence only when a normalized name and other available identity signals identify one person without conflict.

#### Scenario: Exact person receives email evidence
- **WHEN** an official secondary page names one baseline person and visibly contains that person's complete official email
- **THEN** the email evidence is merged into that person's record with source provenance

#### Scenario: Same name maps to conflicting people or emails
- **WHEN** available official pages contain an unresolved identity collision or more than one distinct personal email for the same merge key
- **THEN** the system does not choose automatically and routes the record to review with conflict details

### Requirement: Enforce evidence-grounded completion
The system SHALL complete a record only when person identity is clear, the academic role is included, required fields have official-page evidence, and a complete non-generic personal email is visibly supported by an official page.

#### Scenario: Fully supported professor
- **WHEN** all completion gates are satisfied across one or more official pages
- **THEN** the record enters the completed output and retains each supporting source

#### Scenario: Official pages contain no complete personal email
- **WHEN** a professor is listed but every fetched official page lacks a complete personal email
- **THEN** the record remains in review and the automatic completion count for that record is zero

### Requirement: Isolate page-level failures
The system SHALL continue processing other people and sources when one secondary page fails, while preserving a reviewable failure reason for the affected record or source.

#### Scenario: One profile times out
- **WHEN** a single person's official profile fails after bounded retries
- **THEN** other people continue processing and the affected person remains reviewable with the failure recorded
