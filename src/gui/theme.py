from __future__ import annotations

from dataclasses import dataclass

import customtkinter as ctk


@dataclass(frozen=True, slots=True)
class Palette:
    app_background: str = "#F3F6F8"
    sidebar: str = "#FFFFFF"
    surface: str = "#FFFFFF"
    surface_subtle: str = "#F8FAFB"
    border: str = "#DDE4EA"
    divider: str = "#E8EDF1"
    text: str = "#17212B"
    text_muted: str = "#65717E"
    text_soft: str = "#82909D"
    accent: str = "#176B87"
    accent_hover: str = "#12576E"
    accent_soft: str = "#E7F2F6"
    selected: str = "#DCEEF4"
    success: str = "#277A55"
    success_soft: str = "#E9F6EF"
    warning: str = "#A96413"
    warning_soft: str = "#FFF4E3"
    danger: str = "#B23B3B"
    danger_soft: str = "#FCECEC"
    info: str = "#3A648B"
    info_soft: str = "#EAF2FA"
    table_header: str = "#EAF0F4"
    table_even: str = "#FFFFFF"
    table_odd: str = "#F7F9FA"
    table_selected: str = "#CFE5EE"
    chart_grid: str = "#D9E1E7"
    empty_icon: str = "#A7B3BD"


@dataclass(frozen=True, slots=True)
class Spacing:
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 18
    xl: int = 24
    xxl: int = 32


PALETTE = Palette()
SPACING = Spacing()
FONT_FAMILY = "Segoe UI"
CARD_RADIUS = 10


def font(size: int, *, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT_FAMILY, size=size, weight=weight)


def apply_application_theme() -> None:
    """Configure one restrained light theme for the Phase D presentation shell."""

    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")


def status_colors(kind: str) -> tuple[str, str]:
    normalized = kind.strip().casefold()
    mapping = {
        "ready": (PALETTE.success_soft, PALETTE.success),
        "refreshing": (PALETTE.info_soft, PALETTE.info),
        "warning": (PALETTE.warning_soft, PALETTE.warning),
        "error": (PALETTE.danger_soft, PALETTE.danger),
        "neutral": (PALETTE.surface_subtle, PALETTE.text_muted),
    }
    return mapping.get(normalized, mapping["neutral"])
