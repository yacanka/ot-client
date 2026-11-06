"""Shared scrolling, focus and action layout for the two settings pages."""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from tkinter import font as tkfont, ttk
from typing import Callable

from .settings import AppSettings


class SettingsPage(ttk.Frame):
    """Keep settings fields scrollable while their save action stays visible."""

    def __init__(
        self, parent: tk.Misc, settings: AppSettings, *, title: str, intro: str
    ) -> None:
        super().__init__(parent)
        self._initial_settings = replace(settings)
        self._busy = False
        self._reveal_after: str | None = None
        self._editable: list[ttk.Widget] = []
        self._field_widgets: dict[str, ttk.Widget] = {}
        self._wrap_labels: list[ttk.Label] = []
        self._status_kind: bool | None = None
        self._last_wrap_width = 0
        self._status_var = tk.StringVar(self, value="Ayarları kaydedin.")
        self._configure_styles()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header(title, intro)
        self._build_scroll_area()

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        family = tkfont.nametofont("TkDefaultFont").actual("family")
        style.configure(
            "SettingsCardTitle.TLabel", background="#FFFFFF", foreground="#17253B",
            font=(family, 12, "bold"),
        )
        for kind in ("TCheckbutton", "TRadiobutton"):
            style.configure(
                f"SettingsCard.{kind}", background="#FFFFFF", foreground="#17253B",
                font=(family, 10),
            )
            style.map(
                f"SettingsCard.{kind}",
                background=[("active", "#FFFFFF"), ("disabled", "#FFFFFF")],
                foreground=[("disabled", "#94A0B2")],
            )
        style.configure("SettingsStatus.TLabel", foreground="#627189")
        style.configure("SettingsSuccess.TLabel", foreground="#18794E")
        style.configure("SettingsError.TLabel", foreground="#B42336")
        style.configure("SettingsFormatError.TLabel", background="#FFFFFF", foreground="#B42336")

    def _build_header(self, title: str, intro: str) -> None:
        header = ttk.Frame(self, padding=(0, 0, 0, 17))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="UYGULAMA AYARLARI", style="Overline.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, text=title, style="Title.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 2)
        )
        self._intro_label = ttk.Label(header, text=intro, style="Muted.TLabel", wraplength=660)
        self._intro_label.grid(row=2, column=0, sticky="w")

    def _build_scroll_area(self) -> None:
        area = ttk.Frame(self)
        area.grid(row=1, column=0, sticky="nsew")
        area.columnconfigure(0, weight=1)
        area.rowconfigure(0, weight=1)
        self._canvas = tk.Canvas(
            area, background="#F3F6FB", highlightthickness=0, borderwidth=0,
            width=1, height=1, takefocus=False,
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(area, orient="vertical", command=self._canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(7, 0))
        self._canvas.configure(yscrollcommand=scrollbar.set)
        self._scroll_frame = ttk.Frame(self._canvas)
        self._scroll_frame.columnconfigure(0, weight=1)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._scroll_frame, anchor="nw"
        )
        self._scroll_frame.bind("<Configure>", self._update_scrollregion, add="+")
        self._canvas.bind("<Configure>", self._resize_scroll_contents, add="+")
        self._canvas.bind("<MouseWheel>", self._on_mousewheel, add="+")
        self._canvas.bind("<Button-4>", self._on_mousewheel, add="+")
        self._canvas.bind("<Button-5>", self._on_mousewheel, add="+")

    def _card(self, row: int) -> ttk.Frame:
        card = ttk.Frame(self._scroll_frame, style="Card.TFrame", padding=(20, 17))
        card.grid(row=row, column=0, sticky="ew", pady=(0, 14))
        card.columnconfigure(0, weight=1)
        return card

    @staticmethod
    def _field_label(parent: tk.Misc, text: str, row: int = 0) -> ttk.Label:
        label = ttk.Label(parent, text=text, style="Card.TLabel")
        label.grid(row=row, column=0, sticky="w", pady=(0, 6))
        return label

    def _entry(
        self, parent: tk.Misc, variable: tk.Variable, *, row: int = 1, **options: object
    ) -> ttk.Entry:
        entry = ttk.Entry(parent, textvariable=variable, **options)
        entry.grid(row=row, column=0, sticky="ew")
        self._editable.append(entry)
        entry.bind("<FocusIn>", self._reveal_focused_widget, add="+")
        return entry

    def _build_footer(
        self, on_save: Callable[[], None], on_test: Callable[[], None] | None = None
    ) -> None:
        footer = ttk.Frame(self, padding=(0, 12, 0, 0))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self._status_label = ttk.Label(
            footer, textvariable=self._status_var, style="SettingsStatus.TLabel", wraplength=650,
        )
        self._status_label.grid(row=0, column=0, sticky="ew", pady=(0, 11))
        actions = ttk.Frame(footer)
        actions.grid(row=1, column=0, sticky="e")
        self._action_buttons = []
        if on_test is not None:
            self.test_button = ttk.Button(
                actions, text="Bağlantıyı test et", style="Subtle.TButton", command=on_test
            )
            self.test_button.grid(row=0, column=0, padx=(0, 10))
            self._action_buttons.append(self.test_button)
        self.save_button = ttk.Button(
            actions, text="Ayarları kaydet", style="Accent.TButton", command=on_save
        )
        self.save_button.grid(row=0, column=1)
        self._action_buttons.append(self.save_button)
        self._bind_scroll_widgets(self._scroll_frame)
        self.bind("<Configure>", self._on_view_configure, add="+")

    def set_busy(self, busy: bool) -> None:
        """Freeze editable values and actions while an operation uses them."""
        self._busy = bool(busy)
        states = ["disabled"] if self._busy else ["!disabled"]
        for widget in (*self._editable, *self._action_buttons):
            widget.state(states)

    def set_status(self, message: str, success: bool | None = None) -> None:
        self._status_kind = success
        self._status_var.set(message)
        style = (
            "SettingsSuccess.TLabel" if success is True else
            "SettingsError.TLabel" if success is False else "SettingsStatus.TLabel"
        )
        self._status_label.configure(style=style)

    def mark_saved(self) -> None:
        self.set_status("Ayarlar kaydedildi.", success=True)

    def focus_field(self, field: str) -> None:
        """Reveal the named validation field without discarding the draft."""
        widget = self._field_widgets.get(field)
        if widget is None:
            return
        widget.focus_set()
        if isinstance(widget, ttk.Entry):
            widget.selection_range(0, tk.END)
        self._queue_reveal(widget)

    def _on_settings_changed(self, *_: object) -> None:
        if not self._busy:
            self.set_status("Kaydedilmemiş değişiklikler var.")

    def _resize_scroll_contents(self, event: tk.Event) -> None:
        self._canvas.itemconfigure(self._canvas_window, width=event.width)
        self._layout_fields(event.width)
        self._update_scrollregion()

    def _layout_fields(self, width: int) -> None:
        """Pages with paired fields may stack them when the viewport narrows."""

    def _update_scrollregion(self, _event: tk.Event | None = None) -> None:
        if self._canvas.winfo_exists():
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_view_configure(self, event: tk.Event) -> None:
        if event.widget is not self:
            return
        width = max(160, event.width - 4)
        if width == self._last_wrap_width:
            return
        self._last_wrap_width = width
        self._intro_label.configure(wraplength=width)
        self._status_label.configure(wraplength=width)
        for label in self._wrap_labels:
            label.configure(wraplength=max(140, width - 55))

    def _bind_scroll_widgets(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_mousewheel, add="+")
        widget.bind("<Button-5>", self._on_mousewheel, add="+")
        if isinstance(widget, (ttk.Button, ttk.Checkbutton, ttk.Radiobutton)):
            widget.bind("<FocusIn>", self._reveal_focused_widget, add="+")
        for child in widget.winfo_children():
            self._bind_scroll_widgets(child)

    def _on_mousewheel(self, event: tk.Event) -> str:
        if getattr(event, "num", None) == 4:
            direction = -1
        elif getattr(event, "num", None) == 5:
            direction = 1
        else:
            delta = getattr(event, "delta", 0)
            if not delta:
                return "break"
            direction = -max(1, abs(delta) // 120) if delta > 0 else max(1, abs(delta) // 120)
        if self._canvas.yview() != (0.0, 1.0):
            self._canvas.yview_scroll(direction * 3, "units")
        return "break"

    def _reveal_focused_widget(self, event: tk.Event) -> None:
        self._queue_reveal(event.widget)

    def _queue_reveal(self, widget: tk.Misc) -> None:
        if self._reveal_after is not None:
            self.after_cancel(self._reveal_after)
        self._reveal_after = self.after_idle(self._scroll_to_widget, widget)

    def _scroll_to_widget(self, widget: tk.Misc) -> None:
        self._reveal_after = None
        if not self.winfo_exists() or not widget.winfo_exists():
            return
        self._canvas.update_idletasks()
        content_height = max(1, self._scroll_frame.winfo_height())
        visible_height = self._canvas.winfo_height()
        widget_y = widget.winfo_rooty() - self._scroll_frame.winfo_rooty()
        top = self._canvas.canvasy(0)
        bottom = top + visible_height
        if widget_y < top + 8:
            self._canvas.yview_moveto(max(0, widget_y - 30) / content_height)
        elif widget_y + widget.winfo_height() > bottom - 8:
            self._canvas.yview_moveto(
                (widget_y + widget.winfo_height() + 15 - visible_height) / content_height
            )

    def destroy(self) -> None:
        if self._reveal_after is not None:
            try:
                self.after_cancel(self._reveal_after)
            except tk.TclError:
                pass
            self._reveal_after = None
        super().destroy()
