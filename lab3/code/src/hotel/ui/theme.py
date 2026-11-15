"""界面主题：配色、字体、卡片与表格等常用控件。

配色沿用实验二的桌面端设计：浅灰底、白色卡片、蓝色主色、状态色区分房态。
Tk 不支持圆角，用 1px 描边 + 留白近似卡片效果。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

BG = "#F5F7FA"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F7F9FC"
BORDER = "#E3E8EF"
TEXT = "#1F2933"
MUTED = "#6B7280"
ACCENT = "#1F6FEB"
ACCENT_DARK = "#1759C4"
ACCENT_SOFT = "#E8F1FF"
SUCCESS = "#2E7D5B"
SUCCESS_SOFT = "#E6F4EE"
WARNING = "#B26B00"
WARNING_SOFT = "#FFF4E0"
DANGER = "#B42318"
DANGER_SOFT = "#FDECEA"

FAMILY = "Microsoft YaHei UI"
FONT_BRAND = (FAMILY, 13, "bold")
FONT_TITLE = (FAMILY, 17, "bold")
FONT_H2 = (FAMILY, 11, "bold")
FONT_BODY = (FAMILY, 10)
FONT_SMALL = (FAMILY, 9)
FONT_KPI = (FAMILY, 22, "bold")
FONT_NAV = (FAMILY, 10)


def setup(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("TFrame", background=BG)
    style.configure("App.TLabel", background=BG, foreground=TEXT, font=FONT_BODY)
    style.configure("Card.TLabel", background=SURFACE, foreground=TEXT, font=FONT_BODY)
    style.configure("Muted.TLabel", background=SURFACE, foreground=MUTED, font=FONT_SMALL)

    style.configure(
        "Primary.TButton",
        background=ACCENT,
        foreground="#FFFFFF",
        borderwidth=0,
        focuscolor=ACCENT,
        padding=(16, 8),
        font=FONT_BODY,
    )
    style.map(
        "Primary.TButton",
        background=[("active", ACCENT_DARK), ("disabled", "#C3CCDA")],
        foreground=[("disabled", "#FFFFFF")],
    )
    style.configure(
        "Ghost.TButton",
        background=SURFACE,
        foreground=TEXT,
        bordercolor=BORDER,
        borderwidth=1,
        padding=(14, 7),
        font=FONT_BODY,
    )
    style.map("Ghost.TButton", background=[("active", SURFACE_ALT)])

    style.configure(
        "App.TEntry",
        fieldbackground=SURFACE_ALT,
        bordercolor=BORDER,
        lightcolor=BORDER,
        darkcolor=BORDER,
        padding=6,
    )
    style.configure(
        "App.TCombobox",
        fieldbackground=SURFACE_ALT,
        background=SURFACE_ALT,
        bordercolor=BORDER,
        arrowcolor=MUTED,
        padding=4,
    )
    style.configure(
        "App.TSpinbox",
        fieldbackground=SURFACE_ALT,
        bordercolor=BORDER,
        arrowcolor=MUTED,
        padding=4,
    )

    style.configure(
        "App.Treeview",
        background=SURFACE,
        fieldbackground=SURFACE,
        foreground=TEXT,
        rowheight=32,
        borderwidth=0,
        font=FONT_BODY,
    )
    style.configure(
        "App.Treeview.Heading",
        background=SURFACE_ALT,
        foreground=MUTED,
        relief="flat",
        font=FONT_SMALL,
    )
    style.map(
        "App.Treeview",
        background=[("selected", ACCENT_SOFT)],
        foreground=[("selected", TEXT)],
    )
    style.layout("App.Treeview", [("App.Treeview.treearea", {"sticky": "nswe"})])

    style.configure(
        "App.TNotebook",
        background=BG,
        borderwidth=0,
        tabmargins=(0, 0, 0, 8),
    )
    style.configure(
        "App.TNotebook.Tab",
        background=BG,
        foreground=MUTED,
        padding=(16, 8),
        font=FONT_BODY,
        borderwidth=0,
    )
    style.map(
        "App.TNotebook.Tab",
        background=[("selected", SURFACE)],
        foreground=[("selected", ACCENT)],
    )
    return style


def card(
    parent: tk.Misc,
    title: str | None = None,
    *,
    fill: str = "both",
    expand: bool = False,
    padx: int = 0,
    pady: int = 0,
    side: str = "top",
) -> tk.Frame:
    outer = tk.Frame(parent, bg=BORDER)
    outer.pack(side=side, fill=fill, expand=expand, padx=padx, pady=pady)
    inner = tk.Frame(outer, bg=SURFACE)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    if title:
        head = tk.Frame(inner, bg=SURFACE)
        head.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(head, text=title, bg=SURFACE, fg=TEXT, font=FONT_H2).pack(side="left")
    body = tk.Frame(inner, bg=SURFACE)
    body.pack(fill="both", expand=True, padx=18, pady=14)
    return body


def kpi_row(parent: tk.Misc, items: list[tuple[str, str, str, str]]) -> tk.Frame:
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=(0, 14))
    for index, (label, value, caption, tone) in enumerate(items):
        box = tk.Frame(row, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1)
        box.pack(side="left", fill="x", expand=True, padx=(0 if index == 0 else 12, 0))
        tk.Label(box, text=label, bg=SURFACE, fg=MUTED, font=FONT_SMALL, anchor="w").pack(
            fill="x", padx=16, pady=(12, 0)
        )
        tk.Label(box, text=value, bg=SURFACE, fg=tone, font=FONT_KPI, anchor="w").pack(
            fill="x", padx=16
        )
        tk.Label(box, text=caption, bg=SURFACE, fg=MUTED, font=FONT_SMALL, anchor="w").pack(
            fill="x", padx=16, pady=(0, 12)
        )
    return row


def table(
    parent: tk.Misc, columns: tuple[str, ...], widths: list[int] | None = None, height: int = 12
) -> ttk.Treeview:
    wrap = tk.Frame(parent, bg=SURFACE)
    wrap.pack(fill="both", expand=True)
    # 行高固定，行数太多会把操作栏挤出卡片，这里统一压到 8 行。
    tree = ttk.Treeview(
        wrap, columns=columns, show="headings", height=min(height, 8), style="App.Treeview"
    )
    widths = widths or [150] * len(columns)
    for column, width in zip(columns, widths):
        tree.heading(column, text=column)
        tree.column(column, width=width, anchor="center")
    scroll = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return tree


def actions(parent: tk.Misc, pady: tuple[int, int] = (14, 0)) -> tk.Frame:
    row = tk.Frame(parent, bg=SURFACE)
    row.pack(fill="x", pady=pady)
    return row


def primary(parent: tk.Misc, text: str, command) -> ttk.Button:
    return ttk.Button(parent, text=text, command=command, style="Primary.TButton")


def ghost(parent: tk.Misc, text: str, command) -> ttk.Button:
    return ttk.Button(parent, text=text, command=command, style="Ghost.TButton")


def field_label(parent: tk.Misc, text: str) -> tk.Label:
    return tk.Label(parent, text=text, bg=SURFACE, fg=MUTED, font=FONT_SMALL)


def entry(parent: tk.Misc, variable, width: int = 16) -> ttk.Entry:
    return ttk.Entry(parent, textvariable=variable, width=width, style="App.TEntry")


def badge(parent: tk.Misc, text: str, tone: str = "accent") -> tk.Label:
    colors = {
        "accent": (ACCENT_SOFT, ACCENT),
        "success": (SUCCESS_SOFT, SUCCESS),
        "warning": (WARNING_SOFT, WARNING),
        "danger": (DANGER_SOFT, DANGER),
    }
    bg_color, fg_color = colors.get(tone, colors["accent"])
    return tk.Label(parent, text=text, bg=bg_color, fg=fg_color, font=FONT_SMALL, padx=10, pady=3)
