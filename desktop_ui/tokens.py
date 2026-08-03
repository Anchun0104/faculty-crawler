"""Deterministic design tokens for the light desktop theme."""

from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class DesignTokens:
    """Values shared by all Faculty Crawler desktop UI surfaces."""

    app_background: str = "#F4F7FA"
    nav_background: str = "#EDF2F7"
    surface_primary: str = "#FFFFFF"
    surface_secondary: str = "#F8FAFC"
    surface_hover: str = "#F2F6FA"
    text_primary: str = "#18212F"
    text_secondary: str = "#667085"
    text_tertiary: str = "#98A2B3"
    border_default: str = "#DFE5EC"
    border_subtle: str = "#EDF1F5"
    primary: str = "#1769AA"
    primary_hover: str = "#125C97"
    primary_pressed: str = "#0E4E82"
    primary_soft: str = "#E8F2FB"
    success: str = "#17875B"
    success_soft: str = "#E8F6EF"
    warning: str = "#B56A08"
    warning_soft: str = "#FFF3DC"
    danger: str = "#C53B3F"
    danger_soft: str = "#FDECED"
    info: str = "#3976C6"
    info_soft: str = "#EEF7FE"
    nav_expanded: int = 220
    nav_collapsed: int = 56
    inspector_width: int = 360
    titlebar_height: int = 48
    pagebar_height: int = 64
    control_sm: int = 28
    control_md: int = 34
    control_lg: int = 40
    table_header: int = 36
    table_row: int = 40
    table_row_comfortable: int = 48
    radius_control: int = 8
    radius_panel: int = 12
    radius_dialog: int = 14


LIGHT_TOKENS = DesignTokens()


def load_theme_qss() -> str:
    """Load the packaged theme with its token placeholders resolved."""
    source = resources.files("desktop_ui").joinpath("theme.qss").read_text("utf-8")
    return (
        source.replace("@APP_BACKGROUND@", LIGHT_TOKENS.app_background)
        .replace("@NAV_BACKGROUND@", LIGHT_TOKENS.nav_background)
        .replace("@SURFACE_PRIMARY@", LIGHT_TOKENS.surface_primary)
        .replace("@SURFACE_SECONDARY@", LIGHT_TOKENS.surface_secondary)
        .replace("@SURFACE_HOVER@", LIGHT_TOKENS.surface_hover)
        .replace("@TEXT_PRIMARY@", LIGHT_TOKENS.text_primary)
        .replace("@TEXT_SECONDARY@", LIGHT_TOKENS.text_secondary)
        .replace("@TEXT_TERTIARY@", LIGHT_TOKENS.text_tertiary)
        .replace("@BORDER_DEFAULT@", LIGHT_TOKENS.border_default)
        .replace("@BORDER_SUBTLE@", LIGHT_TOKENS.border_subtle)
        .replace("@PRIMARY@", LIGHT_TOKENS.primary)
        .replace("@PRIMARY_HOVER@", LIGHT_TOKENS.primary_hover)
        .replace("@PRIMARY_PRESSED@", LIGHT_TOKENS.primary_pressed)
        .replace("@PRIMARY_SOFT@", LIGHT_TOKENS.primary_soft)
        .replace("@SUCCESS@", LIGHT_TOKENS.success)
        .replace("@SUCCESS_SOFT@", LIGHT_TOKENS.success_soft)
        .replace("@WARNING@", LIGHT_TOKENS.warning)
        .replace("@WARNING_SOFT@", LIGHT_TOKENS.warning_soft)
        .replace("@DANGER@", LIGHT_TOKENS.danger)
        .replace("@DANGER_SOFT@", LIGHT_TOKENS.danger_soft)
        .replace("@INFO@", LIGHT_TOKENS.info)
        .replace("@INFO_SOFT@", LIGHT_TOKENS.info_soft)
    )
