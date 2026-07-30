from __future__ import annotations

import re
from typing import Protocol


class AccessAdapter(Protocol):
    """A deterministic page transform selected by URL, never by professor identity."""

    name: str

    def matches(self, url: str) -> bool: ...

    def preprocess_html(self, url: str, html: str) -> str: ...


class AdapterRegistry:
    def __init__(self, adapters: list[AccessAdapter] | None = None) -> None:
        self.adapters = list(adapters or [CloudflareEmailAdapter()])

    def preprocess_html(self, url: str, html: str) -> str:
        result = html
        for adapter in self.adapters:
            if adapter.matches(url):
                result = adapter.preprocess_html(url, result)
        return result


class CloudflareEmailAdapter:
    """Decode Cloudflare's public data-cfemail representation without site-specific data."""

    name = "cloudflare_email"
    _ELEMENT = re.compile(
        r"(<(?P<tag>[a-zA-Z0-9]+)\b[^>]*\bdata-cfemail=[\"'](?P<token>[0-9a-fA-F]+)[\"'][^>]*>)(?P<body>.*?)(</(?P=tag)>)",
        re.IGNORECASE | re.DOTALL,
    )
    _MAILTO = re.compile(r"/cdn-cgi/l/email-protection#(?P<token>[0-9a-fA-F]+)", re.IGNORECASE)

    def matches(self, url: str) -> bool:
        return True

    def preprocess_html(self, url: str, html: str) -> str:
        def replace_element(match: re.Match[str]) -> str:
            decoded = _decode_cfemail(match.group("token"))
            return f"{match.group(1)}{decoded}{match.group(5)}" if decoded else match.group(0)

        def replace_mailto(match: re.Match[str]) -> str:
            decoded = _decode_cfemail(match.group("token"))
            return f"mailto:{decoded}" if decoded else match.group(0)

        return self._MAILTO.sub(replace_mailto, self._ELEMENT.sub(replace_element, html))


def _decode_cfemail(token: str) -> str:
    try:
        raw = bytes.fromhex(token)
    except ValueError:
        return ""
    if len(raw) < 2:
        return ""
    key = raw[0]
    return "".join(chr(value ^ key) for value in raw[1:])
