"""Connection and download settings, presented without persistence side effects."""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import replace
from tkinter import filedialog, ttk
from tkinter import font as tkfont
from typing import Callable

from otClient import Document, safe_windows_filename

from .filename_format import format_document_filename, validate_filename_format
from .settings import AppSettings


class SettingsView(ttk.Frame):
    """A responsive settings form with a fixed action footer.

    ``on_save`` and ``on_test`` are called without arguments.  The application
    reads and validates the current settings before performing either action.
    Passwords are only held in the entry variable and returned settings object.
    """

    def __init__(
        self,
        parent: tk.Misc,
        settings: AppSettings,
        on_save: Callable[[], None],
        on_test: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._initial_settings = replace(settings)
        self._busy = False
        self._advanced_open = False
        self._stacked_fields: bool | None = None
        self._reveal_after: str | None = None
        self._editable: list[ttk.Widget] = []
        self._status_kind: bool | None = None
        self._last_wrap_width = 0

        self.base_url_var = tk.StringVar(self, value=settings.base_url)
        self.username_var = tk.StringVar(self, value=settings.username)
        self.password_var = tk.StringVar(self, value=settings.password)
        self.output_dir_var = tk.StringVar(self, value=settings.output_dir)
        self.filename_format_var = tk.StringVar(self, value=settings.filename_format)
        self.filename_preview_var = tk.StringVar(self)
        timeout = settings.timeout
        timeout_text = str(int(timeout)) if float(timeout).is_integer() else str(timeout)
        self.timeout_var = tk.StringVar(self, value=timeout_text)
        self.folder_id_var = tk.StringVar(self, value=settings.folder_id)
        self.ca_bundle_var = tk.StringVar(self, value=settings.ca_bundle)
        self.verify_tls_var = tk.BooleanVar(self, value=settings.verify_tls)
        self.remember_password_var = tk.BooleanVar(self, value=settings.remember_password)
        self.show_password_var = tk.BooleanVar(self, value=False)
        self._status_var = tk.StringVar(
            self, value="Ayarları kaydedin veya bağlantınızı test edin."
        )

        self._configure_styles()
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self._build_header()
        self._build_scroll_area()
        self._build_server_card()
        self._build_output_card()
        self._build_advanced_card()
        self._build_footer(on_save, on_test)
        self._bind_scroll_widgets(self._scroll_frame)

        self.bind("<Configure>", self._on_view_configure, add="+")
        for variable in (
            self.base_url_var,
            self.username_var,
            self.password_var,
            self.output_dir_var,
            self.filename_format_var,
            self.timeout_var,
            self.folder_id_var,
            self.ca_bundle_var,
            self.verify_tls_var,
            self.remember_password_var,
        ):
            variable.trace_add("write", self._on_settings_changed)
        self.filename_format_var.trace_add("write", self._update_filename_preview)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        family = tkfont.nametofont("TkDefaultFont").actual("family")
        style.configure(
            "SettingsCardTitle.TLabel", background="#FFFFFF", foreground="#17253B",
            font=(family, 12, "bold"),
        )
        style.configure(
            "SettingsCard.TCheckbutton", background="#FFFFFF", foreground="#17253B",
            font=(family, 10),
        )
        style.map(
            "SettingsCard.TCheckbutton",
            background=[("active", "#FFFFFF"), ("disabled", "#FFFFFF")],
            foreground=[("disabled", "#94A0B2")],
        )
        style.configure("SettingsStatus.TLabel", foreground="#627189")
        style.configure("SettingsSuccess.TLabel", foreground="#18794E")
        style.configure("SettingsError.TLabel", foreground="#B42336")
        style.configure("SettingsFormatError.TLabel", background="#FFFFFF", foreground="#B42336")

    def _build_header(self) -> None:
        header = ttk.Frame(self, padding=(0, 0, 0, 17))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="UYGULAMA AYARLARI", style="Overline.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(header, text="Bağlantı ve ayarlar", style="Title.TLabel").grid(
            row=1, column=0, sticky="w", pady=(4, 2)
        )
        self._intro_label = ttk.Label(
            header,
            text="OT hesabınızı bağlayın ve dosyaların kaydedileceği konumu belirleyin.",
            style="Muted.TLabel", wraplength=660,
        )
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

    def _build_server_card(self) -> None:
        card = self._card(0)
        ttk.Label(card, text="OT sunucusu", style="SettingsCardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            card, text="Kurum hesabınızla güvenli bağlantı kurun.", style="CardMuted.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(4, 17))

        server_field = ttk.Frame(card, style="Card.TFrame")
        server_field.grid(row=2, column=0, sticky="ew")
        server_field.columnconfigure(0, weight=1)
        self._field_label(server_field, "Sunucu adresi")
        self.base_url_entry = self._entry(server_field, self.base_url_var)
        ttk.Label(
            server_field, text="Örn. https://OT.kurumunuz.com", style="CardMuted.TLabel"
        ).grid(row=2, column=0, sticky="w", pady=(5, 0))

        credentials = ttk.Frame(card, style="Card.TFrame")
        self._credentials_row = credentials
        credentials.grid(row=3, column=0, sticky="ew", pady=(17, 0))
        credentials.columnconfigure(0, weight=1, uniform="credentials")
        credentials.columnconfigure(1, weight=1, uniform="credentials")

        username_field = ttk.Frame(credentials, style="Card.TFrame")
        self._username_field = username_field
        username_field.grid(row=0, column=0, sticky="new", padx=(0, 8))
        username_field.columnconfigure(0, weight=1)
        self._field_label(username_field, "Kullanıcı adı")
        self.username_entry = self._entry(username_field, self.username_var, width=12)

        password_field = ttk.Frame(credentials, style="Card.TFrame")
        self._password_field = password_field
        password_field.grid(row=0, column=1, sticky="new", padx=(8, 0))
        password_field.columnconfigure(0, weight=1)
        self._field_label(password_field, "Parola")
        password_row = ttk.Frame(password_field, style="Card.TFrame")
        password_row.grid(row=1, column=0, sticky="ew")
        password_row.columnconfigure(0, weight=1)
        self.password_entry = self._entry(
            password_row, self.password_var, row=0, show="•", width=8
        )
        self._show_password_button = ttk.Button(
            password_row, text="Göster", width=7, style="Subtle.TButton",
            command=self._toggle_password,
        )
        self._show_password_button.grid(row=0, column=1, padx=(6, 0))
        self._editable.append(self._show_password_button)

        remember = ttk.Checkbutton(
            card, text="Parolayı bu bilgisayarda hatırla",
            variable=self.remember_password_var, style="SettingsCard.TCheckbutton",
        )
        remember.grid(row=4, column=0, sticky="w", pady=(13, 0))
        self._editable.append(remember)

    def _build_output_card(self) -> None:
        card = self._card(1)
        ttk.Label(card, text="İndirme konumu", style="SettingsCardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            card, text="Tamamlanan belgelerin kaydedileceği klasör.", style="CardMuted.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(4, 13))
        path_row = ttk.Frame(card, style="Card.TFrame")
        path_row.grid(row=2, column=0, sticky="ew")
        path_row.columnconfigure(0, weight=1)
        self.output_dir_entry = self._entry(path_row, self.output_dir_var, row=0, width=12)
        browse = ttk.Button(
            path_row, text="Klasör seç…", style="Subtle.TButton", command=self._choose_output
        )
        browse.grid(row=0, column=1, padx=(9, 0))
        self._editable.append(browse)
        self._build_filename_fields(card)

    def _build_filename_fields(self, card: ttk.Frame) -> None:
        field = ttk.Frame(card, style="Card.TFrame")
        field.grid(row=3, column=0, sticky="ew", pady=(17, 0))
        field.columnconfigure(0, weight=1)
        self._field_label(field, "İndirilen dosyanın adı")
        self.filename_format_entry = self._entry(field, self.filename_format_var, width=12)
        tags = ttk.Frame(field, style="Card.TFrame")
        tags.grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.filename_tag_buttons = {}
        for column, (tag, label) in enumerate((
            ("numara", "Belge numarası"), ("ad", "Belge adı"), ("revizyon", "Revizyon"),
        )):
            button = ttk.Button(
                tags, text=label, style="Subtle.TButton",
                command=lambda name=tag: self._insert_filename_tag(name),
            )
            button.grid(row=0, column=column, padx=(0, 6))
            self.filename_tag_buttons[tag] = button
            self._editable.append(button)
        self._filename_hint = ttk.Label(
            field, text="Etiket eklemek için düğmelere tıklayın: {numara}, {ad}, {revizyon}. "
            "Dosya uzantısı otomatik eklenir.",
            style="CardMuted.TLabel", wraplength=580, justify="left",
        )
        self._filename_hint.grid(row=3, column=0, sticky="ew", pady=(7, 0))
        self._filename_preview = ttk.Label(
            field, textvariable=self.filename_preview_var, style="CardMuted.TLabel",
            wraplength=580, justify="left",
        )
        self._filename_preview.grid(row=4, column=0, sticky="ew", pady=(7, 0))
        self._update_filename_preview()

    def _insert_filename_tag(self, name: str) -> None:
        if self._busy:
            return
        entry = self.filename_format_entry
        if entry.selection_present():
            start = entry.index(tk.SEL_FIRST)
            entry.delete(tk.SEL_FIRST, tk.SEL_LAST)
            entry.icursor(start)
        entry.insert(tk.INSERT, "{" + name + "}")
        entry.focus_set()

    def _update_filename_preview(self, *_: object) -> None:
        sample = Document("preview", "PR-001.pdf", "Kalite Prosedürü", "", 3)
        try:
            name = format_document_filename(self.filename_format_var.get(), sample)
        except ValueError as error:
            self.filename_preview_var.set(str(error))
            self._filename_preview.configure(style="SettingsFormatError.TLabel")
        else:
            self.filename_preview_var.set("Örnek: " + safe_windows_filename(name, sample.id))
            self._filename_preview.configure(style="CardMuted.TLabel")

    def _build_advanced_card(self) -> None:
        card = self._card(2)
        self._advanced_toggle = ttk.Button(
            card, text="▸  Gelişmiş ayarlar", style="Subtle.TButton",
            command=self._toggle_advanced,
        )
        self._advanced_toggle.grid(row=0, column=0, sticky="w")
        self._advanced_body = ttk.Frame(card, style="Card.TFrame", padding=(0, 17, 0, 0))
        self._advanced_body.columnconfigure(0, weight=1)

        numeric_row = ttk.Frame(self._advanced_body, style="Card.TFrame")
        self._numeric_row = numeric_row
        numeric_row.grid(row=0, column=0, sticky="ew")
        numeric_row.columnconfigure(0, weight=1, uniform="advanced_fields")
        numeric_row.columnconfigure(1, weight=1, uniform="advanced_fields")

        timeout_field = ttk.Frame(numeric_row, style="Card.TFrame")
        self._timeout_field = timeout_field
        timeout_field.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        timeout_field.columnconfigure(0, weight=1)
        self._field_label(timeout_field, "İstek zaman aşımı (saniye)")
        self.timeout_entry = ttk.Spinbox(
            timeout_field, textvariable=self.timeout_var, from_=1, to=3600,
            increment=1, width=8,
        )
        self.timeout_entry.grid(row=1, column=0, sticky="ew")
        self.timeout_entry.bind("<FocusIn>", self._reveal_focused_widget, add="+")
        self._editable.append(self.timeout_entry)

        folder_field = ttk.Frame(numeric_row, style="Card.TFrame")
        self._folder_field = folder_field
        folder_field.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        folder_field.columnconfigure(0, weight=1)
        self._field_label(folder_field, "Klasör kimliği (isteğe bağlı)")
        self.folder_id_entry = self._entry(folder_field, self.folder_id_var, width=10)

        certificate = ttk.Frame(self._advanced_body, style="Card.TFrame")
        certificate.grid(row=1, column=0, sticky="ew", pady=(17, 0))
        certificate.columnconfigure(0, weight=1)
        self._field_label(certificate, "CA sertifika dosyası (isteğe bağlı)")
        certificate_row = ttk.Frame(certificate, style="Card.TFrame")
        certificate_row.grid(row=1, column=0, sticky="ew")
        certificate_row.columnconfigure(0, weight=1)
        self.ca_bundle_entry = self._entry(
            certificate_row, self.ca_bundle_var, row=0, width=12
        )
        browse = ttk.Button(
            certificate_row, text="Dosya seç…", style="Subtle.TButton",
            command=self._choose_ca_bundle,
        )
        browse.grid(row=0, column=1, padx=(9, 0))
        self._editable.append(browse)
        self._ca_hint = ttk.Label(
            certificate,
            text="Kurumunuz özel bir sertifika kullanıyorsa CA dosyasını seçin.",
            style="CardMuted.TLabel", wraplength=580,
        )
        self._ca_hint.grid(row=2, column=0, sticky="w", pady=(6, 0))

        verify = ttk.Checkbutton(
            self._advanced_body, text="Sunucu sertifikasını doğrula (TLS)",
            variable=self.verify_tls_var, style="SettingsCard.TCheckbutton",
        )
        verify.grid(row=2, column=0, sticky="w", pady=(16, 0))
        self._editable.append(verify)
        self._tls_hint = ttk.Label(
            self._advanced_body,
            text="Bağlantı güvenliği için doğrulamanın açık tutulması önerilir.",
            style="CardMuted.TLabel", wraplength=580,
        )
        self._tls_hint.grid(row=3, column=0, sticky="w", pady=(5, 0))

    def _build_footer(
        self, on_save: Callable[[], None], on_test: Callable[[], None]
    ) -> None:
        footer = ttk.Frame(self, padding=(0, 12, 0, 0))
        footer.grid(row=2, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self._status_label = ttk.Label(
            footer, textvariable=self._status_var, style="SettingsStatus.TLabel",
            wraplength=650,
        )
        self._status_label.grid(row=0, column=0, sticky="ew", pady=(0, 11))
        actions = ttk.Frame(footer)
        actions.grid(row=1, column=0, sticky="e")
        self.test_button = ttk.Button(
            actions, text="Bağlantıyı test et", style="Subtle.TButton", command=on_test
        )
        self.test_button.grid(row=0, column=0, padx=(0, 10))
        self.save_button = ttk.Button(
            actions, text="Ayarları kaydet", style="Accent.TButton", command=on_save
        )
        self.save_button.grid(row=0, column=1)

    def read_settings(self) -> AppSettings:
        """Return form values; reject invalid timeout/filename inputs locally."""
        filename_format = self.filename_format_var.get()
        try:
            validate_filename_format(filename_format)
        except ValueError as error:
            self.set_connection_status(str(error), success=False)
            self.filename_format_entry.focus_set()
            self._queue_reveal(self.filename_format_entry)
            raise
        timeout_text = self.timeout_var.get().strip().replace(",", ".")
        try:
            timeout = float(timeout_text)
        except (ValueError, OverflowError):
            message = "İstek zaman aşımı için geçerli bir sayı girin."
            self.set_connection_status(message, success=False)
            self._focus_timeout()
            raise ValueError(message) from None
        if not math.isfinite(timeout) or not 0 < timeout <= 3600:
            message = "İstek zaman aşımı 0'dan büyük ve en fazla 3600 saniye olmalıdır."
            self.set_connection_status(message, success=False)
            self._focus_timeout()
            raise ValueError(message)
        numeric_timeout = int(timeout) if timeout.is_integer() else timeout
        return replace(
            self._initial_settings,
            base_url=self.base_url_var.get().strip(),
            username=self.username_var.get().strip(),
            password=self.password_var.get(),
            output_dir=self.output_dir_var.get().strip(),
            filename_format=filename_format.strip(),
            timeout=numeric_timeout,
            folder_id=self.folder_id_var.get().strip(),
            ca_bundle=self.ca_bundle_var.get().strip(),
            verify_tls=self.verify_tls_var.get(),
            remember_password=self.remember_password_var.get(),
        )

    def set_busy(self, busy: bool) -> None:
        """Keep the form stable while the application uses its connection."""
        self._busy = bool(busy)
        states = ["disabled"] if self._busy else ["!disabled"]
        for widget in (*self._editable, self.save_button, self.test_button):
            widget.state(states)

    def set_connection_status(self, message: str, success: bool | None = None) -> None:
        self._status_kind = success
        self._status_var.set(message)
        style = (
            "SettingsSuccess.TLabel" if success is True else
            "SettingsError.TLabel" if success is False else "SettingsStatus.TLabel"
        )
        self._status_label.configure(style=style)

    def focus_connection(self) -> None:
        if self._reveal_after is not None:
            self.after_cancel(self._reveal_after)
            self._reveal_after = None
        self._canvas.yview_moveto(0)
        self.base_url_entry.focus_set()
        self.base_url_entry.selection_range(0, tk.END)

    def mark_saved(self) -> None:
        self.set_connection_status("Ayarlar kaydedildi.", success=True)

    def _focus_timeout(self) -> None:
        if not self._advanced_open:
            self._toggle_advanced()
        self.timeout_entry.focus_set()
        self.timeout_entry.selection_range(0, tk.END)
        self._queue_reveal(self.timeout_entry)

    def _toggle_password(self) -> None:
        visible = not self.show_password_var.get()
        self.show_password_var.set(visible)
        self.password_entry.configure(show="" if visible else "•")
        self._show_password_button.configure(text="Gizle" if visible else "Göster")

    def _toggle_advanced(self) -> None:
        self._advanced_open = not self._advanced_open
        if self._advanced_open:
            self._advanced_body.grid(row=1, column=0, sticky="ew")
            self._advanced_toggle.configure(text="▾  Gelişmiş ayarlar")
        else:
            self._advanced_body.grid_remove()
            self._advanced_toggle.configure(text="▸  Gelişmiş ayarlar")

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.winfo_toplevel(), title="İndirme klasörünü seçin",
            initialdir=self.output_dir_var.get() or None, mustexist=False,
        )
        if selected:
            self.output_dir_var.set(selected)

    def _choose_ca_bundle(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.winfo_toplevel(), title="CA sertifika dosyasını seçin",
            filetypes=[("Sertifika dosyaları", "*.pem *.crt *.cer"), ("Tüm dosyalar", "*")],
        )
        if selected:
            self.ca_bundle_var.set(selected)

    def _on_settings_changed(self, *_: object) -> None:
        if not self._busy:
            self.set_connection_status("Kaydedilmemiş değişiklikler var.")

    def _resize_scroll_contents(self, event: tk.Event) -> None:
        self._canvas.itemconfigure(self._canvas_window, width=event.width)
        self._layout_fields(event.width)
        self._update_scrollregion()

    def _layout_fields(self, width: int) -> None:
        """Stack paired fields on compact windows instead of clipping their labels."""
        stacked = width < 570
        if stacked == self._stacked_fields:
            return
        self._stacked_fields = stacked
        for row, first, second, uniform in (
            (self._credentials_row, self._username_field, self._password_field, "credentials"),
            (self._numeric_row, self._timeout_field, self._folder_field, "advanced_fields"),
        ):
            row.columnconfigure(0, weight=1, uniform="" if stacked else uniform)
            row.columnconfigure(1, weight=0 if stacked else 1, uniform="" if stacked else uniform)
            first.grid_configure(row=0, column=0, padx=0 if stacked else (0, 8))
            second.grid_configure(
                row=1 if stacked else 0, column=0 if stacked else 1,
                padx=0 if stacked else (8, 0), pady=(13, 0) if stacked else 0,
            )

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
        self._ca_hint.configure(wraplength=max(140, width - 55))
        self._tls_hint.configure(wraplength=max(140, width - 55))
        self._filename_hint.configure(wraplength=max(140, width - 55))
        self._filename_preview.configure(wraplength=max(140, width - 55))

    def _bind_scroll_widgets(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._on_mousewheel, add="+")
        widget.bind("<Button-4>", self._on_mousewheel, add="+")
        widget.bind("<Button-5>", self._on_mousewheel, add="+")
        if isinstance(widget, (ttk.Button, ttk.Checkbutton)):
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
        """Ensure keyboard tab navigation also scrolls the focused field into view."""
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
