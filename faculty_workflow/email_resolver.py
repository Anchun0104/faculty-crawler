from __future__ import annotations

import html as html_module
import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import unquote, urljoin, urlparse

from faculty_workflow.fetcher import FetchedPage


EMAIL_RE = re.compile(r"[A-Z0-9._%+'-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
OBFUSCATED_EMAIL_RE = re.compile(
    r"(?P<local>[A-Z0-9._%+'-]+)\s*(?:\[\s*at\s*\]|\(\s*at\s*\)|\bat\b)\s*"
    r"(?P<domain>[A-Z0-9.-]+?)\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\bdot\b)\s*"
    r"(?P<tld>[A-Z]{2,})\b",
    re.IGNORECASE,
)
GENERIC_LOCAL_PARTS = {
    "admin", "admissions", "advising", "communications", "contact", "department",
    "dean", "enquiries", "enquiry", "faculty", "help", "info", "media", "office", "press",
    "school", "secretariat", "support", "tiedotus", "webmaster",
    "firstnamelastname", "namesurname", "nombreapellido", "usuario", "user",
}
NAME_STOP_WORDS = {
    "adjunct", "assistant", "associate", "chair", "department", "docent", "doctor", "dr",
    "emeritus", "faculty", "fellow", "lecturer", "phd", "physics", "postdoc",
    "postdoctoral", "prof", "professor", "researcher", "scientist", "senior", "staff",
    "university", "visiting",
}
FOLLOW_LINK_WORDS = {
    "contact", "contacts", "email", "e-mail", "homepage", "person", "personal page",
    "profile", "publications", "publication", "research portal", "staff page", "web page",
}
FOLLOW_PATH_WORDS = (
    "/people/", "/person/", "/profile/", "/profiles/", "/staff/", "/team/",
    "/research/", "/researchers/", "/publications/", "/publication/", "/repository/",
)


@dataclass(frozen=True)
class EmailResolution:
    email: str
    source_url: str
    quote: str
    extraction_method: str
    fetched_pages: tuple[FetchedPage, ...] = ()


@dataclass(frozen=True)
class _EmailCandidate:
    email: str
    quote: str
    score: int
    method: str


class OfficialEmailResolver:
    """Resolve a printed personal email without deriving or guessing an address.

    The current profile is inspected first. Only when it has no defensible personal
    address are a few explicitly linked pages on the confirmed school domain fetched.
    """

    def __init__(self, *, max_followups: int = 3) -> None:
        self.max_followups = max(0, max_followups)

    def resolve(
        self,
        *,
        name: str,
        page: FetchedPage,
        official_domain: str,
        fetch_page: Callable[[str], FetchedPage] | None = None,
    ) -> EmailResolution | None:
        domain = _normalize_domain(official_domain)
        tokens = _name_token_variants(name)
        if not domain or not tokens:
            return None

        current = _best_email(name, tokens, page, domain)
        if current is not None:
            return EmailResolution(
                current.email, page.final_url, current.quote, current.method
            )

        if fetch_page is None or self.max_followups == 0:
            return None

        fetched: list[FetchedPage] = []
        for link in _rank_followup_links(page, name, tokens, domain)[: self.max_followups]:
            try:
                followup = fetch_page(link)
            except Exception:
                # A secondary source is optional; the primary profile remains reviewable.
                continue
            fetched.append(followup)
            if not _page_matches_person(followup, name, tokens):
                continue
            candidate = _best_email(name, tokens, followup, domain)
            if candidate is not None:
                return EmailResolution(
                    candidate.email,
                    followup.final_url,
                    candidate.quote,
                    "official_followup_" + candidate.method,
                    tuple(fetched),
                )
        return None


def _best_email(
    name: str,
    token_variants: tuple[tuple[str, ...], ...],
    page: FetchedPage,
    official_domain: str,
) -> _EmailCandidate | None:
    sources: list[tuple[str, str]] = [(page.text or "", "visible_text")]
    decoded_html = html_module.unescape(unquote(page.html or ""))
    sources.append((decoded_html, "html_attribute"))
    obfuscated = [
        (f"{match.group('local')}@{match.group('domain')}.{match.group('tld')}", match.group(0))
        for match in OBFUSCATED_EMAIL_RE.finditer(page.text or "")
    ]
    split_mailtos = _split_mailto_candidates(page.html or "", official_domain)
    found: dict[str, _EmailCandidate] = {}
    official_candidates: dict[str, _EmailCandidate] = {}
    for source, method in sources:
        for match in EMAIL_RE.finditer(source):
            email = match.group(0).strip(".,;:<>[](){}\"'").casefold()
            if _eligible_official_email(email, official_domain):
                context = " ".join(source[max(0, match.start() - 180):match.end() + 180].split())
                official_candidates.setdefault(
                    email, _EmailCandidate(email, context[:400] or email, 0, method)
                )
            candidate = _score_email(email, source, match.start(), name, token_variants, official_domain, method)
            if candidate is not None and (email not in found or candidate.score > found[email].score):
                found[email] = candidate
    for email, original in obfuscated:
        candidate = _score_email(email.casefold(), original, 0, name, token_variants, official_domain, "obfuscated_text")
        if candidate is not None and (email not in found or candidate.score > found[email].score):
            found[email] = candidate
    for email, original in split_mailtos:
        official_candidates.setdefault(
            email, _EmailCandidate(email, original[:400] or email, 0, "split_mailto")
        )
        candidate = _score_email(email, original, 0, name, token_variants, official_domain, "split_mailto")
        if candidate is not None and (email not in found or candidate.score > found[email].score):
            found[email] = candidate
    if not found:
        # Names and email local-parts often use different scripts (for example,
        # Cyrillic display names and Latin transliterations). A unique, non-generic
        # official address on an identity-matched personal page is still literal
        # evidence and does not require guessing the transliteration.
        if (
            len(official_candidates) == 1
            and _page_matches_person(page, name, token_variants)
            and _requires_transliteration_fallback(name, next(iter(official_candidates)))
        ):
            only = next(iter(official_candidates.values()))
            return _EmailCandidate(only.email, only.quote, 1, "identity_bound_" + only.method)
        return None
    return max(found.values(), key=lambda item: (item.score, item.email))


def _score_email(
    email: str,
    source: str,
    position: int,
    name: str,
    token_variants: tuple[tuple[str, ...], ...],
    official_domain: str,
    method: str,
) -> _EmailCandidate | None:
    if not _eligible_official_email(email, official_domain):
        return None
    local = _ascii_key(email.split("@", 1)[0])

    matched_groups = [variants for variants in token_variants if any(value and value in local for value in variants)]
    if not matched_groups:
        return None
    longest = max((len(value) for variants in matched_groups for value in variants if value in local), default=0)
    if longest < 3 and len(matched_groups) < 2:
        return None

    start = max(0, position - 180)
    end = min(len(source), position + len(email) + 180)
    context = " ".join(source[start:end].split())
    context_key = _ascii_key(context)
    full_name_key = _ascii_key(_strip_name_noise(name))
    score = len(matched_groups) * 5 + min(longest, 10)
    if full_name_key and full_name_key in context_key:
        score += 6
    elif sum(any(value in context_key for value in variants) for variants in token_variants) >= 2:
        score += 3
    if method == "visible_text":
        score += 2
    quote = context[:400] if context else email
    return _EmailCandidate(email, quote, score, method)


class _LinkCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        self._href = dict(attrs).get("href") or ""
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = ""
            self._text = []


class _SplitMailtoCollector(HTMLParser):
    """Collect addresses whose local part and domain are stored separately."""

    def __init__(self, official_domain: str) -> None:
        super().__init__(convert_charrefs=True)
        self.official_domain = official_domain
        self.candidates: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            return
        values = {key.casefold(): value or "" for key, value in attrs}
        classes = {value.casefold() for value in values.get("class", "").split()}
        href = unquote(values.get("href", ""))
        if "email-link" not in classes or not href.casefold().startswith("mailto:"):
            return
        local = href[7:].split("?", 1)[0].strip()
        if "@" in local or not re.fullmatch(r"[A-Z0-9._%+'-]+", local, re.IGNORECASE):
            return
        domain = _complete_split_domain(values.get("rel", ""), self.official_domain)
        email = f"{local}@{domain}".casefold() if domain else ""
        if not _eligible_official_email(email, self.official_domain):
            return
        context = " ".join(
            value for value in (values.get("title", ""), values.get("aria-label", ""), email) if value
        )
        self.candidates.append((email, context))


def _split_mailto_candidates(html: str, official_domain: str) -> list[tuple[str, str]]:
    parser = _SplitMailtoCollector(official_domain)
    try:
        parser.feed(html or "")
    except Exception:
        return []
    return parser.candidates


def _complete_split_domain(fragment: str, official_domain: str) -> str:
    fragment = (fragment or "").strip().casefold().strip(".")
    domain = _normalize_domain(official_domain)
    if not fragment or not domain:
        return ""
    if _host_on_domain(fragment, domain):
        return fragment
    fragment_labels = fragment.split(".")
    domain_labels = domain.split(".")
    if not domain_labels[0].startswith(fragment_labels[-1]):
        return ""
    suffix = domain_labels[0][len(fragment_labels[-1]):]
    candidate = ".".join((*fragment_labels[:-1], fragment_labels[-1] + suffix, *domain_labels[1:]))
    return candidate if _host_on_domain(candidate, domain) else ""


def _rank_followup_links(
    page: FetchedPage,
    name: str,
    token_variants: tuple[tuple[str, ...], ...],
    official_domain: str,
) -> list[str]:
    parser = _LinkCollector()
    try:
        parser.feed(page.html or "")
    except Exception:
        return []
    current = page.final_url.split("#", 1)[0].rstrip("/").casefold()
    ranked: dict[str, int] = {}
    full_name = _ascii_key(_strip_name_noise(name))
    for href, anchor in parser.links:
        absolute = urljoin(page.final_url, href).split("#", 1)[0]
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"} or not _host_on_domain(parsed.hostname or "", official_domain):
            continue
        if absolute.rstrip("/").casefold() == current:
            continue
        path = unquote(parsed.path).casefold()
        if path.endswith((".jpg", ".jpeg", ".png", ".gif", ".zip", ".doc", ".docx", ".xlsx")):
            continue
        haystack = _ascii_key(anchor + " " + path)
        token_hits = sum(any(value in haystack for value in variants) for variants in token_variants)
        anchor_lower = " ".join(anchor.casefold().split())
        link_word = any(word in anchor_lower for word in FOLLOW_LINK_WORDS)
        path_word = any(word in path for word in FOLLOW_PATH_WORDS)
        if not (token_hits or full_name and full_name in haystack or link_word and path_word):
            continue
        score = token_hits * 6 + int(bool(full_name and full_name in haystack)) * 8
        score += int(link_word) * 3 + int(path_word) * 2 + int(path.endswith(".pdf"))
        ranked[absolute] = max(score, ranked.get(absolute, 0))
    return [url for url, _ in sorted(ranked.items(), key=lambda item: (-item[1], item[0]))]


def _page_matches_person(
    page: FetchedPage,
    name: str,
    token_variants: tuple[tuple[str, ...], ...],
) -> bool:
    text_key = _ascii_key(" ".join((page.title or "", page.text or "")))
    full_name = _ascii_key(_strip_name_noise(name))
    if full_name and full_name in text_key:
        return True
    return sum(any(value in text_key for value in variants) for variants in token_variants) >= 2


def _name_token_variants(name: str) -> tuple[tuple[str, ...], ...]:
    cleaned = _strip_name_noise(name)
    groups: list[tuple[str, ...]] = []
    for raw in re.findall(r"[^\W\d_]+", cleaned, flags=re.UNICODE):
        lowered = raw.casefold()
        if lowered in NAME_STOP_WORDS or len(lowered) < 2:
            continue
        variants = {_ascii_key(lowered), _german_email_key(lowered)}
        values = tuple(sorted(value for value in variants if value))
        if values and values not in groups:
            groups.append(values)
    return tuple(groups)


def _strip_name_noise(name: str) -> str:
    return re.sub(r"\b(?:prof(?:essor)?|dr|ph\.?d|msc|bsc)\.?\b", " ", name or "", flags=re.IGNORECASE)


def _ascii_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in normalized if not unicodedata.combining(char) and char.isalnum()).casefold()


def _german_email_key(value: str) -> str:
    translated = value.casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return _ascii_key(translated)


def _normalize_domain(value: str) -> str:
    raw = (value or "").strip().casefold().lstrip(".")
    if "://" in raw:
        raw = urlparse(raw).hostname or ""
    raw = raw.rstrip(".")
    return raw[4:] if raw.startswith("www.") else raw


def _host_on_domain(host: str, official_domain: str) -> bool:
    domain = _normalize_domain(official_domain)
    hostname = (host or "").strip().casefold().rstrip(".")
    return bool(domain and (hostname == domain or hostname.endswith("." + domain)))


def _email_on_domain(email: str, official_domain: str) -> bool:
    return "@" in email and _host_on_domain(email.rsplit("@", 1)[-1], official_domain)


def _eligible_official_email(email: str, official_domain: str) -> bool:
    if not EMAIL_RE.fullmatch(email) or not _email_on_domain(email, official_domain):
        return False
    local = _ascii_key(email.split("@", 1)[0])
    return bool(local and local not in GENERIC_LOCAL_PARTS)


def _requires_transliteration_fallback(name: str, email: str) -> bool:
    """Limit identity-only matching to a real script boundary, not a different person."""
    name_has_non_latin = any(character.isalpha() and ord(character) > 127 for character in name or "")
    local = email.split("@", 1)[0]
    return name_has_non_latin and all(ord(character) < 128 for character in local)
