from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from faculty_workflow.database import WorkflowDatabase
from faculty_workflow.models import CandidateExtraction, DisciplinePolicy, normalize_key


EMAIL_RE = re.compile(r"^[A-Z0-9._%+'-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
GENERIC_EMAIL_LOCAL_PARTS = {
    "admin", "admissions", "advising", "communications", "contact", "dean", "department",
    "enquiries", "enquiry", "faculty", "help", "info", "media", "office", "press",
    "school", "secretariat", "support", "tiedotus", "webmaster",
    "firstname.lastname", "name.surname", "nombre.apellido", "usuario", "user",
}
NON_PERSON_NAME_MARKERS = (
    "cookie", "privacy", "navigation", "site search", "read more", "view abstract",
    "contact information", "opening hours",
)
REQUIRED_EVIDENCE_FIELDS = {"name", "email", "title"}


@dataclass(frozen=True)
class QualityDecision:
    status: str
    reasons: tuple[str, ...]


def evaluate_candidate(
    database: WorkflowDatabase,
    task_id: str,
    school_id: int,
    school_name: str,
    extraction: CandidateExtraction,
    policy: DisciplinePolicy,
    official_domain: str = "",
) -> QualityDecision:
    reasons: list[str] = []
    required_values = {
        "name": extraction.name,
        "email": extraction.email,
    }
    reasons.extend(f"missing_{field}" for field, value in required_values.items() if not value)

    if extraction.name and _is_non_person_name(extraction.name):
        reasons.append("invalid_person_name")

    if extraction.email:
        if not EMAIL_RE.fullmatch(extraction.email):
            reasons.append("invalid_email")
        elif extraction.email.split("@", 1)[0].casefold() in GENERIC_EMAIL_LOCAL_PARTS:
            reasons.append("generic_email")
        elif official_domain and not _email_on_official_domain(extraction.email, official_domain):
            reasons.append("email_domain_not_official")
    if extraction.email_ownership != "verified":
        reasons.append(f"email_ownership_{extraction.email_ownership}")
    if not extraction.official_source:
        reasons.append("source_not_official")
    if not extraction.normalized_title:
        reasons.append("missing_included_academic_role")
    elif extraction.normalized_title not in policy.allowed_titles:
        reasons.append("academic_role_outside_policy")

    supported_fields = {
        normalize_key(item.field)
        for item in extraction.evidence
        if item.quote and item.source_url and item.status == "supported"
    }
    for required in REQUIRED_EVIDENCE_FIELDS:
        if normalize_key(required) not in supported_fields:
            reasons.append(f"missing_evidence_{required}")

    reasons.extend(
        database.duplicate_reasons(
            task_id,
            school_id=school_id,
            name=extraction.name,
            school=school_name,
            email=extraction.email,
            homepage=extraction.homepage,
        )
    )
    reasons.extend(reason for reason in extraction.failure_reasons if reason == "profile_fetch_failed")
    unique_reasons = tuple(dict.fromkeys(reason for reason in reasons if reason))
    if "invalid_person_name" in unique_reasons or any(reason.startswith("duplicate_") for reason in unique_reasons):
        return QualityDecision("rejected", unique_reasons)
    if unique_reasons:
        return QualityDecision("review", unique_reasons)
    return QualityDecision("accepted", ())


def _email_on_official_domain(email: str, official_domain: str) -> bool:
    domain = (official_domain or "").strip().casefold().lstrip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    email_domain = email.rsplit("@", 1)[-1].casefold()
    return bool(
        domain
        and (
            email_domain == domain
            or email_domain.endswith("." + domain)
            or domain.endswith("." + email_domain)
        )
    )


def _is_non_person_name(name: str) -> bool:
    value = " ".join((name or "").casefold().split())
    return "?" in value or any(marker in value for marker in NON_PERSON_NAME_MARKERS)
