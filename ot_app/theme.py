"""Small, asset-free visual system built on standard Tk/ttk."""
import tkinter as tk
from tkinter import font as tkfont, ttk

BG = "#F3F6FB"
SURFACE = "#FFFFFF"
NAV = "#111E33"
NAV_ACTIVE = "#243954"
TEXT = "#17253B"
MUTED = "#65758B"
BORDER = "#DFE6F0"
BLUE = "#225DD8"
BLUE_HOVER = "#194EB9"
BLUE_PALE = "#EAF1FF"
GREEN = "#147866"
RED = "#B93845"
AMBER = "#9B640F"


def apply_theme(root):
    root.configure(background=BG)
    available = {name.casefold(): name for name in tkfont.families(root)}
    family = next((available[name.casefold()] for name in ("Segoe UI", "DejaVu Sans", "Arial", "Helvetica")
                   if name.casefold() in available), "Arial")
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(name).configure(family=family, size=10)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=(family, 10), foreground=TEXT, background=BG)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=SURFACE)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Body.TLabel", background=BG, foreground=TEXT)
    style.configure("Title.TLabel", font=(family, 25, "bold"))
    style.configure("Section.TLabel", font=(family, 12, "bold"), background=SURFACE)
    style.configure("Muted.TLabel", foreground=MUTED, background=BG)
    style.configure("Card.TLabel", background=SURFACE, foreground=TEXT)
    style.configure("CardMuted.TLabel", background=SURFACE, foreground=MUTED, font=(family, 9))
    style.configure("Small.TLabel", foreground=MUTED, font=(family, 9))
    style.configure("Overline.TLabel", foreground=MUTED, font=(family, 9, "bold"))
    style.configure("Metric.TLabel", background=SURFACE, font=(family, 22, "bold"))
    style.configure("SuccessMetric.TLabel", background=SURFACE, foreground=GREEN, font=(family, 22, "bold"))
    style.configure("TButton", borderwidth=1, relief="flat", padding=(12, 9), background=SURFACE,
                    foreground=TEXT, bordercolor=BORDER, focuscolor=BLUE_PALE, focusthickness=2)
    style.map("TButton", background=[("active", "#F1F5FB"), ("disabled", "#EEF1F5")],
              foreground=[("disabled", "#93A0B2")], bordercolor=[("focus", BLUE)])
    style.configure("Accent.TButton", background=BLUE, foreground="white", bordercolor=BLUE,
                    font=(family, 10, "bold"))
    style.map("Accent.TButton", background=[("disabled", "#C1CFEC"), ("active", BLUE_HOVER)],
              foreground=[("disabled", "#F9FAFD"), ("!disabled", "white")],
              bordercolor=[("disabled", "#C1CFEC"), ("!disabled", BLUE)])
    style.configure("Subtle.TButton", background=SURFACE)
    style.configure("Danger.TButton", foreground=RED)
    style.map("Danger.TButton", foreground=[("disabled", "#B7A6AA"), ("!disabled", RED)])
    style.configure("Link.TButton", background=BG, bordercolor=BG, foreground=BLUE,
                    padding=(8, 6), borderwidth=0)
    style.map("Link.TButton", background=[("active", BLUE_PALE)])
    style.configure("TEntry", fieldbackground=SURFACE, bordercolor=BORDER, padding=(10, 8),
                    lightcolor=BORDER, darkcolor=BORDER, insertcolor=TEXT)
    style.map("TEntry", bordercolor=[("focus", BLUE)], fieldbackground=[("disabled", "#EFF2F7")])
    style.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE, bordercolor=BORDER,
                    padding=(9, 7), arrowsize=13)
    style.map("TCombobox", fieldbackground=[("readonly", SURFACE)],
              selectbackground=[("readonly", SURFACE)], selectforeground=[("readonly", TEXT)])
    style.configure("TSpinbox", fieldbackground=SURFACE, bordercolor=BORDER, padding=(8, 7))
    style.configure("TCheckbutton", background=SURFACE, padding=3)
    style.map("TCheckbutton", background=[("active", SURFACE)])
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, foreground=TEXT,
                    rowheight=42, borderwidth=0, font=(family, 10))
    style.configure("Treeview.Heading", background="#F5F7FB", foreground=MUTED,
                    padding=(12, 11), relief="flat", font=(family, 9, "bold"))
    style.map("Treeview", background=[("selected", BLUE_PALE)], foreground=[("selected", TEXT)])
    style.map("Treeview.Heading", background=[("active", "#EDF2F9")])
    style.configure("Horizontal.TProgressbar", background=BLUE, troughcolor="#E6EDF7",
                    borderwidth=0, thickness=5)
    style.configure("Vertical.TScrollbar", background="#C7D2E1", troughcolor=SURFACE,
                    borderwidth=0, arrowsize=12)
    style.configure("TSeparator", background=BORDER)
    return family


def card(parent, padding=18):
    border = tk.Frame(parent, bg=BORDER, bd=0, highlightthickness=0)
    content = ttk.Frame(border, style="Card.TFrame", padding=padding)
    content.pack(fill="both", expand=True, padx=1, pady=1)
    return border, content


def human_bytes(value):
    if value is None:
        return "—"
    value = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
