"""Connection settings, presented without persistence side effects."""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import replace
from tkinter import filedialog, ttk
from typing import Callable

from .settings import AppSettings, SettingsValidationError
from .settings_page import SettingsPage


class SettingsView(SettingsPage):
    """Edit connection fields; callbacks let the application save both pages."""

    def __init__(
        self,
        parent: tk.Misc,
        settings: AppSettings,
        on_save: Callable[[], None],
        on_test: Callable[[], None],
    ) -> None:
        super().__init__(
            parent, settings, title="Bağlantı",
            intro="OT hesabınızın sunucu ve bağlantı bilgilerini düzenleyin.",
        )
        self._advanced_open = False
        self._stacked_fields: bool | None = None
        self.base_url_var = tk.StringVar(self, value=settings.base_url)
        self.username_var = tk.StringVar(self, value=settings.username)
        self.password_var = tk.StringVar(self, value=settings.password)
        timeout = settings.timeout
        timeout_text = str(int(timeout)) if float(timeout).is_integer() else str(timeout)
        self.timeout_var = tk.StringVar(self, value=timeout_text)
        self.folder_id_var = tk.StringVar(self, value=settings.folder_id)
        self.ca_bundle_var = tk.StringVar(self, value=settings.ca_bundle)
        self.verify_tls_var = tk.BooleanVar(self, value=settings.verify_tls)
        self.remember_password_var = tk.BooleanVar(self, value=settings.remember_password)
        self.show_password_var = tk.BooleanVar(self, value=False)
        self._status_var.set("Ayarları kaydedin veya bağlantınızı test edin.")

        self._build_server_card()
        self._build_advanced_card()
        self._build_footer(on_save, on_test)
        self._wrap_labels.extend((self._ca_hint, self._tls_hint))
        self._field_widgets = {
            "base_url": self.base_url_entry,
            "username": self.username_entry,
            "password": self.password_entry,
            "timeout": self.timeout_entry,
            "folder_id": self.folder_id_entry,
            "ca_bundle": self.ca_bundle_entry,
            "verify_tls": self.verify_tls_button,
            "remember_password": self.remember_password_button,
        }
        for variable in (
            self.base_url_var, self.username_var, self.password_var, self.timeout_var,
            self.folder_id_var, self.ca_bundle_var, self.verify_tls_var,
            self.remember_password_var,
        ):
            variable.trace_add("write", self._on_settings_changed)

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
        self.remember_password_button = remember
        remember.grid(row=4, column=0, sticky="w", pady=(13, 0))
        self._editable.append(remember)

    def _build_advanced_card(self) -> None:
        card = self._card(1)
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
        self.verify_tls_button = verify
        verify.grid(row=2, column=0, sticky="w", pady=(16, 0))
        self._editable.append(verify)
        self._tls_hint = ttk.Label(
            self._advanced_body,
            text="Bağlantı güvenliği için doğrulamanın açık tutulması önerilir.",
            style="CardMuted.TLabel", wraplength=580,
        )
        self._tls_hint.grid(row=3, column=0, sticky="w", pady=(5, 0))

    def read_settings(self, base: AppSettings | None = None) -> AppSettings:
        """Merge only connection fields into the supplied draft or initial values."""
        timeout_text = self.timeout_var.get().strip().replace(",", ".")
        try:
            timeout = float(timeout_text)
        except (ValueError, OverflowError):
            message = "İstek zaman aşımı için geçerli bir sayı girin."
            self.set_status(message, success=False)
            self.focus_field("timeout")
            raise SettingsValidationError("timeout", message) from None
        if not math.isfinite(timeout) or not 0 < timeout <= 3600:
            message = "İstek zaman aşımı 0'dan büyük ve en fazla 3600 saniye olmalıdır."
            self.set_status(message, success=False)
            self.focus_field("timeout")
            raise SettingsValidationError("timeout", message)
        numeric_timeout = int(timeout) if timeout.is_integer() else timeout
        return replace(
            self._initial_settings if base is None else base,
            base_url=self.base_url_var.get().strip(),
            username=self.username_var.get().strip(),
            password=self.password_var.get(),
            timeout=numeric_timeout,
            folder_id=self.folder_id_var.get().strip(),
            ca_bundle=self.ca_bundle_var.get().strip(),
            verify_tls=self.verify_tls_var.get(),
            remember_password=self.remember_password_var.get(),
        )

    def set_connection_status(self, message: str, success: bool | None = None) -> None:
        """Compatibility alias for callers reporting connection probe results."""
        self.set_status(message, success)

    def focus_field(self, field: str) -> None:
        if field in {"timeout", "folder_id", "ca_bundle", "verify_tls"} and not self._advanced_open:
            self._toggle_advanced()
        super().focus_field(field)

    def focus_connection(self) -> None:
        if self._reveal_after is not None:
            self.after_cancel(self._reveal_after)
            self._reveal_after = None
        self._canvas.yview_moveto(0)
        self.base_url_entry.focus_set()
        self.base_url_entry.selection_range(0, tk.END)

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

    def _choose_ca_bundle(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self.winfo_toplevel(), title="CA sertifika dosyasını seçin",
            filetypes=[("Sertifika dosyaları", "*.pem *.crt *.cer"), ("Tüm dosyalar", "*")],
        )
        if selected:
            self.ca_bundle_var.set(selected)

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
