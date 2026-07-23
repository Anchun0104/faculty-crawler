from __future__ import annotations

import tkinter as tk
from tkinter import ttk


COLORS = {
    "archive_blue": "#17324D",
    "data_teal": "#177E89",
    "paper_white": "#F7F9FC",
    "line_gray": "#D7E0E8",
    "verification_amber": "#D88917",
    "failure_red": "#B84A4A",
}

HEADING_FONT = ("Microsoft YaHei UI", 11, "bold")
BODY_FONT = ("Microsoft YaHei UI", 10)
UTILITY_FONT = ("Segoe UI", 10)
SECONDARY_BUTTON_MAP = {
    "background": [("disabled", "#E5EBF0")],
    "foreground": [("disabled", "#52697D")],
}


def apply_theme(root: tk.Misc) -> None:
    root.configure(background=COLORS["paper_white"])
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure("TFrame", background=COLORS["paper_white"])
    style.configure("TLabel", background=COLORS["paper_white"], font=BODY_FONT)
    style.configure("Shell.TFrame", background=COLORS["archive_blue"])
    style.configure(
        "Shell.TLabel",
        background=COLORS["archive_blue"],
        foreground="#FFFFFF",
        font=HEADING_FONT,
    )
    style.configure(
        "Nav.TLabel",
        background=COLORS["archive_blue"],
        foreground="#DDE9F2",
        font=BODY_FONT,
        padding=(14, 10),
    )
    style.configure(
        "Nav.TButton",
        background=COLORS["archive_blue"],
        foreground="#DDE9F2",
        borderwidth=0,
        anchor=tk.W,
        font=BODY_FONT,
        padding=(12, 9),
        focusthickness=2,
        focuscolor=COLORS["data_teal"],
    )
    style.map(
        "Nav.TButton",
        background=[("active", "#234967"), ("focus", "#234967")],
        foreground=[("active", "#FFFFFF"), ("focus", "#FFFFFF")],
    )
    style.configure(
        "ActiveNav.TButton",
        background=COLORS["data_teal"],
        foreground="#FFFFFF",
        borderwidth=0,
        anchor=tk.W,
        font=HEADING_FONT,
        padding=(12, 9),
        focusthickness=2,
        focuscolor="#FFFFFF",
    )
    style.map(
        "ActiveNav.TButton",
        background=[("active", COLORS["data_teal"])],
        foreground=[("active", "#FFFFFF")],
    )
    style.configure("Heading.TLabel", font=("Microsoft YaHei UI", 18, "bold"))
    style.configure("Section.TLabel", font=HEADING_FONT)
    style.configure("Utility.TLabel", font=UTILITY_FONT)
    style.configure(
        "Technical.TLabel",
        background="#EAF0F5",
        foreground=COLORS["archive_blue"],
        font=UTILITY_FONT,
        padding=(12, 10),
    )
    style.configure(
        "Primary.TButton",
        background=COLORS["data_teal"],
        foreground="#FFFFFF",
        font=HEADING_FONT,
        padding=(18, 10),
        borderwidth=2,
        focusthickness=3,
        focuscolor=COLORS["archive_blue"],
    )
    style.map(
        "Primary.TButton",
        background=[("active", "#116A73"), ("disabled", "#759DA2")],
        foreground=[("disabled", "#F3F6F8")],
    )
    style.configure(
        "Secondary.TButton",
        background=COLORS["paper_white"],
        foreground=COLORS["archive_blue"],
        bordercolor=COLORS["line_gray"],
        focusthickness=3,
        focuscolor=COLORS["data_teal"],
    )
    style.map("Secondary.TButton", **SECONDARY_BUTTON_MAP)
    style.configure(
        "Warning.TLabel",
        background=COLORS["paper_white"],
        foreground=COLORS["verification_amber"],
        font=BODY_FONT,
    )
    style.configure(
        "Failure.TLabel",
        background=COLORS["paper_white"],
        foreground=COLORS["failure_red"],
        font=BODY_FONT,
    )
    style.configure(
        "Verification.TLabel",
        background=COLORS["paper_white"],
        foreground=COLORS["verification_amber"],
        font=HEADING_FONT,
    )
    style.configure(
        "Verification.TButton",
        background=COLORS["verification_amber"],
        foreground="#FFFFFF",
        font=HEADING_FONT,
        padding=(14, 8),
        focusthickness=3,
        focuscolor=COLORS["archive_blue"],
    )
    style.map("Verification.TButton", background=[("active", "#B96F0D"), ("disabled", "#BBA680")])
    style.configure(
        "Destructive.TButton",
        background=COLORS["paper_white"],
        foreground=COLORS["failure_red"],
        bordercolor=COLORS["failure_red"],
        focusthickness=3,
        focuscolor=COLORS["failure_red"],
    )
    style.map("Destructive.TButton", foreground=[("disabled", "#8B7777")])
    style.configure(
        "Treeview",
        background="#FFFFFF",
        fieldbackground="#FFFFFF",
        foreground=COLORS["archive_blue"],
        rowheight=34,
        font=BODY_FONT,
        bordercolor=COLORS["line_gray"],
    )
    style.configure(
        "Treeview.Heading",
        background="#EAF0F5",
        foreground=COLORS["archive_blue"],
        font=HEADING_FONT,
        relief=tk.FLAT,
    )
    style.map("Treeview", background=[("selected", COLORS["data_teal"])], foreground=[("selected", "#FFFFFF")])
    style.configure("Task.Treeview", rowheight=46)
