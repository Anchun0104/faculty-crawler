"""Deterministic design tokens for the light desktop theme."""

from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class DesignTokens:
    """Values shared by all Faculty Crawler desktop UI surfaces."""

    app_background: str = "#F4F7FA"
    primary: str = "#1769AA"
    nav_expanded: int = 220
    nav_collapsed: int = 56
    inspector_width: int = 360


LIGHT_TOKENS = DesignTokens()


def load_theme_qss() -> str:
    """Load the packaged theme with its token placeholders resolved."""
    source = resources.files("desktop_ui").joinpath("theme.qss").read_text("utf-8")
    return (
        source.replace("@APP_BACKGROUND@", LIGHT_TOKENS.app_background)
        .replace("@PRIMARY@", LIGHT_TOKENS.primary)
    )
