from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse


DEFAULT_ALLOWED_TITLES = (
    "Professor",
    "Associate Professor",
    "Assistant Professor",
    "Reader",
    "Lecturer",
    "Senior Lecturer",
    "Postdoctoral Researcher",
    "Researcher",
    "Senior Researcher",
    "Staff Scientist",
)
TASK_STATUSES = {
    "needs_policy_confirmation",
    "ready",
    "running",
    "paused_budget",
    "completed",
    "failed",
}
SCHOOL_STATUSES = {
    "pending",
    "discovering",
    "crawling",
    "extracting",
    "review",
    "completed",
    "failed",
    "skipped_processed",
    "blocked_robots",
    "blocked_access",
}
CANDIDATE_STATUSES = {"candidate", "accepted", "review", "rejected"}


@dataclass(frozen=True)
class DisciplinePolicy:
    discipline: str
    include_topics: tuple[str, ...]
    exclude_topics: tuple[str, ...]
    allowed_titles: tuple[str, ...] = DEFAULT_ALLOWED_TITLES
    title_mappings: dict[str, str] = field(default_factory=dict)
    prompt_version: str = "discipline-policy-v1"

    def __post_init__(self) -> None:
        if not self.discipline.strip():
            raise ValueError("Discipline must not be empty")
        if not self.include_topics:
            raise ValueError("At least one included topic is required")
        if not self.allowed_titles:
            raise ValueError("At least one allowed title is required")

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, value: str | dict[str, Any]) -> "DisciplinePolicy":
        raw = json.loads(value) if isinstance(value, str) else dict(value)
        allowed = {
            "discipline",
            "include_topics",
            "exclude_topics",
            "allowed_titles",
            "title_mappings",
            "prompt_version",
        }
        unexpected = set(raw) - allowed
        if unexpected:
            raise ValueError(f"Unexpected policy fields: {sorted(unexpected)}")
        return cls(
            discipline=str(raw.get("discipline", "")).strip(),
            include_topics=_string_tuple(raw.get("include_topics")),
            exclude_topics=_string_tuple(raw.get("exclude_topics")),
            allowed_titles=_string_tuple(raw.get("allowed_titles")) or DEFAULT_ALLOWED_TITLES,
            title_mappings={str(k): str(v) for k, v in dict(raw.get("title_mappings") or {}).items()},
            prompt_version=str(raw.get("prompt_version") or "discipline-policy-v1"),
        )


@dataclass(frozen=True)
class SchoolInput:
    name: str
    original_row: str = ""
    official_domain: str = ""
    directory_url: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("School name must not be empty")
        if self.directory_url and not is_http_url(self.directory_url):
            raise ValueError(f"Invalid directory URL: {self.directory_url}")


@dataclass(frozen=True)
class Evidence:
    field: str
    quote: str
    source_url: str
    extraction_method: str = "model"
    status: str = "supported"

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "Evidence":
        allowed = {"field", "quote", "source_url", "extraction_method", "status"}
        unexpected = set(value) - allowed
        if unexpected:
            raise ValueError(f"Unexpected evidence fields: {sorted(unexpected)}")
        missing = allowed - set(value)
        if missing:
            raise ValueError(f"Missing evidence fields: {sorted(missing)}")
        return cls(
            field=str(value.get("field", "")).strip(),
            quote=str(value.get("quote", "")).strip(),
            source_url=str(value.get("source_url", "")).strip(),
            extraction_method=str(value.get("extraction_method") or "model"),
            status=str(value.get("status") or "supported"),
        )


@dataclass(frozen=True)
class CandidateExtraction:
    name: str = ""
    email: str = ""
    last_name: str = ""
    title_raw: str = ""
    normalized_title: str = ""
    title_translated: str = ""
    title_language: str = ""
    translation_status: str = "not_needed"
    translation_engine: str = ""
    classification_rules_version: str = ""
    department: str = ""
    homepage: str = ""
    professional_relevance: str = "uncertain"
    email_ownership: str = "uncertain"
    homepage_identity: str = "uncertain"
    official_source: bool = False
    group_homepage: bool = False
    evidence: tuple[Evidence, ...] = ()
    failure_reasons: tuple[str, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "CandidateExtraction":
        allowed = {
            "name",
            "email",
            "last_name",
            "title_raw",
            "normalized_title",
            "title_translated",
            "title_language",
            "translation_status",
            "translation_engine",
            "classification_rules_version",
            "department",
            "homepage",
            "professional_relevance",
            "email_ownership",
            "homepage_identity",
            "official_source",
            "group_homepage",
            "evidence",
            "failure_reasons",
        }
        unexpected = set(value) - allowed
        if unexpected:
            raise ValueError(f"Unexpected extraction fields: {sorted(unexpected)}")
        optional = {
            "title_translated",
            "title_language",
            "translation_status",
            "translation_engine",
            "classification_rules_version",
        }
        missing = (allowed - optional) - set(value)
        if missing:
            raise ValueError(f"Missing extraction fields: {sorted(missing)}")
        evidence = tuple(Evidence.from_mapping(dict(item)) for item in value.get("evidence") or [])
        return cls(
            name=_clean(value.get("name")),
            email=_clean(value.get("email")).lower(),
            last_name=_clean(value.get("last_name")),
            title_raw=_clean(value.get("title_raw")),
            normalized_title=_clean(value.get("normalized_title")),
            title_translated=_clean(value.get("title_translated")),
            title_language=_clean(value.get("title_language")),
            translation_status=_clean(value.get("translation_status")) or "not_needed",
            translation_engine=_clean(value.get("translation_engine")),
            classification_rules_version=_clean(value.get("classification_rules_version")),
            department=_clean(value.get("department")),
            homepage=_clean(value.get("homepage")),
            professional_relevance=str(value.get("professional_relevance") or "uncertain"),
            email_ownership=str(value.get("email_ownership") or "uncertain"),
            homepage_identity=str(value.get("homepage_identity") or "uncertain"),
            official_source=bool(value.get("official_source", False)),
            group_homepage=bool(value.get("group_homepage", False)),
            evidence=evidence,
            failure_reasons=_string_tuple(value.get("failure_reasons")),
        )

    def evidence_json(self) -> str:
        return json.dumps([asdict(item) for item in self.evidence], ensure_ascii=False)


def normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", normalized.casefold())


def normalize_email(value: str) -> str:
    return (value or "").strip().casefold()


def normalize_url(value: str) -> str:
    parsed = urlparse((value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        fragment="",
    ).geturl().rstrip("/")


def normalize_profile_identity(value: str) -> str:
    normalized = normalize_url(value)
    if not normalized:
        return ""
    parsed = urlparse(normalized)
    query = urlencode(sorted(
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in {"fbclid", "gclid"}
    ))
    return parsed._replace(query=query).geturl().rstrip("/")


def is_http_url(value: str) -> bool:
    return bool(normalize_url(value))


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.splitlines() if item.strip())
    return tuple(str(item).strip() for item in value if str(item).strip())


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()
