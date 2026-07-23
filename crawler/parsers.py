from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from collections import Counter
from typing import Iterable
from urllib.parse import parse_qs, parse_qsl, quote, urlencode, urljoin, urlparse


@dataclass(frozen=True)
class FacultyRecord:
    name: str
    title: str
    profile_url: str
    email: str = ""


@dataclass(frozen=True)
class TitlePendingRecord:
    name: str
    directory_title: str
    profile_url: str
    section: str
    source_url: str
    pending_reason: str
    email: str = ""
    next_action: str = "extract_title_from_profile"
    status: str = "pending"


@dataclass(frozen=True)
class ParseResult:
    records: list[FacultyRecord]
    page_type: str
    candidate_count: int
    parsed_count: int
    failure_stage: str
    possible_person_link_count: int = 0
    fallback_person_links_count: int = 0
    fallback_candidates_count: int = 0
    fallback_link_debug: list[dict[str, object]] = field(default_factory=list)
    heading_person_candidates_count: int = 0
    heading_records_parsed: int = 0
    recovered_profile_links_count: int = 0
    heading_person_link_debug: list[dict[str, object]] = field(default_factory=list)
    cards_missing_profile_url_count: int = 0
    card_recovered_profile_links_count: int = 0
    card_profile_link_debug: list[dict[str, object]] = field(default_factory=list)
    table_rows_detected: int = 0
    table_rows_parsed: int = 0
    dropped_candidate_debug: list[dict[str, object]] = field(default_factory=list)
    table_headers_debug: list[str] = field(default_factory=list)
    section_headings_debug: list[str] = field(default_factory=list)
    href_patterns_debug: list[str] = field(default_factory=list)
    heading_card_candidates_count: int = 0
    generic_profile_links_count: int = 0
    heading_card_debug: list[dict[str, object]] = field(default_factory=list)
    role_group_count: int = 0
    person_rows_detected: int = 0
    role_group_debug: list[dict[str, object]] = field(default_factory=list)
    faculty_profile_links_detected: int = 0
    unique_profile_links_count: int = 0
    local_person_blocks_created: int = 0
    duplicate_profile_links_count: int = 0
    excluded_section_count: int = 0
    wrapper_person_links_count: int = 0
    segmented_person_blocks_count: int = 0
    segmented_person_debug: list[dict[str, object]] = field(default_factory=list)
    segmented_academic_section_count: int = 0
    segmented_administrative_exclusion_count: int = 0
    segmented_emeritus_exclusion_count: int = 0
    ancestor_profile_links_recovered_count: int = 0
    same_block_partial_records_merged_count: int = 0
    flattened_name_title_split_count: int = 0
    unresolved_cards_missing_profile_url_count: int = 0
    title_pending_records: list[TitlePendingRecord] = field(default_factory=list)


@dataclass(frozen=True)
class _CardProfileRecovery:
    url: str = ""
    profile_search_scope: str = ""
    scanned_sibling_count: int = 0
    stop_boundary: str = ""
    reject_reason: str = ""


TITLE_KEYWORDS = (
    "professor",
    "reader",
    "lecturer",
    "university teacher",
    "teaching fellow",
    "postdoctoral fellow",
    "phd candidate",
    "research fellow",
    "research associate",
    "instructor",
    "educator",
    "dean",
    "chair",
    "research scientist",
    "scientist",
    "faculty",
    "principal investigator",
    "docente",
    "professore",
    "ricercatore",
    "insegnamento",
    "associate",
    "assistant",
    "emeritus",
    "emerita",
    "catedràtic",
    "catedràtica",
    "titular",
    "investigador",
    "investigadora",
)

COMPACT_TITLE_PATTERNS = (
    "Research Assistant Professor",
    "Post-Doctoral Fellow",
    "Associate Professor",
    "Assistant Professor",
    "Principal Lecturer",
    "Senior Lecturer",
    "Honorary Professor",
    "Emeritus Professor",
    "Adjunct Assistant Professor",
    "Adjunct Professor",
    "Lecturer",
    "Professor",
)
PREFIX_TITLE_PATTERNS = {
    "prof.": "Prof.",
    "dr.": "Dr.",
}

PROFILE_PATH_HINTS = (
    "people",
    "person",
    "profile",
    "profs",
    "faculty",
    "staff",
    "academic-staff",
    "academic_staff",
    "directory",
    "employees",
)

SKIP_TAGS = {"nav", "footer", "script", "style", "noscript", "header"}
CONTAINER_TAGS = {"article", "li", "div", "section", "tr"}
CONTAINER_HINTS = ("person", "people", "faculty", "profile", "card", "member", "team")
SKIP_CONTAINER_HINTS = (
    "nav",
    "menu",
    "footer",
    "header",
    "search",
    "filter",
    "breadcrumb",
    "metadata",
    "sidebar",
)
DIRECTORY_HINTS = ("faculty", "people", "staff", "academic", "professors", "directory")
GENERIC_LINK_WORDS = {
    "contact",
    "detail",
    "faculty",
    "faculty experts guide",
    "homepage",
    "main navigation",
    "more",
    "more details",
    "personal page",
    "people directory",
    "directory",
    "profile",
    "perfil",
    "profile detail",
    "read more",
    "read profile",
    "ver perfil",
    "view profile",
    "web page",
    "personal website",
    "website",
}
NON_NAME_WORDS = {
    "about",
    "contact",
    "privacy",
    "policy",
    "home",
    "directory",
    "faculty",
    "staff",
    "research",
    "education",
    "search",
    "people",
    "website",
    "personal",
    "main",
    "navigation",
}

ACCORDION_UTILITY_LABELS = {
    "contact",
    "office hours",
    "responsibilities",
    "write an e-mail",
    "write an email",
    "website",
    "details",
    "to the publication list",
}

FACULTY_CATEGORY_LABELS = {
    "acting chairs",
    "associate professors",
    "civil law",
    "criminal law",
    "emeriti",
    "honorary professors",
    "lecturers",
    "professors",
    "public law",
    "senior professors",
    "visiting professors",
}

NEUTRAL_DIRECTORY_SECTIONS = {
    "staff",
    "our staff",
    "people",
    "directory",
    "faculty and staff",
    "all faculty & staff",
    "all faculty and staff",
}

EXCLUDED_DIRECTORY_SECTIONS = {
    "administrative staff",
    "administration",
    "professional services staff",
    "professional staff",
    "support staff",
    "operations staff",
    "technical staff",
    "emeritus faculty",
    "retired faculty",
}

ACADEMIC_TITLE_PATTERNS = (
    "professor",
    "reader",
    "lecturer",
    "university teacher",
    "teaching fellow",
    "postdoctoral fellow",
    "phd candidate",
    "research fellow",
    "research associate",
    "instructor",
    "educator",
    "dean",
    "chair",
    "research scientist",
    "scientist",
    "principal investigator",
    "docente",
    "professore",
    "ricercatore",
    "insegnamento",
    "profesor asociado",
    "profesora asociada",
    "profesor asistente",
    "profesora asistente",
    "profesor titular",
    "profesora titular",
    "profesor auxiliar",
    "profesora auxiliar",
    "privatdozent",
    "catedràtic",
    "catedràtica",
    "titular d'universitat",
    "titular d'escola universitària",
    "investigador",
    "investigadora",
)

SPANISH_ACADEMIC_TITLE_SUFFIXES = (
    "Profesor asociado",
    "Profesora asociada",
    "Profesor asistente",
    "Profesora asistente",
    "Profesor titular",
    "Profesora titular",
    "Profesor auxiliar",
    "Profesora auxiliar",
)

NON_ACADEMIC_TITLE_WORDS = ("administrator", "coordinator", "officer", "assistant", "manager", "secretary")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


class _Node:
    def __init__(self, tag: str, attrs: dict[str, str], parent: _Node | None = None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_Node] = []
        self.text_parts: list[str] = []
        self.content_parts: list[str | _Node] = []

    def add_text(self, text: str) -> None:
        cleaned = normalize_space(text)
        if cleaned:
            self.text_parts.append(cleaned)
            self.content_parts.append(cleaned)

    def text(self) -> str:
        parts = list(self.text_parts)
        for child in self.children:
            child_text = child.text()
            if child_text:
                parts.append(child_text)
        return normalize_space(" ".join(parts))

    def attr_text(self, name: str) -> str:
        return self.attrs.get(name, "")

    def ancestors(self) -> Iterable[_Node]:
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def descendants(self) -> Iterable[_Node]:
        for child in self.children:
            yield child
            yield from child.descendants()

    def text_chunks(self) -> list[str]:
        chunks = list(self.text_parts)
        for child in self.children:
            chunks.extend(child.text_chunks())
        return [normalize_space(chunk) for chunk in chunks if normalize_space(chunk)]


class _FacultyHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self.current = self.root
        self.links: list[_Node] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.lower(), {key.lower(): value or "" for key, value in attrs}, self.current)
        self.current.children.append(node)
        self.current.content_parts.append(node)
        self.current = node
        if node.tag == "a" and node.attr_text("href"):
            self.links.append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data: str) -> None:
        self.current.add_text(data)


def parse_faculty_members(html: str, base_url: str) -> list[FacultyRecord]:
    return parse_faculty_page(html, base_url).records


def normalized_person_profile_urls(html: str, base_url: str) -> set[str]:
    parser = _FacultyHTMLParser()
    parser.feed(html)
    return _possible_person_profile_urls(parser.root, base_url)


def parse_faculty_page(html: str, base_url: str) -> ParseResult:
    parser = _FacultyHTMLParser()
    parser.feed(html)

    records: list[FacultyRecord] = []
    dropped_candidate_debug: list[dict[str, object]] = []
    faculty_table_rows = _find_faculty_like_table_rows(parser.root)
    faculty_table_row_ids = {id(row) for row in faculty_table_rows}
    linked_person_containers = [
        container
        for container in _find_faculty_containers(parser.root, base_url)
        if id(container) not in faculty_table_row_ids
        and not any(id(ancestor) in faculty_table_row_ids for ancestor in container.ancestors())
    ]
    containers = [*faculty_table_rows, *linked_person_containers]
    possible_person_link_count = _possible_person_link_count(parser.root, base_url)
    fallback_person_links_count = 0
    fallback_candidates_count = 0
    fallback_link_debug: list[dict[str, object]] = []
    heading_person_candidates_count = 0
    heading_records: list[FacultyRecord] = []
    recovered_profile_links_count = 0
    heading_person_link_debug: list[dict[str, object]] = []
    cards_missing_profile_url_count = 0
    card_recovered_profile_links_count = 0
    card_profile_link_debug: list[dict[str, object]] = []
    ancestor_profile_links_recovered_count = 0
    same_block_partial_records_merged_count = 0
    unresolved_cards_missing_profile_url_count = 0
    table_rows_parsed = 0
    for container in containers:
        if _is_inside_skipped_region(container) or _is_skipped_container(container):
            continue

        is_faculty_table_row = id(container) in faculty_table_row_ids
        card_profile_url_was_missing = False
        card_debug_name = ""
        card_recovery = _CardProfileRecovery()
        if is_faculty_table_row:
            record = _record_from_faculty_like_table_row(container, base_url, _table_context_title_from_root(parser.root))
        else:
            local_name = _extract_name(container)
            heading_name = ""
            heading_profile_url = ""
            if not local_name or _name_matches_organizational_link(container, local_name, base_url):
                _, heading_name, heading_profile_url = _bounded_card_person_heading_identity(container, base_url)
            card_debug_name = heading_name or local_name
            card_debug_title = _extract_title(container, card_debug_name) if card_debug_name else ""
            direct_profile_url = heading_profile_url or _extract_descendant_profile_url(container, base_url)
            ancestor_profile_url = _ancestor_profile_url(container, base_url)
            if card_debug_name and card_debug_title and not direct_profile_url and ancestor_profile_url:
                ancestor_profile_links_recovered_count += 1
            card_profile_url_was_missing = bool(card_debug_name and card_debug_title and not direct_profile_url)
            if card_profile_url_was_missing:
                cards_missing_profile_url_count += 1
                if ancestor_profile_url:
                    card_recovery = _CardProfileRecovery(
                        url=ancestor_profile_url,
                        profile_search_scope="ancestor_anchor",
                    )
                else:
                    card_recovery = _recover_card_profile(container, base_url, card_debug_name)
            record = _record_from_container(
                container,
                base_url,
                preferred_name=heading_name,
                preferred_profile_url=heading_profile_url,
            )
        if record is None:
            if card_profile_url_was_missing and not card_recovery.url:
                unresolved_cards_missing_profile_url_count += 1
            if card_profile_url_was_missing and len(card_profile_link_debug) < 5:
                card_profile_link_debug.append(
                    {
                        "extracted_name": card_debug_name,
                        "recovered_url": "",
                        "link_text": _card_profile_link_text(container, base_url),
                        "drop_reason": "missing_profile_url",
                        "profile_search_scope": card_recovery.profile_search_scope,
                        "scanned_sibling_count": card_recovery.scanned_sibling_count,
                        "stop_boundary": card_recovery.stop_boundary,
                        "reject_reason": card_recovery.reject_reason,
                    }
                )
            if len(dropped_candidate_debug) < 10:
                dropped_candidate_debug.append(_candidate_debug(container, base_url))
            continue

        records.append(record)
        if is_faculty_table_row:
            table_rows_parsed += 1
        elif card_profile_url_was_missing:
            if card_recovery.profile_search_scope != "ancestor_anchor":
                card_recovered_profile_links_count += 1
                same_block_partial_records_merged_count += 1
            if len(card_profile_link_debug) < 5:
                card_profile_link_debug.append(
                    {
                        "extracted_name": record.name,
                        "recovered_url": record.profile_url,
                        "link_text": _card_profile_link_text(container, base_url, record.profile_url),
                        "drop_reason": "ok",
                        "profile_search_scope": card_recovery.profile_search_scope,
                        "scanned_sibling_count": card_recovery.scanned_sibling_count,
                        "stop_boundary": card_recovery.stop_boundary,
                        "reject_reason": card_recovery.reject_reason,
                    }
                )

    unique_records = remove_duplicates(records)
    candidate_count = len(containers)
    accordion_records, accordion_candidate_count, accordion_profile_urls = _recover_accordion_person_records(
        parser.root, base_url
    )
    segmented_wrapper_used = False
    if not faculty_table_rows:
        strong_profile_records = _strong_stref_profile_records(parser.root, base_url)
        if strong_profile_records:
            unique_records = remove_duplicates([*strong_profile_records, *unique_records])
            candidate_count = max(candidate_count, len(unique_records))
        for item in _strong_stref_rejection_debug(parser.root, base_url):
            if len(dropped_candidate_debug) >= 10:
                break
            dropped_candidate_debug.append(item)
    heading_card_candidates_count = 0
    generic_profile_links_count = 0
    heading_card_debug: list[dict[str, object]] = []
    role_group_records, role_group_count, person_rows_detected, role_group_debug = _recover_role_group_records(
        parser.root, base_url
    )
    if role_group_records:
        unique_records = remove_duplicates([*role_group_records, *unique_records])
        candidate_count = max(candidate_count, person_rows_detected)
    (
        repeated_faculty_records,
        faculty_profile_links_detected,
        unique_profile_links_count,
        local_person_blocks_created,
        duplicate_profile_links_count,
        excluded_section_count,
    ) = _recover_repeated_listing_subpage_records(parser.root, base_url)
    if repeated_faculty_records:
        unique_records = remove_duplicates([*repeated_faculty_records, *unique_records])
        candidate_count = max(candidate_count, local_person_blocks_created)
    (
        segmented_records,
        wrapper_person_links_count,
        segmented_person_blocks_count,
        segmented_person_debug,
        segmented_academic_section_count,
        segmented_administrative_exclusion_count,
        segmented_emeritus_exclusion_count,
        flattened_name_title_split_count,
    ) = (
        _recover_segmented_wrapper_records(parser.root, base_url)
    )
    professorship_records, professorship_candidates_count, professorship_debug = (
        _recover_professorship_linked_name_records(parser.root, base_url)
    )
    professorship_layout_used = professorship_candidates_count >= 2
    if professorship_layout_used:
        segmented_records = professorship_records
        wrapper_person_links_count = professorship_candidates_count
        segmented_person_blocks_count = professorship_candidates_count
        segmented_person_debug = professorship_debug
    if wrapper_person_links_count >= 10:
        candidate_count = max(candidate_count, segmented_person_blocks_count)
    low_segmented_coverage = wrapper_person_links_count >= 10 and len(unique_records) <= max(1, wrapper_person_links_count // 2)
    if (
        wrapper_person_links_count >= 10
        and not faculty_table_rows
        and not repeated_faculty_records
        and (len(containers) <= 1 or low_segmented_coverage or professorship_layout_used)
    ):
        if segmented_records:
            unique_records = remove_duplicates(segmented_records)
            candidate_count = segmented_person_blocks_count
            segmented_wrapper_used = True
    if not containers or not unique_records:
        heading_card_records, heading_card_candidates_count, generic_profile_links_count, heading_card_debug = (
            _recover_heading_card_records(parser.root, base_url)
        )
        if heading_card_candidates_count:
            unique_records = remove_duplicates([*heading_card_records, *unique_records])
            candidate_count = max(candidate_count, heading_card_candidates_count)
    if not faculty_table_rows and not unique_records:
        linked_teaser_records, linked_teaser_candidates_count, linked_teaser_debug = (
            _recover_repeated_linked_teaser_records(parser.root, base_url)
        )
        if linked_teaser_candidates_count:
            unique_records = remove_duplicates(linked_teaser_records)
            candidate_count = linked_teaser_candidates_count
            fallback_person_links_count = linked_teaser_candidates_count
            fallback_candidates_count = linked_teaser_candidates_count
            fallback_link_debug = linked_teaser_debug

    if not faculty_table_rows and not unique_records:
        section_name_records, section_name_candidates_count, section_name_debug = (
            _recover_academic_section_name_link_records(parser.root, base_url)
        )
        if section_name_candidates_count:
            unique_records = section_name_records
            candidate_count = section_name_candidates_count
            fallback_person_links_count = section_name_candidates_count
            fallback_candidates_count = section_name_candidates_count
            fallback_link_debug = section_name_debug

    if not faculty_table_rows and not unique_records:
        embedded_records, embedded_candidates_count, embedded_debug = (
            _recover_embedded_filtered_staff_records(html, base_url)
        )
        if embedded_candidates_count:
            unique_records = remove_duplicates(embedded_records)
            candidate_count = embedded_candidates_count
            fallback_person_links_count = embedded_candidates_count
            fallback_candidates_count = embedded_candidates_count
            fallback_link_debug = embedded_debug

    if not faculty_table_rows and not unique_records:
        if not containers:
            fallback_person_records, fallback_candidates_count, fallback_link_debug = _fallback_repeated_person_link_records(parser.root, base_url)
            fallback_person_links_count = fallback_candidates_count
            if fallback_candidates_count:
                unique_records = remove_duplicates(fallback_person_records)
                candidate_count = fallback_candidates_count
        if not unique_records:
            heading_records, heading_person_candidates_count, recovered_profile_links_count, heading_person_link_debug = _recover_heading_person_records(parser.root, base_url)
            if heading_person_candidates_count:
                unique_records = remove_duplicates(heading_records)
                candidate_count = heading_person_candidates_count

    if not faculty_table_rows and not segmented_wrapper_used and len(unique_records) < 10:
        fallback_records = _fallback_profile_link_records(parser.root, base_url)
        unique_fallback_records = remove_duplicates(fallback_records)
        strong_fallback_records = [
            record for record in unique_fallback_records if _is_strong_stref_profile_url(record.profile_url, base_url)
        ]
        other_fallback_records = [
            record for record in unique_fallback_records if not _is_strong_stref_profile_url(record.profile_url, base_url)
        ]
        if strong_fallback_records:
            unique_records = remove_duplicates([*strong_fallback_records, *unique_records, *other_fallback_records])
            candidate_count = max(candidate_count, len(unique_records))
        elif len(unique_fallback_records) > len(unique_records) and _fallback_quality_ok(unique_fallback_records):
            unique_records = unique_fallback_records
            candidate_count = max(candidate_count, len(unique_records))
        else:
            unique_records = remove_duplicates([*unique_records, *unique_fallback_records])
    if accordion_candidate_count:
        unique_records = remove_duplicates(
            [
                *accordion_records,
                *(
                    record
                    for record in unique_records
                    if _normalize_record_profile_url(record.profile_url) not in accordion_profile_urls
                ),
            ]
        )
        candidate_count = max(candidate_count, accordion_candidate_count)
    complete_profile_urls = {
        _normalize_record_profile_url(record.profile_url)
        for record in unique_records
        if record.profile_url
    }
    title_pending_records = [
        record
        for record in _collect_title_pending_records(parser.root, base_url)
        if _normalize_record_profile_url(record.profile_url) not in complete_profile_urls
    ]
    failure_stage = _failure_stage(
        candidate_count,
        len(unique_records),
        html_length=len(html or ""),
        base_url=base_url,
        page_title=_page_title(parser.root),
    )

    return ParseResult(
        records=unique_records,
        page_type=_detect_page_type(containers),
        candidate_count=candidate_count,
        parsed_count=len(unique_records),
        failure_stage=failure_stage,
        possible_person_link_count=possible_person_link_count,
        fallback_person_links_count=fallback_person_links_count,
        fallback_candidates_count=fallback_candidates_count,
        fallback_link_debug=fallback_link_debug,
        heading_person_candidates_count=heading_person_candidates_count,
        heading_records_parsed=len(heading_records) if heading_person_candidates_count else 0,
        recovered_profile_links_count=recovered_profile_links_count,
        heading_person_link_debug=heading_person_link_debug,
        cards_missing_profile_url_count=cards_missing_profile_url_count,
        card_recovered_profile_links_count=card_recovered_profile_links_count,
        card_profile_link_debug=card_profile_link_debug,
        table_rows_detected=len(faculty_table_rows),
        table_rows_parsed=table_rows_parsed,
        dropped_candidate_debug=dropped_candidate_debug,
        table_headers_debug=_table_headers_debug(parser.root),
        section_headings_debug=_section_headings_debug(parser.root),
        href_patterns_debug=_href_patterns_debug(parser.root, base_url),
        heading_card_candidates_count=heading_card_candidates_count,
        generic_profile_links_count=generic_profile_links_count,
        heading_card_debug=heading_card_debug,
        role_group_count=role_group_count,
        person_rows_detected=person_rows_detected,
        role_group_debug=role_group_debug,
        faculty_profile_links_detected=faculty_profile_links_detected,
        unique_profile_links_count=unique_profile_links_count,
        local_person_blocks_created=local_person_blocks_created,
        duplicate_profile_links_count=duplicate_profile_links_count,
        excluded_section_count=excluded_section_count,
        wrapper_person_links_count=wrapper_person_links_count,
        segmented_person_blocks_count=segmented_person_blocks_count,
        segmented_person_debug=segmented_person_debug,
        segmented_academic_section_count=segmented_academic_section_count,
        segmented_administrative_exclusion_count=segmented_administrative_exclusion_count,
        segmented_emeritus_exclusion_count=segmented_emeritus_exclusion_count,
        ancestor_profile_links_recovered_count=ancestor_profile_links_recovered_count,
        same_block_partial_records_merged_count=same_block_partial_records_merged_count,
        flattened_name_title_split_count=flattened_name_title_split_count,
        unresolved_cards_missing_profile_url_count=unresolved_cards_missing_profile_url_count,
        title_pending_records=title_pending_records,
    )


def remove_duplicate_title_pending_records(
    records: Iterable[TitlePendingRecord],
) -> list[TitlePendingRecord]:
    unique: list[TitlePendingRecord] = []
    seen: set[str] = set()
    for record in records:
        key = _normalize_record_profile_url(record.profile_url)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique


def remove_duplicates(records: Iterable[FacultyRecord]) -> list[FacultyRecord]:
    unique_records: list[FacultyRecord] = []
    record_indexes: dict[tuple[str, str], int] = {}

    for record in records:
        if record.profile_url:
            key = ("url", _normalize_record_profile_url(record.profile_url))
        else:
            key = ("name_title", f"{_normalize_key(record.name)}|{_normalize_key(record.title)}")
        if key in record_indexes:
            index = record_indexes[key]
            existing = unique_records[index]
            preferred = max((existing, record), key=_record_completeness)
            email = preferred.email or existing.email or record.email
            unique_records[index] = FacultyRecord(
                name=preferred.name,
                title=preferred.title,
                profile_url=preferred.profile_url,
                email=email,
            )
            continue
        record_indexes[key] = len(unique_records)
        unique_records.append(record)

    return unique_records


def _record_completeness(record: FacultyRecord) -> int:
    return sum(bool(normalize_space(value)) for value in (record.name, record.title, record.profile_url, record.email))


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def find_next_directory_page_url(html: str, current_url: str) -> str:
    parser = _FacultyHTMLParser()
    parser.feed(html)
    current = urlparse(current_url)
    for link in parser.links:
        rel_tokens = {token.casefold() for token in link.attr_text("rel").split()}
        label = _normalize_key(" ".join((link.text(), link.attr_text("title"), link.attr_text("aria-label"))))
        is_next = "next" in rel_tokens or any(word in label for word in ("next", "próxim", "proxim"))
        if not is_next:
            continue
        candidate = urlparse(urljoin(current_url, link.attr_text("href")))
        if candidate.scheme not in {"http", "https"} or candidate.netloc.lower() != current.netloc.lower():
            continue
        if candidate.path.rstrip("/") != current.path.rstrip("/"):
            continue
        return candidate.geturl()
    return ""


def _find_faculty_containers(root: _Node, base_url: str = "") -> list[_Node]:
    candidates = [
        node
        for node in root.descendants()
        if node.tag in CONTAINER_TAGS
        and not _is_inside_skipped_region(node)
        and not _is_skipped_container(node)
        and not _contains_navigation_region(node)
        and _has_faculty_signal(node)
    ]
    repeated_signatures = _repeated_container_signatures(candidates)
    leaf_candidates = [
        node
        for node in candidates
        if _container_signature(node) in repeated_signatures or _has_strong_person_hint(node)
    ]
    containers = [node for node in leaf_candidates if not _has_candidate_descendant(node, leaf_candidates)]
    if not containers and base_url:
        return _link_list_candidate_containers(root, base_url)
    return containers


def _link_list_candidate_containers(root: _Node, base_url: str) -> list[_Node]:
    containers: list[_Node] = []
    seen: set[int] = set()
    for search_root in _fallback_search_roots(root):
        for link in _links_in(search_root):
            if _is_inside_repeated_person_link_skipped_region(link):
                continue
            if not _is_fallback_profile_href(link.attr_text("href"), base_url):
                continue
            container = _nearest_link_list_container(link)
            if container is None or id(container) in seen:
                continue
            seen.add(id(container))
            containers.append(container)
    return containers


def _nearest_link_list_container(link: _Node) -> _Node | None:
    for ancestor in link.ancestors():
        if ancestor.tag not in CONTAINER_TAGS:
            continue
        if _is_inside_skipped_region(ancestor) or _is_skipped_container(ancestor) or _contains_navigation_region(ancestor):
            return None
        return ancestor
    return None


def _detect_page_type(containers: list[_Node]) -> str:
    if not containers:
        return "unknown"
    if any(node.tag == "tr" for node in containers):
        return "table"
    return "card"


def _failure_stage(
    candidate_count: int,
    parsed_count: int,
    html_length: int = 0,
    base_url: str = "",
    page_title: str = "",
) -> str:
    if parsed_count:
        if html_length > 30000 and parsed_count <= 3:
            return "low_coverage_warning"
        if parsed_count < 10 and _looks_like_directory_page(base_url, page_title):
            return "low_coverage_warning"
        return "none"
    if candidate_count:
        return "extraction"
    return "detection"


def _looks_like_directory_page(base_url: str, page_title: str) -> bool:
    haystack = f"{base_url} {page_title}".lower()
    return any(hint in haystack for hint in DIRECTORY_HINTS)


def _repeated_container_signatures(candidates: list[_Node]) -> set[str]:
    counts = Counter(_container_signature(node) for node in candidates)
    return {signature for signature, count in counts.items() if count > 1}


def _container_signature(node: _Node) -> str:
    class_names = " ".join(sorted(node.attr_text("class").lower().split()))
    useful_classes = [name for name in class_names.split() if any(hint in name for hint in CONTAINER_HINTS)]
    if useful_classes:
        return f"{node.tag}:{'.'.join(useful_classes)}"
    return node.tag


def _has_candidate_descendant(node: _Node, candidates: list[_Node]) -> bool:
    candidate_ids = {id(candidate) for candidate in candidates}
    return any(id(descendant) in candidate_ids for descendant in node.descendants())


def _has_faculty_signal(node: _Node) -> bool:
    if node.tag == "tr":
        return _has_table_row_signal(node)
    if _is_businesscard(node):
        return _record_from_businesscard(node, "https://example.edu/") is not None

    name = _extract_name(node)
    if not name:
        return False
    title = _extract_title(node, name)
    if not title:
        return False
    return bool(_has_profile_link(node) or _has_email(node))


def _has_strong_person_hint(node: _Node) -> bool:
    if node.tag == "tr":
        return True
    class_id = _node_class_id(node)
    return any(
        hint in class_id
        for hint in ("person", "faculty", "profile", "card", "businesscard", "member", "views-col", "views-row", "faculty-caption")
    )


def _record_from_container(
    container: _Node,
    base_url: str,
    preferred_name: str = "",
    preferred_profile_url: str = "",
) -> FacultyRecord | None:
    if container.tag == "tr":
        return _record_from_table_row(container, base_url)
    if _is_businesscard(container):
        return _record_from_businesscard(container, base_url)
    if _is_navigation_or_category_block(container):
        return None
    if _profile_link_count(container, base_url) >= 5:
        return None

    name = preferred_name or _extract_name(container)
    profile_url = preferred_profile_url or _extract_profile_url(container, base_url, name)
    context = container
    if _is_bad_name_candidate(name):
        better_context, better_name = _directory_profile_context_and_name(container, base_url, profile_url)
        if better_name:
            context = better_context
            name = better_name
    if not name or not _looks_like_name(name):
        return None

    if not profile_url:
        profile_url = _extract_profile_url(container, base_url, name)
    if not profile_url:
        profile_url = _recover_card_profile_url(container, base_url, name)

    title = _extract_title(context, name)
    if not title:
        return None
    title = _strip_name_prefix(title, name)
    if _is_excluded_directory_section(container, title):
        return None
    if _is_emeritus_academic_title(title):
        return None
    if _is_non_faculty_member_title(title):
        return None

    if not profile_url:
        return None
    if profile_url and _is_page_profile_url(profile_url, base_url):
        return None

    return FacultyRecord(name=name, title=title, profile_url=profile_url, email=_extract_email(context))


def _candidate_debug(container: _Node, base_url: str) -> dict[str, object]:
    name = _extract_name(container)
    title = _extract_title(container, name) if name else ""
    profile_url = _extract_profile_url(container, base_url)
    if not profile_url and name:
        profile_url = _extract_profile_url(container, base_url, name) or _recover_card_profile_url(container, base_url, name)
    profile_link = next((link for link in _links_in(container) if _is_fallback_profile_href(link.attr_text("href"), base_url)), None)
    reason = "ok"
    if container.tag == "tr":
        cells = _direct_children_by_tag(container, {"td", "th"})
        headers = _table_header_labels(cells)
        if _has_surname_contact_header(headers):
            name_cell = _cell_with_header(cells, headers, "surname, first name") or (cells[0] if cells else None)
            if name_cell is not None:
                name = _extract_name(name_cell) or _clean_name(name_cell.text())
                profile_url = _extract_profile_url(name_cell, base_url, name) or _extract_profile_url(container, base_url, name)
        if _has_surname_contact_header(headers) and not _has_table_row_contact(cells, headers):
            reason = "missing_contact"
        elif not name:
            reason = "missing_name"
        elif not (_looks_like_name(name) or (_has_surname_contact_header(headers) and _looks_like_surname_contact_name(name))):
            reason = "invalid_name"
        elif not profile_url:
            reason = "missing_profile_url"
    elif container.tag != "tr" and _is_navigation_or_category_block(container):
        reason = "navigation_or_category_block"
    elif container.tag != "tr" and _profile_link_count(container, base_url) >= 5:
        reason = "multiple_profile_links"
    elif not name:
        reason = "missing_name"
    elif not _looks_like_name(name):
        reason = "invalid_name"
    elif not title:
        reason = "missing_title"
    elif _is_excluded_directory_section(container, title):
        reason = "section_excluded"
    elif _is_non_faculty_member_title(title):
        reason = "non_faculty_title"
    elif not profile_url:
        reason = "missing_profile_url"
    elif _is_page_profile_url(profile_url, base_url):
        reason = "profile_url_is_page_url"
    return {
        "raw_text": normalize_space(container.text())[:300],
        "name": name,
        "title": title,
        "profile_url": profile_url,
        "email": _extract_email(container),
        "section_heading": _nearest_section_heading(container),
        "raw_name_source": _raw_name_source(container),
        "raw_title_text": _raw_title_text(container, name),
        "profile_link": urljoin(base_url, profile_link.attr_text("href")) if profile_link is not None else "",
        "link_text": _clean_name(profile_link.text()) if profile_link is not None else "",
        "extracted_name": name,
        "extracted_title": title,
        "reject_reason": reason,
        "reason": reason,
        "drop_reason": reason,
    }


def _collect_title_pending_records(root: _Node, base_url: str) -> list[TitlePendingRecord]:
    records: list[TitlePendingRecord] = []
    for container in root.descendants():
        if container.tag not in CONTAINER_TAGS:
            continue
        if _is_inside_skipped_region(container) or _is_skipped_container(container):
            continue
        if container.tag not in {"article", "li", "tr"} and not _has_strong_person_hint(container):
            continue

        section = _nearest_directory_section_heading(container)
        if not _is_explicit_academic_pending_section(section):
            continue

        name = _extract_name(container)
        heading_profile_url = ""
        if not name or _is_bad_name_candidate(name):
            _, heading_name, heading_profile_url = _bounded_card_person_heading_identity(container, base_url)
            name = heading_name or name
        if not name or not _looks_like_name(name) or _is_bad_name_candidate(name):
            continue

        profile_url = heading_profile_url or _extract_profile_url(container, base_url, name)
        if not _is_valid_title_pending_profile_url(profile_url, base_url):
            continue

        extracted_title = _extract_title(container, name)
        directory_title = _pending_directory_title(container, name, extracted_title)
        if directory_title and _has_valid_academic_title(directory_title):
            continue
        if directory_title and not _is_honorific_only_title(directory_title):
            continue
        if _is_emeritus_academic_title(directory_title) or _pending_text_is_excluded(container.text()):
            continue

        records.append(
            TitlePendingRecord(
                name=name,
                directory_title=directory_title,
                profile_url=profile_url,
                email=_extract_email(container),
                section=section,
                source_url=base_url,
                pending_reason=(
                    "honorific_only_title" if directory_title else "missing_title"
                ),
            )
        )
    return remove_duplicate_title_pending_records(records)


def _is_explicit_academic_pending_section(value: str) -> bool:
    normalized = _normalize_key(value)
    if not normalized or normalized in NEUTRAL_DIRECTORY_SECTIONS or normalized in EXCLUDED_DIRECTORY_SECTIONS:
        return False
    if any(
        term in normalized
        for term in (
            "administrative",
            "administration",
            "support staff",
            "professional services",
            "operations staff",
            "technical staff",
            "emeritus",
            "emerita",
            "retired",
            "student",
        )
    ):
        return False
    if normalized in {"faculty", "faculty members", "academics", "docentes", "corpo docente", "pessoal docente"}:
        return True
    if "faculty" in normalized:
        return " staff" not in normalized and "staff " not in normalized
    if "academic" in normalized and any(
        term in normalized for term in ("staff", "faculty", "personnel", "members")
    ):
        return True
    return any(term in normalized for term in ("professors", "professorships", "lecturers"))


def _pending_directory_title(container: _Node, name: str, extracted_title: str) -> str:
    if extracted_title:
        return extracted_title
    if container.tag == "tr":
        cells = _direct_children_by_tag(container, {"td", "th"})
        headers = _table_header_labels(cells)
        title_cell = _cell_with_header(cells, headers, "title")
        if title_cell is not None:
            return normalize_space(title_cell.text())
    for node in container.descendants():
        class_id = _node_class_id(node)
        tokens = {token for token in re.split(r"[^a-z0-9]+", class_id) if token}
        if not (
            tokens & {"title", "role", "position", "designation", "jobtitle"}
            or "job-title" in class_id
            or "job-role" in class_id
        ):
            continue
        value = normalize_space(node.text())
        if value and _normalize_key(value) != _normalize_key(name) and not EMAIL_RE.search(value):
            return value
    for chunk in _local_title_text_chunks(container):
        value = normalize_space(chunk)
        if _is_honorific_only_title(value):
            return value
    return ""


def _is_honorific_only_title(value: str) -> bool:
    return _normalize_key(value).rstrip(".") == "dr"


def _is_valid_title_pending_profile_url(value: str, base_url: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if _is_page_profile_url(value, base_url) or _is_organizational_card_profile_url(value):
        return False
    if _is_generic_policy_url(value):
        return False
    return (
        _is_same_institution_host(parsed.netloc, urlparse(base_url).netloc)
        or _is_trusted_external_academic_profile_url(value, base_url)
    )


def _pending_text_is_excluded(value: str) -> bool:
    normalized = _normalize_key(value)
    return any(
        re.search(rf"\b{re.escape(term)}\b", normalized)
        for term in (
            "emeritus",
            "emerita",
            "retired",
            "student",
            *NON_ACADEMIC_TITLE_WORDS,
        )
    )


def _is_bad_name_candidate(value: str) -> bool:
    if not value:
        return False
    return (
        _is_accordion_utility_label(value)
        or _is_title_text(value)
        or _is_office_like_text(value)
        or _is_faculty_category_label(value)
    )


def _is_office_like_text(value: str) -> bool:
    lowered = _normalize_key(value)
    return any(word in lowered for word in ("office", "department", "school", "college", "center", "centre", "unit"))


def _directory_profile_context_and_name(container: _Node, base_url: str, profile_url: str) -> tuple[_Node, str]:
    if not profile_url:
        return container, ""

    for context in (container, *container.ancestors()):
        if context.tag in SKIP_TAGS:
            break
        for link in _links_in(context):
            href = link.attr_text("href")
            absolute_url = urljoin(base_url, href) if base_url else href
            if _normalize_record_profile_url(absolute_url) != _normalize_record_profile_url(profile_url):
                continue
            name = _clean_name(link.text())
            if name and _looks_like_name(name) and not _is_bad_name_candidate(name):
                return context, name
    return container, ""


def _record_from_businesscard(container: _Node, base_url: str) -> FacultyRecord | None:
    name = _businesscard_contact_name(container)
    if not name or not _looks_like_name(name):
        return None

    title = _businesscard_title(name)
    if not title:
        return None

    profile_url = _businesscard_profile_url(container, base_url)
    if not profile_url:
        return None

    return FacultyRecord(name=name, title=title, profile_url=profile_url)


def _is_businesscard(node: _Node) -> bool:
    return "businesscard" in _node_class_id(node)


def _businesscard_contact_name(container: _Node) -> str:
    for node in container.descendants():
        if "contact-name" not in node.attr_text("class").lower().split():
            continue
        name = _clean_name(node.text())
        if name:
            return name
    return ""


def _businesscard_title(name: str) -> str:
    if re.search(r"\bprof\.?", name, flags=re.IGNORECASE):
        return "Professor"
    return ""


def _businesscard_profile_url(container: _Node, base_url: str) -> str:
    for link in _links_in(container):
        if _normalize_key(link.text()) == "additional contact information":
            href = link.attr_text("href")
            if _is_candidate_profile_href(href):
                return urljoin(base_url, href) if base_url else href
    return ""


def _record_from_table_row(row: _Node, base_url: str) -> FacultyRecord | None:
    cells = _direct_children_by_tag(row, {"td", "th"})
    split_name_record = _record_from_split_name_table_row(cells, base_url)
    if split_name_record is not None:
        return split_name_record

    if len(cells) == 1:
        return _record_from_single_cell_table_row(cells[0], base_url)
    if len(cells) < 2 or _is_header_row(cells):
        return None

    name_cell = cells[0]
    name = _extract_name(name_cell)
    if not name or not _looks_like_name(name):
        return None

    title = ""
    for cell in cells[1:]:
        cell_text = cell.text()
        if _is_title_text(cell_text):
            title = cell_text
            break
    if not title:
        return None
    title = _strip_name_prefix(title, name)
    if _is_excluded_directory_section(row, title):
        return None

    profile_url = _extract_profile_url(row, base_url, name)
    if not profile_url:
        return None

    return FacultyRecord(name=name, title=title, profile_url=profile_url)


def _find_faculty_like_table_rows(root: _Node) -> list[_Node]:
    rows: list[_Node] = []
    for table in _nodes_by_tag(root, "table"):
        header_cells = _faculty_like_table_header_cells(table)
        if not header_cells:
            continue
        header_count = len(header_cells)
        for row in _nodes_by_tag(table, "tr"):
            cells = _direct_children_by_tag(row, {"td", "th"})
            if not cells or _is_header_row(cells):
                continue
            if len(cells) < min(2, header_count):
                continue
            rows.append(row)
    return rows


def _faculty_like_table_header_cells(table: _Node) -> list[_Node]:
    for row in _nodes_by_tag(table, "tr"):
        cells = _direct_children_by_tag(row, {"th", "td"})
        if not any(cell.tag == "th" for cell in cells):
            continue
        labels = [_header_label(cell.text()) for cell in cells]
        label_set = set(labels)
        if "name" in label_set and "title" in label_set and ({"institute", "e-mail", "email"} & label_set):
            return cells
        if "name" in label_set and "title" in label_set and "job responsibilities" in label_set:
            return cells
        if "surname, first name" in label_set and "phone number" in label_set and "email address" in label_set:
            return cells
        if {"last name", "first name", "title"}.issubset(label_set) and ({"e-mail", "email"} & label_set):
            return cells
    return []


def _record_from_faculty_like_table_row(row: _Node, base_url: str, page_title: str = "") -> FacultyRecord | None:
    cells = _direct_children_by_tag(row, {"td", "th"})
    split_name_record = _record_from_split_name_table_row(cells, base_url)
    if split_name_record is not None:
        return split_name_record
    if len(cells) < 2 or _is_header_row(cells):
        return None

    headers = _table_header_labels(cells)
    allow_missing_profile_url = _has_job_responsibilities_header(headers)
    has_surname_contact_header = _has_surname_contact_header(headers)
    name_cell = _cell_with_header(cells, headers, "name") or _cell_with_header(cells, headers, "surname, first name") or cells[0]
    title_cell = _cell_with_header(cells, headers, "title") or (None if has_surname_contact_header else (cells[1] if len(cells) > 1 else None))
    if title_cell is None:
        title = _table_context_title(page_title) if has_surname_contact_header else ""
    else:
        title = normalize_space(title_cell.text().strip(" -|,;"))

    name = _extract_name(name_cell) or _clean_name(name_cell.text())
    if not name or not (_looks_like_name(name) or (has_surname_contact_header and _looks_like_surname_contact_name(name))):
        return None

    if not title:
        return None
    title = _strip_name_prefix(title, name)
    if _is_excluded_directory_section(row, title):
        return None
    if allow_missing_profile_url and (not _is_title_text(title) or _is_non_faculty_member_title(title)):
        return None

    profile_url = _extract_profile_url(name_cell, base_url, name) or _extract_profile_url(row, base_url, name)
    if not profile_url:
        if has_surname_contact_header:
            return None
        if not allow_missing_profile_url:
            return None
    elif _is_page_profile_url(profile_url, base_url) and not _is_query_person_profile_url(profile_url):
        if has_surname_contact_header:
            return None
        if not allow_missing_profile_url:
            return None
        profile_url = ""

    return FacultyRecord(name=name, title=title, profile_url=profile_url)


def _has_job_responsibilities_header(headers: dict[int, str]) -> bool:
    return any(_header_label(value) == "job responsibilities" for value in headers.values())


def _has_surname_contact_header(headers: dict[int, str]) -> bool:
    labels = {_header_label(value) for value in headers.values()}
    return {"surname, first name", "phone number", "email address"}.issubset(labels)


def _table_context_title(page_title: str) -> str:
    if _normalize_key(page_title) in {"full professors", "full professor"}:
        return "Full Professor"
    return ""


def _table_context_title_from_root(root: _Node) -> str:
    page_title = _table_context_title(_page_title(root))
    if page_title:
        return page_title
    for heading in _section_headings_debug(root):
        title = _table_context_title(heading)
        if title:
            return title
    return ""


def _has_table_row_contact(cells: list[_Node], headers: dict[int, str]) -> bool:
    email_cell = _cell_with_header(cells, headers, "email address") or _cell_with_header(cells, headers, "email")
    phone_cell = _cell_with_header(cells, headers, "phone number")
    return bool((email_cell and normalize_space(email_cell.text())) or (phone_cell and normalize_space(phone_cell.text())))


def _looks_like_surname_contact_name(value: str) -> bool:
    if not value or len(value) > 140 or "," not in value:
        return False
    surname, rest = (part.strip() for part in value.split(",", 1))
    if not surname or not rest:
        return False
    lowered_words = {word.strip(".,").lower() for word in value.split()}
    if lowered_words & NON_NAME_WORDS:
        return False
    return bool(re.search(r"[^\W\d_]{2,}", surname, flags=re.UNICODE) and re.search(r"[^\W\d_]{2,}", rest, flags=re.UNICODE))


def _cell_with_header(cells: list[_Node], headers: dict[int, str], label: str) -> _Node | None:
    for cell in cells:
        if _header_label(headers.get(id(cell), "")) == label:
            return cell
    return None


def _header_label(value: str) -> str:
    return normalize_space(value).casefold().replace("-", "")


def _record_from_split_name_table_row(cells: list[_Node], base_url: str) -> FacultyRecord | None:
    last_name_cell = _cell_with_label(cells, "lastname", "last name", "last")
    first_name_cell = _cell_with_label(cells, "firstname", "first name", "first")
    title_cell = _cell_with_label(cells, "title", "position", "role")
    if last_name_cell is None or first_name_cell is None or title_cell is None:
        return None

    first_name = _clean_name(first_name_cell.text())
    last_name = _clean_name(last_name_cell.text())
    name = normalize_space(f"{first_name} {last_name}")
    if not _looks_like_name(name):
        return None

    title = normalize_space(title_cell.text().strip(" -|,;"))
    title = _strip_name_prefix(title, name)
    if _is_excluded_directory_section(title_cell, title):
        return None
    if not _is_title_text(title) and not re.match(
        r"^(?:(?:apl\.|ao\.)\s*)?(?:prof\.|pd\b|dr\.)",
        title,
        flags=re.IGNORECASE,
    ):
        return None

    profile_url = _split_name_profile_url(last_name_cell, first_name_cell, base_url)
    if not profile_url:
        return None

    return FacultyRecord(name=name, title=title, profile_url=profile_url)


def _cell_with_class(cells: list[_Node], class_name: str) -> _Node | None:
    for cell in cells:
        if class_name in cell.attr_text("class").lower().split():
            return cell
    return None


def _cell_with_label(cells: list[_Node], *labels: str) -> _Node | None:
    headers = _table_header_labels(cells)
    for cell in cells:
        haystack = f"{cell.attr_text('class')} {cell.attr_text('headers')} {headers.get(id(cell), '')}".lower()
        if any(label in haystack for label in labels):
            return cell
    return None


def _split_name_profile_url(last_name_cell: _Node, first_name_cell: _Node, base_url: str) -> str:
    for cell in (last_name_cell, first_name_cell):
        for link in _links_in(cell):
            href = link.attr_text("href")
            absolute_url = urljoin(base_url, href) if base_url else href
            if _looks_like_profile_url(absolute_url) or _is_candidate_profile_href(href):
                return absolute_url
    return ""


def _table_header_labels(cells: list[_Node]) -> dict[int, str]:
    if not cells or cells[0].parent is None:
        return {}
    table = _ancestor_by_tag(cells[0].parent, "table")
    if table is None:
        return {}
    for row in _nodes_by_tag(table, "tr"):
        header_cells = _direct_children_by_tag(row, {"th", "td"})
        if not any(cell.tag == "th" for cell in header_cells):
            continue
        headers = [normalize_space(cell.text()).casefold() for cell in header_cells]
        return {id(cell): headers[index] for index, cell in enumerate(cells) if index < len(headers)}
    return {}


def _ancestor_by_tag(node: _Node, tag: str) -> _Node | None:
    for ancestor in node.ancestors():
        if ancestor.tag == tag:
            return ancestor
    return None


def _record_from_single_cell_table_row(cell: _Node, base_url: str) -> FacultyRecord | None:
    if _is_header_row([cell]):
        return None

    name = _extract_name(cell)
    if not name or not _looks_like_name(name):
        return None

    title = _extract_title(cell, name)
    if not title:
        return None
    title = _strip_name_prefix(title, name)
    if _is_excluded_directory_section(cell, title):
        return None

    profile_url = _extract_profile_url(cell, base_url, name)
    if not profile_url:
        return None

    return FacultyRecord(name=name, title=title, profile_url=profile_url)


def _fallback_profile_link_records(root: _Node, base_url: str) -> list[FacultyRecord]:
    records: list[FacultyRecord] = []
    for search_root in _fallback_search_roots(root):
        for link in _links_in(search_root):
            has_prefixed_person_text = _prefixed_title_and_name(link.text()) is not None
            has_strong_profile = _is_strong_stref_profile_url(link.attr_text("href"), base_url)
            if _is_inside_fallback_skipped_region(link) and not has_prefixed_person_text and not has_strong_profile:
                continue

            href = link.attr_text("href")
            if not _is_fallback_profile_href(href, base_url) and not has_prefixed_person_text and not has_strong_profile:
                continue

            record = _record_from_profile_link(link, base_url)
            if record is not None:
                records.append(record)
    return records


def _strong_stref_profile_records(root: _Node, base_url: str) -> list[FacultyRecord]:
    records: list[FacultyRecord] = []
    for search_root in _fallback_search_roots(root):
        for link in _links_in(search_root):
            if not _is_strong_stref_profile_url(link.attr_text("href"), base_url):
                continue
            record = _record_from_profile_link(link, base_url)
            if record is not None:
                records.append(record)
    return remove_duplicates(records)


def _strong_stref_rejection_debug(root: _Node, base_url: str) -> list[dict[str, object]]:
    debug: list[dict[str, object]] = []
    for search_root in _fallback_search_roots(root):
        for link in _links_in(search_root):
            href = link.attr_text("href")
            if not _is_strong_stref_profile_url(href, base_url):
                continue
            if _record_from_profile_link(link, base_url) is not None:
                continue
            name = _clean_name(link.text())
            context = _strong_profile_record_context(link)
            raw_title = _raw_text_after_link(link, context)
            title = _strip_trailing_affiliation(raw_title) if _is_title_text(raw_title) else ""
            validation_name = re.sub(r"^(?:(?:Associate\s+)?Professor|Dr\.?)\s+", "", name, flags=re.IGNORECASE)
            if not _looks_like_name(validation_name):
                reason = "invalid_name"
            elif not raw_title:
                reason = "missing_title"
            elif not title:
                reason = "non_academic_title"
            else:
                reason = "filtered_title"
            debug.append(
                {
                    "profile_link": urljoin(base_url, href),
                    "link_text": _clean_name(link.text()),
                    "raw_title_text": raw_title,
                    "extracted_name": name,
                    "extracted_title": title,
                    "reject_reason": reason,
                    "drop_reason": reason,
                }
            )
            if len(debug) >= 10:
                return debug
    return debug


def _recover_repeated_linked_teaser_records(
    root: _Node, base_url: str
) -> tuple[list[FacultyRecord], int, list[dict[str, object]]]:
    eligible: list[tuple[_Node, FacultyRecord, str]] = []
    for search_root in _fallback_search_roots(root):
        if search_root.tag not in {"main", "article"} and not _is_fallback_search_root(search_root):
            continue
        for link in _links_in(search_root):
            record = _record_from_linked_teaser(link, base_url)
            if record is not None:
                eligible.append((link, record, _linked_teaser_signature(link)))

    repeated_signatures = {
        signature
        for signature, count in Counter(signature for _, _, signature in eligible).items()
        if count >= 2
    }
    records: list[FacultyRecord] = []
    debug: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    for link, record, signature in eligible:
        if signature not in repeated_signatures:
            continue
        normalized_url = _normalize_record_profile_url(record.profile_url)
        if normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        records.append(record)
        if len(debug) < 5:
            debug.append(
                {
                    "profile_link": record.profile_url,
                    "link_text": _clean_name(link.text())[:160],
                    "extracted_name": record.name,
                    "inferred_title": record.title,
                    "drop_reason": "ok",
                }
            )
    return records, len(records), debug


def _record_from_linked_teaser(link: _Node, base_url: str) -> FacultyRecord | None:
    if link.tag != "a" or _is_inside_linked_teaser_skipped_region(link) or _is_skipped_container(link):
        return None
    if _links_in(link) or len([node for node in link.descendants() if node.tag not in SKIP_TAGS]) < 2:
        return None
    if not _is_linked_teaser_personnel_context(link):
        return None

    names = _linked_teaser_person_names(link)
    if len(names) != 1:
        return None
    name = names[0]
    title = _linked_teaser_title(link, name)
    if not title:
        return None
    if _is_excluded_directory_section(link, title):
        return None
    if _is_emeritus_academic_title(title) or _is_non_faculty_member_title(title):
        return None
    profile_url = _linked_teaser_profile_url(link, base_url)
    if not profile_url:
        return None
    return FacultyRecord(name=name, title=title, profile_url=profile_url)


def _is_inside_linked_teaser_skipped_region(node: _Node) -> bool:
    if _is_inside_skipped_region(node):
        return True
    skip_hints = (
        "nav",
        "footer",
        "header",
        "search",
        "breadcrumb",
        "metadata",
        "sidebar",
        "cookie",
        "privacy",
        "consent",
        "quick-link",
        "quicklink",
    )
    for ancestor in node.ancestors():
        if ancestor.tag in {"main", "article"} or _is_fallback_search_root(ancestor):
            break
        class_id = _node_class_id(ancestor)
        matched_hints = {hint for hint in skip_hints if hint in class_id}
        academic_sidebar = matched_hints == {"sidebar"} and any(
            hint in class_id for hint in ("faculty", "person", "profile")
        )
        if matched_hints and not academic_sidebar:
            return True
    return False


def _linked_teaser_person_names(link: _Node) -> list[str]:
    names: dict[str, str] = {}
    for node in link.descendants():
        if node.tag == "img":
            continue
        dedicated = node.tag in {"strong", "b", "h1", "h2", "h3", "h4", "h5", "h6"} or _is_dedicated_person_name_node(node)
        values = [node.text()] if dedicated else list(node.text_parts)
        for value in values:
            name = _linked_teaser_person_name(value, dedicated=dedicated)
            if name:
                names[_normalize_key(name)] = name
    return list(names.values())


def _linked_teaser_person_name(value: str, *, dedicated: bool) -> str:
    text = normalize_space(value)
    if not text:
        return ""
    professor_prefix = re.search(r"\b(?:Professor|Prof\.)\s+(?:Dr\.\s+)?", text, flags=re.IGNORECASE)
    if professor_prefix:
        text = text[professor_prefix.start() :]
    elif dedicated:
        text = re.sub(
            r"^(?:image|photo(?:graph)?|picture|credit|image credit|photo credit|copyright|bild|foto|©)\s*(?::|by\b|[-–—])\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
    else:
        return ""
    text = re.split(r"\s+(?=(?:Chair|Professorship)\b)", text, maxsplit=1, flags=re.IGNORECASE)[0]
    name = _clean_name(text)
    validation_name = re.sub(
        r"^(?:Professor|Prof\.)\s+(?:Dr\.\s+)?",
        "",
        name,
        flags=re.IGNORECASE,
    )
    if re.match(r"^(?:for|of|in|at)\b", validation_name, flags=re.IGNORECASE):
        return ""
    if not _looks_like_name(validation_name) or _is_bad_name_candidate(validation_name):
        return ""
    return name


def _linked_teaser_title(link: _Node, name: str) -> str:
    for chunk in link.text_chunks():
        if re.match(
            r"^(?:image|photo(?:graph)?|picture|credit|image credit|photo credit|copyright|bild|foto|©)\b",
            chunk,
            flags=re.IGNORECASE,
        ):
            continue
        cleaned = normalize_space(chunk.strip(" -|,;"))
        if _normalize_key(cleaned) == _normalize_key(name):
            continue
        if _is_title_text(cleaned) or re.search(
            r"\b(?:professur|lehrstuhl)\b", cleaned, flags=re.IGNORECASE
        ):
            return cleaned
    prefix = re.match(r"^(Professor|Prof\.(?:\s+Dr\.)?)\s+", name, flags=re.IGNORECASE)
    return normalize_space(prefix.group(1)) if prefix else ""


def _linked_teaser_profile_url(link: _Node, base_url: str) -> str:
    href = link.attr_text("href")
    if not _is_candidate_profile_href(href):
        return ""
    absolute_url = urljoin(base_url, href)
    parsed = urlparse(absolute_url)
    base = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if base.netloc and not _is_same_institution_host(parsed.netloc, base.netloc):
        return ""
    if _normalize_record_profile_url(absolute_url) == _normalize_record_profile_url(base_url):
        return ""
    segments = [segment.casefold() for segment in parsed.path.split("/") if segment]
    if not segments or any(segment in {"category", "categories", "search", "navigation", "menu"} for segment in segments):
        return ""
    if segments[-1] in {
        "department",
        "departments",
        "directory",
        "faculty",
        "people",
        "personnel",
        "professors",
        "professorships",
        "staff",
    }:
        return ""
    path = parsed.path.casefold()
    if any(segment in {"department", "departments"} for segment in segments) and len(segments) <= 2 and not any(
        hint in path for hint in ("chair", "professorship", "professur", "lehrstuhl")
    ):
        return ""
    if path.endswith((".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp")):
        return ""
    query_keys = {key.casefold() for key in parse_qs(parsed.query, keep_blank_values=True)}
    if query_keys & {"category", "filter", "page", "search", "query", "q"}:
        return ""
    return absolute_url


def _is_linked_teaser_personnel_context(link: _Node) -> bool:
    heading = _normalize_key(_nearest_section_heading(link))
    academic_hints = (
        "academic",
        "chair",
        "faculty",
        "lehrstuhl",
        "people",
        "personnel",
        "professor",
        "professur",
        "staff",
    )
    if any(hint in heading for hint in academic_hints):
        return True
    return any(
        any(hint in _node_class_id(ancestor) for hint in academic_hints)
        for ancestor in link.ancestors()
        if ancestor.tag not in SKIP_TAGS
    )


def _linked_teaser_signature(link: _Node) -> str:
    classes = ".".join(sorted(link.attr_text("class").casefold().split()))
    child_tags = ".".join(sorted({child.tag for child in link.children}))
    return f"{link.tag}:{classes}:{child_tags}"


def _fallback_repeated_person_link_records(root: _Node, base_url: str) -> tuple[list[FacultyRecord], int, list[dict[str, object]]]:
    repeated_patterns = _repeated_person_link_patterns(root, base_url)
    if not repeated_patterns:
        return [], 0, []

    records: list[FacultyRecord] = []
    debug: list[dict[str, object]] = []
    candidate_count = 0
    seen_urls: set[str] = set()
    for search_root in _fallback_search_roots(root):
        for link in _links_in(search_root):
            href = link.attr_text("href")
            absolute_url = urljoin(base_url, href)
            if _repeated_person_link_pattern(href, base_url) not in repeated_patterns:
                continue
            if _is_inside_repeated_person_link_skipped_region(link):
                continue
            normalized_url = _normalize_person_link_url(absolute_url)
            if normalized_url in seen_urls:
                continue
            seen_urls.add(normalized_url)

            candidate_count += 1
            record, item_debug = _record_from_repeated_person_link(link, base_url)
            if len(debug) < 5:
                debug.append(item_debug)
            if record is not None:
                records.append(record)
    return records, candidate_count, debug


def _recover_academic_section_name_link_records(
    root: _Node, base_url: str
) -> tuple[list[FacultyRecord], int, list[dict[str, object]]]:
    candidates: list[tuple[int, FacultyRecord, dict[str, object]]] = []
    seen_urls: set[str] = set()

    for search_root in _fallback_search_roots(root):
        for link in _links_in(search_root):
            if _is_inside_repeated_person_link_skipped_region(link):
                continue
            section_title, section_key, section_context = _bounded_faculty_section(link)
            if not section_title:
                continue

            name = _clean_name(link.text())
            if (
                not _is_segmented_person_link_name(name)
                or _is_office_like_text(name)
                or _is_faculty_category_label(name)
            ):
                continue

            profile_url = urljoin(base_url, link.attr_text("href"))
            profile_key = _opaque_local_page_key(profile_url)
            if not _is_bounded_local_person_page(profile_url, base_url) or profile_key in seen_urls:
                continue
            seen_urls.add(profile_key)

            context = _fallback_record_context(link)
            local_title, local_email = _flat_person_fields(link, section_context, base_url)
            if not local_title:
                local_title = _extract_title(context, name)
            title = local_title if _is_valid_flat_academic_title(local_title) else section_title
            if _is_non_faculty_member_title(title):
                continue

            record = FacultyRecord(
                name=name,
                title=title,
                profile_url=profile_url,
                email=local_email or _extract_email(context),
            )
            candidates.append(
                (
                    section_key,
                    record,
                    {
                        "link_text": normalize_space(link.text())[:160],
                        "href": link.attr_text("href"),
                        "name": name,
                        "inferred_title": title,
                        "drop_reason": "ok",
                    },
                )
            )

    section_counts = Counter(section_key for section_key, _, _ in candidates)
    accepted = [item for item in candidates if section_counts[item[0]] >= 2]
    return [record for _, record, _ in accepted], len(accepted), [item[2] for item in accepted[:5]]


def _recover_embedded_filtered_staff_records(
    html: str, base_url: str
) -> tuple[list[FacultyRecord], int, list[dict[str, object]]]:
    requested_sections = [
        normalize_space(value)
        for value in parse_qs(urlparse(base_url).query).get("staff", [])
        if normalize_space(value)
    ]
    if len(requested_sections) != 1 or not _is_explicit_academic_pending_section(requested_sections[0]):
        return [], 0, []

    profile_assignment = re.search(
        r"(?:window\.)?([A-Za-z_$][\w$]*)\.staff_profiles\s*=\s*",
        html,
    )
    if profile_assignment is None:
        return [], 0, []
    namespace = profile_assignment.group(1)
    profiles = _decode_embedded_json_assignment(html, namespace, "staff_profiles")
    manual_tabs = _decode_embedded_json_assignment(html, namespace, "manual_tabs")
    if not isinstance(profiles, list) or not isinstance(manual_tabs, list):
        return [], 0, []

    requested_key = _normalize_key(requested_sections[0])
    selected_tabs = [
        tab
        for tab in manual_tabs
        if isinstance(tab, dict) and _normalize_key(str(tab.get("title", ""))) == requested_key
    ]
    if len(selected_tabs) != 1 or not isinstance(selected_tabs[0].get("usernames"), str):
        return [], 0, []
    allowed_usernames = {
        normalize_space(username)
        for username in selected_tabs[0]["usernames"].split(",")
        if normalize_space(username)
    }
    if not allowed_usernames:
        return [], 0, []

    profile_base_url = _embedded_profile_base_url(html, namespace, base_url)
    records: list[FacultyRecord] = []
    debug: list[dict[str, object]] = []
    seen_usernames: set[str] = set()
    candidate_count = 0
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        username = _embedded_profile_text(profile.get("username"))
        if username not in allowed_usernames or username in seen_usernames:
            continue
        seen_usernames.add(username)
        candidate_count += 1

        first_name = _embedded_profile_text(profile.get("first_name"))
        last_name = _embedded_profile_text(profile.get("last_name"))
        honorific = _embedded_profile_text(profile.get("title"))
        person_name = normalize_space(f"{first_name} {last_name}")
        name = normalize_space(f"{honorific} {person_name}")
        title = _embedded_profile_text(profile.get("roles_flattened"))
        if not title and isinstance(profile.get("roles"), list):
            role_names = [
                _embedded_profile_text(role.get("role"))
                for role in profile["roles"]
                if isinstance(role, dict) and _embedded_profile_text(role.get("role"))
            ]
            title = "; ".join(role_names)

        profile_id = str(profile.get("id", "")).strip()
        slug = _embedded_profile_slug(f"{last_name} {first_name}")
        profile_url = ""
        if re.fullmatch(r"[A-Za-z0-9_-]+", profile_id) and slug:
            profile_url = f"{profile_base_url.rstrip('/')}/{profile_id}/{quote(slug, safe='-')}"

        reject_reason = "ok"
        if not _looks_like_name(person_name):
            reject_reason = "invalid_name"
        elif not title:
            reject_reason = "missing_title"
        elif not profile_url:
            reject_reason = "missing_profile_url"
        else:
            records.append(
                FacultyRecord(
                    name=name,
                    title=title,
                    profile_url=profile_url,
                    email=_embedded_profile_text(profile.get("email")),
                )
            )
        if len(debug) < 5:
            debug.append(
                {
                    "link_text": name,
                    "href": profile_url,
                    "name": name,
                    "inferred_title": title,
                    "drop_reason": reject_reason,
                }
            )

    return records, candidate_count, debug


def _decode_embedded_json_assignment(html: str, namespace: str, name: str) -> object | None:
    assignment = re.search(
        rf"(?:window\.)?{re.escape(namespace)}\.{re.escape(name)}\s*=\s*",
        html,
    )
    if assignment is None:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(html, assignment.end())
    except (json.JSONDecodeError, TypeError):
        return None
    return value


def _embedded_profile_base_url(html: str, namespace: str, base_url: str) -> str:
    assignment = re.search(
        rf"(?:window\.)?{re.escape(namespace)}\.staff_profiles_base_url\s*=\s*(['\"])(.*?)\1",
        html,
    )
    candidate = normalize_space(assignment.group(2)) if assignment else ""
    page = urlparse(base_url)
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() == page.netloc.lower():
        return candidate.rstrip("/")
    return page._replace(query="", fragment="").geturl().rstrip("/")


def _embedded_profile_slug(value: str) -> str:
    value = unicodedata.normalize("NFKC", normalize_space(value)).casefold()
    slug = "".join(character if character.isalnum() else "-" for character in value)
    return re.sub(r"-+", "-", slug).strip("-")


def _embedded_profile_text(value: object) -> str:
    return normalize_space(value) if isinstance(value, str) else ""


def _bounded_faculty_section(node: _Node) -> tuple[str, int, _Node | None]:
    current: _Node | None = node
    while current is not None and current.parent is not None:
        siblings = current.parent.children
        try:
            index = siblings.index(current)
        except ValueError:
            index = 0
        for sibling in reversed(siblings[:index]):
            if _looks_like_person_card_for_section(sibling):
                continue
            heading = _last_heading_text(sibling)
            if not heading:
                continue
            if _is_flat_person_detail_heading(heading):
                continue
            normalized = re.sub(r"[-\s]+", " ", _normalize_key(heading)).strip()
            if normalized not in {"full time faculty", "fulltime faculty"}:
                return "", 0, None
            return "Full-time Faculty", id(sibling), current.parent
        current = current.parent
    return "", 0, None


def _flat_person_fields(link: _Node, context: _Node | None, base_url: str) -> tuple[str, str]:
    if context is None:
        return "", ""
    nodes = list(context.descendants())
    try:
        start = nodes.index(link) + 1
    except ValueError:
        return "", ""

    title = ""
    email = ""
    for node in nodes[start:]:
        if node.tag == "a":
            following_name = _clean_name(node.text())
            following_url = urljoin(base_url, node.attr_text("href"))
            if _is_segmented_person_link_name(following_name) and _is_bounded_local_person_page(
                following_url, base_url
            ):
                break
        for value in (*node.text_parts, node.attr_text("href")):
            cleaned = normalize_space(value.strip(" -|,;"))
            if not title and _is_valid_flat_academic_title(cleaned):
                title = cleaned
            if not email and (match := EMAIL_RE.search(value)):
                email = match.group(0)
        if title and email:
            break
    return title, email


def _is_flat_person_detail_heading(value: str) -> bool:
    normalized = _normalize_key(value).strip(" .:-")
    if not normalized or _is_valid_flat_academic_title(value):
        return True
    return bool(
        EMAIL_RE.search(value)
        or re.search(r"\b(?:office|phone|telephone|e-?mail|lab\s+(?:page|website)|room|website)\b", normalized)
    )


def _is_valid_flat_academic_title(value: str) -> bool:
    if _has_valid_academic_title(value):
        return True
    return bool(
        re.fullmatch(
            r"(?:(?:visiting|adjunct|honorary)\s+)?(?:(?:assoc(?:iate)?|asst|assistant)\.?\s+)?prof\.?",
            normalize_space(value),
            flags=re.IGNORECASE,
        )
    )


def _is_bounded_local_person_page(value: str, base_url: str) -> bool:
    parsed = urlparse(value)
    base = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != base.netloc.lower():
        return False
    if _is_generic_policy_url(value) or _is_organizational_card_profile_url(value):
        return False
    if parsed.path.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp")):
        return False
    segments = {segment.casefold() for segment in parsed.path.split("/") if segment}
    if segments & {"category", "categories", "search", "tag", "tags"}:
        return False
    query_keys = {key.casefold() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if query_keys & {"cat", "category", "category_name", "s", "search", "tag"}:
        return False
    if not parsed.path.strip("/") and not _opaque_query_pairs(value):
        return False
    return _opaque_local_page_key(value) != _opaque_local_page_key(base_url)


def _opaque_local_page_key(value: str) -> str:
    parsed = urlparse(value)
    path = parsed.path.rstrip("/") or "/"
    query = urlencode(sorted(_opaque_query_pairs(value), key=lambda pair: (pair[0].casefold(), pair[1].casefold())))
    return parsed._replace(path=path, query=query, fragment="").geturl().lower()


def _opaque_query_pairs(value: str) -> list[tuple[str, str]]:
    return [
        (key, item)
        for key, item in parse_qsl(urlparse(value).query, keep_blank_values=True)
        if item.strip() and not key.casefold().startswith("utm_") and key.casefold() not in {"fbclid", "gclid"}
    ]


def _repeated_person_link_patterns(root: _Node, base_url: str) -> set[str]:
    counts: Counter[str] = Counter()
    for search_root in _fallback_search_roots(root):
        for link in _links_in(search_root):
            if _is_inside_repeated_person_link_skipped_region(link):
                continue
            pattern = _repeated_person_link_pattern(link.attr_text("href"), base_url)
            if pattern:
                counts[pattern] += 1
    return {pattern for pattern, count in counts.items() if count >= 2}


def _repeated_person_link_pattern(href: str, base_url: str) -> str:
    if not _is_candidate_profile_href(href):
        return ""
    lowered = href.lower()
    if "void(0)" in lowered or lowered.startswith("javascript:"):
        return ""
    absolute_url = urljoin(base_url, href)
    parsed = urlparse(absolute_url)
    base = urlparse(base_url)
    if _is_itu_rehber_search_url(absolute_url):
        return f"{parsed.netloc}{parsed.path.lower().rstrip('/')}"
    if base.netloc and parsed.netloc and parsed.netloc != base.netloc:
        return ""

    path = parsed.path.lower().rstrip("/")
    query_keys = {key.casefold() for key in parse_qs(parsed.query, keep_blank_values=True)}
    if _is_locale_scoped_short_profile_url(absolute_url):
        return f"{parsed.netloc}/{'/'.join(path.strip('/').split('/')[:-1])}"
    is_person_like = (
        any(hint in path for hint in PROFILE_PATH_HINTS)
        or "detalle-investigadores-cv" in path
        or bool(query_keys & {"investigadorid", "personid", "profileid", "staffid", "stref"})
    )
    if not is_person_like or path == base.path.lower().rstrip("/"):
        return ""
    return f"{parsed.netloc}{path}"


def _normalize_person_link_url(value: str) -> str:
    if _is_itu_rehber_search_url(value):
        parsed = urlparse(value)
        path = parsed.path.rstrip("/")
        return parsed._replace(path=path, fragment="").geturl().lower()
    return _normalize_record_profile_url(value)


def _is_inside_repeated_person_link_skipped_region(node: _Node) -> bool:
    if _is_inside_skipped_region(node):
        return True
    skip_tokens = {
        "nav",
        "menu",
        "footer",
        "header",
        "search",
        "breadcrumb",
        "metadata",
        "sidebar",
        "cookie",
        "privacy",
        "consent",
    }
    utility_hints = ("quick-link", "quicklink", "cookie-preference", "privacy-preference")
    for ancestor in node.ancestors():
        if ancestor.tag in {"main", "article"} or _is_fallback_search_root(ancestor):
            break
        if ancestor.tag in {"nav", "footer", "header"}:
            return True
        class_id = _node_class_id(ancestor)
        tokens = {token for token in re.split(r"[^a-z0-9]+", class_id) if token}
        if tokens & skip_tokens or any(hint in class_id for hint in utility_hints):
            return True
    return False


def _record_from_repeated_person_link(link: _Node, base_url: str) -> tuple[FacultyRecord | None, dict[str, object]]:
    context = _repeated_person_link_context(link)
    name = _fallback_nearby_name(context) or _fallback_nearby_name(link)
    profile_url = _recover_card_profile_url(context, base_url, name) if name else ""
    if not profile_url:
        profile_url = urljoin(base_url, link.attr_text("href"))
    title = _extract_title(context, name) if name else ""
    reason = "ok"
    record: FacultyRecord | None = None

    if not name:
        reason = "missing_name"
    elif not _looks_like_name(name):
        reason = "invalid_name"
    elif not title:
        reason = "missing_title"
    elif _is_non_faculty_member_title(title):
        reason = "non_faculty_title"
    else:
        record = FacultyRecord(name=name, title=title, profile_url=profile_url)

    return record, {
        "link_text": normalize_space(link.text())[:160],
        "href": link.attr_text("href"),
        "name": name,
        "inferred_title": title,
        "drop_reason": reason,
    }


def _repeated_person_link_context(link: _Node) -> _Node:
    for ancestor in link.ancestors():
        if ancestor.tag in SKIP_TAGS:
            break
        if _is_navigation_or_category_block(ancestor):
            continue
        if _fallback_nearby_name(ancestor):
            return ancestor
    return link


def _fallback_nearby_name(container: _Node) -> str:
    for node in container.descendants():
        if "name" not in _node_class_id(node):
            continue
        name = _clean_name(node.text())
        if _looks_like_name(name):
            return name
    for image in _nodes_by_tag(container, "img"):
        alt = re.sub(r"^image:\s*", "", image.attr_text("alt"), flags=re.IGNORECASE)
        if _is_generic_person_image_alt(alt):
            continue
        name = _clean_name(alt)
        if _looks_like_name(name):
            return name
    name = _extract_name(container)
    if name and not _is_cv_action_text(name):
        return name
    return ""


def _recover_accordion_person_records(
    root: _Node, base_url: str
) -> tuple[list[FacultyRecord], int, set[str]]:
    nodes = list(root.descendants())
    candidates: list[tuple[int, _Node, str, str]] = []
    active_role = ""

    for index, node in enumerate(nodes):
        role = _accordion_role_group_heading(node)
        if role:
            active_role = role
            continue
        if node.tag == "h1":
            active_role = ""
            continue
        if node.tag != "h2":
            continue
        name = normalize_space(node.text()).strip(" -|,;")
        if (
            not _looks_like_heading_person_name(name)
            or _is_bad_name_candidate(name)
            or _is_accordion_utility_label(name)
        ):
            continue
        title = active_role or _accordion_person_heading_title(name)
        candidates.append((index, node, name, title))

    if len(candidates) < 2:
        return [], 0, set()

    records: list[FacultyRecord] = []
    profile_urls: set[str] = set()
    for heading_index, _, name, title in candidates:
        start = heading_index + 1
        end = len(nodes)
        for position in range(start, len(nodes)):
            node = nodes[position]
            if _accordion_role_group_heading(node):
                end = position
                break
            if node.tag == "h2":
                following_name = normalize_space(node.text()).strip(" -|,;")
                if _looks_like_heading_person_name(following_name) and not _is_bad_name_candidate(following_name):
                    end = position
                    break

        block_nodes = nodes[start:end]
        profile_url = _accordion_website_profile_url(block_nodes, base_url)
        if profile_url:
            profile_urls.add(_normalize_record_profile_url(profile_url))
        if not title or not _has_valid_academic_title(title):
            continue
        if _is_emeritus_academic_title(title) or _is_non_faculty_member_title(title):
            continue
        if not profile_url:
            continue
        records.append(
            FacultyRecord(
                name=name,
                title=title,
                profile_url=profile_url,
                email=_accordion_block_email(block_nodes),
            )
        )

    return records, len(candidates), profile_urls


def _accordion_role_group_heading(node: _Node) -> str:
    if node.tag not in {"h2", "h3"}:
        return ""
    text = normalize_space(node.text())
    if not text or len(text) > 100 or _is_accordion_utility_label(text):
        return ""
    normalized = _normalize_key(text)
    role_terms = ("professors", "professorships", "privatdozent", "faculty", "lecturers", "readers")
    return text if any(term in normalized for term in role_terms) else ""


def _accordion_person_heading_title(name: str) -> str:
    if re.match(r"^(?:apl\.\s+|hon\.-?\s*)?prof\.", name, flags=re.IGNORECASE):
        return "Professor"
    if re.match(r"^PD\b", name, flags=re.IGNORECASE):
        return "Privatdozent"
    return ""


def _accordion_website_profile_url(nodes: list[_Node], base_url: str) -> str:
    for link in nodes:
        if link.tag != "a" or _normalize_key(link.text()) != "website":
            continue
        href = link.attr_text("href")
        if not _is_candidate_profile_href(href):
            continue
        absolute_url = urljoin(base_url, href)
        parsed = urlparse(absolute_url)
        base = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if _is_page_profile_url(absolute_url, base_url) or _is_organizational_card_profile_url(absolute_url):
            continue
        segments = {segment.casefold() for segment in parsed.path.split("/") if segment}
        if segments & {"publication", "publications", "research"}:
            continue
        if _is_same_institution_host(parsed.netloc, base.netloc) or _is_trusted_external_academic_profile_url(
            absolute_url, base_url
        ):
            return absolute_url
    return ""


def _accordion_block_email(nodes: list[_Node]) -> str:
    for node in nodes:
        values = [*node.text_parts]
        if node.tag == "a":
            values.append(node.attr_text("href"))
        for value in values:
            match = EMAIL_RE.search(value)
            if match:
                return match.group(0)
    return ""


def _is_accordion_utility_label(value: str) -> bool:
    return _normalize_key(value) in ACCORDION_UTILITY_LABELS


def _is_cv_action_text(value: str) -> bool:
    return _normalize_key(value) in {"view cv", "see cv", "view curriculum vitae", "see curriculum vitae"}


def _recover_heading_person_records(root: _Node, base_url: str) -> tuple[list[FacultyRecord], int, int, list[dict[str, object]]]:
    records: list[FacultyRecord] = []
    debug: list[dict[str, object]] = []
    candidate_count = 0
    recovered_count = 0
    seen_names: set[str] = set()

    section_default_title = ""
    for heading in (node for node in root.descendants() if node.tag in {"h1", "h2", "h3", "h4"}):
        if _is_inside_repeated_person_link_skipped_region(heading):
            continue
        heading_text = normalize_space(heading.text())
        section_title = _faculty_heading_default_title(heading_text)
        if section_title:
            section_default_title = section_title
            continue
        if heading.tag == "h1":
            section_default_title = ""
            continue
        if not section_default_title:
            continue

        name = _clean_name(heading_text)
        if not _looks_like_heading_person_name(name) or _is_bad_name_candidate(name):
            if len(debug) < 5:
                debug.append(
                    {
                        "heading_text": heading_text,
                        "accepted": False,
                        "reject_reason": "not_person_name",
                        "nearest_profile_url": "",
                        "email_found": "",
                    }
                )
            continue
        name_key = _normalize_key(name)
        if name_key in seen_names:
            continue
        seen_names.add(name_key)

        context = _heading_person_context(heading)
        profile_url, recovered_url = _recover_profile_url_for_heading(heading, context, base_url)
        email = _extract_email(context)
        candidate_count += 1
        if profile_url:
            recovered_count += 1

        title = _extract_title(context, name) or ("Dosen" if section_default_title == "Dosen" else "")
        reason = ""
        if not profile_url:
            reason = "missing_profile_url"
        elif not title:
            reason = "missing_title"
        record = FacultyRecord(name=name, title=title, profile_url=profile_url, email=email) if not reason else None
        if len(debug) < 5:
            debug.append(
                {
                    "heading_text": heading_text,
                    "accepted": record is not None,
                    "reject_reason": reason,
                    "nearest_profile_url": profile_url,
                    "email_found": email,
                    "name": name,
                    "heading_name": name,
                    "recovered_url": recovered_url,
                    "inferred_title": title,
                    "profile_url_source": "acadstaff_link" if "acadstaff.ugm.ac.id" in profile_url else "nearby_profile_link",
                    "section_default_title": section_default_title,
                    "drop_reason": reason or "ok",
                }
            )
        if record is not None:
            records.append(record)

    return records, candidate_count, recovered_count, debug


def _recover_heading_card_records(
    root: _Node, base_url: str
) -> tuple[list[FacultyRecord], int, int, list[dict[str, object]]]:
    records: list[FacultyRecord] = []
    debug: list[dict[str, object]] = []
    candidate_count = 0
    generic_link_count = 0
    seen_contexts: set[int] = set()

    for heading in root.descendants():
        if heading.tag not in {"h4", "h5", "h6"} or _is_inside_skipped_region(heading):
            continue
        name = _clean_name(heading.text())
        if not _looks_like_heading_person_name(name) or _is_bad_name_candidate(name):
            continue
        context = _heading_card_context(heading)
        if context is None or id(context) in seen_contexts:
            continue
        seen_contexts.add(id(context))
        candidate_count += 1

        profile_link = _generic_profile_link(context)
        title = _extract_title(context, name)
        profile_url = urljoin(base_url, profile_link.attr_text("href")) if profile_link is not None else ""
        if profile_link is not None:
            generic_link_count += 1
        reason = ""
        if not title:
            reason = "missing_title"
        elif _is_non_faculty_member_title(title):
            reason = "non_faculty_title"
        elif not profile_url or _is_page_profile_url(profile_url, base_url):
            reason = "missing_profile_url"
        if not reason:
            records.append(
                FacultyRecord(
                    name=name,
                    title=_strip_name_prefix(title, name),
                    profile_url=profile_url,
                    email=_extract_email(context),
                )
            )
        if len(debug) < 10:
            debug.append(
                {
                    "candidate_name": name,
                    "candidate_title": title,
                    "profile_url": profile_url,
                    "reject_reason": reason or "ok",
                }
            )
    return records, candidate_count, generic_link_count, debug


def _recover_role_group_records(
    root: _Node, base_url: str
) -> tuple[list[FacultyRecord], int, int, list[dict[str, object]]]:
    records: list[FacultyRecord] = []
    debug: list[dict[str, object]] = []
    active_role = ""
    roles_with_rows: set[str] = set()
    person_rows = 0

    for node in root.descendants():
        if node.tag in {"h2", "h3"}:
            heading = normalize_space(node.text())
            active_role = heading if _is_academic_role_heading(heading) else ""
            continue
        if node.tag != "a" or not active_role:
            continue
        href = node.attr_text("href")
        profile_url = urljoin(base_url, href)
        if not _is_meaningful_query_person_url(profile_url, base_url):
            continue
        person_rows += 1
        raw_link_text = normalize_space(node.text())
        name = _strip_trailing_phone(raw_link_text)
        reason = ""
        if not _looks_like_heading_person_name(name) or _is_bad_name_candidate(name):
            reason = "invalid_name"
        elif not _has_valid_academic_title(active_role):
            reason = "non_academic_role"
        if not reason:
            context = next((ancestor for ancestor in node.ancestors() if ancestor.tag in {"li", "tr"}), node.parent or node)
            records.append(
                FacultyRecord(
                    name=name,
                    title=active_role,
                    profile_url=profile_url,
                    email=_extract_email(context),
                )
            )
            roles_with_rows.add(_normalize_key(active_role))
        if len(debug) < 10:
            debug.append(
                {
                    "inherited_role_title": active_role,
                    "raw_person_link_text": raw_link_text,
                    "normalized_profile_url": _normalize_record_profile_url(profile_url),
                    "reject_reason": reason or "ok",
                }
            )
    return records, len(roles_with_rows), person_rows, debug


def _recover_repeated_listing_subpage_records(
    root: _Node, base_url: str
) -> tuple[list[FacultyRecord], int, int, int, int, int]:
    grouped: dict[str, dict[str, object]] = {}
    order: list[str] = []
    active_role = ""
    total_links = 0

    for node in root.descendants():
        if node.tag in {"h4", "h5"}:
            heading = normalize_space(node.text())
            active_role = heading if _has_valid_academic_title(heading) else ""
            continue
        if node.tag != "a" or not active_role:
            continue
        profile_url = urljoin(base_url, node.attr_text("href"))
        if not _is_listing_subpage_profile_url(profile_url, base_url):
            continue
        total_links += 1
        key = _normalize_record_profile_url(profile_url)
        if key not in grouped:
            grouped[key] = {"url": profile_url, "role": active_role, "texts": []}
            order.append(key)
        text = _clean_name(node.text())
        if text:
            grouped[key]["texts"].append(text)

    records: list[FacultyRecord] = []
    excluded_sections = 0
    for key in order:
        item = grouped[key]
        role = str(item["role"])
        if any(term in _normalize_key(role) for term in ("emeritus", "emerita")):
            excluded_sections += 1
            continue
        names = [
            text
            for text in item["texts"]
            if _looks_like_heading_person_name(text) and not _is_bad_name_candidate(text)
        ]
        if not names or _is_non_faculty_member_title(role):
            continue
        records.append(FacultyRecord(name=max(names, key=len), title=role, profile_url=str(item["url"])))

    unique_count = len(grouped)
    return (
        records,
        total_links,
        unique_count,
        len(records),
        max(0, total_links - unique_count),
        excluded_sections,
    )


def _recover_segmented_wrapper_records(
    root: _Node, base_url: str
) -> tuple[list[FacultyRecord], int, int, list[dict[str, object]], int, int, int, int]:
    nodes: list[_Node] = []
    for search_root in _fallback_search_roots(root):
        nodes.extend(search_root.descendants())

    person_links: list[_Node] = []
    seen_urls: dict[str, int] = {}
    for node in nodes:
        if node.tag != "a" or _is_inside_repeated_person_link_skipped_region(node):
            continue
        if any(
            re.match(
                r"^(?:image|photo(?:graph)?|picture|credit|image credit|photo credit|copyright|bild|foto|©)\b",
                chunk,
                flags=re.IGNORECASE,
            )
            for chunk in node.text_chunks()
        ):
            continue
        structural_name, _ = _segmented_link_structural_fields(node)
        flattened_name, _ = _split_flattened_name_title_contact(node.text())
        trailing_name, _ = _split_trailing_academic_title(node.text())
        name = structural_name or flattened_name or trailing_name or _clean_name(node.text())
        if not _is_segmented_person_link_name(name):
            continue
        profile_url = urljoin(base_url, node.attr_text("href"))
        if not _is_local_person_profile_candidate(profile_url, base_url):
            continue
        key = _normalize_record_profile_url(profile_url)
        if key in seen_urls:
            existing_index = seen_urls[key]
            if _ancestor_by_tag(node, "li") is not None and _ancestor_by_tag(person_links[existing_index], "li") is None:
                person_links[existing_index] = node
            continue
        seen_urls[key] = len(person_links)
        person_links.append(node)

    person_url_keys = set(seen_urls)
    ordered_events = list(_ordered_content_events(root))
    event_indexes = {id(event): index for index, event in enumerate(ordered_events) if isinstance(event, _Node)}
    discipline_terms = _page_discipline_terms(base_url)
    records: list[FacultyRecord] = []
    debug: list[dict[str, object]] = []
    academic_section_count = 0
    administrative_exclusion_count = 0
    emeritus_exclusion_count = 0
    flattened_name_title_split_count = 0

    for index, link in enumerate(person_links):
        start = event_indexes.get(id(link), -1) + 1
        end = event_indexes.get(id(person_links[index + 1]), len(ordered_events)) if index + 1 < len(person_links) else len(ordered_events)
        person_entry = _segmented_person_entry_container(link, base_url, person_url_keys)
        if person_entry is not None:
            entry_event_indexes = [
                event_index
                for event_index, event in enumerate(ordered_events)
                if _ordered_event_is_inside(event, person_entry)
            ]
            if entry_event_indexes:
                end = min(end, entry_event_indexes[-1] + 1)
        row = next((ancestor for ancestor in link.ancestors() if ancestor.tag == "tr"), None)
        if row is not None and sum(1 for candidate in person_links if candidate is link or row in candidate.ancestors()) == 1:
            row_event_indexes = [
                event_index
                for event_index, event in enumerate(ordered_events)
                if _ordered_event_is_inside(event, row)
            ]
            if row_event_indexes:
                end = min(end, row_event_indexes[-1] + 1)
        structural_name, structural_title = _segmented_link_structural_fields(link)
        flattened_name, flattened_title = _split_flattened_name_title_contact(link.text())
        if flattened_name and flattened_title:
            flattened_name_title_split_count += 1
        name = structural_name or flattened_name or _clean_name(link.text())
        entry_title = _segmented_entry_local_title(person_entry, link)
        group_title = _bounded_segmented_group_title(link, base_url, person_url_keys, person_entry)
        initial_title = structural_title or flattened_title or entry_title
        title_candidates: list[str] = []
        for title in (group_title, initial_title):
            if title and title not in title_candidates:
                title_candidates.append(title)
        block_text_parts: list[str] = []
        email = _extract_email(link)
        for event in ordered_events[start:end]:
            if isinstance(event, _Node):
                if event.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and link not in event.ancestors():
                    break
                continue
            owner, text = event
            if owner is link or link in owner.ancestors():
                continue
            cleaned = normalize_space(text.strip(" -|,;"))
            if not cleaned:
                continue
            block_text_parts.append(cleaned)
            if not email:
                match = EMAIL_RE.search(cleaned)
                if match:
                    email = match.group(0)
            if (
                (_is_title_text(cleaned) and not _is_segmented_person_link_name(cleaned))
                or _validated_trailing_academic_title(cleaned) == cleaned
            ) and cleaned not in title_candidates:
                title_candidates.append(cleaned)
        selected_title = group_title or next(
            (title for title in title_candidates if any(term in _normalize_key(title) for term in discipline_terms)),
            title_candidates[0] if title_candidates else "",
        )
        if not selected_title:
            combined_block_text = normalize_space(" ".join([link.text(), *block_text_parts]))
            split_name, split_title = _split_trailing_academic_title(combined_block_text)
            if split_name and split_title:
                name = split_name
                selected_title = split_title
        prefix_title_context = bool(
            (person_entry is not None and person_entry.tag == "li")
            or (link.parent is not None and link.parent.tag in {"h1", "h2", "h3", "h4", "h5", "h6"})
        )
        if not selected_title and prefix_title_context:
            academic_prefix = re.match(r"^(Professor|Prof\.?|Dr\.?)\s+", name, flags=re.IGNORECASE)
            if academic_prefix:
                selected_title = "Professor" if academic_prefix.group(1).lower().startswith("prof") else "Dr."
                title_candidates.append(selected_title)
        section_heading = _nearest_directory_section_heading(link)
        normalized_section = _normalize_key(section_heading)
        reason = ""
        if normalized_section in EXCLUDED_DIRECTORY_SECTIONS:
            reason = "excluded_section"
            administrative_exclusion_count += 1
        elif _is_emeritus_academic_title(entry_title) or _is_emeritus_academic_title(selected_title):
            reason = "emeritus_title"
            emeritus_exclusion_count += 1
        elif entry_title and _is_non_faculty_member_title(entry_title):
            reason = "non_faculty_title"
        elif not selected_title:
            reason = "missing_title"
        elif _is_non_faculty_member_title(selected_title):
            reason = "non_faculty_title"
        if normalized_section == "academic staff":
            academic_section_count += 1
        profile_url = urljoin(base_url, link.attr_text("href"))
        if not reason:
            records.append(
                FacultyRecord(
                    name=name,
                    title=selected_title,
                    profile_url=profile_url,
                    email=email,
                )
            )
        if len(debug) < 25:
            debug.append(
                {
                    "block_name": name,
                    "block_title_candidates": title_candidates,
                    "selected_title": selected_title,
                    "block_profile_url": profile_url,
                    "section_heading": section_heading,
                    "reject_reason": reason or "ok",
                }
            )
    return (
        records,
        len(person_links),
        len(person_links),
        debug,
        academic_section_count,
        administrative_exclusion_count,
        emeritus_exclusion_count,
        flattened_name_title_split_count,
    )


def _recover_professorship_linked_name_records(
    root: _Node, base_url: str
) -> tuple[list[FacultyRecord], int, list[dict[str, object]]]:
    links: list[_Node] = []
    seen_urls: set[str] = set()
    for search_root in _fallback_search_roots(root):
        for link in _links_in(search_root):
            if _is_inside_repeated_person_link_skipped_region(link):
                continue
            section = _normalize_key(_nearest_directory_section_heading(link))
            if not any(term in section for term in ("professorship", "chair")) or any(
                term in section for term in ("deputy", "emerit")
            ):
                continue
            profile_url = urljoin(base_url, link.attr_text("href"))
            if not _is_local_person_profile_candidate(profile_url, base_url):
                continue
            key = _normalize_record_profile_url(profile_url)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            links.append(link)

    person_url_keys = set(seen_urls)
    records: list[FacultyRecord] = []
    debug: list[dict[str, object]] = []
    for link in links:
        entry = _segmented_person_entry_container(link, base_url, person_url_keys) or link.parent or link
        names: dict[str, str] = {}
        for chunk in entry.text_chunks():
            text = re.sub(r"\s*\([^()]*\)\s*$", "", normalize_space(chunk))
            name = _linked_teaser_person_name(text, dedicated=False)
            if name:
                names[_normalize_key(name)] = name
        title = normalize_space(link.text().strip(" -|,;"))
        profile_url = urljoin(base_url, link.attr_text("href"))
        reason = ""
        if len(names) != 1:
            reason = "missing_or_ambiguous_local_name"
        elif not title or len(title) > 180 or EMAIL_RE.search(title) or _is_generic_link_text(title):
            reason = "invalid_professorship_title"
        if not reason:
            records.append(
                FacultyRecord(
                    name=next(iter(names.values())),
                    title=title,
                    profile_url=profile_url,
                    email=_extract_email(entry),
                )
            )
        if len(debug) < 25:
            debug.append(
                {
                    "block_name": next(iter(names.values()), ""),
                    "block_title_candidates": [title] if title else [],
                    "selected_title": title,
                    "block_profile_url": profile_url,
                    "section_heading": _nearest_directory_section_heading(link),
                    "reject_reason": reason or "ok",
                }
            )
    return records, len(records), debug


def _ordered_content_events(node: _Node) -> Iterable[_Node | tuple[_Node, str]]:
    for part in node.content_parts:
        if isinstance(part, _Node):
            yield part
            yield from _ordered_content_events(part)
        else:
            yield node, part


def _nearest_directory_section_heading(node: _Node) -> str:
    current: _Node | None = node
    while current is not None and current.parent is not None:
        siblings = current.parent.children
        try:
            index = siblings.index(current)
        except ValueError:
            index = 0
        for sibling in reversed(siblings[:index]):
            headings = [
                candidate
                for candidate in (sibling, *sibling.descendants())
                if candidate.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}
                and not _looks_like_heading_person_name(_clean_name(candidate.text()))
            ]
            if headings:
                return normalize_space(headings[-1].text())
        current = current.parent
    return ""


def _ordered_event_is_inside(event: _Node | tuple[_Node, str], container: _Node) -> bool:
    node = event if isinstance(event, _Node) else event[0]
    return node is container or container in node.ancestors()


def _segmented_person_entry_container(
    link: _Node, base_url: str, person_url_keys: set[str]
) -> _Node | None:
    profile_key = _normalize_record_profile_url(urljoin(base_url, link.attr_text("href")))
    entry: _Node | None = None
    for ancestor in link.ancestors():
        if ancestor.tag in SKIP_TAGS:
            break
        if ancestor.tag not in CONTAINER_TAGS:
            continue
        local_keys = _segmented_person_url_keys(ancestor, base_url, person_url_keys)
        if profile_key not in local_keys:
            continue
        if len(local_keys) > 1:
            break
        entry = ancestor
    return entry


def _segmented_entry_local_title(person_entry: _Node | None, link: _Node) -> str:
    if person_entry is None:
        return ""
    entry_text = normalize_space(person_entry.text())
    link_text = normalize_space(link.text())
    position = entry_text.find(link_text)
    if position < 0:
        return ""
    title = normalize_space(f"{entry_text[:position]} {entry_text[position + len(link_text):]}")
    if not title or len(title) > 140 or EMAIL_RE.search(title):
        return ""
    if re.fullmatch(r"\([^()]+\)", title) or _is_title_text(title):
        return title
    return ""


def _segmented_person_url_keys(container: _Node, base_url: str, person_url_keys: set[str]) -> set[str]:
    return {
        key
        for link in _links_in(container)
        if (key := _normalize_record_profile_url(urljoin(base_url, link.attr_text("href")))) in person_url_keys
    }


def _bounded_segmented_group_title(
    link: _Node,
    base_url: str,
    person_url_keys: set[str],
    person_entry: _Node | None,
) -> str:
    current = person_entry or link.parent
    while current is not None and current.parent is not None:
        parent = current.parent
        siblings = parent.children
        try:
            index = siblings.index(current)
        except ValueError:
            index = 0
        for sibling in reversed(siblings[:index]):
            if _segmented_person_url_keys(sibling, base_url, person_url_keys):
                continue
            for chunk in reversed(sibling.text_chunks()):
                title = normalize_space(chunk.strip(" -|,;"))
                if (
                    _is_title_text(title)
                    and _has_valid_academic_title(title)
                    and not _is_segmented_person_link_name(_clean_name(title))
                ):
                    return title
            if normalize_space(sibling.text()):
                break
        if parent.tag in SKIP_TAGS:
            break
        current = parent

    current = person_entry or link.parent
    branching_person_levels = 0
    while current is not None and current.parent is not None:
        parent = current.parent
        if parent.tag in SKIP_TAGS:
            break
        siblings = [sibling for sibling in parent.children if sibling is not current]
        parent_keys = _segmented_person_url_keys(parent, base_url, person_url_keys)
        if len(parent_keys) > 1 and siblings:
            titles: dict[str, str] = {}
            for sibling in siblings:
                if _segmented_person_url_keys(sibling, base_url, person_url_keys):
                    continue
                for chunk in sibling.text_chunks():
                    title = normalize_space(chunk.strip(" -|,;"))
                    if (
                        _is_title_text(title)
                        and _has_valid_academic_title(title)
                        and not _is_segmented_person_link_name(_clean_name(title))
                    ):
                        titles.setdefault(_normalize_key(title), title)
            if len(titles) == 1:
                return next(iter(titles.values()))
            branching_person_levels += 1
            if branching_person_levels >= 2:
                break
        current = parent
    return ""


def _is_segmented_person_link_name(value: str) -> bool:
    if not _looks_like_heading_person_name(value):
        return False
    if not _is_bad_name_candidate(value):
        return True
    match = re.match(r"^(?:Professor|Prof\.?|Dr\.?|Mr\.?|Mrs\.?|Ms\.?)\s+(.+)$", value, flags=re.IGNORECASE)
    return bool(match and _looks_like_heading_person_name(match.group(1)))


def _segmented_link_structural_fields(link: _Node) -> tuple[str, str]:
    title_nodes = [
        node
        for node in link.descendants()
        if normalize_space(node.text())
        and len(normalize_space(node.text())) <= 140
        and not EMAIL_RE.search(node.text())
        and _has_valid_academic_title(node.text())
        and not _is_segmented_person_link_name(_clean_name(node.text()))
    ]
    if not title_nodes:
        return "", ""

    title = normalize_space(title_nodes[-1].text().strip(" -|,;"))
    heading_name = next(
        (
            _clean_name(node.text())
            for node in link.descendants()
            if (
                node.tag in {"strong", "b", "h2", "h3", "h4", "h5", "h6"}
                or any(hint in _node_class_id(node) for hint in ("fullname", "full-name", "person-name"))
            )
            and node not in title_nodes
            and _looks_like_heading_person_name(_clean_name(node.text()))
        ),
        "",
    )
    direct_name = _clean_name(" ".join(link.text_parts))
    name = heading_name or (direct_name if _looks_like_heading_person_name(direct_name) else "")
    return name, title


def _split_flattened_name_title_contact(value: str) -> tuple[str, str]:
    value = normalize_space(value)
    if "," not in value:
        return "", ""
    raw_name, remainder = value.split(",", 1)
    name = _clean_name(raw_name)
    if not _looks_like_heading_person_name(name) or _is_bad_name_candidate(name):
        return "", ""

    boundaries = [len(remainder)]
    email_match = EMAIL_RE.search(remainder)
    if email_match:
        boundaries.append(email_match.start())
    phone_match = re.search(r"(?:\+?\d[\d\s().-]{5,})", remainder)
    if phone_match:
        boundaries.append(phone_match.start())
    title = normalize_space(remainder[: min(boundaries)].strip(" -|,;"))
    if not title or not _has_valid_academic_title(title) or EMAIL_RE.search(title) or re.search(r"\d", title):
        return "", ""
    return name, title


def _split_trailing_academic_title(value: str) -> tuple[str, str]:
    title = _validated_trailing_academic_title(value)
    if not title:
        return "", ""
    name = _clean_name(value[: -len(title)])
    if not _looks_like_heading_person_name(name):
        return "", ""
    return name, title


def _validated_trailing_academic_title(value: str) -> str:
    value = normalize_space(value)
    for title in SPANISH_ACADEMIC_TITLE_SUFFIXES:
        match = re.search(rf"{re.escape(title)}$", value, flags=re.IGNORECASE)
        if match:
            matched_title = value[match.start() :]
            if _has_valid_academic_title(matched_title):
                return matched_title
    return ""


def _is_local_person_profile_candidate(value: str, base_url: str) -> bool:
    parsed = urlparse(value)
    base = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not _is_same_institution_host(parsed.netloc, base.netloc):
        return False
    if _is_generic_policy_url(value):
        return False
    if _normalize_record_profile_url(value) == _normalize_record_profile_url(base_url):
        return False
    return bool(parsed.path.strip("/") and not parsed.path.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".svg")))


def _page_discipline_terms(base_url: str) -> set[str]:
    ignored = {"people", "person", "faculty", "staff", "academic", "bio", "www", "html"}
    return {
        _normalize_key(part)
        for part in urlparse(base_url).path.split("/")
        if len(part) >= 4 and _normalize_key(part) not in ignored
    }


def _is_listing_subpage_profile_url(value: str, base_url: str) -> bool:
    parsed = urlparse(value)
    base = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != base.netloc.lower():
        return False
    base_path = base.path.rstrip("/")
    if not base_path.lower().endswith((".html", ".htm")):
        return False
    listing_stem = re.sub(r"\.html?$", "", base_path, flags=re.IGNORECASE)
    candidate_path = parsed.path.rstrip("/")
    return (
        candidate_path.lower().endswith((".html", ".htm"))
        and candidate_path.rsplit("/", 1)[0].lower() == listing_stem.lower()
        and candidate_path.lower() != base_path.lower()
    )


def _is_academic_role_heading(value: str) -> bool:
    normalized = _normalize_key(value)
    if normalized in {"personale docente", "docenti", "faculty", "academic staff", "teaching staff"}:
        return False
    if any(term in normalized for term in ("amministrativ", "emerit", "dottorand", "tecnico", "onorario")):
        return False
    return any(term in normalized for term in ("professore", "ricercatore", "docente", "insegnamento"))


def _strip_trailing_phone(value: str) -> str:
    return normalize_space(re.sub(r"\s+\+?\d[\d\s()./-]{5,}$", "", value).strip(" -|,;"))


def _heading_card_context(heading: _Node) -> _Node | None:
    for ancestor in heading.ancestors():
        if ancestor.tag in SKIP_TAGS:
            break
        if ancestor.tag not in CONTAINER_TAGS:
            continue
        person_headings = [
            node
            for node in ancestor.descendants()
            if node.tag in {"h4", "h5", "h6"}
            and _looks_like_heading_person_name(_clean_name(node.text()))
            and not _is_bad_name_candidate(_clean_name(node.text()))
        ]
        if len(person_headings) != 1:
            continue
        if _extract_title(ancestor, _clean_name(heading.text())) and _generic_profile_link(ancestor) is not None:
            return ancestor
    return None


def _generic_profile_link(container: _Node) -> _Node | None:
    supported = {"ver perfil", "perfil", "view profile", "profile", "read profile", "more details"}
    for link in _links_in(container):
        if _normalize_key(link.text()) in supported and _is_candidate_profile_href(link.attr_text("href")):
            return link
    return None


def _person_heading_nodes(root: _Node) -> list[_Node]:
    headings: list[_Node] = []
    for node in root.descendants():
        if node.tag not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            continue
        name = _clean_name(node.text())
        if _looks_like_name(name) and not _is_bad_name_candidate(name):
            headings.append(node)
    return headings


def _heading_person_context(heading: _Node) -> _Node:
    for ancestor in heading.ancestors():
        if ancestor.tag in SKIP_TAGS:
            break
        if "elementor-column" in _node_class_id(ancestor):
            return ancestor
    for ancestor in heading.ancestors():
        if ancestor.tag in SKIP_TAGS:
            break
        if ancestor.tag in {"article", "li"}:
            return ancestor
        if ancestor.tag == "div" and ancestor.parent is not None and ancestor.parent.tag in {"main", "section", "article", "li", "div"}:
            return ancestor
        if any(hint in _node_class_id(ancestor) for hint in ("card", "expert", "person", "people", "profile", "item")):
            return ancestor
    return heading.parent or heading


def _recover_profile_url_for_heading(heading: _Node, context: _Node, base_url: str) -> tuple[str, str]:
    candidates: list[str] = []
    for ancestor in (heading, *heading.ancestors()):
        if ancestor.tag in SKIP_TAGS:
            break
        if ancestor.tag == "a":
            candidates.append(ancestor.attr_text("href"))
        candidates.extend(_node_embedded_urls(ancestor))
        if ancestor is context:
            break

    candidates.extend(link.attr_text("href") for link in _links_in(heading))
    candidates.extend(link.attr_text("href") for link in _links_in(context))
    for sibling in _nearby_siblings(heading):
        if sibling.tag == "a":
            candidates.append(sibling.attr_text("href"))
        candidates.extend(link.attr_text("href") for link in _links_in(sibling))
        candidates.extend(_node_embedded_urls(sibling))
    for sibling in _nearby_siblings(context):
        if sibling.tag == "a":
            candidates.append(sibling.attr_text("href"))
        candidates.extend(link.attr_text("href") for link in _links_in(sibling))
        candidates.extend(_node_embedded_urls(sibling))

    for value in candidates:
        if value.startswith("/http://") or value.startswith("/https://"):
            value = value[1:]
        if _is_recovered_heading_profile_url(value, base_url):
            return urljoin(base_url, value), value
    return "", ""


def _node_embedded_urls(node: _Node) -> list[str]:
    values = [node.attr_text("href"), node.attr_text("data-href"), node.attr_text("data-url")]
    for attr_name in ("onclick", "data-onclick"):
        text = node.attr_text(attr_name)
        values.extend(match.group(1) for match in re.finditer(r"['\"]([^'\"]+)['\"]", text))
    return [value for value in values if value]


def _nearby_siblings(node: _Node) -> list[_Node]:
    if node.parent is None:
        return []
    siblings = node.parent.children
    try:
        index = siblings.index(node)
    except ValueError:
        return []
    nearby: list[_Node] = []
    if index > 0:
        nearby.append(siblings[index - 1])
    if index + 1 < len(siblings):
        nearby.append(siblings[index + 1])
    return nearby


def _is_recovered_heading_profile_url(value: str, base_url: str) -> bool:
    if not _is_candidate_profile_href(value):
        return False
    lowered = value.lower()
    if "void(0)" in lowered or lowered.startswith("javascript:"):
        return False
    absolute_url = urljoin(base_url, value)
    parsed = urlparse(absolute_url)
    base = urlparse(base_url)
    if base.netloc and parsed.netloc and parsed.netloc != base.netloc and parsed.netloc != "acadstaff.ugm.ac.id":
        return False
    if parsed.path.rstrip("/").lower() == base.path.rstrip("/").lower():
        return False
    return bool(parsed.scheme in {"http", "https"} and parsed.netloc and parsed.path.strip("/"))


def _faculty_heading_default_title(value: str) -> str:
    normalized = _normalize_key(value)
    defaults = {
        "dosen": "Dosen",
        "faculty": "Faculty",
        "academic staff": "Academic Staff",
        "teaching staff": "Teaching Staff",
    }
    return defaults.get(normalized, "")


def _looks_like_heading_person_name(value: str) -> bool:
    if not value or len(value) > 160:
        return False
    tokens = value.split()
    if len(tokens) < 2 or len(tokens) > 14:
        return False
    lowered_words = {word.strip(".,").lower() for word in tokens}
    if lowered_words & NON_NAME_WORDS:
        return False
    academic_prefix = re.match(r"^(?:Dr|Prof|Ir|R|S)\.?\s+", value, flags=re.IGNORECASE)
    person_tokens = [token for token in tokens if re.search(r"[A-Za-z]", token)]
    return bool(academic_prefix or len(person_tokens) >= 2)


def _fallback_search_roots(root: _Node) -> list[_Node]:
    scoped_roots = [
        node
        for node in root.descendants()
        if _is_fallback_search_root(node)
    ]
    if scoped_roots:
        return [node for node in scoped_roots if not _has_fallback_root_ancestor(node, scoped_roots)]
    return [root]


def _is_fallback_search_root(node: _Node) -> bool:
    if _is_inside_skipped_region(node):
        return False
    if node.tag in {"main", "article"}:
        return True
    semantic_content_names = {"content", "main-content", "site-content", "page-content", "content-area"}
    class_names = {name.casefold() for name in node.attr_text("class").split()}
    node_id = node.attr_text("id").casefold()
    return node_id in semantic_content_names or bool(class_names & semantic_content_names) or any(
        name.endswith("-main-content") for name in class_names
    )


def _has_fallback_root_ancestor(node: _Node, roots: list[_Node]) -> bool:
    root_ids = {id(root) for root in roots}
    return any(id(ancestor) in root_ids for ancestor in node.ancestors())


def _fallback_quality_ok(records: list[FacultyRecord]) -> bool:
    return bool(records) and all(record.profile_url and _looks_like_name(record.name) for record in records)


def _record_from_profile_link(link: _Node, base_url: str) -> FacultyRecord | None:
    profile_url = urljoin(base_url, link.attr_text("href"))
    if _is_bio_profile_link_text(link.text()):
        return None
    if _is_page_profile_url(profile_url, base_url):
        return None
    linked_person_names = {
        _normalize_key(name)
        for name in _wrapping_anchor_person_names(link)
        if _looks_like_heading_person_name(name) and not _is_bad_name_candidate(name)
    }
    if len(linked_person_names) > 1:
        return None
    if _is_strong_stref_profile_url(profile_url, base_url):
        return _record_from_strong_stref_profile_link(link, profile_url)
    name = _extract_name(link)
    if not name:
        name = _clean_name(link.text())
    if _is_faculty_category_label(name):
        return None
    context = _fallback_record_context(link)
    if _is_bad_name_candidate(name):
        better_context, better_name = _directory_profile_context_and_name(link, base_url, profile_url)
        if better_name:
            context = better_context
            name = better_name
    if _is_navigation_or_category_block(context):
        return None
    title = _extract_title(context, name) if name else ""

    if not title:
        title = _lab_title_from_context(context)

    if not title:
        prefixed_record = _record_from_prefixed_title_link_text(link, profile_url)
        if prefixed_record is not None:
            if _is_excluded_directory_section(context, prefixed_record.title):
                return None
            return prefixed_record

        compact_record = _record_from_compact_link_text(link, profile_url)
        if compact_record is not None:
            if _is_excluded_directory_section(context, compact_record.title):
                return None
            return compact_record

    if _is_excluded_directory_section(context, title):
        return None
    if _is_non_faculty_member_title(title):
        return None
    if not name or not title or not _looks_like_name(name):
        return None
    return FacultyRecord(name=name, title=title, profile_url=profile_url)


def _record_from_strong_stref_profile_link(link: _Node, profile_url: str) -> FacultyRecord | None:
    name = _clean_name(link.text())
    validation_name = re.sub(r"^(?:(?:Associate\s+)?Professor|Dr\.?)\s+", "", name, flags=re.IGNORECASE)
    if not _looks_like_name(validation_name):
        return None
    context = _strong_profile_record_context(link)
    raw_title = _academic_title_after_link(link, context)
    title = _strip_trailing_affiliation(raw_title)
    if not title or _is_non_faculty_member_title(title) or _is_excluded_directory_section(context, title):
        return None
    return FacultyRecord(name=name, title=title, profile_url=profile_url, email=_extract_email(context))


def _strong_profile_record_context(link: _Node) -> _Node:
    for ancestor in link.ancestors():
        if ancestor.tag in SKIP_TAGS:
            break
        if ancestor.tag in {"li", "article", "tr"}:
            return ancestor
        if ancestor.tag == "div" and _academic_title_after_link(link, ancestor):
            return ancestor
    return link.parent or link


def _academic_title_after_link(link: _Node, context: _Node) -> str:
    found_link = False
    for node in context.descendants():
        if node is link:
            found_link = True
            continue
        if not found_link or link in node.ancestors():
            continue
        if node.tag == "a" and _is_strong_stref_profile_url(node.attr_text("href"), ""):
            break
        for text in node.text_parts:
            cleaned = normalize_space(text.strip(" -|,;"))
            lowered = cleaned.lower()
            if not cleaned or _normalize_key(cleaned) == _normalize_key(link.text()):
                continue
            if lowered.startswith(("email", "ph:", "phone", "tel:")) or EMAIL_RE.search(cleaned):
                return ""
            if _is_title_text(cleaned):
                return cleaned
    return ""


def _raw_text_after_link(link: _Node, context: _Node) -> str:
    found_link = False
    for node in context.descendants():
        if node is link:
            found_link = True
            continue
        if not found_link or link in node.ancestors():
            continue
        for text in node.text_parts:
            cleaned = normalize_space(text.strip(" -|,;"))
            if not cleaned or _normalize_key(cleaned) == _normalize_key(link.text()):
                continue
            lowered = cleaned.lower()
            if lowered.startswith(("email", "ph:", "phone", "tel:")) or EMAIL_RE.search(cleaned):
                return ""
            return cleaned
    return ""


def _strip_trailing_affiliation(title: str) -> str:
    title = re.split(
        r"\s+-\s+(?=(?:school|college|faculty|department|institute|centre|center)\b)",
        title,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return normalize_space(title.strip(" -|,;"))


def _record_from_compact_link_text(link: _Node, profile_url: str) -> FacultyRecord | None:
    text = _clean_name(link.text())
    for pattern in COMPACT_TITLE_PATTERNS:
        match = re.search(rf"\b{re.escape(pattern)}\b.*$", text, flags=re.IGNORECASE)
        if not match:
            continue
        name = _clean_name(text[: match.start()])
        title = normalize_space(text[match.start() :].strip(" -|,;"))
        if name and title and _looks_like_name(name):
            return FacultyRecord(name=name, title=title, profile_url=profile_url)
    return None


def _record_from_prefixed_title_link_text(link: _Node, profile_url: str) -> FacultyRecord | None:
    parsed = _prefixed_title_and_name(link.text())
    if parsed is None:
        return None

    title, name = parsed
    return FacultyRecord(name=name, title=title, profile_url=profile_url)


def _prefixed_title_and_name(value: str) -> tuple[str, str] | None:
    if _is_bio_profile_link_text(value):
        return None
    text = _clean_name(value)
    match = re.match(r"^(Prof\.|Dr\.)\s+(.+)$", text, flags=re.IGNORECASE)
    if not match:
        return None

    title = PREFIX_TITLE_PATTERNS.get(match.group(1).casefold(), match.group(1))
    name = _clean_name(match.group(2))
    if not name or not _looks_like_name(name) or _is_bad_name_candidate(name):
        return None
    return title, name


def _fallback_record_context(link: _Node) -> _Node:
    for ancestor in link.ancestors():
        class_id = _node_class_id(ancestor)
        if ancestor.tag in {"li", "p", "tr"}:
            return ancestor
        if any(hint in class_id for hint in ("member-details", "staff", "person", "profile", "card")):
            return ancestor
    return link


def _is_non_faculty_member_title(title: str) -> bool:
    lowered = title.lower()
    if "associate member" in lowered or "affiliate member" in lowered:
        return True
    if _has_valid_academic_title(title):
        return False
    return any(re.search(rf"\b{re.escape(word)}\b", lowered) for word in NON_ACADEMIC_TITLE_WORDS)


def _is_emeritus_academic_title(title: str) -> bool:
    normalized = _normalize_key(title)
    return any(term in normalized for term in ("emeritus", "emerita"))


def _is_navigation_or_category_block(container: _Node) -> bool:
    if _has_email(container) or _person_detail_link(container) is not None:
        return False

    link_labels = [_clean_name(link.text()) for link in _links_in(container) if _clean_name(link.text())]
    if not link_labels:
        return False

    category_count = sum(1 for label in link_labels if _is_faculty_category_label(label))
    return category_count >= 2 and category_count >= len(link_labels) / 2


def _is_faculty_category_label(value: str) -> bool:
    return _normalize_key(value) in FACULTY_CATEGORY_LABELS


def _lab_title_from_context(container: _Node) -> str:
    for link in _links_in(container):
        if "lab-website-link" in link.attr_text("class").lower().split():
            title = normalize_space(link.text().strip(" -|,;"))
            if title:
                return title
    return ""


def _has_table_row_signal(row: _Node) -> bool:
    cells = _direct_children_by_tag(row, {"td", "th"})
    if _record_from_split_name_table_row(cells, "https://www.arch.kth.se/") is not None:
        return True
    if len(cells) == 1:
        return _record_from_single_cell_table_row(cells[0], "https://example.edu/") is not None
    if len(cells) < 2 or _is_header_row(cells):
        return False
    name = _extract_name(cells[0])
    if not name:
        return False
    has_title = any(_is_title_text(cell.text()) for cell in cells[1:])
    has_contact = _extract_profile_url(row, "https://example.edu/", name) or any(_has_email(cell) for cell in cells)
    return bool(has_title and has_contact)


def _direct_children_by_tag(node: _Node, tags: set[str]) -> list[_Node]:
    return [child for child in node.children if child.tag in tags]


def _is_header_row(cells: list[_Node]) -> bool:
    if any(cell.tag == "th" for cell in cells):
        return True
    labels = {normalize_space(cell.text()).casefold() for cell in cells}
    header_labels = {"name", "title", "email", "phone", "department", "office"}
    return len(labels & header_labels) >= 2


def _extract_name(container: _Node) -> str:
    for node in container.descendants():
        if not _is_dedicated_person_name_node(node):
            continue
        name = _clean_name(node.text())
        if _is_usable_person_name(name):
            return name

    person_link = _person_detail_link(container)
    if person_link is not None:
        name = _clean_name(person_link.text())
        if _is_usable_person_name(name):
            return name

    for tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        for node in container.descendants():
            if node.tag == tag:
                name = _clean_name(_name_text_from_node(node))
                if _is_usable_person_name(name):
                    return name

    if container.tag not in {"td", "th", "tr"}:
        for node in container.descendants():
            if not _is_name_text_node(node):
                continue
            name = _clean_name(_name_text_from_node(node))
            if _is_plain_text_person_name(name):
                return name

        if _has_strong_person_hint(container):
            for chunk in container.text_chunks():
                name = _clean_name(chunk)
                if _is_plain_text_person_name(name):
                    return name

    for link in _links_in(container):
        compact_name = _compact_name_from_link(link)
        if compact_name and _is_usable_person_name(compact_name):
            return compact_name

        name = _clean_name(link.text())
        if _is_usable_person_name(name):
            return name

    for image in _nodes_by_tag(container, "img"):
        alt = re.sub(r"^image:\s*", "", image.attr_text("alt"), flags=re.IGNORECASE)
        if _is_generic_person_image_alt(alt):
            continue
        name = _clean_name(alt)
        if _is_usable_person_name(name):
            return name

    return ""


def _bounded_card_person_heading_identity(container: _Node, base_url: str) -> tuple[_Node, str, str]:
    for context in (container, *container.ancestors()):
        if context.tag in SKIP_TAGS:
            break
        headings = [
            node
            for node in context.descendants()
            if node.tag in {"h2", "h3", "h4", "h5", "h6"}
        ]
        identities: dict[str, tuple[str, _Node]] = {}
        for heading in headings:
            name = _person_name_from_heading(heading, base_url)
            if name:
                identities[_normalize_key(name)] = (name, heading)
        if identities:
            if len(identities) != 1:
                return container, "", ""
            name, heading = next(iter(identities.values()))
            profile_url = _person_name_bound_profile_url(heading, context, name, base_url)
            return context, name, profile_url
        if context is not container and any(
            hint in _node_class_id(context) for hint in ("card", "person", "profile", "member", "staff-item")
        ):
            break
        if context.tag in {"main", "section", "article"}:
            break
    return container, "", ""


def _name_matches_organizational_link(container: _Node, name: str, base_url: str) -> bool:
    normalized_name = _normalize_key(name)
    return any(
        _normalize_key(_clean_name(link.text())) == normalized_name
        and _is_organizational_card_profile_url(urljoin(base_url, link.attr_text("href")))
        for link in _links_in(container)
    )


def _person_name_from_heading(heading: _Node, base_url: str) -> str:
    for node in heading.descendants():
        if not _is_dedicated_person_name_node(node):
            continue
        name = _clean_name(node.text())
        if _is_plain_text_person_name(name):
            return name
    direct_name = _clean_name(" ".join(heading.text_parts))
    if _is_plain_text_person_name(direct_name) and _normalize_key(direct_name) not in {"back", "search"}:
        return direct_name
    for link in _links_in(heading):
        absolute_url = urljoin(base_url, link.attr_text("href"))
        name = _clean_name(link.text())
        if (
            not _is_organizational_card_profile_url(absolute_url)
            and _is_plain_text_person_name(name)
            and _normalize_key(name) not in {"back", "search"}
        ):
            return name
    return ""


def _person_name_bound_profile_url(heading: _Node, context: _Node, name: str, base_url: str) -> str:
    links = [*_links_in(heading), *(link for link in _links_in(context) if heading not in link.ancestors())]
    for link in links:
        href = link.attr_text("href")
        absolute_url = urljoin(base_url, href)
        if _is_organizational_card_profile_url(absolute_url):
            continue
        if _normalize_key(_clean_name(link.text())) != _normalize_key(name):
            continue
        if _looks_like_profile_url(absolute_url) or _is_context_profile_link(link, href, name):
            return absolute_url
    for link in links:
        if _is_safe_same_card_bio_profile_link(link, base_url):
            return urljoin(base_url, link.attr_text("href"))
    return ""


def _is_name_text_node(node: _Node) -> bool:
    class_tokens = {token for token in re.split(r"[^a-z0-9]+", _node_class_id(node)) if token}
    return node.tag in {"strong", "b"} or bool(class_tokens & {"name", "title"})


def _is_dedicated_person_name_node(node: _Node) -> bool:
    class_tokens = {token for token in re.split(r"[^a-z0-9]+", _node_class_id(node)) if token}
    return "name" in class_tokens and not bool(class_tokens & {"department", "faculty", "institute", "school"})


def _is_usable_person_name(value: str) -> bool:
    return (
        _looks_like_name(value)
        and not _is_generic_link_text(value)
        and not _is_bio_profile_link_text(value)
        and not _is_accordion_utility_label(value)
    )


def _is_bio_profile_link_text(value: str) -> bool:
    normalized = _normalize_key(value)
    return bool(re.search(r"\b(?:bio|biography|profile)\b", normalized))


def _card_has_single_matching_person_heading(container: _Node, name: str, base_url: str) -> bool:
    heading_names = {
        _normalize_key(heading_name)
        for heading in container.descendants()
        if heading.tag in {"h2", "h3", "h4", "h5", "h6"}
        for heading_name in [_person_name_from_heading(heading, base_url)]
        if heading_name
    }
    return heading_names == {_normalize_key(name)}


def _is_safe_same_card_bio_profile_link(link: _Node, base_url: str) -> bool:
    if not _is_bio_profile_link_text(link.text()) or any(node.tag == "img" for node in link.descendants()):
        return False
    if _is_inside_skipped_region(link):
        return False
    href = link.attr_text("href")
    if not _is_candidate_profile_href(href):
        return False
    absolute_url = urljoin(base_url, href)
    if _normalize_record_profile_url(absolute_url) == _normalize_record_profile_url(base_url):
        return False
    if _is_organizational_card_profile_url(absolute_url):
        return False
    parsed = urlparse(absolute_url)
    if parsed.path.lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp")):
        return False
    if any(segment.casefold() in {"category", "categories", "directory", "search"} for segment in parsed.path.split("/")):
        return False
    return _is_same_institution_host(parsed.netloc, urlparse(base_url).netloc) or _is_trusted_external_academic_profile_url(
        absolute_url, base_url
    )


def _is_same_institution_host(first: str, second: str) -> bool:
    def institutional_root(host: str) -> tuple[str, ...]:
        labels = tuple(part for part in host.lower().split(":", 1)[0].split(".") if part)
        if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in {"ac", "co", "edu", "gov", "org"}:
            return labels[-3:]
        return labels[-2:]

    return bool(first and second and institutional_root(first) == institutional_root(second))


def _is_plain_text_person_name(value: str) -> bool:
    return _is_usable_person_name(value) and not _is_bad_name_candidate(value)


def _is_generic_person_image_alt(value: str) -> bool:
    lowered = _normalize_key(value)
    return any(term in lowered for term in ("photo", "headshot", "portrait", "image", "no photo", "this person has no photo", "podium"))


def _name_text_from_node(node: _Node) -> str:
    direct_text = _clean_name(" ".join(node.text_parts))
    if _is_plain_text_person_name(direct_text):
        return direct_text
    for link in _links_in(node):
        text = _clean_name(link.text())
        if _is_usable_person_name(text):
            return text
    return node.text()


def _extract_title(container: _Node, name: str) -> str:
    for node in container.descendants():
        if _is_inside_people_control_region(node, container):
            continue
        if "job-role" in node.attr_text("class").lower().split():
            title = normalize_space(node.text().strip(" -|,;"))
            if title and not EMAIL_RE.search(title) and len(title) <= 180:
                return title

    accordion_title = _accordion_group_title(container)
    if accordion_title:
        return accordion_title

    person_link = _person_detail_link(container)
    if person_link is not None:
        title = _title_after_person_link(container, name)
        if title:
            return title

    fu_title = _fu_professorship_title(container, name)
    if fu_title:
        return fu_title

    for chunk in _local_title_text_chunks(container):
        sentence = chunk.replace(name, " ")
        cleaned = normalize_space(sentence.strip(" -|,;"))
        if _is_title_text(cleaned):
            return cleaned
    return ""


def _strip_name_prefix(title: str, name: str) -> str:
    if not title or not name:
        return title
    pattern = rf"^\s*{re.escape(name)}\b\s*[-|,;:]?\s*"
    stripped = re.sub(pattern, "", title, flags=re.IGNORECASE)
    cleaned = normalize_space(stripped.strip(" -|,;"))
    if cleaned != normalize_space(title):
        return cleaned or title
    matches = [
        match
        for keyword in TITLE_KEYWORDS
        if (match := re.search(rf"\b{re.escape(keyword)}\b", title, flags=re.IGNORECASE)) is not None
    ]
    if matches:
        first_match = min(matches, key=lambda match: match.start())
        prefix = title[: first_match.start()]
        if first_match.start() > 0 and _name_variant_in_title_prefix(prefix, name):
            return normalize_space(title[first_match.start() :].strip(" -|,;")) or title
    return title


def _name_variant_in_title_prefix(prefix: str, name: str) -> bool:
    def tokens(value: str) -> set[str]:
        ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
        return {token for token in re.findall(r"[a-z]+", ascii_value) if len(token) >= 3}

    prefix_tokens = tokens(prefix)
    name_tokens = tokens(name)
    return bool(prefix_tokens & name_tokens)


def _is_excluded_directory_section(container: _Node, title: str) -> bool:
    heading = _normalize_key(_nearest_section_heading(container))
    if not heading:
        return False
    if heading in EXCLUDED_DIRECTORY_SECTIONS:
        return True
    if heading in NEUTRAL_DIRECTORY_SECTIONS:
        return not _has_valid_academic_title(title)
    if "visiting faculty" in heading and "scholars" in heading:
        return not _has_valid_academic_title(title)
    return False


def _has_valid_academic_title(title: str) -> bool:
    lowered = _normalize_key(title)
    return any(pattern in lowered for pattern in ACADEMIC_TITLE_PATTERNS)


def _nearest_section_heading(node: _Node) -> str:
    current: _Node | None = node
    while current is not None and current.parent is not None:
        siblings = current.parent.children
        try:
            index = siblings.index(current)
        except ValueError:
            index = 0
        for sibling in reversed(siblings[:index]):
            if _looks_like_person_card_for_section(sibling):
                continue
            heading = _last_heading_text(sibling)
            if heading:
                return heading
        current = current.parent
    return ""


def _looks_like_person_card_for_section(node: _Node) -> bool:
    class_id = _node_class_id(node)
    if any(hint in class_id for hint in ("person", "profile", "faculty", "member", "team", "card")):
        return True
    headings = [
        normalize_space(descendant.text())
        for descendant in node.descendants()
        if descendant.tag in {"h2", "h3", "h4", "h5", "h6"}
    ]
    has_person_heading = any(_looks_like_name(_clean_name(text)) for text in headings)
    return has_person_heading and (_has_email(node) or any(_is_title_text(chunk) for chunk in node.text_chunks()))


def _last_heading_text(node: _Node) -> str:
    texts: list[str] = []
    if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6", "dt", "th"}:
        text = normalize_space(node.text())
        if (
            text
            and not _is_table_field_heading(node, text)
            and not _is_segmented_person_link_name(_clean_name(text))
            and not _is_accordion_utility_label(text)
        ):
            texts.append(text)
    for descendant in node.descendants():
        if descendant.tag in {"h1", "h2", "h3", "h4", "h5", "h6", "dt", "th"}:
            text = normalize_space(descendant.text())
            if (
                text
                and not _is_table_field_heading(descendant, text)
                and not _is_segmented_person_link_name(_clean_name(text))
                and not _is_accordion_utility_label(text)
            ):
                texts.append(text)
    return texts[-1] if texts else ""


def _is_table_field_heading(node: _Node, text: str) -> bool:
    return node.tag == "th" and _header_label(text) in {
        "name",
        "title",
        "email",
        "email address",
        "phone",
        "phone number",
    }


def _raw_name_source(container: _Node) -> str:
    for tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        for node in container.descendants():
            if node.tag == tag and _clean_name(node.text()):
                return f"{tag}:{_clean_name(node.text())[:120]}"
    for link in _links_in(container):
        text = _clean_name(link.text())
        if text:
            return f"link:{text[:120]}"
    for image in _nodes_by_tag(container, "img"):
        alt = _clean_name(image.attr_text("alt"))
        if alt:
            return f"img_alt:{alt[:120]}"
    return ""


def _raw_title_text(container: _Node, name: str) -> str:
    for chunk in _local_title_text_chunks(container):
        cleaned = normalize_space(chunk.strip(" -|,;"))
        if cleaned and (not name or name in cleaned or _is_title_text(_strip_name_prefix(cleaned, name))):
            return cleaned[:180]
    return ""


def _fu_professorship_title(container: _Node, name: str) -> str:
    if not _has_fu_professorship_link(container):
        return ""
    text = container.text()
    if name:
        text = text.replace(name, " ", 1)
    match = re.search(r"\(([^()]{5,180})\)", text)
    if not match:
        return ""
    title = normalize_space(match.group(1).strip(" -|,;"))
    if title and not EMAIL_RE.search(title):
        return title
    return ""


def _has_fu_professorship_link(container: _Node) -> bool:
    return any(_is_fu_professorship_url(urljoin("https://www.jura.fu-berlin.de/", link.attr_text("href"))) for link in _links_in(container))


def _accordion_group_title(node: _Node) -> str:
    current: _Node | None = node
    while current is not None:
        if current.tag == "dd" and "accordion" in _node_class_id(current):
            previous = _previous_sibling(current)
            if previous is not None and previous.tag == "dt" and "accordion" in _node_class_id(previous):
                title = normalize_space(previous.text().strip(" -|,;"))
                if _is_title_text(title):
                    return title
        current = current.parent
    return ""


def _previous_sibling(node: _Node) -> _Node | None:
    if node.parent is None:
        return None
    siblings = node.parent.children
    for index, sibling in enumerate(siblings):
        if sibling is node:
            for previous in reversed(siblings[:index]):
                if previous.text() or previous.children:
                    return previous
            return None
    return None


def _title_after_person_link(container: _Node, name: str) -> str:
    found_name = False
    for chunk in _local_title_text_chunks(container):
        cleaned = normalize_space(chunk.strip(" -|,;"))
        if not cleaned:
            continue
        if not found_name:
            found_name = _normalize_key(cleaned) == _normalize_key(name)
            continue
        if _is_eth_non_title_text(cleaned):
            continue
        if len(cleaned) <= 180 and not EMAIL_RE.search(cleaned):
            return cleaned
    return ""


def _is_eth_non_title_text(text: str) -> bool:
    lowered = text.lower()
    return lowered in {"group website", "external page"} or "group website" in lowered


def _compact_name_from_link(link: _Node) -> str:
    if not _has_job_role_descendant(link):
        return ""
    return _clean_name(" ".join(link.text_parts))


def _has_job_role_descendant(node: _Node) -> bool:
    return any("job-role" in descendant.attr_text("class").lower().split() for descendant in node.descendants())


def _contains_title_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in TITLE_KEYWORDS)


def _is_title_text(text: str) -> bool:
    if not text or EMAIL_RE.search(text):
        return False
    if len(text) > 140:
        return False
    if not _contains_title_keyword(text):
        return False
    lowered = text.lower()
    if lowered in NON_NAME_WORDS:
        return False
    return True


def _extract_profile_url(container: _Node, base_url: str, name: str = "") -> str:
    ancestor_profile_url = _ancestor_profile_url(container, base_url)
    if ancestor_profile_url:
        return ancestor_profile_url

    return _extract_descendant_profile_url(container, base_url, name)


def _extract_descendant_profile_url(container: _Node, base_url: str, name: str = "") -> str:
    if container.tag == "a":
        href = container.attr_text("href")
        absolute_url = urljoin(base_url, href) if base_url else href
        if not _is_organizational_card_profile_url(absolute_url) and _is_structurally_plausible_individual_profile_url(
            absolute_url, base_url
        ):
            return absolute_url

    links = _links_in(container)
    for link in links:
        href = link.attr_text("href")
        absolute_url = urljoin(base_url, href) if base_url else href
        if (
            name
            and _normalize_key(_clean_name(link.text())) == _normalize_key(name)
            and not _is_organizational_card_profile_url(absolute_url)
            and (_looks_like_profile_url(absolute_url) or _is_context_profile_link(link, href, name))
        ):
            return absolute_url

    if name and _card_has_single_matching_person_heading(container, name, base_url):
        for link in links:
            if _is_safe_same_card_bio_profile_link(link, base_url):
                return urljoin(base_url, link.attr_text("href"))

    for link in links:
        href = link.attr_text("href")
        absolute_url = urljoin(base_url, href) if base_url else href
        if _is_person_detail_href(href) and not _is_organizational_card_profile_url(absolute_url):
            return urljoin(base_url, href) if base_url else href

    for link in links:
        href = link.attr_text("href")
        if not _is_candidate_profile_href(href):
            continue
        absolute_url = urljoin(base_url, href) if base_url else href
        if _is_organizational_card_profile_url(absolute_url):
            continue
        if _looks_like_profile_url(absolute_url) or _is_context_profile_link(link, href, name):
            return absolute_url
    return ""


def _recover_card_profile_url(container: _Node, base_url: str, name: str) -> str:
    return _recover_card_profile(container, base_url, name).url


def _recover_card_profile(container: _Node, base_url: str, name: str) -> _CardProfileRecovery:
    email = _extract_email(container)
    if _card_has_single_matching_person_heading(container, name, base_url):
        for link in _links_in(container):
            if _is_safe_same_card_bio_profile_link(link, base_url):
                return _CardProfileRecovery(
                    url=urljoin(base_url, link.attr_text("href")),
                    profile_search_scope="inside_card_bio",
                )
    for link in _links_in(container):
        href = link.attr_text("href")
        if _is_card_profile_url(href, base_url, name, email, link.text(), require_match=False):
            return _CardProfileRecovery(
                url=urljoin(base_url, href) if base_url else href,
                profile_search_scope="inside_card",
            )

    for value in _embedded_urls_in(container):
        if _is_card_profile_url(value, base_url, name, email, "", require_match=False):
            return _CardProfileRecovery(
                url=urljoin(base_url, value) if base_url else value,
                profile_search_scope="inside_card",
            )

    scanned_count = 0
    current = container
    while current.parent is not None:
        siblings = current.parent.children
        try:
            index = siblings.index(current)
        except ValueError:
            break
        for node in siblings[index + 1 :]:
            boundary = _following_profile_stop_boundary(node, base_url)
            if boundary:
                return _CardProfileRecovery(
                    profile_search_scope="following_siblings",
                    scanned_sibling_count=scanned_count,
                    stop_boundary=boundary,
                    reject_reason="no_trusted_profile_before_boundary",
                )
            scanned_count += 1
            values = [link.attr_text("href") for link in _links_in(node)]
            if node.tag == "a":
                values.insert(0, node.attr_text("href"))
            values.extend(_node_embedded_urls(node))
            for href in values:
                absolute_url = urljoin(base_url, href) if base_url else href
                if _is_trusted_external_academic_profile_url(absolute_url, base_url):
                    return _CardProfileRecovery(
                        url=absolute_url,
                        profile_search_scope="following_siblings",
                        scanned_sibling_count=scanned_count,
                    )
        current = current.parent
        if current.tag in {"main", "section", "article"}:
            break
    return _CardProfileRecovery(
        profile_search_scope="following_siblings",
        scanned_sibling_count=scanned_count,
        stop_boundary="end_of_scope",
        reject_reason="no_trusted_profile_before_boundary",
    )


def _following_profile_stop_boundary(node: _Node, base_url: str = "") -> str:
    headings = [node] if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"} else []
    headings.extend(descendant for descendant in node.descendants() if descendant.tag in {"h1", "h2", "h3", "h4", "h5", "h6"})
    person_heading = any(
        _looks_like_heading_person_name(_clean_name(heading.text()))
        and not _is_contact_or_location_heading(heading.text())
        for heading in headings
    )
    class_id = _node_class_id(node)
    card_hint = any(hint in class_id for hint in ("person", "faculty", "member", "team", "card"))
    links = ([node] if node.tag == "a" else []) + _links_in(node)
    if any(
        not _is_organizational_card_profile_url(urljoin(base_url, link.attr_text("href")))
        and _is_fallback_profile_href(link.attr_text("href"), base_url)
        for link in links
    ):
        return "next_person_profile_link"
    if person_heading and (card_hint or _has_email(node) or any(_is_title_text(chunk) for chunk in node.text_chunks())):
        return "next_person_card"
    if person_heading:
        return "next_person_name_heading"
    local_name = next(
        (
            _clean_name(candidate.text())
            for candidate in (node, *node.descendants())
            if _is_dedicated_person_name_node(candidate)
            and _looks_like_heading_person_name(_clean_name(candidate.text()))
            and not _is_bad_name_candidate(_clean_name(candidate.text()))
        ),
        "",
    )
    if local_name:
        return "next_person_name"
    if node.tag in {"li", "article"} or card_hint:
        return "next_card_or_list_item"
    if node.tag == "section" or any(heading.tag in {"h1", "h2", "h3"} for heading in headings):
        return "next_major_section"
    return ""


def _is_contact_or_location_heading(value: str) -> bool:
    lowered = _normalize_key(value)
    labels = (
        "piso",
        "gabinete",
        "bloco",
        "office",
        "contact",
        "contacto",
        "phone",
        "telefone",
        "location",
        "localização",
        "research area",
        "research interests",
        "áreas de investigação",
    )
    return bool(EMAIL_RE.search(value) or any(label in lowered for label in labels))


def _embedded_urls_in(container: _Node) -> list[str]:
    values = list(_node_embedded_urls(container))
    for node in container.descendants():
        values.extend(_node_embedded_urls(node))
    return values


def _card_profile_link_text(container: _Node, base_url: str, profile_url: str = "") -> str:
    for link in _links_in(container):
        href = link.attr_text("href")
        if not _is_candidate_profile_href(href):
            continue
        absolute_url = urljoin(base_url, href) if base_url else href
        if not profile_url or _normalize_record_profile_url(absolute_url) == _normalize_record_profile_url(profile_url):
            return _clean_name(link.text())
    return ""


def _is_card_profile_url(
    href: str,
    base_url: str,
    name: str,
    email: str,
    link_text: str,
    *,
    require_match: bool,
) -> bool:
    if not _is_candidate_profile_href(href):
        return False
    absolute_url = urljoin(base_url, href) if base_url else href
    if _is_organizational_card_profile_url(absolute_url):
        return False
    if _is_trusted_external_academic_profile_url(absolute_url, base_url):
        return not require_match or _profile_link_matches_person(absolute_url, name, email, link_text)
    if _is_itu_academi_profile_url(absolute_url):
        return not require_match or _profile_link_matches_person(absolute_url, name, email, link_text)
    if not _is_waikato_profile_url(absolute_url):
        return _looks_like_profile_url(absolute_url) and (not require_match or _profile_link_matches_person(absolute_url, name, email, link_text))
    if _is_waikato_search_url(absolute_url):
        return _profile_link_matches_person(absolute_url, name, email, link_text)
    return not require_match or _profile_link_matches_person(absolute_url, name, email, link_text)


def _is_organizational_card_profile_url(value: str) -> bool:
    organizational_segments = {
        "departments",
        "faculties",
        "institutes",
        "research-groups",
        "centres",
        "schools",
    }
    segments = {segment.casefold() for segment in urlparse(value).path.split("/") if segment}
    return bool(segments & organizational_segments)


def _is_trusted_external_academic_profile_url(value: str, base_url: str) -> bool:
    parsed = urlparse(value)
    base = urlparse(base_url)
    hostname = parsed.netloc.lower().split(":", 1)[0]
    if parsed.scheme not in {"http", "https"} or not hostname or hostname == base.netloc.lower():
        return False
    if hostname == "cienciavitae.pt" or hostname.endswith(".cienciavitae.pt"):
        return bool(parsed.path.strip("/"))
    if hostname == "orcid.org" or hostname.endswith(".orcid.org"):
        return bool(re.fullmatch(r"/\d{4}-\d{4}-\d{4}-\d{3}[\dXx]/?", parsed.path))
    if hostname == "elsevierpure.com" or hostname.endswith(".elsevierpure.com"):
        return bool(parsed.path.strip("/"))
    portal_host = any(hint in hostname for hint in ("pure.", "researchportal", "research-portal", "researchprofiles", "research-profiles", "repository"))
    profile_path = any(hint in parsed.path.lower() for hint in ("/person/", "/persons/", "/profile/", "/profiles/", "/researcher/", "/researchers/"))
    return portal_host and profile_path


def _is_waikato_profile_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "profiles.waikato.ac.nz"


def _is_itu_academi_profile_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "akademi.itu.edu.tr" and bool(parsed.path.strip("/"))


def _is_itu_rehber_search_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "rehber.itu.edu.tr" and parsed.path.rstrip("/").lower() == "/search"


def _is_waikato_search_url(value: str) -> bool:
    parsed = urlparse(value)
    return _is_waikato_profile_url(value) and parsed.path.rstrip("/").lower() == "/search"


def _profile_link_matches_person(value: str, name: str, email: str, link_text: str) -> bool:
    if name and link_text and _normalize_key(link_text) == _normalize_key(name):
        return True
    haystack = _normalize_key(value)
    if email and _normalize_key(email) in haystack:
        return True
    name_tokens = [token for token in re.split(r"[^A-Za-z]+", name) if len(token) > 1]
    if len(name_tokens) >= 2:
        normalized_tokens = [_normalize_key(token) for token in name_tokens[-2:]]
        return all(token in haystack for token in normalized_tokens)
    return False


def _has_profile_link(container: _Node) -> bool:
    if _ancestor_profile_url(container, "https://example.edu/"):
        return True
    if _person_detail_link(container) is not None:
        return True

    name = _extract_name(container)
    for link in _links_in(container):
        href = link.attr_text("href")
        if not _is_candidate_profile_href(href):
            continue
        absolute_url = urljoin("https://example.edu/", href)
        if (
            _looks_like_profile_url(absolute_url)
            or _is_trusted_external_academic_profile_url(absolute_url, "")
            or _is_context_profile_link(link, href, name)
        ):
            return True
    return False


def _ancestor_profile_url(container: _Node, base_url: str) -> str:
    for ancestor in container.ancestors():
        if ancestor.tag != "a":
            continue
        href = ancestor.attr_text("href")
        absolute_url = urljoin(base_url, href) if base_url else href
        if _is_bu_profile_url(absolute_url) and _has_profile_listing_context(container):
            return absolute_url
        if _is_safe_single_person_wrapping_profile_anchor(ancestor, container, absolute_url, base_url):
            return absolute_url
    return ""


def _is_safe_single_person_wrapping_profile_anchor(
    anchor: _Node, container: _Node, absolute_url: str, base_url: str
) -> bool:
    if anchor is container or anchor not in container.ancestors():
        return False
    if _is_inside_fallback_skipped_region(anchor):
        return False
    if not _is_structurally_plausible_individual_profile_url(absolute_url, base_url):
        return False
    person_names = {
        _normalize_key(name)
        for name in _wrapping_anchor_person_names(anchor)
        if _looks_like_heading_person_name(name) and not _is_bad_name_candidate(name)
    }
    return len(person_names) == 1


def _wrapping_anchor_person_names(anchor: _Node) -> list[str]:
    names: list[str] = []
    for node in anchor.descendants():
        class_id = _node_class_id(node)
        if node.tag in {"strong", "b", "h2", "h3", "h4", "h5", "h6"} or any(
            hint in class_id for hint in ("fullname", "full-name", "person-name", "profile-name")
        ):
            value = _clean_name(node.text().rstrip(" ,"))
            if value:
                names.append(value)
    return names


def _is_generic_policy_url(value: str) -> bool:
    policy_segment = re.compile(
        r"(?:privacy|cookies?)(?:-(?:policy|notice|preferences?|settings?|options?))?",
        flags=re.IGNORECASE,
    )
    segments = [segment.replace("_", "-") for segment in urlparse(value).path.split("/") if segment]
    return any(policy_segment.fullmatch(segment) for segment in segments)


def _is_locale_scoped_short_profile_url(value: str) -> bool:
    segments = [segment for segment in urlparse(value).path.split("/") if segment]
    if len(segments) != 3 or segments[1].casefold() != "p":
        return False
    locale, _, unique_id = segments
    if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})*", locale, flags=re.IGNORECASE):
        return False
    if not unique_id or unique_id in {".", ".."} or _is_generic_policy_url(value):
        return False
    return True


def _is_structurally_plausible_individual_profile_url(value: str, base_url: str) -> bool:
    parsed = urlparse(value)
    base = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if base.netloc and parsed.netloc.lower() != base.netloc.lower():
        return False
    if _is_generic_policy_url(value):
        return False
    if (
        _profile_identity_query_pairs(value)
        and parsed.path.rstrip("/").lower() != base.path.rstrip("/").lower()
    ):
        return True
    if _is_locale_scoped_short_profile_url(value):
        return True
    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        return False
    generic_last_segments = {"directory", "employees", "faculty", "people", "profiles", "search", "staff"}
    if segments[-1].lower() in generic_last_segments:
        return False
    if any(term in parsed.path.lower() for term in ("/search/", "/category/", "/departments/")):
        return False
    return any(hint.strip("-").replace("_", "-") in segment.lower().replace("_", "-") for hint in PROFILE_PATH_HINTS for segment in segments[:-1])


def _is_candidate_profile_href(href: str) -> bool:
    if not href:
        return False
    lowered = href.lower()
    if "sort_table=" in lowered:
        return False
    if lowered.startswith(("mailto:", "tel:", "#")):
        return False
    if any(domain in lowered for domain in ("facebook.com", "twitter.com", "x.com", "linkedin.com", "instagram.com")):
        return False
    if _is_generic_policy_url(href):
        return False
    return True


def _is_fallback_profile_href(href: str, base_url: str) -> bool:
    if not _is_candidate_profile_href(href):
        return False
    absolute_url = urljoin(base_url, href)
    parsed = urlparse(absolute_url)
    base = urlparse(base_url)
    if _is_strong_stref_profile_url(absolute_url, base_url):
        return True
    if _is_uwa_profile_url(absolute_url):
        return True
    if _is_kth_profile_url(absolute_url):
        return True
    if parsed.netloc == "people.epfl.ch":
        return True
    if _is_fu_professorship_url(absolute_url):
        return True
    if base.netloc and parsed.netloc and parsed.netloc != base.netloc:
        return False
    path = parsed.path.lower()
    if path.rstrip("/") == base.path.lower().rstrip("/"):
        return False
    return (
        _is_locale_scoped_short_profile_url(absolute_url)
        or any(hint in path for hint in PROFILE_PATH_HINTS)
        or _is_fac_profile_path(path)
        or _is_person_detail_href(href)
    )


def _is_strong_stref_profile_url(value: str, base_url: str) -> bool:
    parsed = urlparse(urljoin(base_url, value) if base_url else value)
    base = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if base.netloc and parsed.netloc.lower() != base.netloc.lower():
        return False
    params = {key.casefold(): values for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
    return parsed.path.lower().endswith("/profile.cfm") and any(value.strip() for value in params.get("stref", []))


def _person_detail_link(container: _Node) -> _Node | None:
    for link in _links_in(container):
        if _is_person_detail_href(link.attr_text("href")):
            return link
    return None


def _is_person_detail_href(href: str) -> bool:
    return "person-detail" in href.lower()


def _is_query_person_profile_url(value: str) -> bool:
    return bool(urlparse(value).query) and "/persons/" in value.lower()


def _is_page_profile_url(profile_url: str, base_url: str) -> bool:
    parsed = urlparse(profile_url)
    if (
        parsed.query
        and _is_query_profile_endpoint_path(parsed.path)
        and not _profile_identity_query_pairs(profile_url)
    ):
        return True
    if _normalize_record_profile_url(profile_url) != _normalize_record_profile_url(base_url):
        return False
    return not _has_person_like_query(profile_url, base_url)


def _has_person_like_query(profile_url: str, base_url: str) -> bool:
    parsed = urlparse(profile_url)
    base = urlparse(base_url)
    if not parsed.query:
        return False
    if parsed.scheme and base.scheme and parsed.scheme.lower() != base.scheme.lower():
        return False
    if parsed.netloc and base.netloc and parsed.netloc.lower() != base.netloc.lower():
        return False
    if parsed.path.rstrip("/").lower() != base.path.rstrip("/").lower():
        return False

    return bool(_profile_identity_query_pairs(profile_url))


def _is_meaningful_query_person_url(value: str, base_url: str) -> bool:
    parsed = urlparse(value)
    base = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != base.netloc.lower():
        return False
    if parsed.path.rstrip("/").lower() != base.path.rstrip("/").lower():
        return False
    params = {key.casefold(): values for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
    return any(value.strip() for key in ("key", "personid", "profileid", "staffid", "stref") for value in params.get(key, []))


def _is_context_profile_link(link: _Node, href: str, name: str) -> bool:
    parsed = urlparse(href)
    if parsed.fragment and not parsed.path:
        return False
    link_text = _clean_name(link.text())
    if _is_generic_link_text(link_text):
        return False
    if "name" in link.attr_text("class").lower().split() and _looks_like_name(link_text):
        return True
    if name and _normalize_key(link_text) == _normalize_key(name):
        return True
    if _looks_like_name(link_text) and _link_has_title_context(link):
        return True
    path = parsed.path.strip("/")
    if not path or "/" in path or "." in path:
        return False
    if link.parent and link.parent.tag in {"h1", "h2", "h3", "h4"}:
        return True
    return any(child.tag == "img" for child in link.children)


def _link_has_title_context(link: _Node) -> bool:
    for ancestor in link.ancestors():
        if ancestor.tag in {"tr", "li", "p"}:
            return any(_is_title_text(chunk) for chunk in ancestor.text_chunks())
    return False


def _is_fac_profile_path(path: str) -> bool:
    parts = [part for part in path.strip("/").split("/") if part]
    return len(parts) == 2 and parts[0] == "fac"


def _is_generic_link_text(value: str) -> bool:
    normalized = _normalize_key(value)
    return not normalized or normalized in GENERIC_LINK_WORDS


def _has_email(container: _Node) -> bool:
    return bool(EMAIL_RE.search(container.text()))


def _extract_email(container: _Node) -> str:
    match = EMAIL_RE.search(container.text())
    return match.group(0) if match else ""


def _links_in(container: _Node) -> list[_Node]:
    return [node for node in container.descendants() if node.tag == "a" and node.attr_text("href")]


def _profile_link_count(container: _Node, base_url: str) -> int:
    return len(
        {
            _normalize_record_profile_url(urljoin(base_url, link.attr_text("href")))
            for link in _links_in(container)
            if _is_fallback_profile_href(link.attr_text("href"), base_url)
        }
    )


def _possible_person_link_count(root: _Node, base_url: str) -> int:
    return len(_possible_person_profile_urls(root, base_url))


def _possible_person_profile_urls(root: _Node, base_url: str) -> set[str]:
    urls: set[str] = set()
    for search_root in _fallback_search_roots(root):
        for link in _links_in(search_root):
            href = link.attr_text("href")
            absolute_url = urljoin(base_url, href)
            is_profile_href = _is_fallback_profile_href(href, base_url)
            is_contextual_person = _looks_like_name(_clean_name(link.text())) and _link_has_title_context(link)
            has_prefixed_person_text = _prefixed_title_and_name(link.text()) is not None
            has_strong_profile = _is_strong_stref_profile_url(absolute_url, base_url)
            if not is_profile_href and not is_contextual_person and not has_prefixed_person_text:
                continue
            if (
                _is_inside_fallback_skipped_region(link)
                and not _is_kth_profile_url(absolute_url)
                and not _is_bu_profile_listing_link(link, absolute_url)
                and not is_contextual_person
                and not has_prefixed_person_text
                and not has_strong_profile
            ):
                continue
            urls.add(_normalize_record_profile_url(absolute_url))
    return urls


def _local_title_text_chunks(container: _Node) -> list[str]:
    chunks: list[str] = []

    def append_chunks(node: _Node) -> bool:
        chunks.extend(normalize_space(part) for part in node.text_parts if normalize_space(part))
        for child in node.children:
            if _is_people_scope_boundary_node(child):
                return False
            if _is_people_control_node(child):
                continue
            if not append_chunks(child):
                return False
        return True

    append_chunks(container)
    return chunks


def _is_inside_people_control_region(node: _Node, boundary: _Node) -> bool:
    current: _Node | None = node
    while current is not None and current is not boundary:
        if _is_people_control_node(current):
            return True
        current = current.parent
    return False


def _is_people_control_node(node: _Node) -> bool:
    if node.tag in {"nav", "select", "option", "button"}:
        return True
    class_id = _node_class_id(node)
    if any(
        hint in class_id
        for hint in ("filter", "pagination", "pager", "page-size", "pagesize", "role-control", "result-control")
    ):
        return True
    interactive_attributes = " ".join(
        f"{key} {value}" for key, value in node.attrs.items() if key.startswith("ng-") or key.startswith("data-")
    ).lower()
    return node.tag in {"a", "label", "input"} and any(
        hint in interactive_attributes for hint in ("filter", "page", "items", "per-page", "pagesize")
    )


def _is_people_scope_boundary_node(node: _Node) -> bool:
    if node.tag in {"nav", "select", "option"}:
        return True
    class_id = _node_class_id(node)
    if any(
        hint in class_id
        for hint in ("filter", "pagination", "pager", "page-size", "pagesize", "role-control", "result-control")
    ):
        return True
    interactive_attributes = " ".join(
        f"{key} {value}" for key, value in node.attrs.items() if key.startswith("ng-") or key.startswith("data-")
    ).lower()
    if any(hint in interactive_attributes for hint in ("filter", "page", "items", "per-page", "pagesize")):
        return True
    return node.tag == "button" and _is_title_text(normalize_space(node.text()))


def _nodes_by_tag(container: _Node, tag: str) -> list[_Node]:
    return [node for node in container.descendants() if node.tag == tag]


def _clean_name(value: str) -> str:
    value = normalize_space(value)
    value = re.sub(r"\s+,", ",", value)
    value = re.sub(r"\s+(Ph\.?D\.?|MD|M\.D\.|Sc\.?D\.?)$", "", value, flags=re.IGNORECASE)
    return value.strip(" -|,;")


def _looks_like_name(value: str) -> bool:
    if not value or len(value) > 80:
        return False
    words = value.split()
    if len(words) < 2 or len(words) > 6:
        return False
    lowered_words = {word.strip(".,").lower() for word in words}
    if lowered_words & NON_NAME_WORDS:
        return False
    return bool(re.search(r"[A-Z][a-zA-Z'.-]+", value))


def _looks_like_profile_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if _is_generic_policy_url(value):
        return False
    if _is_locale_scoped_short_profile_url(value):
        return True
    if _is_uwa_profile_url(value):
        return True
    if _is_kth_profile_url(value):
        return True
    if _is_bu_profile_url(value):
        return True
    if _is_fu_professorship_url(value):
        return True
    path = parsed.path.lower()
    return any(hint in path for hint in PROFILE_PATH_HINTS)


def _is_uwa_profile_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.netloc.lower() == "research-repository.uwa.edu.au" and parsed.path.lower().startswith("/en/persons/")


def _is_kth_profile_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.netloc.lower().endswith("kth.se") and parsed.path.lower().startswith("/profile/")


def _is_bu_profile_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.netloc.lower() == "www.bu.edu" and "/pardeeschool/profile/" in parsed.path.lower()


def _is_fu_professorship_url(value: str) -> bool:
    parsed = urlparse(value)
    path = parsed.path.lower()
    return parsed.netloc.lower() == "www.jura.fu-berlin.de" and "/fachbereich/einrichtungen/" in path and "/lehrende/" in path


def _is_bu_profile_listing_link(link: _Node, absolute_url: str) -> bool:
    return _is_bu_profile_url(absolute_url) and _has_profile_listing_context(link)


def _has_profile_listing_context(node: _Node) -> bool:
    nodes = [node, *node.ancestors()]
    return any("profile-listing" in ancestor.attr_text("class").lower().split() for ancestor in nodes)


def _is_inside_skipped_region(node: _Node) -> bool:
    return any(ancestor.tag in SKIP_TAGS for ancestor in node.ancestors())


def _is_inside_fallback_skipped_region(node: _Node) -> bool:
    if _is_inside_skipped_region(node):
        return True
    skip_hints = ("nav", "menu", "footer", "header", "search", "breadcrumb", "metadata", "sidebar", "cookie", "privacy", "consent", "quick-link", "quicklink")
    return any(any(hint in _node_class_id(ancestor) for hint in skip_hints) for ancestor in node.ancestors())


def _is_skipped_container(node: _Node) -> bool:
    class_id = _node_class_id(node)
    if any(hint in class_id for hint in ("cookie", "privacy", "consent", "quick-link", "quicklink")):
        return True
    if _has_name_profile_link(node):
        return False
    return any(hint in class_id for hint in SKIP_CONTAINER_HINTS)


def _has_name_profile_link(node: _Node) -> bool:
    for link in _links_in(node):
        if "name" not in link.attr_text("class").lower().split():
            continue
        if _looks_like_name(_clean_name(link.text())):
            return True
    return False


def _contains_navigation_region(node: _Node) -> bool:
    if _has_strong_person_hint(node):
        return False
    navigation_hints = ("nav", "menu", "breadcrumb", "sidebar")
    return any(
        descendant.tag == "nav" or any(hint in _node_class_id(descendant) for hint in navigation_hints)
        for descendant in node.descendants()
    )


def _node_class_id(node: _Node) -> str:
    return f"{node.attr_text('class')} {node.attr_text('id')} {node.attr_text('role')}".lower()


def _table_headers_debug(root: _Node) -> list[str]:
    headers: list[str] = []
    for row in _nodes_by_tag(root, "tr"):
        cells = _direct_children_by_tag(row, {"th", "td"})
        if not cells or not any(cell.tag == "th" for cell in cells):
            continue
        text = " | ".join(normalize_space(cell.text()) for cell in cells if normalize_space(cell.text()))
        if text:
            headers.append(text[:200])
        if len(headers) >= 5:
            break
    return headers


def _section_headings_debug(root: _Node) -> list[str]:
    headings: list[str] = []
    for node in root.descendants():
        if node.tag not in {"h1", "h2", "h3", "dt"}:
            continue
        text = normalize_space(node.text())
        if text and not _is_accordion_utility_label(text):
            headings.append(text[:160])
        if len(headings) >= 10:
            break
    return headings


def _href_patterns_debug(root: _Node, base_url: str) -> list[str]:
    counts: Counter[str] = Counter()
    for link in _links_in(root):
        href = link.attr_text("href")
        if not _is_candidate_profile_href(href):
            continue
        parsed = urlparse(urljoin(base_url, href))
        path = re.sub(r"/[0-9a-f]{8,}(?=\.|/|$)", "/<id>", parsed.path.lower())
        path = re.sub(r"/[^/]+\.(html|php|aspx)$", "/<slug>.\\1", path)
        parts = [part for part in path.split("/") if part][:4]
        pattern = f"{parsed.netloc}/{'/'.join(parts)}"
        counts[pattern] += 1
    patterns = [f"{pattern} ({count})" for pattern, count in counts.most_common(8)]
    category_link_count = _faculty_category_link_count(root)
    if category_link_count >= 3:
        patterns.append(f"possible_directory_index_page ({category_link_count} category links)")
    patterns.extend(_dynamic_filtered_directory_debug(root))
    return patterns


def _dynamic_filtered_directory_debug(root: _Node) -> list[str]:
    if not _has_faculty_department_designation_table(root):
        return []

    row_count = _faculty_department_designation_row_count(root)
    if row_count > 10:
        return []

    return [
        "possible_dynamic_or_filtered_directory "
        f"(rows={row_count}, "
        f"default_or_sample_rows={row_count <= 5}, "
        f"department_select={_has_department_select(root)}, "
        f"form_action={_first_form_action(root)}, "
        f"api_hints={'; '.join(_script_api_hints(root)) or 'none'})"
    ]


def _has_faculty_department_designation_table(root: _Node) -> bool:
    for header in _table_headers_debug(root):
        labels = [_header_label(part) for part in header.split("|")]
        if labels[:3] == ["faculty", "department", "designation"]:
            return True
    return False


def _faculty_department_designation_row_count(root: _Node) -> int:
    rows = 0
    for table in _nodes_by_tag(root, "table"):
        table_headers = []
        for row in _nodes_by_tag(table, "tr"):
            cells = _direct_children_by_tag(row, {"th", "td"})
            if not cells:
                continue
            if any(cell.tag == "th" for cell in cells):
                table_headers = [_header_label(cell.text()) for cell in cells]
                continue
            if table_headers[:3] == ["faculty", "department", "designation"]:
                rows += 1
    return rows


def _has_department_select(root: _Node) -> bool:
    for node in _nodes_by_tag(root, "select"):
        haystack = f"{node.attr_text('id')} {node.attr_text('name')} {node.attr_text('class')} {node.text()}".lower()
        if "department" in haystack or "dept" in haystack:
            return True
    return False


def _first_form_action(root: _Node) -> str:
    for node in _nodes_by_tag(root, "form"):
        return node.attr_text("action") or ""
    return "none"


def _script_api_hints(root: _Node) -> list[str]:
    hints: list[str] = []
    for node in _nodes_by_tag(root, "script"):
        haystack = f"{node.attr_text('src')} {node.text()}"
        for match in re.finditer(r"['\"]([^'\"]*(?:Departments|department|faculty|faclist)[^'\"]*)['\"]", haystack, flags=re.IGNORECASE):
            hint = normalize_space(match.group(1))
            if hint and hint not in hints:
                hints.append(hint[:120])
            if len(hints) >= 3:
                return hints
    return hints


def _faculty_category_link_count(root: _Node) -> int:
    count = 0
    for link in _links_in(root):
        href = link.attr_text("href").lower()
        if _is_faculty_category_label(link.text()) or "lehrende-personenverzeichnis" in href or "teaching-staff/teaching-staff" in href:
            count += 1
    return count


def _normalize_record_profile_url(value: str) -> str:
    parsed = urlparse(value)
    path = parsed.path.rstrip("/")
    query = urlencode(_profile_identity_query_pairs(value))
    return parsed._replace(path=path, query=query, fragment="").geturl().lower()


def _profile_identity_query_pairs(value: str) -> list[tuple[str, str]]:
    parsed = urlparse(value)
    pairs = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if item.strip()
        and not key.casefold().startswith("utm_")
        and key.casefold() not in {"fbclid", "gclid"}
        and key.casefold()
        not in {
            "page",
            "paged",
            "pagenum",
            "page_num",
            "page-number",
            "offset",
            "start",
            "limit",
            "sort",
            "sortby",
            "sort_by",
            "order",
            "orderby",
            "order_by",
            "search",
            "q",
            "query",
            "keyword",
            "filter",
            "filters",
            "department",
            "faculty",
            "school",
            "college",
            "unit",
            "category",
            "role",
            "type",
            "letter",
        }
    ]
    if not pairs:
        return []

    query_keys = {key.casefold() for key, _ in pairs}
    path = parsed.path.lower()
    has_legacy_identity = bool(
        query_keys & {"key", "page_id", "personid", "profileid", "staffid", "stref", "investigadorid"}
    )
    has_numeric_identity = any(item.isdigit() for _, item in pairs) and any(
        hint in path for hint in PROFILE_PATH_HINTS
    )
    endpoint = path.rstrip("/").rsplit("/", 1)[-1]
    has_html_id_identity = (
        "id" in query_keys
        and endpoint.endswith((".html", ".htm"))
        and endpoint not in {"index.html", "index.htm"}
    )
    if not (
        _is_query_profile_endpoint_path(parsed.path)
        or _is_person_detail_href(value)
        or _is_query_person_profile_url(value)
        or _is_repeated_person_detail_url(value)
        or _is_strong_stref_profile_url(value, "")
        or has_legacy_identity
        or has_numeric_identity
        or has_html_id_identity
    ):
        return []
    return sorted(pairs, key=lambda pair: (pair[0].casefold(), pair[1].casefold()))


def _is_query_profile_endpoint_path(path: str) -> bool:
    endpoint = path.rstrip("/").rsplit("/", 1)[-1].casefold()
    return endpoint in {
        "person",
        "persons",
        "profile",
        "profiles",
        "people",
        "employee",
        "employees",
        "staff",
        "faculty",
        "directory",
        "academic-staff",
        "academic_staff",
    }


def _is_repeated_person_detail_url(value: str) -> bool:
    parsed = urlparse(value)
    query_keys = {key.casefold() for key in parse_qs(parsed.query, keep_blank_values=True)}
    return "detalle-investigadores-cv" in parsed.path.lower() and "investigadorid" in query_keys


def _normalize_key(value: str) -> str:
    return normalize_space(value).casefold()


def _page_title(root: _Node) -> str:
    for node in root.descendants():
        if node.tag == "title":
            return node.text()
    return ""
