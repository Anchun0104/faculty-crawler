from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


SAFE_QUERY_KEYS = {
    "page",
    "paged",
    "offset",
    "start",
    "limit",
    "lang",
    "language",
    "department",
    "faculty",
    "school",
    "category",
    "group",
    "filter",
    "search",
    "q",
    "letter",
    "sort",
    "order",
}
_SENSITIVE_KEY_SEGMENTS = {
    "auth",
    "authentication",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "credentials",
    "csrf",
    "password",
    "passwd",
    "secret",
    "session",
    "sessionid",
    "sig",
    "signature",
    "ticket",
    "token",
}
_KEY_TOKEN = r"[A-Za-z][A-Za-z0-9_-]*"
_STRUCTURED_VALUE = re.compile(
    rf'''(?P<key_quote>["'])(?P<key>{_KEY_TOKEN})(?P=key_quote)\s*:\s*'''
    rf'''(?P<value_quote>["'])(?P<value>.*?)(?P=value_quote)''',
    re.IGNORECASE,
)
_LABEL_START = re.compile(
    rf"\b(?P<key>{_KEY_TOKEN})\s*(?P<separator>[:=])\s*",
    re.IGNORECASE,
)


def safe_exception_message(exc: Exception) -> str:
    message = next(
        (line.strip() for line in str(exc).splitlines() if line.strip()),
        type(exc).__name__,
    )
    message = redact_log_text(message)
    html_positions = [
        position
        for marker in ("<html", "<!doctype")
        if (position := message.lower().find(marker)) >= 0
    ]
    if html_positions:
        message = f"{message[:min(html_positions)].rstrip()} [HTML omitted]".strip()
    return message[:500]


def safe_url_for_log(value: str) -> str:
    parsed = urlparse(value)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        port = ""
    safe_query = []
    for key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.casefold() not in SAFE_QUERY_KEYS:
            query_value = "<redacted>"
        else:
            query_value = _redact_sensitive_text(query_value)
        safe_query.append((key, query_value))
    return urlunparse(
        (
            parsed.scheme,
            f"{hostname}{port}",
            parsed.path,
            parsed.params,
            urlencode(safe_query),
            "",
        )
    )


def redact_log_text(value: str, output_dir: Path | None = None) -> str:
    text = value
    if output_dir is not None:
        for directory in {str(output_dir), str(output_dir.resolve())}:
            text = text.replace(directory, "<output_dir>")
    text = re.sub(
        r"https?://[^\s'\"\]\[()<>]+",
        lambda match: safe_url_for_log(match.group(0).rstrip(".,;")),
        text,
        flags=re.IGNORECASE,
    )
    return _redact_sensitive_text(text)


def is_sensitive_key(key: str) -> bool:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    normalized = re.sub(r"[^a-z0-9]+", "_", separated.casefold()).strip("_")
    segments = set(normalized.split("_"))
    return (
        bool(segments & _SENSITIVE_KEY_SEGMENTS)
        or normalized.endswith("api_key")
        or normalized.endswith("apikey")
        or normalized.endswith("private_key")
        or normalized.endswith("privatekey")
    )


def _redact_sensitive_text(value: str) -> str:
    text = re.sub(
        r"(?i)\b(?:bearer|basic)\s+[^\s,;\"']+",
        lambda match: f"{match.group(0).split(maxsplit=1)[0]} <redacted>",
        value,
    )
    text = _STRUCTURED_VALUE.sub(_redact_structured_value, text)
    text = "".join(_redact_labeled_line(line) for line in text.splitlines(keepends=True))
    text = re.sub(r"(?i)\b[A-Z]:[\\/][^\r\n]*", "<local_path>", text)
    text = re.sub(
        r"(?i)\\\\[^\\/\r\n]+[\\/][^\\/\r\n]+(?:[\\/][^\r\n]*)?",
        "<local_path>",
        text,
    )
    return text


def _redact_structured_value(match: re.Match[str]) -> str:
    if not is_sensitive_key(match.group("key")):
        return match.group(0)
    return (
        f"{match.group('key_quote')}{match.group('key')}{match.group('key_quote')}: "
        f"{match.group('value_quote')}<redacted>{match.group('value_quote')}"
    )


def _redact_labeled_line(line: str) -> str:
    for match in _LABEL_START.finditer(line):
        if is_sensitive_key(match.group("key")):
            ending = "\n" if line.endswith("\n") else ""
            if line.endswith("\r\n"):
                ending = "\r\n"
            return (
                f"{line[:match.start()]}{match.group('key')}"
                f"{match.group('separator')}<redacted>{ending}"
            )
    return line
