## Purpose

Ensure the crawler produces a complete and diagnosable baseline of eligible people visibly listed by an official faculty directory before evidence enrichment begins.

## ADDED Requirements

### Requirement: Exhaust supported directory result states
The system SHALL enumerate every unique person exposed by supported pagination, page-size controls, load-more controls, scrolling, and dynamic result states on an official faculty directory.

#### Scenario: Multi-page directory
- **WHEN** an official directory exposes eligible people across multiple supported result pages
- **THEN** the baseline contains every unique eligible person from every successfully visited page

#### Scenario: Dynamically loaded directory
- **WHEN** additional people appear after a supported load-more or scrolling interaction
- **THEN** the system continues until the result state stops changing or a configured safety bound is reached

### Requirement: Preserve visible person identity before enrichment
The system SHALL retain each directory person's displayed name, original title, profile link when present, directory source, and directory evidence even when no email is available.

#### Scenario: Directory card without email
- **WHEN** a valid professor card contains a name and title but no email
- **THEN** the person remains in the baseline and proceeds to evidence discovery rather than being dropped

### Requirement: Classify titles without replacing official evidence
The system SHALL preserve the official title text and MAY use the bundled local translation pipeline to classify an otherwise unknown non-English title.

#### Scenario: Translated title is eligible
- **WHEN** an official non-English title is translated locally and maps to an included academic role
- **THEN** the person remains eligible while the original official title and translation metadata are retained

#### Scenario: Translation is unavailable
- **WHEN** an unknown non-English title cannot be translated or classified
- **THEN** the person is routed to review and is not silently excluded or completed

### Requirement: Report incomplete enumeration
The system SHALL record visited result states, unique-person counts, duplicate counts, stop reason, and any safety bound or page failure that may make coverage incomplete.

#### Scenario: Safety bound reached
- **WHEN** a directory reaches a configured page, interaction, or person limit before exhaustion
- **THEN** the school is marked as coverage-incomplete with a reviewable diagnostic reason

#### Scenario: Regression fixture has a known population
- **WHEN** a fixture declares an expected set of eligible directory people
- **THEN** the enumeration test passes only when recall is 100 percent for that set
