"""Modal dialogs for document input, number editing and explicit disambiguation."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont
from typing import TYPE_CHECKING, Callable

from .documents import parse_document_text

if TYPE_CHECKING:
    from otClient import Document


def _family(window: tk.Misc, *, monospace: bool = False) -> str:
    if monospace:
        available = {name.casefold(): name for name in tkfont.families(window)}
        for name in ("Consolas", "DejaVu Sans Mono", "Liberation Mono", "Courier"):
            if name.casefold() in available:
                return available[name.casefold()]
        return tkfont.nametofont("TkFixedFont").actual("family")
    return tkfont.nametofont("TkDefaultFont").actual("family")


def center(window: tk.Toplevel, parent: tk.Misc, width: int, height: int) -> None:
    """Size a dialog within the screen and center it on its parent window."""
    window.update_idletasks()
    owner = parent.winfo_toplevel()
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    width = min(width, max(320, screen_width - 40))
    height = min(height, max(300, screen_height - 80))
    if owner.winfo_ismapped():
        x = owner.winfo_rootx() + (owner.winfo_width() - width) // 2
        y = owner.winfo_rooty() + (owner.winfo_height() - height) // 2
    else:
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
    x = max(0, min(x, screen_width - width))
    y = max(0, min(y, screen_height - height - 35))
    window.geometry(f"{width}x{height}+{x}+{y}")


class BulkInputDialog(tk.Toplevel):
    """Collect a pasted document list and return a validated unique list."""

    def __init__(
        self, parent: tk.Misc, initial: str = "", title: str = "Toplu belge ekle"
    ) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.configure(background="#F3F6FB")
        self.transient(parent.winfo_toplevel())
        self.result: list[str] | None = None
        self._preview_after: str | None = None
        self._parsed: list[str] = []
        self._parse_error: str | None = None
        self._count_var = tk.StringVar(self, value="Belge numaralarını yapıştırın.")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(24, 22, 24, 14))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header, text=title, style="Body.TLabel", font=(_family(self), 15, "bold")
        ).grid(row=0, column=0, sticky="w")
        self._hint = ttk.Label(
            header,
            text=("Belge numaralarını yeni satır, sekme, virgül veya noktalı virgülle ayırın. "
                  'JSON metin listesi de kullanabilirsiniz: ["BELGE-001", "BELGE-002"].'),
            style="Muted.TLabel", wraplength=650, justify="left",
        )
        self._hint.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        editor = ttk.Frame(self, padding=(24, 0, 24, 0))
        editor.grid(row=1, column=0, sticky="nsew")
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(0, weight=1)
        self.text = tk.Text(
            editor, width=70, height=15, wrap="word", undo=True,
            font=(_family(self, monospace=True), 11), foreground="#17253B", background="#FFFFFF",
            insertbackground="#17253B", selectbackground="#DCE9FF",
            selectforeground="#17253B", borderwidth=0, highlightthickness=1,
            highlightbackground="#CCD5E2", highlightcolor="#3478D4",
            padx=12, pady=12,
        )
        self.text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(editor, orient="vertical", command=self.text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.insert("1.0", initial)
        self.text.edit_modified(False)
        self.text.bind("<<Modified>>", self._on_modified, add="+")
        self.text.bind("<Control-a>", self._select_all, add="+")
        self.text.bind("<Control-A>", self._select_all, add="+")
        self.text.bind("<Control-Tab>", self._focus_next, add="+")

        footer = ttk.Frame(self, padding=(24, 12, 24, 20))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self._count_label = ttk.Label(
            footer, textvariable=self._count_var, style="Muted.TLabel", wraplength=640
        )
        self._count_label.grid(row=0, column=0, sticky="ew", pady=(0, 13))
        controls = ttk.Frame(footer)
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)
        ttk.Label(
            controls, text="Yinelenen numaralar bir kez eklenir.", style="Muted.TLabel"
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))
        self.cancel_button = ttk.Button(
            controls, text="Vazgeç", style="Subtle.TButton", command=self._cancel
        )
        self.cancel_button.grid(row=0, column=1, padx=(0, 9))
        self.add_button = ttk.Button(
            controls, text="Ekle", style="Accent.TButton", command=self._accept
        )
        self.add_button.grid(row=0, column=2)
        self.add_button.bind("<Return>", self._accept, add="+")
        self.cancel_button.bind("<Return>", self._cancel, add="+")

        self.bind("<Escape>", self._cancel)
        self.bind("<Configure>", self._on_configure, add="+")
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.minsize(550, 400)
        center(self, parent, 740, 540)
        self._update_preview()
        self.deiconify()
        self.wait_visibility()
        self.grab_set()
        self.text.focus_set()
        self.wait_window(self)

    def _on_modified(self, _event: tk.Event | None = None) -> None:
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if self._preview_after is not None:
            self.after_cancel(self._preview_after)
        self._preview_after = self.after(180, self._update_preview)

    def _update_preview(self) -> None:
        self._preview_after = None
        try:
            self._parsed = parse_document_text(self.text.get("1.0", "end-1c"))
        except ValueError as exc:
            self._parsed = []
            self._parse_error = str(exc)
            self._count_var.set(f"Liste okunamadı: {self._parse_error}")
            self._count_label.configure(foreground="#B42336")
            self.add_button.state(["disabled"])
        else:
            self._parse_error = None
            count = len(self._parsed)
            self._count_var.set(
                f"{count:,} benzersiz belge numarası eklenmeye hazır.".replace(",", ".")
                if count else "Belge numaralarını yapıştırın."
            )
            self._count_label.configure(foreground="#18794E" if count else "#627189")
            self.add_button.state(["!disabled"] if count else ["disabled"])

    def _accept(self, _event: tk.Event | None = None) -> str:
        if self._preview_after is not None:
            self.after_cancel(self._preview_after)
            self._preview_after = None
        self._update_preview()
        if self._parse_error is None and self._parsed:
            self.result = list(self._parsed)
            self.destroy()
        else:
            self.text.focus_set()
        return "break"

    def _cancel(self, _event: tk.Event | None = None) -> str:
        self.result = None
        self.destroy()
        return "break"

    def destroy(self) -> None:
        if self._preview_after is not None:
            try:
                self.after_cancel(self._preview_after)
            except tk.TclError:
                pass
            self._preview_after = None
        super().destroy()

    def _select_all(self, _event: tk.Event) -> str:
        self.text.tag_add("sel", "1.0", "end-1c")
        self.text.mark_set("insert", "1.0")
        self.text.see("insert")
        return "break"

    def _focus_next(self, _event: tk.Event) -> str:
        self.text.tk_focusNext().focus_set()
        return "break"

    def _on_configure(self, event: tk.Event) -> None:
        if event.widget is self:
            width = max(200, event.width - 55)
            self._hint.configure(wraplength=width)
            self._count_label.configure(wraplength=width)


class DocumentNumberDialog(tk.Toplevel):
    """Edit one literal identifier, retaining the modal on validation failure."""

    def __init__(
        self, parent: tk.Misc, number: str, *, validate: Callable[[str], str]
    ) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title("Belge numarasını düzenle")
        self.configure(background="#F3F6FB")
        self.transient(parent.winfo_toplevel())
        self.result: str | None = None
        self._validate = validate
        self.number_var = tk.StringVar(self, value=number)
        self.error_var = tk.StringVar(self)
        self.columnconfigure(0, weight=1)
        content = ttk.Frame(self, padding=(24, 22))
        content.grid(row=0, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        ttk.Label(
            content, text="Belge numarasını düzenle", style="Body.TLabel",
            font=(_family(self), 15, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            content, text="Yeni belge numarasını girin. Değişiklik sonrası belge yeniden indirilmeye hazır olur.",
            style="Muted.TLabel", wraplength=470, justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(8, 14))
        self.entry = ttk.Entry(content, textvariable=self.number_var)
        self.entry.grid(row=2, column=0, sticky="ew")
        ttk.Label(
            content, textvariable=self.error_var, foreground="#B42336",
            wraplength=470, justify="left",
        ).grid(row=3, column=0, sticky="ew", pady=(8, 16))
        controls = ttk.Frame(content)
        controls.grid(row=4, column=0, sticky="e")
        self.cancel_button = ttk.Button(
            controls, text="Vazgeç", style="Subtle.TButton", command=self._cancel,
        )
        self.cancel_button.grid(row=0, column=0, padx=(0, 10))
        self.save_button = ttk.Button(
            controls, text="Kaydet", style="Accent.TButton", command=self._accept,
        )
        self.save_button.grid(row=0, column=1)
        self.bind("<Return>", self._accept)
        self.cancel_button.bind("<Return>", self._cancel)
        self.bind("<Escape>", self._cancel)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.resizable(False, False)
        center(self, parent, 530, 285)
        self.deiconify()
        self.wait_visibility()
        self.grab_set()
        self.entry.focus_set()
        self.entry.selection_range(0, tk.END)
        self.wait_window(self)

    def _accept(self, _event: tk.Event | None = None) -> str:
        try:
            self.result = self._validate(self.number_var.get())
        except ValueError as exc:
            self.error_var.set(str(exc))
            self.entry.focus_set()
        else:
            self.destroy()
        return "break"

    def _cancel(self, _event: tk.Event | None = None) -> str:
        self.result = None
        self.destroy()
        return "break"


class CandidateDialog(tk.Toplevel):
    """Ask the user to choose one document when a search is ambiguous."""

    def __init__(self, parent: tk.Misc, number: str, candidates: list[Document]) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title("Belgeyi seçin")
        self.configure(background="#F3F6FB")
        self.transient(parent.winfo_toplevel())
        self.result: Document | None = None
        self._candidates = list(candidates)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, padding=(24, 22, 24, 16))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(
            header, text="Eşleşen belgeyi seçin", style="Body.TLabel",
            font=(_family(self), 15, "bold"),
        ).grid(
            row=0, column=0, sticky="w"
        )
        self._hint = ttk.Label(
            header,
            text=f'“{number}” için {len(candidates)} sonuç bulundu. İndirilecek belgeyi seçip onaylayın.',
            style="Muted.TLabel", wraplength=710, justify="left",
        )
        self._hint.grid(row=1, column=0, sticky="ew", pady=(8, 0))

        table_frame = ttk.Frame(self, padding=(24, 0, 24, 0))
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table_frame, columns=("name", "title", "author"),
            show="headings", selectmode="browse", height=10,
        )
        self.tree.heading("name", text="Belge adı", anchor="w")
        self.tree.heading("title", text="Başlık", anchor="w")
        self.tree.heading("author", text="Hazırlayan", anchor="w")
        self.tree.column("name", width=190, minwidth=115, stretch=True, anchor="w")
        self.tree.column("title", width=330, minwidth=170, stretch=True, anchor="w")
        self.tree.column("author", width=150, minwidth=100, stretch=True, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        for index, candidate in enumerate(self._candidates):
            self.tree.insert(
                "", "end", iid=str(index),
                values=(candidate.name or "—", candidate.title or "—", candidate.author or "—"),
            )
        self.tree.bind("<<TreeviewSelect>>", self._update_selection, add="+")
        self.tree.bind("<Return>", self._accept, add="+")

        footer = ttk.Frame(self, padding=(24, 15, 24, 20))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        details = ttk.Frame(footer)
        details.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        details.columnconfigure(0, weight=1)
        self._details_text = tk.Text(
            details, height=4, width=1, wrap="word", state="disabled",
            font=(_family(self), 10), foreground="#17253B", background="#F3F6FB",
            borderwidth=0, highlightthickness=0, padx=0, pady=0,
            selectbackground="#DCE9FF", selectforeground="#17253B",
        )
        self._details_text.grid(row=0, column=0, sticky="ew")
        detail_scroll = ttk.Scrollbar(details, orient="vertical", command=self._details_text.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        self._details_text.configure(yscrollcommand=detail_scroll.set)
        self._set_details("Listeden bir belge seçin.")
        controls = ttk.Frame(footer)
        controls.grid(row=1, column=0, sticky="e")
        self.cancel_button = ttk.Button(
            controls, text="Vazgeç", style="Subtle.TButton", command=self._cancel
        )
        self.cancel_button.grid(row=0, column=0, padx=(0, 10))
        self.use_button = ttk.Button(
            controls, text="Bu belgeyi kullan", style="Accent.TButton", command=self._accept
        )
        self.use_button.grid(row=0, column=1)
        self.use_button.bind("<Return>", self._accept, add="+")
        self.cancel_button.bind("<Return>", self._cancel, add="+")
        if self._candidates:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self._update_selection()
        else:
            self.use_button.state(["disabled"])

        self.bind("<Escape>", self._cancel)
        self.bind("<Configure>", self._on_configure, add="+")
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.minsize(590, 380)
        center(self, parent, 800, 520)
        self.deiconify()
        self.wait_visibility()
        self.grab_set()
        self.tree.focus_set()
        self.wait_window(self)

    def _selected(self) -> Document | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self._candidates[int(selection[0])]

    def _update_selection(self, _event: tk.Event | None = None) -> None:
        selected = self._selected()
        if selected is None:
            self._set_details("Listeden bir belge seçin.")
            self.use_button.state(["disabled"])
            return
        self.use_button.state(["!disabled"])
        self._set_details(
            f"Belge adı: {selected.name or '—'}\n"
            f"Başlık: {selected.title or '—'}\n"
            f"Hazırlayan: {selected.author or '—'}    •    Belge kimliği: {selected.id}"
        )

    def _set_details(self, text: str) -> None:
        self._details_text.configure(state="normal")
        self._details_text.delete("1.0", tk.END)
        self._details_text.insert("1.0", text)
        self._details_text.configure(state="disabled")
        self._details_text.yview_moveto(0)

    def _accept(self, _event: tk.Event | None = None) -> str:
        selected = self._selected()
        if selected is not None:
            self.result = selected
            self.destroy()
        return "break"

    def _cancel(self, _event: tk.Event | None = None) -> str:
        self.result = None
        self.destroy()
        return "break"

    def _on_configure(self, event: tk.Event) -> None:
        if event.widget is self:
            width = max(200, event.width - 55)
            self._hint.configure(wraplength=width)
