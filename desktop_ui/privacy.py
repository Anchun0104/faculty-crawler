"""Shared presentation-layer redaction for diagnostics shown to operators."""

from __future__ import annotations

from crawler.privacy import safe_exception_message


def redact_diagnostic(value: object) -> str:
    """Keep diagnostic categories readable without exposing credential values."""
    return safe_exception_message(RuntimeError(str(value)))
