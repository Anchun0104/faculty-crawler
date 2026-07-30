from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse


EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", re.UNICODE)
HONORIFIC_RE = re.compile(
    r"^(?:(?:prof(?:essor)?|dr|dra|doctor|doctora|ph\.?d|dipl\.-?ing)\.?\s+)+",
    re.IGNORECASE,
)
ACADEMIC_ROLE_MARKERS = (
    # English
    "professor", "reader", "lecturer", "postdoc", "postdoctoral", "researcher",
    "research fellow", "research associate", "staff scientist", "research scientist",
    # Spanish / Portuguese
    "profesor", "profesora", "docente", "catedrático", "catedrática",
    "investigador", "investigadora", "pesquisador", "pesquisadora",
    # German
    "professor", "professorin", "wissenschaftlicher mitarbeiter",
    "wissenschaftliche mitarbeiterin", "akademischer rat", "akademische rätin",
    # Russian
    "профессор", "доцент", "старший преподаватель", "преподаватель", "постдок",
    "главный научный сотрудник", "ведущий научный сотрудник",
    "старший научный сотрудник", "младший научный сотрудник", "научный сотрудник",
)
NON_PERSON_LABELS = {
    "view abstract", "read more", "staff profile", "personal docente", "contact",
    "email", "e-mail", "publications", "publication", "research", "profile",
    "about the group", "head of division", "head of divison",
}
NON_PERSON_NAME_MARKERS = (
    "content on this page", "current members", "featured in", "leave feedback",
    "physics and astronomy", "related content", "release of ", "research group",
    "research projects",
)
PLACEHOLDER_EMAIL_LOCAL_PARTS = {
    "firstname.lastname", "name.surname", "nombre.apellido", "usuario", "user",
}
PROFILE_PATH_MARKERS = (
    "/people/", "/person/", "/profile/", "/profiles/", "/staff/", "/userprofile/",
    "/employee/", "/employees/",
)


@dataclass(frozen=True)
class DirectoryRecord:
    name: str
    title: str = ""
    profile_url: str = ""
    email: str = ""
    quote: str = ""
    extraction_method: str = "universal_directory"


@dataclass(frozen=True)
class DirectoryExtraction:
    records: tuple[DirectoryRecord, ...]
    page_kind: str
    authoritative: bool


class _Node:
    def __init__(self, tag: str, attrs: dict[str, str], parent: _Node | None = None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_Node] = []
        self.parts: list[str] = []
        self.content: list[str | _Node] = []

    def text(self) -> str:
        values: list[str] = []
        for item in self.content:
            value = item.text() if isinstance(item, _Node) else item
            if value:
                values.append(value)
        return _space(" ".join(values))

    def descendants(self) -> list[_Node]:
        result: list[_Node] = []
        for child in self.children:
            result.append(child)
            result.extend(child.descendants())
        return result

    def classes(self) -> set[str]:
        return {item.casefold() for item in self.attrs.get("class", "").split() if item}


class _DOMParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self.current = self.root

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.casefold(), {key.casefold(): value or "" for key, value in attrs}, self.current)
        self.current.children.append(node)
        self.current.content.append(node)
        self.current = node

    def handle_endtag(self, tag: str) -> None:
        wanted = tag.casefold()
        node = self.current
        while node.parent is not None:
            if node.tag == wanted:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data: str) -> None:
        value = _space(data)
        if value:
            self.current.parts.append(value)
            self.current.content.append(value)


def _looks_like_single_profile_url(value: str) -> bool:
    path = urlparse(value).path.casefold()
    return any(marker in path for marker in (
        "/people/", "/person/", "/persons/", "/profile/", "/profiles/",
        "/employee/", "/employees/", "/userprofile/",
    ))


def _looks_like_directory_url(value: str) -> bool:
    path = urlparse(value).path.casefold()
    return any(marker in path for marker in (
        "/directory", "/faculty", "/people", "/personal", "/staff", "/team",
    ))


class UniversalDirectoryAdapter:
    """Recognize reusable directory archetypes without school-specific identities."""

    def extract(self, html: str, base_url: str) -> DirectoryExtraction:
        parser = _DOMParser()
        try:
            parser.feed(html or "")
        except Exception:
            return DirectoryExtraction((), "unknown", False)
        nodes = parser.root.descendants()

        accordion = self._accordion_records(nodes, base_url)
        if len(accordion) >= 2:
            return DirectoryExtraction(_deduplicate(accordion), "accordion_directory", True)

        employee_list = self._employee_list_records(nodes, base_url)
        if len(employee_list) >= 2:
            return DirectoryExtraction(_deduplicate(employee_list), "employee_list", True)

        single = self._single_profile_record(nodes, base_url)
        if single is not None:
            return DirectoryExtraction((single,), "single_profile", True)

        email_cards = _deduplicate(self._email_card_records(nodes, base_url))
        if len(email_cards) >= 2:
            return DirectoryExtraction(email_cards, "email_cards", True)
        if (
            len(email_cards) == 1
            and not email_cards[0].profile_url
            and not _looks_like_directory_url(base_url)
        ):
            email_cards = ()
        return DirectoryExtraction(email_cards, "unknown", False)

    def _accordion_records(self, nodes: list[_Node], base_url: str) -> list[DirectoryRecord]:
        records: list[DirectoryRecord] = []
        for node in nodes:
            if "accordion-item" not in node.classes():
                continue
            emails = _emails(node.text())
            if len(emails) != 1:
                continue
            name = _first_name_heading(node, tags={"button", "h2", "h3", "h4", "h5"})
            if not name:
                continue
            title = _labeled_value(node.text(), ("cargo", "position", "title", "puesto"))
            email = _usable_email(emails[0])
            records.append(DirectoryRecord(
                name=name,
                title=title,
                profile_url=_profile_link(node, base_url, name),
                email=email,
                quote=_quote(name, title, email),
                extraction_method="accordion_directory",
            ))
        return records

    def _employee_list_records(self, nodes: list[_Node], base_url: str) -> list[DirectoryRecord]:
        records: list[DirectoryRecord] = []
        for node in nodes:
            if node.tag != "a" or "list-group-item-action" not in node.classes():
                continue
            heading = next((item for item in node.descendants() if item.tag in {"h3", "h4", "h5"}), None)
            if heading is None:
                continue
            name = _clean_name(heading.text())
            title_node = next((
                item for item in node.descendants()
                if item.tag in {"p", "span", "div"}
                and ("list-group-item-text" in item.classes() or "role" in " ".join(item.classes()))
            ), None)
            title = _space(title_node.text() if title_node else "")
            if not _plausible_name(name) or not _academic_role(title):
                continue
            href = node.attrs.get("href", "")
            profile_url = urljoin(base_url, href) if href else ""
            records.append(DirectoryRecord(
                name=name,
                title=title,
                profile_url=profile_url,
                email=(_emails(node.text()) or [""])[0],
                quote=_quote(name, title, (_emails(node.text()) or [""])[0]),
                extraction_method="employee_list",
            ))
        return records

    def _single_profile_record(self, nodes: list[_Node], base_url: str) -> DirectoryRecord | None:
        if not _looks_like_single_profile_url(base_url):
            return None
        name_node = next((
            node for node in nodes
            if node.tag == "h1" and (
                any("profile-name" in value for value in node.classes())
                or node.attrs.get("itemprop", "").casefold() == "name"
            )
        ), None)
        if name_node is None:
            return None
        name = _clean_name(name_node.text())
        if not _plausible_name(name):
            return None
        page_text = _nearest_profile_container(name_node).text()
        emails = _emails(page_text)
        if len(emails) != 1:
            return None
        title_node = next((
            node for node in nodes
            if any("profile-role" in value or "profile-title" in value for value in node.classes())
        ), None)
        title = _space(title_node.text() if title_node else "")
        return DirectoryRecord(
            name=name,
            title=title,
            profile_url=base_url,
            email=emails[0],
            quote=_quote(name, title, emails[0]),
            extraction_method="single_profile_header",
        )

    def _email_card_records(self, nodes: list[_Node], base_url: str) -> list[DirectoryRecord]:
        records: list[DirectoryRecord] = []
        seen_containers: set[int] = set()
        for node in nodes:
            if node.tag != "a" or not node.attrs.get("href", "").casefold().startswith("mailto:"):
                continue
            container = _person_email_container(node)
            if container is None or id(container) in seen_containers:
                continue
            seen_containers.add(id(container))
            emails = _emails(container.text())
            if len(emails) != 1:
                continue
            name = _first_name_heading(container)
            if not name:
                continue
            title = _title_from_container(container)
            records.append(DirectoryRecord(
                name=name,
                title=title,
                profile_url=_profile_link(container, base_url, name),
                email=emails[0],
                quote=_quote(name, title, emails[0]),
                extraction_method="repeated_email_card",
            ))
        return records


def _person_email_container(node: _Node) -> _Node | None:
    current = node.parent
    while current is not None and current.tag != "document":
        if current.tag in {"article", "li", "tr", "section", "div"}:
            emails = _emails(current.text())
            if len(emails) > 2:
                return None
            if len(emails) == 1 and _first_name_heading(current):
                return current
        current = current.parent
    return None


def _nearest_profile_container(node: _Node) -> _Node:
    current = node
    fallback = node.parent or node
    while current.parent is not None:
        if current.tag in {"article", "section", "main"} or any("profile-card" in value for value in current.classes()):
            fallback = current
            if _emails(current.text()):
                return current
        current = current.parent
    return fallback


def _first_name_heading(node: _Node, tags: set[str] | None = None) -> str:
    allowed = tags or {"h1", "h2", "h3", "h4", "h5", "h6", "button"}
    candidates = [node, *node.descendants()]
    for candidate in candidates:
        if candidate.tag not in allowed:
            continue
        name, _ = _name_and_parenthesized_title(candidate.text())
        if _plausible_name(name):
            return name
    return ""


def _name_and_parenthesized_title(value: str) -> tuple[str, str]:
    """Split headings such as ``Name (Visiting Professor)`` conservatively."""
    cleaned = _space(value)
    match = re.fullmatch(r"(?P<name>.+?)\s*\((?P<title>[^()]{2,100})\)", cleaned)
    if match and _academic_role(match.group("title")):
        return _clean_name(match.group("name")), _space(match.group("title"))
    return _clean_name(cleaned), ""


def _clean_name(value: str) -> str:
    result = HONORIFIC_RE.sub("", _space(value)).strip(" ,;|-–—")
    return re.sub(r"\s+(?:Ph\.?D\.?|M\.?D\.?)$", "", result, flags=re.IGNORECASE).strip()


def _plausible_name(value: str) -> bool:
    if not value or len(value) > 100 or value.casefold() in NON_PERSON_LABELS:
        return False
    if any(marker in value.casefold() for marker in NON_PERSON_NAME_MARKERS):
        return False
    if re.search(r"\b(?:lab|laboratory)\s*$", value, flags=re.IGNORECASE):
        return False
    if re.search(r"https?://|@|\d{3,}", value):
        return False
    words = [item.strip(".,;:()[]") for item in value.split() if item.strip(".,;:()[]")]
    if not 2 <= len(words) <= 7:
        return False
    name_particles = {
        "al", "bin", "da", "das", "de", "del", "della", "den", "der", "di",
        "dos", "du", "el", "la", "le", "van", "von", "y", "zu", "zum", "zur",
    }
    unexpected_lowercase = [
        word for word in words[1:]
        if word[:1].islower() and word.casefold() not in name_particles
    ]
    if unexpected_lowercase:
        return False
    alpha_words = [word for word in words if sum(character.isalpha() for character in word) >= 2]
    return len(alpha_words) >= 2 and not _academic_role(value)


def _academic_role(value: str) -> bool:
    lowered = _space(value).casefold()
    return any(marker in lowered for marker in ACADEMIC_ROLE_MARKERS)


def _title_from_container(node: _Node) -> str:
    text = node.text()
    labeled = _labeled_value(text, ("cargo", "position", "title", "puesto"))
    if labeled:
        return labeled
    for child in node.descendants():
        value = child.text()
        _, parenthesized_title = _name_and_parenthesized_title(value)
        if parenthesized_title:
            return parenthesized_title
        if len(value) <= 120 and _academic_role(value):
            return value
    return ""


def _labeled_value(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(
            rf"\b{re.escape(label)}\s*:\s*(?P<value>[^|;\n]{{2,100}}?)(?=\s+(?:tel[eé]fono|phone|correo|email|e-mail|especializaci[oó]n)\s*:|$)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            value = _space(match.group("value"))
            # A flattened container can be long; the role itself is normally short.
            for marker in sorted(ACADEMIC_ROLE_MARKERS, key=len, reverse=True):
                role = re.search(re.escape(marker), value, flags=re.IGNORECASE)
                if role:
                    return value[: role.end()].strip()
            return value[:100].strip()
    return ""


def _profile_link(node: _Node, base_url: str, name: str) -> str:
    generic_tokens = {
        "department", "faculty", "group", "laboratory", "people", "physics",
        "research", "science", "staff", "team", "workshop",
    }
    name_tokens = {
        _key(part) for part in name.split()
        if len(_key(part)) >= 3 and _key(part) not in generic_tokens
    }
    for candidate in [node, *node.descendants()]:
        if candidate.tag != "a":
            continue
        href = candidate.attrs.get("href", "")
        if not href or href.casefold().startswith(("mailto:", "tel:", "#")):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        path = parsed.path.casefold()
        haystack = _key(candidate.text() + " " + path)
        if any(marker in path for marker in PROFILE_PATH_MARKERS) and (
            not name_tokens or any(token in haystack for token in name_tokens)
        ):
            return absolute
    return ""


def _emails(value: str) -> list[str]:
    return list(dict.fromkeys(match.group(0).casefold() for match in EMAIL_RE.finditer(value or "")))


def _usable_email(email: str) -> str:
    local = (email or "").split("@", 1)[0].casefold()
    return "" if local in PLACEHOLDER_EMAIL_LOCAL_PARTS else email


def _quote(name: str, title: str, email: str) -> str:
    return " | ".join(value for value in (name, title, email) if value)[:500]


def _space(value: str) -> str:
    return " ".join((value or "").split())


def _key(value: str) -> str:
    return "".join(character for character in (value or "").casefold() if character.isalnum())


def _deduplicate(records: list[DirectoryRecord]) -> tuple[DirectoryRecord, ...]:
    result: list[DirectoryRecord] = []
    seen: set[tuple[str, str, str]] = set()
    for record in records:
        key = (_key(record.name), record.email.casefold(), record.profile_url.casefold().rstrip("/"))
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return tuple(result)
