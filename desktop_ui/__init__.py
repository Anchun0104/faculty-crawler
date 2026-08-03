"""Shared desktop UI primitives for Faculty Crawler."""

from .app import run_desktop
from .tokens import DesignTokens, LIGHT_TOKENS, load_theme_qss

__all__ = ("DesignTokens", "LIGHT_TOKENS", "load_theme_qss", "run_desktop")
