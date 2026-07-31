from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from faculty_workflow.models import (
    CANDIDATE_STATUSES,
    SCHOOL_STATUSES,
    TASK_STATUSES,
    CandidateExtraction,
    DisciplinePolicy,
    SchoolInput,
    normalize_email,
    normalize_key,
    normalize_profile_identity,
    normalize_url,
)


SCHEMA_VERSION = 6


class WorkflowDatabase:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    discipline TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    policy_confirmed INTEGER NOT NULL DEFAULT 0,
                    budget_usd REAL NOT NULL,
                    spent_usd REAL NOT NULL DEFAULT 0,
                    routine_model TEXT NOT NULL,
                    escalation_model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_dir TEXT NOT NULL,
                    warning TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    original_row TEXT NOT NULL DEFAULT '',
                    official_domain TEXT NOT NULL DEFAULT '',
                    directory_url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    failure_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, normalized_name)
                );
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    url TEXT NOT NULL,
                    normalized_url TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    official INTEGER NOT NULL DEFAULT 0,
                    final_url TEXT NOT NULL DEFAULT '',
                    http_status INTEGER,
                    content_hash TEXT NOT NULL DEFAULT '',
                    snapshot_path TEXT NOT NULL DEFAULT '',
                    fetched_at TEXT NOT NULL DEFAULT '',
                    failure_reason TEXT NOT NULL DEFAULT '',
                    discovered_from TEXT NOT NULL DEFAULT '',
                    depth INTEGER NOT NULL DEFAULT 0,
                    official_boundary TEXT NOT NULL DEFAULT '',
                    fetch_state TEXT NOT NULL DEFAULT 'queued',
                    stop_reason TEXT NOT NULL DEFAULT '',
                    fetch_duration_ms INTEGER NOT NULL DEFAULT 0,
                    fetch_attempts INTEGER NOT NULL DEFAULT 0,
                    cache_hit_count INTEGER NOT NULL DEFAULT 0,
                    dynamic_actions_json TEXT NOT NULL DEFAULT '[]',
                    UNIQUE(task_id, normalized_url)
                );
                CREATE TABLE IF NOT EXISTS access_reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    url TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id, school_id, url)
                );
                CREATE INDEX IF NOT EXISTS idx_access_reviews_task_status
                    ON access_reviews(task_id, status);
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    school_id INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
                    name TEXT NOT NULL DEFAULT '',
                    normalized_person_identity TEXT NOT NULL DEFAULT '',
                    email TEXT NOT NULL DEFAULT '',
                    last_name TEXT NOT NULL DEFAULT '',
                    title_raw TEXT NOT NULL DEFAULT '',
                    normalized_title TEXT NOT NULL DEFAULT '',
                    title_translated TEXT NOT NULL DEFAULT '',
                    title_language TEXT NOT NULL DEFAULT '',
                    translation_status TEXT NOT NULL DEFAULT 'not_needed',
                    translation_engine TEXT NOT NULL DEFAULT '',
                    classification_rules_version TEXT NOT NULL DEFAULT '',
                    department TEXT NOT NULL DEFAULT '',
                    homepage TEXT NOT NULL DEFAULT '',
                    normalized_profile_identity TEXT NOT NULL DEFAULT '',
                    direction TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    review_reason TEXT NOT NULL DEFAULT '',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    extraction_json TEXT NOT NULL DEFAULT '{}',
                    decision_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_candidates_task_status ON candidates(task_id, status);
                CREATE INDEX IF NOT EXISTS idx_candidates_email ON candidates(task_id, email);
                CREATE TABLE IF NOT EXISTS field_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                    field TEXT NOT NULL,
                    value TEXT NOT NULL DEFAULT '',
                    quote TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    extraction_method TEXT NOT NULL,
                    support_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_field_evidence_candidate
                    ON field_evidence(candidate_id, field);
                CREATE TABLE IF NOT EXISTS api_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    school_id INTEGER REFERENCES schools(id) ON DELETE SET NULL,
                    operation TEXT NOT NULL,
                    model TEXT NOT NULL,
                    response_id TEXT NOT NULL DEFAULT '',
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    tool_calls INTEGER NOT NULL DEFAULT 0,
                    estimated_cost_usd REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS historical_people (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    email TEXT NOT NULL DEFAULT '',
                    normalized_name TEXT NOT NULL DEFAULT '',
                    normalized_school TEXT NOT NULL DEFAULT '',
                    homepage TEXT NOT NULL DEFAULT '',
                    source_file TEXT NOT NULL,
                    UNIQUE(task_id, email, normalized_name, normalized_school, homepage)
                );
                CREATE INDEX IF NOT EXISTS idx_history_email ON historical_people(task_id, email);
                CREATE TABLE IF NOT EXISTS processed_schools (
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    normalized_school TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    PRIMARY KEY(task_id, normalized_school)
                );
                CREATE TABLE IF NOT EXISTS reprocessing_generations (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    superseded_candidate_ids TEXT NOT NULL DEFAULT '[]',
                    requeued_school_ids TEXT NOT NULL DEFAULT '[]',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    attempt_number INTEGER NOT NULL DEFAULT 0,
                    reopened_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_active_reprocessing_generation
                    ON reprocessing_generations(task_id) WHERE status = 'running';
                """
            )
            self._ensure_column(connection, "sources", "discovered_from", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "sources", "depth", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "sources", "official_boundary", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "sources", "fetch_state", "TEXT NOT NULL DEFAULT 'queued'")
            self._ensure_column(connection, "sources", "stop_reason", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "sources", "fetch_duration_ms", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "sources", "fetch_attempts", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "sources", "cache_hit_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "sources", "dynamic_actions_json", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(connection, "candidates", "title_translated", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "candidates", "title_language", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "candidates", "translation_status", "TEXT NOT NULL DEFAULT 'not_needed'")
            self._ensure_column(connection, "candidates", "translation_engine", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "candidates", "classification_rules_version", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "candidates", "normalized_person_identity", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "candidates", "normalized_profile_identity", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "reprocessing_generations", "attempt_number", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "reprocessing_generations", "reopened_reason", "TEXT NOT NULL DEFAULT ''")
            connection.execute(
                """UPDATE sources SET fetch_state = 'fetched'
                   WHERE fetch_state = 'queued' AND snapshot_path != ''
                     AND content_hash != '' AND failure_reason = ''"""
            )
            connection.execute(
                """UPDATE sources SET official_boundary = 'official'
                   WHERE official = 1 AND official_boundary = ''"""
            )
            connection.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_active_candidate_person
                   ON candidates(task_id, school_id, normalized_person_identity)
                   WHERE status IN ('candidate', 'accepted', 'review')
                     AND normalized_person_identity != ''"""
            )
            connection.execute(
                """CREATE UNIQUE INDEX IF NOT EXISTS idx_active_candidate_profile
                   ON candidates(task_id, school_id, normalized_profile_identity)
                   WHERE status IN ('candidate', 'accepted', 'review')
                     AND normalized_profile_identity != ''"""
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        declaration: str,
    ) -> None:
        existing = {
            str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def create_task(
        self,
        policy: DisciplinePolicy,
        schools: Iterable[SchoolInput],
        *,
        output_dir: str | Path,
        budget_usd: float = 20.0,
        routine_model: str = "deepseek-v4-flash",
        escalation_model: str = "deepseek-v4-pro",
        policy_confirmed: bool = False,
    ) -> str:
        if budget_usd <= 0:
            raise ValueError("Budget must be greater than zero")
        task_id = uuid.uuid4().hex[:12]
        now = _now()
        status = "ready" if policy_confirmed else "needs_policy_confirmation"
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO tasks(
                    id, discipline, policy_json, policy_confirmed, budget_usd, routine_model,
                    escalation_model, status, output_dir, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    policy.discipline,
                    policy.to_json(),
                    int(policy_confirmed),
                    budget_usd,
                    routine_model,
                    escalation_model,
                    status,
                    str(Path(output_dir).resolve()),
                    now,
                    now,
                ),
            )
            for school in schools:
                connection.execute(
                    """INSERT INTO schools(
                        task_id, name, normalized_name, original_row, official_domain,
                        directory_url, status, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
                    (
                        task_id,
                        school.name.strip(),
                        normalize_key(school.name),
                        school.original_row,
                        school.official_domain.lower().strip(),
                        school.directory_url.strip(),
                        now,
                        now,
                    ),
                )
        return task_id

    def get_task(self, task_id: str) -> sqlite3.Row:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown task: {task_id}")
        return row

    def get_policy(self, task_id: str) -> DisciplinePolicy:
        return DisciplinePolicy.from_json(self.get_task(task_id)["policy_json"])

    def confirm_policy(self, task_id: str, policy: DisciplinePolicy) -> None:
        self.update_task(
            task_id,
            status="ready",
            policy_json=policy.to_json(),
            policy_confirmed=1,
            discipline=policy.discipline,
        )

    def recover_interrupted_task(self, task_id: str) -> int:
        """Make unfinished school work resumable after an unexpected process exit."""
        now = _now()
        active_statuses = ("discovering", "crawling", "extracting")
        with self.transaction() as connection:
            cursor = connection.execute(
                f"""UPDATE schools SET status = 'failed',
                    failure_reason = 'interrupted_before_completion', updated_at = ?
                    WHERE task_id = ? AND status IN ({','.join('?' for _ in active_statuses)})""",
                (now, task_id, *active_statuses),
            )
            connection.execute(
                """UPDATE tasks SET status = 'ready', error = '', updated_at = ?
                   WHERE id = ? AND status = 'running'""",
                (now, task_id),
            )
        return int(cursor.rowcount)

    def update_task(self, task_id: str, **values: Any) -> None:
        allowed = {
            "discipline", "policy_json", "policy_confirmed", "budget_usd", "spent_usd",
            "routine_model", "escalation_model", "status", "warning", "error",
        }
        self._update("tasks", task_id, values, allowed)

    def list_schools(self, task_id: str, statuses: Iterable[str] | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM schools WHERE task_id = ?"
        params: list[Any] = [task_id]
        if statuses:
            selected = tuple(statuses)
            query += f" AND status IN ({','.join('?' for _ in selected)})"
            params.extend(selected)
        query += " ORDER BY id"
        with closing(self.connect()) as connection:
            return list(connection.execute(query, params).fetchall())

    def update_school(self, school_id: int, *, status: str, failure_reason: str = "", **values: Any) -> None:
        if status not in SCHOOL_STATUSES:
            raise ValueError(f"Invalid school status: {status}")
        allowed = {"name", "original_row", "official_domain", "directory_url", "status", "failure_reason"}
        values.update(status=status, failure_reason=failure_reason)
        self._update("schools", school_id, values, allowed)

    def add_source(
        self,
        task_id: str,
        school_id: int,
        url: str,
        source_type: str,
        *,
        official: bool = False,
        discovered_from: str = "",
        depth: int = 0,
        official_boundary: str = "",
        fetch_state: str = "queued",
        stop_reason: str = "",
    ) -> int:
        normalized = normalize_url(url)
        if not normalized:
            raise ValueError(f"Invalid source URL: {url}")
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO sources(
                    task_id, school_id, url, normalized_url, source_type, official,
                    discovered_from, depth, official_boundary, fetch_state, stop_reason
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, normalized_url) DO UPDATE SET
                    source_type = excluded.source_type,
                    official = MAX(sources.official, excluded.official),
                    discovered_from = CASE WHEN sources.discovered_from = ''
                        THEN excluded.discovered_from ELSE sources.discovered_from END,
                    depth = MIN(sources.depth, excluded.depth),
                    official_boundary = CASE WHEN excluded.official_boundary != ''
                        THEN excluded.official_boundary ELSE sources.official_boundary END,
                    stop_reason = CASE WHEN excluded.stop_reason != ''
                        THEN excluded.stop_reason ELSE sources.stop_reason END""",
                (
                    task_id, school_id, url, normalized, source_type, int(official),
                    normalize_url(discovered_from), max(0, int(depth)), official_boundary,
                    fetch_state, stop_reason,
                ),
            )
            row = connection.execute(
                "SELECT id FROM sources WHERE task_id = ? AND normalized_url = ?",
                (task_id, normalized),
            ).fetchone()
        return int(row["id"])

    def update_source(self, source_id: int, **values: Any) -> None:
        allowed = {
            "official", "final_url", "http_status", "content_hash", "snapshot_path",
            "fetched_at", "failure_reason", "source_type", "discovered_from", "depth",
            "official_boundary", "fetch_state", "stop_reason",
            "fetch_duration_ms", "fetch_attempts", "cache_hit_count", "dynamic_actions_json",
        }
        self._update("sources", source_id, values, allowed, timestamp=False)

    def record_source_cache_hit(self, source_id: int) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE sources SET cache_hit_count = cache_hit_count + 1 WHERE id = ?",
                (source_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown sources id: {source_id}")

    def list_sources(self, task_id: str, school_id: int | None = None) -> list[sqlite3.Row]:
        query = "SELECT * FROM sources WHERE task_id = ?"
        params: list[Any] = [task_id]
        if school_id is not None:
            query += " AND school_id = ?"
            params.append(school_id)
        query += " ORDER BY id"
        with closing(self.connect()) as connection:
            return list(connection.execute(query, params).fetchall())

    def create_access_review(self, task_id: str, school_id: int, url: str, reason: str) -> int:
        """Queue a site that requires a user-held login or human verification.

        This intentionally stores no browser storage, credentials, page body, or
        screenshot. The URL and short classification are sufficient for a user to
        decide whether to retry through a lawful, manual process.
        """
        if not url.strip():
            raise ValueError("Access review URL is required")
        now = _now()
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO access_reviews(task_id, school_id, url, reason, status, created_at, updated_at)
                   VALUES(?, ?, ?, ?, 'pending', ?, ?)
                   ON CONFLICT(task_id, school_id, url) DO UPDATE SET
                     reason = excluded.reason, status = 'pending', updated_at = excluded.updated_at""",
                (task_id, school_id, url.strip(), reason[:500], now, now),
            )
            row = connection.execute(
                "SELECT id FROM access_reviews WHERE task_id = ? AND school_id = ? AND url = ?",
                (task_id, school_id, url.strip()),
            ).fetchone()
        return int(row["id"])

    def list_access_reviews(
        self, task_id: str, statuses: Iterable[str] | None = None
    ) -> list[sqlite3.Row]:
        query = """SELECT r.*, s.name AS school FROM access_reviews r
                   JOIN schools s ON s.id = r.school_id WHERE r.task_id = ?"""
        params: list[Any] = [task_id]
        if statuses:
            selected = tuple(statuses)
            query += f" AND r.status IN ({','.join('?' for _ in selected)})"
            params.extend(selected)
        query += " ORDER BY r.updated_at DESC, r.id DESC"
        with closing(self.connect()) as connection:
            return list(connection.execute(query, params).fetchall())

    def get_access_review(self, review_id: int) -> sqlite3.Row:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT * FROM access_reviews WHERE id = ?", (review_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown access review: {review_id}")
        return row

    def resolve_access_review(self, review_id: int, *, retry: bool) -> None:
        now = _now()
        review_status = "ready_to_retry" if retry else "dismissed"
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT school_id FROM access_reviews WHERE id = ?", (review_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown access review: {review_id}")
            connection.execute(
                "UPDATE access_reviews SET status = ?, updated_at = ? WHERE id = ?",
                (review_status, now, review_id),
            )
            if retry:
                connection.execute(
                    """UPDATE schools SET status = 'pending', failure_reason = '', updated_at = ?
                       WHERE id = ?""",
                    (now, row["school_id"]),
                )

    def add_candidate(
        self,
        task_id: str,
        school_id: int,
        extraction: CandidateExtraction,
        *,
        direction: str,
        source_url: str,
        status: str,
        review_reason: str = "",
    ) -> int:
        if status not in CANDIDATE_STATUSES:
            raise ValueError(f"Invalid candidate status: {status}")
        now = _now()
        extraction_json = json.dumps(
            {
                "professional_relevance": extraction.professional_relevance,
                "email_ownership": extraction.email_ownership,
                "homepage_identity": extraction.homepage_identity,
                "official_source": extraction.official_source,
                "group_homepage": extraction.group_homepage,
                "title_translated": extraction.title_translated,
                "title_language": extraction.title_language,
                "translation_status": extraction.translation_status,
                "translation_engine": extraction.translation_engine,
                "classification_rules_version": extraction.classification_rules_version,
                "failure_reasons": list(extraction.failure_reasons),
            },
            ensure_ascii=False,
        )
        with self.transaction() as connection:
            cursor = connection.execute(
                """INSERT INTO candidates(
                    task_id, school_id, name, normalized_person_identity, email, last_name,
                    title_raw, normalized_title,
                    title_translated, title_language, translation_status, translation_engine,
                    classification_rules_version,
                    department, homepage, normalized_profile_identity, direction, source_url,
                    status, review_reason,
                    evidence_json, extraction_json, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    school_id,
                    extraction.name,
                    normalize_key(extraction.name),
                    extraction.email,
                    extraction.last_name,
                    extraction.title_raw,
                    extraction.normalized_title,
                    extraction.title_translated,
                    extraction.title_language,
                    extraction.translation_status,
                    extraction.translation_engine,
                    extraction.classification_rules_version,
                    extraction.department,
                    extraction.homepage,
                    normalize_profile_identity(extraction.homepage),
                    direction,
                    source_url,
                    status,
                    review_reason,
                    extraction.evidence_json(),
                    extraction_json,
                    now,
                    now,
                ),
            )
            candidate_id = int(cursor.lastrowid)
            field_values = {
                "name": extraction.name,
                "email": extraction.email,
                "title": extraction.title_raw,
                "department": extraction.department,
                "homepage": extraction.homepage,
                "professional_relevance": extraction.professional_relevance,
            }
            connection.executemany(
                """INSERT INTO field_evidence(
                    candidate_id, field, value, quote, source_url,
                    extraction_method, support_status, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        candidate_id,
                        item.field,
                        str(field_values.get(item.field, "")),
                        item.quote,
                        item.source_url,
                        item.extraction_method,
                        item.status,
                        now,
                    )
                    for item in extraction.evidence
                ],
            )
            return candidate_id

    def list_candidates(self, task_id: str, statuses: Iterable[str] | None = None) -> list[sqlite3.Row]:
        query = """SELECT c.*, s.name AS school, s.original_row
                   FROM candidates c JOIN schools s ON s.id = c.school_id
                   WHERE c.task_id = ?"""
        params: list[Any] = [task_id]
        if statuses:
            selected = tuple(statuses)
            query += f" AND c.status IN ({','.join('?' for _ in selected)})"
            params.extend(selected)
        query += " ORDER BY c.id"
        with closing(self.connect()) as connection:
            return list(connection.execute(query, params).fetchall())

    def get_source(self, source_id: int) -> sqlite3.Row:
        with closing(self.connect()) as connection:
            row = connection.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown source: {source_id}")
        return row

    def find_source(self, task_id: str, url: str) -> sqlite3.Row | None:
        normalized = normalize_url(url)
        if not normalized:
            return None
        with closing(self.connect()) as connection:
            return connection.execute(
                "SELECT * FROM sources WHERE task_id = ? AND normalized_url = ?",
                (task_id, normalized),
            ).fetchone()

    def list_field_evidence(self, candidate_id: int) -> list[sqlite3.Row]:
        with closing(self.connect()) as connection:
            return list(
                connection.execute(
                    "SELECT * FROM field_evidence WHERE candidate_id = ? ORDER BY id",
                    (candidate_id,),
                ).fetchall()
            )

    def has_candidate_homepage(self, task_id: str, school_id: int, homepage: str) -> bool:
        normalized = normalize_url(homepage)
        if not normalized:
            return False
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """SELECT homepage FROM candidates
                   WHERE task_id = ? AND school_id = ? AND status != 'rejected'""",
                (task_id, school_id),
            ).fetchall()
        return any(normalize_url(row["homepage"]) == normalized for row in rows)

    def has_accepted_candidate_name(self, task_id: str, school_id: int, name: str) -> bool:
        normalized = normalize_key(name)
        if not normalized:
            return False
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """SELECT name FROM candidates
                   WHERE task_id = ? AND school_id = ? AND status = 'accepted'""",
                (task_id, school_id),
            ).fetchall()
        return any(normalize_key(row["name"]) == normalized for row in rows)

    def reprocess_reviews(self, task_id: str) -> tuple[int, tuple[int, ...]]:
        """Supersede only active review rows and requeue their schools atomically."""
        with self.transaction() as connection:
            task = connection.execute(
                "SELECT id FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise KeyError(f"Unknown task: {task_id}")
            school_ids = tuple(
                int(row["school_id"])
                for row in connection.execute(
                    """SELECT DISTINCT school_id FROM candidates
                       WHERE task_id = ? AND status = 'review' ORDER BY school_id""",
                    (task_id,),
                ).fetchall()
            )
            if not school_ids:
                return 0, ()
            now = _now()
            cursor = connection.execute(
                """UPDATE candidates SET status = 'rejected',
                   decision_note = 'superseded_by_review_reprocess', updated_at = ?
                   WHERE task_id = ? AND status = 'review'""",
                (now, task_id),
            )
            placeholders = ",".join("?" for _ in school_ids)
            connection.execute(
                f"""UPDATE schools SET status = 'pending', failure_reason = '', updated_at = ?
                    WHERE task_id = ? AND id IN ({placeholders})""",
                (now, task_id, *school_ids),
            )
            return int(cursor.rowcount), school_ids

    def begin_review_generation(self, task_id: str) -> sqlite3.Row:
        """Start one idempotent review-only generation and preserve accepted rows."""
        with self.transaction() as connection:
            task = connection.execute(
                "SELECT id FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if task is None:
                raise KeyError(f"Unknown task: {task_id}")
            active = connection.execute(
                """SELECT * FROM reprocessing_generations
                   WHERE task_id = ? AND status = 'running'
                   ORDER BY created_at DESC LIMIT 1""",
                (task_id,),
            ).fetchone()
            if active is not None:
                return active

            review_rows = connection.execute(
                """SELECT id, school_id FROM candidates
                   WHERE task_id = ? AND status = 'review' ORDER BY id""",
                (task_id,),
            ).fetchall()
            candidate_ids = [int(row["id"]) for row in review_rows]
            school_ids = sorted({int(row["school_id"]) for row in review_rows})
            completed_attempts = int(connection.execute(
                """SELECT COUNT(*) FROM reprocessing_generations
                   WHERE task_id = ? AND status = 'completed' AND requeued_school_ids != '[]'""",
                (task_id,),
            ).fetchone()[0])
            if candidate_ids and completed_attempts >= 2:
                now = _now()
                placeholders = ",".join("?" for _ in candidate_ids)
                connection.execute(
                    f"""UPDATE candidates SET status = 'unresolved',
                       decision_note = 'review_attempt_limit_reached', updated_at = ?
                       WHERE id IN ({placeholders}) AND status = 'review'""",
                    (now, *candidate_ids),
                )
                generation_id = uuid.uuid4().hex[:12]
                connection.execute(
                    """INSERT INTO reprocessing_generations(
                        id, task_id, status, superseded_candidate_ids,
                        requeued_school_ids, summary_json, attempt_number, created_at, updated_at
                    ) VALUES(?, ?, 'completed', '[]', '[]', ?, ?, ?, ?)""",
                    (
                        generation_id, task_id,
                        json.dumps({"unresolved_limit": len(candidate_ids)}),
                        completed_attempts + 1, now, now,
                    ),
                )
                return connection.execute(
                    "SELECT * FROM reprocessing_generations WHERE id = ?", (generation_id,)
                ).fetchone()
            if not candidate_ids:
                latest = connection.execute(
                    """SELECT * FROM reprocessing_generations
                       WHERE task_id = ? AND status = 'completed'
                       ORDER BY created_at DESC, id DESC LIMIT 1""",
                    (task_id,),
                ).fetchone()
                if latest is not None:
                    return latest
            generation_id = uuid.uuid4().hex[:12]
            now = _now()
            if candidate_ids:
                candidate_placeholders = ",".join("?" for _ in candidate_ids)
                connection.execute(
                    f"""UPDATE candidates SET status = 'rejected',
                       decision_note = ?, updated_at = ?
                       WHERE id IN ({candidate_placeholders}) AND status = 'review'""",
                    (f"superseded_by_review_generation:{generation_id}", now, *candidate_ids),
                )
            if school_ids:
                school_placeholders = ",".join("?" for _ in school_ids)
                connection.execute(
                    f"""UPDATE schools SET status = 'pending', failure_reason = '', updated_at = ?
                       WHERE task_id = ? AND id IN ({school_placeholders})""",
                    (now, task_id, *school_ids),
                )
            status = "running" if candidate_ids else "completed"
            connection.execute(
                """INSERT INTO reprocessing_generations(
                    id, task_id, status, superseded_candidate_ids,
                    requeued_school_ids, summary_json, attempt_number, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, '{}', ?, ?, ?)""",
                (
                    generation_id,
                    task_id,
                    status,
                    json.dumps(candidate_ids),
                    json.dumps(school_ids),
                    completed_attempts + 1 if candidate_ids else completed_attempts,
                    now,
                    now,
                ),
            )
            return connection.execute(
                "SELECT * FROM reprocessing_generations WHERE id = ?",
                (generation_id,),
            ).fetchone()

    def list_review_generations(self, task_id: str) -> list[sqlite3.Row]:
        with closing(self.connect()) as connection:
            return list(
                connection.execute(
                    """SELECT * FROM reprocessing_generations
                       WHERE task_id = ? ORDER BY created_at, id""",
                    (task_id,),
                ).fetchall()
            )

    def reopen_unresolved(
        self,
        task_id: str,
        candidate_ids: Iterable[int],
        reason: str,
    ) -> tuple[int, tuple[int, ...]]:
        selected = tuple(sorted({int(value) for value in candidate_ids}))
        if not selected:
            return 0, ()
        if not reason.strip():
            raise ValueError("A reopening reason is required")
        placeholders = ",".join("?" for _ in selected)
        with self.transaction() as connection:
            rows = connection.execute(
                f"""SELECT id, school_id FROM candidates
                    WHERE task_id = ? AND status = 'unresolved' AND id IN ({placeholders})""",
                (task_id, *selected),
            ).fetchall()
            if not rows:
                return 0, ()
            ids = tuple(int(row["id"]) for row in rows)
            school_ids = tuple(sorted({int(row["school_id"]) for row in rows}))
            now = _now()
            ids_sql = ",".join("?" for _ in ids)
            connection.execute(
                f"""UPDATE candidates SET status = 'rejected', decision_note = ?, updated_at = ?
                    WHERE id IN ({ids_sql})""",
                (f"superseded_by_reopen:{reason.strip()[:200]}", now, *ids),
            )
            schools_sql = ",".join("?" for _ in school_ids)
            connection.execute(
                f"""UPDATE schools SET status = 'pending', failure_reason = '', updated_at = ?
                    WHERE task_id = ? AND id IN ({schools_sql})""",
                (now, task_id, *school_ids),
            )
            return len(ids), school_ids

    def close_unchanged_reviews(self, task_id: str, generation_id: str) -> int:
        """Stop automatic retry when the same evidence yields the same uncertainty."""
        with self.transaction() as connection:
            previous = connection.execute(
                """SELECT normalized_person_identity, normalized_profile_identity,
                          review_reason, evidence_json, source_url
                   FROM candidates
                   WHERE task_id = ? AND decision_note = ?""",
                (task_id, f"superseded_by_review_generation:{generation_id}"),
            ).fetchall()
            if not previous:
                return 0
            fingerprints = {
                (
                    str(row["normalized_person_identity"] or ""),
                    str(row["normalized_profile_identity"] or ""),
                    str(row["review_reason"] or ""),
                    str(row["evidence_json"] or ""),
                    str(row["source_url"] or ""),
                )
                for row in previous
            }
            active = connection.execute(
                """SELECT id, normalized_person_identity, normalized_profile_identity,
                          review_reason, evidence_json, source_url
                   FROM candidates WHERE task_id = ? AND status = 'review'""",
                (task_id,),
            ).fetchall()
            ids = [
                int(row["id"])
                for row in active
                if (
                    str(row["normalized_person_identity"] or ""),
                    str(row["normalized_profile_identity"] or ""),
                    str(row["review_reason"] or ""),
                    str(row["evidence_json"] or ""),
                    str(row["source_url"] or ""),
                ) in fingerprints
            ]
            if not ids:
                return 0
            placeholders = ",".join("?" for _ in ids)
            cursor = connection.execute(
                f"""UPDATE candidates SET status = 'unresolved', decision_note = ?, updated_at = ?
                    WHERE id IN ({placeholders}) AND status = 'review'""",
                (f"unchanged_review:{generation_id}", _now(), *ids),
            )
            return int(cursor.rowcount)

    def complete_review_generation(self, generation_id: str, summary: dict[str, Any]) -> None:
        now = _now()
        with self.transaction() as connection:
            cursor = connection.execute(
                """UPDATE reprocessing_generations
                   SET status = 'completed', summary_json = ?, updated_at = ?
                   WHERE id = ? AND status = 'running'""",
                (json.dumps(summary, ensure_ascii=False, sort_keys=True), now, generation_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown active review generation: {generation_id}")

    def reprocess_candidate(self, candidate_id: int) -> int:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT school_id FROM candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown candidate row: {candidate_id}")
            school_id = int(row["school_id"])
            now = _now()
            connection.execute(
                """UPDATE candidates SET status = 'rejected',
                   decision_note = 'superseded_by_reprocess', updated_at = ? WHERE id = ?""",
                (now, candidate_id),
            )
            connection.execute(
                """UPDATE schools SET status = 'pending', failure_reason = '', updated_at = ?
                   WHERE id = ?""",
                (now, school_id),
            )
        return school_id

    def reprocess_school(self, school_id: int) -> None:
        """Atomically supersede prior active results and return one school to pending."""
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM schools WHERE id = ?", (school_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown school row: {school_id}")
            now = _now()
            connection.execute(
                """UPDATE candidates SET status = 'rejected',
                   decision_note = 'superseded_by_school_reprocess', updated_at = ?
                   WHERE school_id = ? AND status != 'rejected'""",
                (now, school_id),
            )
            connection.execute(
                """UPDATE schools SET status = 'pending', failure_reason = '', updated_at = ?
                   WHERE id = ?""",
                (now, school_id),
            )

    def decide_candidate(
        self,
        candidate_id: int,
        status: str,
        *,
        note: str = "",
        edits: dict[str, str] | None = None,
    ) -> None:
        if status not in {"accepted", "rejected", "review"}:
            raise ValueError("Review decision must be accepted, rejected, or review")
        allowed_edits = {
            "name", "email", "last_name", "title_raw", "normalized_title",
            "department", "homepage", "direction", "source_url",
        }
        values: dict[str, Any] = {"status": status, "decision_note": note}
        for key, value in (edits or {}).items():
            if key not in allowed_edits:
                raise ValueError(f"Field cannot be edited: {key}")
            values[key] = str(value).strip()
        self._update("candidates", candidate_id, values, allowed_edits | {"status", "decision_note"})

    def add_historical_person(
        self,
        task_id: str,
        *,
        email: str = "",
        name: str = "",
        school: str = "",
        homepage: str = "",
        source_file: str,
    ) -> None:
        normalized_email = normalize_email(email)
        normalized_homepage = normalize_url(homepage)
        if not any((normalized_email, name.strip(), normalized_homepage)):
            return
        with self.transaction() as connection:
            connection.execute(
                """INSERT OR IGNORE INTO historical_people(
                    task_id, email, normalized_name, normalized_school, homepage, source_file
                ) VALUES(?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    normalized_email,
                    normalize_key(name),
                    normalize_key(school),
                    normalized_homepage,
                    source_file,
                ),
            )

    def add_processed_school(self, task_id: str, name: str, source_file: str) -> None:
        if not name.strip():
            return
        with self.transaction() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO processed_schools(
                    task_id, normalized_school, display_name, source_file
                ) VALUES(?, ?, ?, ?)""",
                (task_id, normalize_key(name), name.strip(), source_file),
            )

    def is_processed_school(self, task_id: str, school_name: str) -> bool:
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT 1 FROM processed_schools WHERE task_id = ? AND normalized_school = ?",
                (task_id, normalize_key(school_name)),
            ).fetchone()
        return row is not None

    def duplicate_reasons(
        self,
        task_id: str,
        *,
        school_id: int,
        name: str,
        school: str,
        email: str,
        homepage: str,
    ) -> list[str]:
        reasons: list[str] = []
        normalized_email = normalize_email(email)
        normalized_name = normalize_key(name)
        normalized_school = normalize_key(school)
        normalized_homepage = normalize_url(homepage)
        with closing(self.connect()) as connection:
            if normalized_email:
                if connection.execute(
                    "SELECT 1 FROM historical_people WHERE task_id = ? AND email = ?",
                    (task_id, normalized_email),
                ).fetchone():
                    reasons.append("duplicate_historical_email")
                if connection.execute(
                    "SELECT 1 FROM candidates WHERE task_id = ? AND email = ? AND status != 'rejected'",
                    (task_id, normalized_email),
                ).fetchone():
                    reasons.append("duplicate_task_email")
            if normalized_name and normalized_school:
                if connection.execute(
                    """SELECT 1 FROM historical_people
                       WHERE task_id = ? AND normalized_name = ? AND normalized_school = ?""",
                    (task_id, normalized_name, normalized_school),
                ).fetchone():
                    reasons.append("duplicate_historical_name_school")
                rows = connection.execute(
                    """SELECT c.name FROM candidates c JOIN schools s ON s.id = c.school_id
                       WHERE c.task_id = ? AND s.normalized_name = ? AND c.status != 'rejected'""",
                    (task_id, normalized_school),
                ).fetchall()
                if any(normalize_key(row["name"]) == normalized_name for row in rows):
                    reasons.append("duplicate_task_name_school")
            if normalized_homepage:
                if connection.execute(
                    "SELECT 1 FROM historical_people WHERE task_id = ? AND homepage = ?",
                    (task_id, normalized_homepage),
                ).fetchone():
                    reasons.append("duplicate_historical_homepage")
                rows = connection.execute(
                    "SELECT homepage FROM candidates WHERE task_id = ? AND school_id = ? AND status != 'rejected'",
                    (task_id, school_id),
                ).fetchall()
                if any(normalize_url(row["homepage"]) == normalized_homepage for row in rows):
                    reasons.append("duplicate_task_homepage")
        return reasons

    def record_api_call(
        self,
        task_id: str,
        *,
        operation: str,
        model: str,
        estimated_cost_usd: float,
        status: str,
        school_id: int | None = None,
        response_id: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        tool_calls: int = 0,
        error: str = "",
    ) -> None:
        now = _now()
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO api_calls(
                    task_id, school_id, operation, model, response_id, input_tokens,
                    output_tokens, tool_calls, estimated_cost_usd, status, error, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id, school_id, operation, model, response_id, input_tokens,
                    output_tokens, tool_calls, estimated_cost_usd, status, error, now,
                ),
            )
            connection.execute(
                "UPDATE tasks SET spent_usd = spent_usd + ?, updated_at = ? WHERE id = ?",
                (max(0.0, estimated_cost_usd), now, task_id),
            )

    def ai_usage_summary(self, since: datetime | None) -> sqlite3.Row:
        """Return aggregate API-call usage without altering recorded accounting."""
        where = ""
        params: tuple[str, ...] = ()
        if since is not None:
            where = "WHERE created_at >= ?"
            params = (since.isoformat(),)
        with closing(self.connect()) as connection:
            return connection.execute(
                f"""
                SELECT COUNT(*) AS calls,
                       COALESCE(SUM(status = 'succeeded'), 0) AS succeeded,
                       COALESCE(SUM(status != 'succeeded'), 0) AS failed,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd
                FROM api_calls {where}
                """,
                params,
            ).fetchone()

    def list_ai_usage(self, task_id: str | None, limit: int = 200) -> list[sqlite3.Row]:
        """Return the newest recorded API calls, optionally limited to one task."""
        if limit < 1:
            raise ValueError("limit must be at least 1")
        where = ""
        params: tuple[str | int, ...] = (limit,)
        if task_id is not None:
            where = "WHERE task_id = ?"
            params = (task_id, limit)
        with closing(self.connect()) as connection:
            return list(
                connection.execute(
                    f"SELECT * FROM api_calls {where} ORDER BY created_at DESC, id DESC LIMIT ?",
                    params,
                ).fetchall()
            )

    def set_budget(self, task_id: str, budget_usd: float) -> None:
        if budget_usd <= 0:
            raise ValueError("Budget must be greater than zero")
        task = self.get_task(task_id)
        status = "ready" if task["status"] == "paused_budget" else task["status"]
        self.update_task(task_id, budget_usd=budget_usd, status=status, warning="")

    def summary(self, task_id: str) -> dict[str, Any]:
        task = dict(self.get_task(task_id))
        with closing(self.connect()) as connection:
            school_counts = dict(
                connection.execute(
                    "SELECT status, COUNT(*) FROM schools WHERE task_id = ? GROUP BY status",
                    (task_id,),
                ).fetchall()
            )
            candidate_counts = dict(
                connection.execute(
                    "SELECT status, COUNT(*) FROM candidates WHERE task_id = ? GROUP BY status",
                    (task_id,),
                ).fetchall()
            )
            history_count = connection.execute(
                "SELECT COUNT(*) FROM historical_people WHERE task_id = ?", (task_id,)
            ).fetchone()[0]
        task.update(
            schools=school_counts,
            candidates=candidate_counts,
            historical_people=history_count,
        )
        return task

    def _update(
        self,
        table: str,
        row_id: str | int,
        values: dict[str, Any],
        allowed: set[str],
        *,
        timestamp: bool = True,
    ) -> None:
        unexpected = set(values) - allowed
        if unexpected:
            raise ValueError(f"Unexpected {table} fields: {sorted(unexpected)}")
        if not values:
            return
        if "status" in values:
            valid = TASK_STATUSES if table == "tasks" else SCHOOL_STATUSES if table == "schools" else CANDIDATE_STATUSES
            if values["status"] not in valid:
                raise ValueError(f"Invalid {table} status: {values['status']}")
        payload = dict(values)
        if timestamp:
            payload["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in payload)
        with self.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE {table} SET {assignments} WHERE id = ?",
                (*payload.values(), row_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Unknown {table} row: {row_id}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
