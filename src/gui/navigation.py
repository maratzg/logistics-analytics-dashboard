from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import customtkinter as ctk

from .theme import PALETTE, SPACING, font


@dataclass(frozen=True, slots=True)
class NavigationItem:
    route: str
    label: str
    title: str
    subtitle: str
    group: str
    prominent: bool = False


NAVIGATION_ITEMS: tuple[NavigationItem, ...] = (
    NavigationItem("Dashboard", "Dashboard", "Dashboard", "Current operational overview and recent change activity.", "Primary", True),
    NavigationItem("Voyages", "Voyages", "Voyages", "Browse complete voyage instances and operational details.", "Primary", True),
    NavigationItem("History", "History", "History", "Explore recorded workbook changes and material revisions.", "Primary", True),
    NavigationItem("Vessel Analytics", "Vessel Analytics", "Vessel Analytics", "Compare operational and schedule patterns by vessel.", "Analytics"),
    NavigationItem("Service Analytics", "Service Analytics", "Service Analytics", "Review volume, mix, and schedule behavior by service.", "Analytics"),
    NavigationItem("Customers", "Customers", "Customers", "Review customer volume, mix, destinations, and cancellations.", "Analytics"),
    NavigationItem("Compare", "Compare", "Compare Voyages", "Compare two to five safely identified voyage instances.", "Analytics"),
    NavigationItem("Data Quality", "Data Quality", "Data Quality", "Review transparent workbook and operational data issues.", "Analytics"),
    NavigationItem("Settings", "Settings", "Settings", "Configure the read-only workbook source and diagnostics.", "Secondary"),
)


ROUTE_ALIASES = {
    "Vessels": "Vessel Analytics",
    "Voyage Comparison": "Compare",
}


def resolve_route(route: str) -> str | None:
    candidate = ROUTE_ALIASES.get(route, route)
    return candidate if candidate in {item.route for item in NAVIGATION_ITEMS} else None


def navigation_item(route: str) -> NavigationItem | None:
    resolved = resolve_route(route)
    return next((item for item in NAVIGATION_ITEMS if item.route == resolved), None)


def navigation_groups(items: Iterable[NavigationItem] = NAVIGATION_ITEMS) -> dict[str, list[NavigationItem]]:
    groups: dict[str, list[NavigationItem]] = {}
    for item in items:
        groups.setdefault(item.group, []).append(item)
    return groups


class NavigationSidebar(ctk.CTkFrame):
    def __init__(self, parent: Any, on_navigate: Callable[[str], None]) -> None:
        super().__init__(parent, width=224, corner_radius=0, fg_color=PALETTE.sidebar, border_width=0)
        self.on_navigate = on_navigate
        self.buttons: dict[str, ctk.CTkButton] = {}
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=SPACING.xl, pady=(SPACING.xl, SPACING.lg))
        ctk.CTkLabel(brand, text="Operations", text_color=PALETTE.text, font=font(19, weight="bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(brand, text="Analytics", text_color=PALETTE.accent, font=font(13, weight="bold"), anchor="w").pack(fill="x", pady=(1, 0))

        primary = self._group_frame(1, "PRIMARY")
        self._add_items(primary, navigation_groups()["Primary"])
        analytics = self._group_frame(2, "ANALYTICS")
        self._add_items(analytics, navigation_groups()["Analytics"])

        ctk.CTkFrame(self, height=1, fg_color=PALETTE.divider).grid(row=3, column=0, sticky="ew", padx=SPACING.lg, pady=SPACING.sm)

        secondary = ctk.CTkFrame(self, fg_color="transparent")
        secondary.grid(row=5, column=0, sticky="sew", padx=SPACING.md, pady=(SPACING.sm, SPACING.lg))
        secondary.grid_columnconfigure(0, weight=1)
        self._add_items(secondary, navigation_groups()["Secondary"])

    def select(self, route: str) -> None:
        resolved = resolve_route(route)
        for item_route, button in self.buttons.items():
            selected = item_route == resolved
            button.configure(
                fg_color=PALETTE.selected if selected else "transparent",
                text_color=PALETTE.accent if selected else PALETTE.text,
                hover_color=PALETTE.accent_soft,
                border_width=0,
            )

    def _group_frame(self, row: int, label: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=SPACING.md, pady=(0, SPACING.md))
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=label, text_color=PALETTE.text_soft, font=font(10, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="ew", padx=SPACING.md, pady=(0, SPACING.xs)
        )
        return frame

    def _add_items(self, frame: ctk.CTkFrame, items: Iterable[NavigationItem]) -> None:
        start_row = len(frame.winfo_children())
        for offset, item in enumerate(items):
            button = ctk.CTkButton(
                frame,
                text=item.label,
                anchor="w",
                height=36 if item.prominent else 34,
                corner_radius=8,
                fg_color="transparent",
                hover_color=PALETTE.accent_soft,
                text_color=PALETTE.text,
                font=font(13, weight="bold" if item.prominent else "normal"),
                command=lambda selected=item.route: self.on_navigate(selected),
            )
            button.grid(row=start_row + offset, column=0, sticky="ew", pady=2)
            self.buttons[item.route] = button
