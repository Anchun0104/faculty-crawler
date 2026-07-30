## Purpose

Allow improved discovery and parsing rules to revisit unresolved records safely while preserving completed results and providing an auditable, resumable execution history.

## ADDED Requirements

### Requirement: Requeue only active review records
The system SHALL create a reprocessing run from records currently in review and SHALL NOT requeue completed records from the same task.

#### Scenario: Task contains completed and review records
- **WHEN** review-only reprocessing starts for a task
- **THEN** only schools and people represented by active review records are requeued

### Requirement: Preserve completed records
The system MUST NOT reject, replace, or modify an existing completed record merely because review-only reprocessing is requested.

#### Scenario: Completed person also appears on a revisited source
- **WHEN** a revisited directory contains a person already completed in the task
- **THEN** the crawler skips creating a replacement candidate and keeps the completed record unchanged

### Requirement: Make reprocessing resumable and idempotent
The system SHALL persist reprocessing state so interruption and retry do not duplicate active candidates or repeat already successful page work unnecessarily.

#### Scenario: Process is interrupted
- **WHEN** review-only reprocessing stops during a school
- **THEN** a subsequent run resumes from persisted state and does not reset review records a second time

#### Scenario: Same profile is encountered twice
- **WHEN** the same normalized profile URL is rediscovered during one reprocessing generation
- **THEN** at most one active candidate is retained for that person and source identity

### Requirement: Audit each reprocessing generation
The system SHALL record which prior review records were superseded, which schools were requeued, and the completed, review, and rejected counts produced by the generation.

#### Scenario: Review-only run finishes
- **WHEN** reprocessing completes or stops with a recoverable status
- **THEN** the audit output identifies the generation scope and proves that completed records were preserved
