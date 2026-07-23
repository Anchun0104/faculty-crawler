from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class StaffClassification(str, Enum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    REVIEW = "review"


class AcademicTrack(str, Enum):
    TEACHING_AND_RESEARCH = "teaching_and_research"
    RESEARCH = "research"
    TEACHING = "teaching"
    CLINICAL = "clinical"
    PROFESSIONAL_PRACTICE = "professional_practice"
    VISITING = "visiting"
    ADJUNCT = "adjunct"
    POSTDOCTORAL = "postdoctoral"
    DOCTORAL_RESEARCHER = "doctoral_researcher"
    UNKNOWN = "unknown"


class AffiliationStatus(str, Enum):
    CURRENT = "current"
    VISITING = "visiting"
    ADJUNCT = "adjunct"
    INACTIVE_OR_HONORARY = "inactive_or_honorary"
    UNKNOWN = "unknown"


class ConfidenceTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class ClassificationResult:
    classification: StaffClassification
    academic_track: AcademicTrack = AcademicTrack.UNKNOWN
    affiliation_status: AffiliationStatus = AffiliationStatus.UNKNOWN
    reason: str = "no_rule_matched"
    matched_rule: str = ""
    confidence: ConfidenceTier = ConfidenceTier.LOW


def normalize_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()


RULES_VERSION = "2026.07.1"

STATUS_EXCLUSIONS = (
    "emeritus",
    "emerita",
    "honorary",
    "retired",
    "former",
)

STUDENT_AND_ASSISTANT_EXCLUSIONS = (
    "doctoral research assistant",
    "graduate research assistant",
    "graduate teaching assistant",
    "doctoral candidate",
    "doctoral student",
    "phd candidate",
    "phd student",
    "master's student",
    "masters student",
    "undergraduate student",
    "graduate student",
    "teaching assistant",
    "research assistant",
    "student researcher",
    "research intern",
)

PROFESSIONAL_STAFF_EXCLUSIONS = {
    "library_staff": (
        "scholarly communications librarian",
        "electronic resources librarian",
        "research data librarian",
        "academic librarian",
        "subject librarian",
        "faculty librarian",
        "reference librarian",
        "research librarian",
        "systems librarian",
        "digital librarian",
        "senior librarian",
        "library technician",
        "library officer",
        "library assistant",
        "library manager",
        "information librarian",
        "information resources officer",
        "repository manager",
        "repository officer",
        "collections manager",
        "collections officer",
        "archives officer",
        "records manager",
        "records officer",
        "librarian",
        "archivist",
        "cataloguer",
        "cataloging specialist",
        "open access officer",
    ),
    "it_staff": (
        "research software engineer",
        "scientific programmer",
        "research data scientist",
        "research data engineer",
        "research computing specialist",
        "computational specialist",
        "information technology technologist",
        "information systems officer",
        "business intelligence analyst",
        "it support specialist",
        "it support technician",
        "it technologist",
        "it technician",
        "it officer",
        "it support",
        "ict technician",
        "ict officer",
        "ict support",
        "systems administrator",
        "network administrator",
        "network engineer",
        "business systems analyst",
        "systems analyst",
        "database administrator",
        "application administrator",
        "application support analyst",
        "application support",
        "web administrator",
        "web developer",
        "software developer",
        "software engineer",
        "solutions architect",
        "infrastructure engineer",
        "cloud engineer",
        "cybersecurity analyst",
        "security analyst",
        "service desk analyst",
        "helpdesk technician",
        "computer technician",
        "digital services officer",
        "digital technology officer",
        "learning technologist",
        "educational technologist",
        "av technician",
        "multimedia technician",
        "business intelligence analyst",
        "data analyst",
        "data engineer",
        "bioinformatician",
        "biostatistician",
    ),
    "technical_staff": (
        "senior laboratory technician",
        "teaching laboratory technician",
        "laboratory technician",
        "lab technician",
        "research technician",
        "senior technical officer",
        "technical officer",
        "technical specialist",
        "technical manager",
        "laboratory manager",
        "lab manager",
        "core facility manager",
        "facility technician",
        "instrumentation technician",
        "equipment technician",
        "workshop technician",
        "electronics technician",
        "mechanical technician",
        "chemical technician",
        "scientific officer",
        "experimental officer",
        "animal care technician",
        "animal technician",
        "microscopy specialist",
        "imaging specialist",
        "histology technician",
        "sample processing technician",
        "field technician",
        "demonstration technician",
        "technical staff",
    ),
    "administrative_staff": (
        "senior administrative officer",
        "administrative assistant",
        "administrative officer",
        "department administrator",
        "faculty administrator",
        "school administrator",
        "program administrator",
        "programme administrator",
        "department manager",
        "faculty manager",
        "school manager",
        "operations manager",
        "operations officer",
        "business manager",
        "office manager",
        "executive officer",
        "executive assistant",
        "personal assistant",
        "department secretary",
        "faculty secretary",
        "project administrator",
        "project officer",
        "project manager",
        "programme manager",
        "program manager",
        "governance officer",
        "committee secretary",
        "administrator",
        "secretary",
        "receptionist",
        "clerical officer",
    ),
    "student_services_staff": (
        "international student advisor",
        "teaching administrator",
        "education administrator",
        "academic administrator",
        "course administrator",
        "program support officer",
        "programme support officer",
        "student services officer",
        "student support officer",
        "student experience officer",
        "academic services officer",
        "academic skills advisor",
        "academic advisor",
        "student advisor",
        "admissions officer",
        "admissions coordinator",
        "enrollment officer",
        "enrolment officer",
        "registry officer",
        "examinations officer",
        "timetable officer",
        "scheduling officer",
        "placement officer",
        "disability support officer",
        "learning support officer",
        "careers advisor",
        "career consultant",
        "student counsellor",
        "wellbeing officer",
    ),
    "finance_hr_legal_staff": (
        "people and culture advisor",
        "talent acquisition specialist",
        "human resources officer",
        "research finance officer",
        "human resources advisor",
        "recruitment officer",
        "management accountant",
        "procurement officer",
        "purchasing officer",
        "contracts officer",
        "contracts manager",
        "legal officer",
        "legal counsel",
        "compliance officer",
        "finance officer",
        "finance manager",
        "accounts officer",
        "budget officer",
        "payroll officer",
        "risk officer",
        "audit officer",
        "hr officer",
        "hr advisor",
        "accountant",
    ),
    "research_support_staff": (
        "research development officer",
        "research administration officer",
        "research administrator",
        "research support officer",
        "research grants officer",
        "grants administrator",
    ),
    "communications_staff": (
        "digital communications officer",
        "communications officer",
        "communications manager",
        "media relations officer",
        "public relations officer",
        "social media officer",
        "conference coordinator",
        "international partnerships officer",
        "strategic partnerships officer",
        "alumni relations officer",
        "donor relations officer",
        "external relations officer",
        "marketing officer",
        "marketing manager",
        "media officer",
        "press officer",
        "content officer",
        "content editor",
        "web content editor",
        "events officer",
        "events coordinator",
        "engagement officer",
        "outreach officer",
        "development officer",
        "fundraising officer",
        "partnerships officer",
        "publishing officer",
        "editorial assistant",
        "copy editor",
        "graphic designer",
        "photographer",
        "videographer",
    ),
    "facilities_staff": (
        "health and safety officer",
        "room booking officer",
        "facilities manager",
        "facilities officer",
        "property officer",
        "building manager",
        "maintenance officer",
        "security officer",
        "security guard",
        "groundskeeper",
        "stores officer",
        "logistics officer",
        "catering manager",
        "catering assistant",
        "accommodation officer",
        "estates officer",
        "caretaker",
        "cleaner",
        "porter",
        "driver",
        "storekeeper",
    ),
}

ACADEMIC_INCLUSIONS = (
    ("senior principal research fellow", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("professorial research fellow", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("principal research scientist", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("principal research fellow", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("senior research scientist", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("senior research fellow", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("postdoctoral research fellow", AcademicTrack.POSTDOCTORAL, AffiliationStatus.CURRENT),
    ("postdoctoral researcher", AcademicTrack.POSTDOCTORAL, AffiliationStatus.CURRENT),
    ("postdoctoral fellow", AcademicTrack.POSTDOCTORAL, AffiliationStatus.CURRENT),
    ("clinical associate professor", AcademicTrack.CLINICAL, AffiliationStatus.CURRENT),
    ("clinical assistant professor", AcademicTrack.CLINICAL, AffiliationStatus.CURRENT),
    ("associate teaching professor", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
    ("assistant teaching professor", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
    ("senior clinical lecturer", AcademicTrack.CLINICAL, AffiliationStatus.CURRENT),
    ("professor of practice", AcademicTrack.PROFESSIONAL_PRACTICE, AffiliationStatus.CURRENT),
    ("principal investigator", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("principal lecturer", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
    ("associate professor", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("assistant professor", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("distinguished professor", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("university professor", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("research professor", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("teaching professor", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
    ("clinical professor", AcademicTrack.CLINICAL, AffiliationStatus.CURRENT),
    ("visiting professor", AcademicTrack.VISITING, AffiliationStatus.VISITING),
    ("adjunct professor", AcademicTrack.ADJUNCT, AffiliationStatus.ADJUNCT),
    ("affiliate professor", AcademicTrack.ADJUNCT, AffiliationStatus.ADJUNCT),
    ("senior lecturer", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("associate lecturer", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
    ("university lecturer", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("college lecturer", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
    ("clinical lecturer", AcademicTrack.CLINICAL, AffiliationStatus.CURRENT),
    ("senior teaching fellow", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
    ("teaching fellow", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
    ("research scientist", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("research fellow", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("research associate", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("doctoral researcher", AcademicTrack.DOCTORAL_RESEARCHER, AffiliationStatus.CURRENT),
    ("clinical educator", AcademicTrack.CLINICAL, AffiliationStatus.CURRENT),
    ("clinical teacher", AcademicTrack.CLINICAL, AffiliationStatus.CURRENT),
    ("maître de conférences", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("professeur des universités", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("universitair hoofddocent", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("universitair docent", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("privatdozent", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("juniorprofessor", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("hochschuldozent", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("universitätsprofessor", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("professore ordinario", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("professore associato", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("professor catedrático", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("professor associado", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("professor auxiliar", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("professor adjunto", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("profesor titular", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("profesora titular", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("profesor asociado", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("profesora asociada", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("profesor asistente", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("profesora asistente", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("profesor auxiliar", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("profesora auxiliar", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("catedrático", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("catedrática", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("catedràtic", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("catedràtica", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("أستاذ مشارك", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("أستاذ مساعد", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("محاضر أول", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
    ("باحث مشارك", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("باحث رئيسي", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("أستاذ زائر", AcademicTrack.VISITING, AffiliationStatus.VISITING),
    ("أستاذ ممارس", AcademicTrack.PROFESSIONAL_PRACTICE, AffiliationStatus.CURRENT),
    ("عضو هيئة تدريس", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("full professor", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("chair professor", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("professor", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("senior instructor", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
    ("instructor", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
    ("lecturer", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("reader", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("professore", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("ricercatore", AcademicTrack.RESEARCH, AffiliationStatus.CURRENT),
    ("hoogleraar", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("docent", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("docente", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("أستاذ", AcademicTrack.TEACHING_AND_RESEARCH, AffiliationStatus.CURRENT),
    ("محاضر", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
    ("مدرس", AcademicTrack.TEACHING, AffiliationStatus.CURRENT),
)

AMBIGUOUS_TITLES = (
    "consultant cardiologist",
    "consultant physician",
    "consultant surgeon",
    "medical specialist",
    "program coordinator",
    "programme coordinator",
    "group leader",
    "faculty member",
    "researcher",
    "director",
    "coordinator",
    "tutor",
    "demonstrator",
    "chair",
    "dean",
    "fellow",
    "scholar",
    "scientist",
    "academic",
    "consultant",
    "clinician",
    "psychologist",
    "therapist",
    "pharmacist",
    "nurse",
    "dietitian",
)


def _contains_phrase(title: str, phrase: str) -> bool:
    pattern = rf"(?<!\w){re.escape(phrase)}(?!\w)"
    return re.search(pattern, title, flags=re.IGNORECASE) is not None


def _excluded(category: str, phrase: str) -> ClassificationResult:
    affiliation = (
        AffiliationStatus.INACTIVE_OR_HONORARY
        if category == "inactive_or_honorary"
        else AffiliationStatus.UNKNOWN
    )
    return ClassificationResult(
        classification=StaffClassification.EXCLUDE,
        affiliation_status=affiliation,
        reason=f"{category}:{phrase}",
        matched_rule=phrase,
        confidence=ConfidenceTier.HIGH,
    )


class TitleClassifier:
    def classify(self, value: str, *, translated: bool = False) -> ClassificationResult:
        title = normalize_title(value)
        if not title:
            return ClassificationResult(
                classification=StaffClassification.REVIEW,
                reason="missing_title",
            )

        folded = title.casefold()
        for phrase in STATUS_EXCLUSIONS:
            if _contains_phrase(folded, phrase):
                return _excluded("inactive_or_honorary", phrase)

        for phrase in STUDENT_AND_ASSISTANT_EXCLUSIONS:
            if _contains_phrase(folded, phrase):
                return _excluded("student_or_assistant", phrase)

        professional_phrases = (
            (category, phrase)
            for category, phrases in PROFESSIONAL_STAFF_EXCLUSIONS.items()
            for phrase in phrases
        )
        for category, phrase in sorted(
            professional_phrases,
            key=lambda item: len(item[1]),
            reverse=True,
        ):
            if _contains_phrase(folded, phrase):
                return _excluded(category, phrase)

        for phrase, track, status in ACADEMIC_INCLUSIONS:
            if _contains_phrase(folded, phrase):
                return ClassificationResult(
                    classification=StaffClassification.INCLUDE,
                    academic_track=track,
                    affiliation_status=status,
                    reason=f"academic_phrase:{phrase}",
                    matched_rule=phrase,
                    confidence=ConfidenceTier.MEDIUM if translated else ConfidenceTier.HIGH,
                )

        for phrase in AMBIGUOUS_TITLES:
            if _contains_phrase(folded, phrase):
                return ClassificationResult(
                    classification=StaffClassification.REVIEW,
                    reason=f"ambiguous_phrase:{phrase}",
                    matched_rule=phrase,
                    confidence=ConfidenceTier.LOW,
                )

        return ClassificationResult(classification=StaffClassification.REVIEW)

