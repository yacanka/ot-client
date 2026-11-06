"""Download location and document naming preferences, without persistence."""

from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from tkinter import filedialog, ttk
from typing import Callable

from otClient import Document, safe_windows_filename

from .filename_format import (
    format_document_filename,
    format_document_folder,
    validate_filename_format,
    validate_folder_format,
)
from .settings import AppSettings, SettingsValidationError
from .settings_page import SettingsPage


class StorageView(SettingsPage):
    """Edit storage fields while preserving the connection page's draft."""

    def __init__(
        self, parent: tk.Misc, settings: AppSettings, on_save: Callable[[], None]
    ) -> None:
        super().__init__(
            parent, settings, title="Depolama",
            intro="İndirme konumunu, dosya adlarını ve belge klasörlerini düzenleyin.",
        )
        self.output_dir_var = tk.StringVar(self, value=settings.output_dir)
        self.filename_format_var = tk.StringVar(self, value=settings.filename_format)
        self.filename_preview_var = tk.StringVar(self)
        self.document_subfolder_enabled_var = tk.BooleanVar(
            self, value=settings.document_subfolder_enabled
        )
        self.manual_folder_hierarchy_enabled_var = tk.BooleanVar(
            self, value=settings.manual_folder_hierarchy_enabled
        )
        self.document_subfolder_format_var = tk.StringVar(
            self, value=settings.document_subfolder_format
        )
        self.document_subfolder_match_var = tk.StringVar(
            self, value=settings.document_subfolder_match
        )
        self.folder_preview_var = tk.StringVar(self)
        self.download_related_forms_var = tk.BooleanVar(self, value=settings.download_related_forms)
        self.download_related_attachments_var = tk.BooleanVar(self, value=settings.download_related_attachments)
        self._build_output_card()
        self._build_hierarchy_card()
        self._build_folder_card()
        self._build_related_card()
        self._build_footer(on_save)
        self._field_widgets = {
            "output_dir": self.output_dir_entry,
            "filename_format": self.filename_format_entry,
            "document_subfolder_enabled": self.document_subfolder_enabled_button,
            "manual_folder_hierarchy_enabled": self.manual_folder_hierarchy_enabled_button,
            "document_subfolder_format": self.document_subfolder_format_entry,
            "document_subfolder_match": self._folder_match_buttons[0],
            "download_related_forms": self.download_related_forms_button,
            "download_related_attachments": self.download_related_attachments_button,
        }
        for variable in (
            self.output_dir_var, self.filename_format_var,
            self.document_subfolder_enabled_var, self.document_subfolder_format_var,
            self.manual_folder_hierarchy_enabled_var,
            self.document_subfolder_match_var,
            self.download_related_forms_var, self.download_related_attachments_var,
        ):
            variable.trace_add("write", self._on_settings_changed)
        self.filename_format_var.trace_add("write", self._update_filename_preview)
        self.document_subfolder_format_var.trace_add("write", self._update_folder_preview)
        self.document_subfolder_enabled_var.trace_add("write", self._update_folder_controls)
        self.manual_folder_hierarchy_enabled_var.trace_add("write", self._update_folder_controls)
        self._update_folder_controls()

    def _build_output_card(self) -> None:
        card = self._card(0)
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
        self._filename_hint = ttk.Label(
            field, text="Etiketleri doğrudan yazın: {numara} belge numarası, {ad} belge adı, "
            "{revizyon} revizyon, {index} listedeki sıradır (1; manuel modda 1.1 gibi). "
            "Örnek format: {index} - {numara} - {ad}. "
            "Dosya uzantısı otomatik eklenir.",
            style="CardMuted.TLabel", wraplength=580, justify="left",
        )
        self._filename_hint.grid(row=2, column=0, sticky="ew", pady=(7, 0))
        self._filename_preview = ttk.Label(
            field, textvariable=self.filename_preview_var, style="CardMuted.TLabel",
            wraplength=580, justify="left",
        )
        self._filename_preview.grid(row=3, column=0, sticky="ew", pady=(7, 0))
        self._wrap_labels.extend((self._filename_hint, self._filename_preview))
        self._update_filename_preview()

    def _build_hierarchy_card(self) -> None:
        card = self._card(1)
        card.configure(style="SettingsHierarchy.TFrame")
        ttk.Label(card, text="Klasör hiyerarşisi", style="SettingsHierarchyTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.manual_folder_hierarchy_enabled_button = ttk.Checkbutton(
            card, text="Klasör hiyerarşisini manuel düzenle",
            variable=self.manual_folder_hierarchy_enabled_var, style="SettingsHierarchy.TCheckbutton",
        )
        self.manual_folder_hierarchy_enabled_button.grid(row=1, column=0, sticky="w", pady=(10, 7))
        self._editable.append(self.manual_folder_hierarchy_enabled_button)
        explanation = ttk.Label(
            card, text="Belgeleri üst ve alt klasörler olarak düzenleyin. Özel belge klasörleriyle "
            "birlikte kullanılabilir. Alt belgesi olan üst belgeler için her zaman klasör oluşturulur. "
            "Özel belge klasörü kapalıysa alt belgesi olmayan belgeler üst klasöre, "
            "üst klasörü de olmayanlar indirme konumuna kaydedilir.",
            style="SettingsHierarchy.TLabel", wraplength=580, justify="left",
        )
        explanation.grid(row=2, column=0, sticky="ew")
        controls_hint = ttk.Label(
            card, text="Belgeler tablosunda ↑ ↓ aynı seviyedeki sıralamayı alt belgelerle birlikte "
            "değiştirir; ← → üst / alt seviyeyi düzenler. Ardışık kardeş belgeler birlikte "
            "taşınabilir. Yapı saklanır; önceden indirilen dosyalar taşınmaz.",
            style="SettingsHierarchy.TLabel", wraplength=580, justify="left",
        )
        controls_hint.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self._wrap_labels.extend((explanation, controls_hint))

    def _build_folder_card(self) -> None:
        card = self._card(2)
        ttk.Label(card, text="Belge klasörleri", style="SettingsCardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.document_subfolder_enabled_button = ttk.Checkbutton(
            card, text="Her belgeyi özel bir klasöre kaydet",
            variable=self.document_subfolder_enabled_var, style="SettingsCard.TCheckbutton",
        )
        self.document_subfolder_enabled_button.grid(row=1, column=0, sticky="w", pady=(10, 15))
        self._editable.append(self.document_subfolder_enabled_button)
        field = ttk.Frame(card, style="Card.TFrame")
        field.grid(row=2, column=0, sticky="ew")
        field.columnconfigure(0, weight=1)
        self._field_label(field, "Klasör adı formatı")
        self.document_subfolder_format_entry = self._entry(
            field, self.document_subfolder_format_var, width=12
        )
        hint = ttk.Label(
            field, text="Etiketleri doğrudan yazın: {numara}, {ad}, {revizyon}, {index}. "
            "{index} listedeki sıradır (1; manuel modda 1.1 gibi). "
            "Format ve eşleştirme her iki seçenek için ortaktır. Klasör adına dosya uzantısı eklenmez.",
            style="CardMuted.TLabel", wraplength=580, justify="left",
        )
        hint.grid(row=2, column=0, sticky="ew", pady=(7, 0))
        self._folder_preview = ttk.Label(
            field, textvariable=self.folder_preview_var, style="CardMuted.TLabel",
            wraplength=580, justify="left",
        )
        self._folder_preview.grid(row=3, column=0, sticky="ew", pady=(7, 0))
        self._wrap_labels.extend((hint, self._folder_preview))
        self._field_label(card, "Mevcut klasörle eşleştirme", row=3).grid_configure(pady=(17, 6))
        self._folder_match_buttons = []
        for row, value, text in (
            (4, "exact", "Birebir eşleşme"),
            (5, "contains", "İçerme"),
        ):
            button = ttk.Radiobutton(
                card, text=text, value=value, variable=self.document_subfolder_match_var,
                style="SettingsCard.TRadiobutton",
            )
            button.grid(row=row, column=0, sticky="w", pady=(0, 5))
            self._folder_match_buttons.append(button)
            self._editable.append(button)
        match_hint = ttk.Label(
            card, text="Her belgenin üst klasöründeki doğrudan alt klasörler, büyük/küçük harf "
            "ayrımı olmadan aranır. Manuel modda bu kural her seviyede uygulanır. "
            "Birebir eşleşme önceliklidir. Eşleşme yoksa klasör "
            "oluşturulur; birden çok eşleşme varsa belge atlanır.",
            style="CardMuted.TLabel", wraplength=580, justify="left",
        )
        match_hint.grid(row=6, column=0, sticky="ew", pady=(5, 0))
        self._wrap_labels.append(match_hint)
        self._update_folder_preview()

    def _build_related_card(self) -> None:
        card = self._card(3)
        ttk.Label(card, text="İlgili belgeler", style="SettingsCardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.download_related_forms_button = ttk.Checkbutton(
            card, text="İlgili formları da indir", variable=self.download_related_forms_var,
            style="SettingsCard.TCheckbutton",
        )
        self.download_related_forms_button.grid(row=1, column=0, sticky="w", pady=(10, 5))
        self.download_related_attachments_button = ttk.Checkbutton(
            card, text="İlgili ekleri de indir", variable=self.download_related_attachments_var,
            style="SettingsCard.TCheckbutton",
        )
        self.download_related_attachments_button.grid(row=2, column=0, sticky="w", pady=(0, 5))
        self._editable.extend((self.download_related_forms_button, self.download_related_attachments_button))
        hint = ttk.Label(
            card, text="Form ve ekler belgeyle aynı klasöre kaydedilir. Dosya adı formatı "
            "her form ve ekin kendi bilgileriyle uygulanır.",
            style="CardMuted.TLabel", wraplength=580, justify="left",
        )
        hint.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        self._wrap_labels.append(hint)

    def _update_filename_preview(self, *_: object) -> None:
        sample = Document("preview", "PR-001.pdf", "Kalite Prosedürü", "", 3)
        try:
            name = format_document_filename(
                self.filename_format_var.get(), sample,
                index="1.1" if self.manual_folder_hierarchy_enabled_var.get() else "1",
            )
        except ValueError as error:
            self.filename_preview_var.set(str(error))
            self._filename_preview.configure(style="SettingsFormatError.TLabel")
        else:
            self.filename_preview_var.set("Örnek: " + safe_windows_filename(name, sample.id))
            self._filename_preview.configure(style="CardMuted.TLabel")

    def _update_folder_preview(self, *_: object) -> None:
        sample = Document("preview", "PR-001.pdf", "Kalite Prosedürü", "", 3)
        try:
            name = format_document_folder(
                self.document_subfolder_format_var.get(), sample,
                index="1.1" if self.manual_folder_hierarchy_enabled_var.get() else "1",
            )
        except ValueError as error:
            self.folder_preview_var.set(str(error))
            self._folder_preview.configure(style="SettingsFormatError.TLabel")
        else:
            self.folder_preview_var.set("Örnek: " + safe_windows_filename(name))
            self._folder_preview.configure(style="CardMuted.TLabel")

    def read_settings(self, base: AppSettings | None = None) -> AppSettings:
        """Merge storage fields, validating folder grammar only when enabled."""
        enabled = self.document_subfolder_enabled_var.get()
        manual = self.manual_folder_hierarchy_enabled_var.get()
        formats = [("filename_format", self.filename_format_var.get(), validate_filename_format)]
        folder_format = self.document_subfolder_format_var.get()
        if enabled or manual:
            formats.append(("document_subfolder_format", folder_format, validate_folder_format))
        for field, value, validate in formats:
            try:
                validate(value)
            except ValueError as error:
                self.set_status(str(error), success=False)
                self.focus_field(field)
                raise SettingsValidationError(field, str(error)) from None
        return replace(
            self._initial_settings if base is None else base,
            output_dir=self.output_dir_var.get().strip(),
            filename_format=self.filename_format_var.get().strip(),
            document_subfolder_enabled=enabled,
            manual_folder_hierarchy_enabled=manual,
            document_subfolder_format=folder_format.strip() if enabled or manual else folder_format,
            document_subfolder_match=self.document_subfolder_match_var.get(),
            download_related_forms=self.download_related_forms_var.get(),
            download_related_attachments=self.download_related_attachments_var.get(),
        )

    def set_busy(self, busy: bool) -> None:
        super().set_busy(busy)
        self._update_folder_controls()

    def _update_folder_controls(self, *_: object) -> None:
        individual = self.document_subfolder_enabled_var.get()
        manual = self.manual_folder_hierarchy_enabled_var.get()
        self.document_subfolder_enabled_button.state(
            ["disabled"] if self._busy else ["!disabled"]
        )
        self.manual_folder_hierarchy_enabled_button.state(
            ["disabled"] if self._busy else ["!disabled"]
        )
        disabled = self._busy or not (individual or manual)
        states = ["disabled"] if disabled else ["!disabled"]
        for widget in (self.document_subfolder_format_entry, *self._folder_match_buttons):
            widget.state(states)
        self._update_filename_preview()
        self._update_folder_preview()

    def _choose_output(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.winfo_toplevel(), title="İndirme klasörünü seçin",
            initialdir=self.output_dir_var.get() or None, mustexist=False,
        )
        if selected:
            self.output_dir_var.set(selected)
