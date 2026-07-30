from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from faculty_workflow.models import normalize_url


SUPPORTED_SOURCE_TYPES = frozenset({"faculty_directory", "research_unit", "research_portal", "profile"})


@dataclass(frozen=True)
class DiscoveryLimits:
    max_depth: int = 2
    max_pages: int = 50

    def __post_init__(self) -> None:
        if self.max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        if self.max_pages <= 0:
            raise ValueError("max_pages must be positive")


@dataclass(frozen=True)
class DirectorySource:
    url: str
    source_type: str
    discovered_from: str = ""
    depth: int = 0


@dataclass(frozen=True)
class DiscoveryHint:
    """An untrusted search result containing only a candidate URL and its query."""

    url: str
    query: str


class DiscoveryProvider(Protocol):
    def discover(
        self,
        *,
        name: str,
        school: str,
        official_domain: str,
    ) -> tuple[DiscoveryHint, ...]: ...


class EmptyDiscoveryProvider:
    def discover(
        self,
        *,
        name: str,
        school: str,
        official_domain: str,
    ) -> tuple[DiscoveryHint, ...]:
        return ()


class OfficialSourceGraph:
    """Finite FIFO of validated same-institution source URLs."""

    def __init__(self, official_domain: str, limits: DiscoveryLimits | None = None) -> None:
        parsed = urlparse(
            official_domain if "://" in official_domain else f"https://{official_domain}"
        )
        self.official_host = (parsed.hostname or "").casefold().rstrip(".")
        if not self.official_host:
            raise ValueError("official_domain must contain a hostname")
        self.limits = limits or DiscoveryLimits()
        self._queue: deque[DirectorySource] = deque()
        self._seen: set[str] = set()
        self._stop_reason = ""

    @property
    def stop_reason(self) -> str:
        return self._stop_reason

    def enqueue(
        self,
        url: str,
        source_type: str,
        discovered_from: str = "",
        depth: int = 0,
    ) -> bool:
        normalized = normalize_url(url)
        if source_type not in SUPPORTED_SOURCE_TYPES or not normalized:
            return False
        host = (urlparse(normalized).hostname or "").casefold().rstrip(".")
        if not _same_institution_host(host, self.official_host):
            return False
        if depth < 0 or depth > self.limits.max_depth:
            self._stop_reason = self._stop_reason or "depth_limit_reached"
            return False
        if normalized in self._seen:
            return False
        if len(self._seen) >= self.limits.max_pages:
            self._stop_reason = "page_budget_reached"
            return False
        self._seen.add(normalized)
        self._queue.append(
            DirectorySource(
                url=normalized,
                source_type=source_type,
                discovered_from=normalize_url(discovered_from),
                depth=depth,
            )
        )
        return True

    def pop(self) -> DirectorySource | None:
        return self._queue.popleft() if self._queue else None


def _same_institution_host(host: str, official_host: str) -> bool:
    return bool(
        host
        and official_host
        and (host == official_host or host.endswith("." + official_host))
    )
