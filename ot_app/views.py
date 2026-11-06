"""Document workspace: layout and widget state, independent of networking."""
import tkinter as tk
from tkinter import ttk

from .theme import AMBER, BLUE, GREEN, MUTED, RED, card

STATUS_LABELS = {
    "pending": "Bekliyor", "searching": "Aranıyor", "downloading": "İndiriliyor",
    "downloaded": "İndirildi", "updated": "Güncellendi", "unchanged": "Güncel",
    "not_found": "Bulunamadı", "ambiguous": "Seçim gerekli", "error": "Hata",
    "cancelled": "İptal edildi",
    "folder_ambiguous": "Klasör belirsiz",
}
SUCCESS = {"downloaded", "updated", "unchanged"}
PROBLEMS = {"error", "not_found", "ambiguous", "folder_ambiguous", "cancelled"}


class DocumentsView(ttk.Frame):
    def __init__(self, parent, callbacks):
        super().__init__(parent)
        self.callbacks = callbacks
        self.busy = False
        self.manual_hierarchy = False
        self.compact = False
        self.input_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self.filter_var = tk.StringVar(value="Tüm belgeler")
        self.total_var = tk.StringVar(value="0")
        self.done_var = tk.StringVar(value="0")
        self.waiting_var = tk.StringVar(value="0")
        self.selection_var = tk.StringVar(value="0 belge")
        self.progress_var = tk.StringVar(value="İşlem başlatılmadı")
        self.detail_var = tk.StringVar(value="Durumunu görmek için listeden bir belge seçin.")
        self.path_var = tk.StringVar(value="İndirme klasörü ayarlardan seçilebilir.")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self._header()
        self._metrics()
        self._input_card()
        self._table_card()
        self._footer()
        self.search_var.trace_add("write", lambda *_: self.callbacks["filter"]())
        self.filter_var.trace_add("write", lambda *_: self.callbacks["filter"]())
        self.bind("<Configure>", self._resize)

    def _header(self):
        row = ttk.Frame(self)
        row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        row.columnconfigure(0, weight=1)
        ttk.Label(row, text="ÇALIŞMA ALANI", style="Overline.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(row, text="Belgeler", style="Title.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 2))
        self.header_hint = ttk.Label(row, style="Muted.TLabel")
        self.header_hint.grid(row=2, column=0, sticky="w")
        self.header_hint.grid_remove()
        self.connection_button = ttk.Button(row, text="Bağlantıyı ayarla", style="Link.TButton",
                                            command=self.callbacks["settings"])
        self.connection_button.grid(row=1, column=1, sticky="e", padx=(14, 0))

    def _metrics(self):
        area = ttk.Frame(self)
        self.metrics_area = area
        area.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        for col, (label, variable, style, subtitle) in enumerate([
            ("BELGE LİSTESİ", self.total_var, "Metric.TLabel", "Kayıtlı belge numarası"),
            ("TAMAMLANAN", self.done_var, "SuccessMetric.TLabel", "İndirilen veya zaten güncel"),
            ("İŞLEM BEKLEYEN", self.waiting_var, "Metric.TLabel", "Henüz tamamlanmayan"),
        ]):
            area.columnconfigure(col, weight=1, uniform="metrics")
            border, content = card(area, padding=(16, 12))
            border.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0 if col == 2 else 6))
            content.columnconfigure(0, weight=1)
            ttk.Label(content, text=label, style="CardMuted.TLabel").grid(row=0, column=0, sticky="w")
            ttk.Label(content, textvariable=variable, style=style).grid(row=0, column=1, sticky="e", padx=(8, 0))
            ttk.Label(content, text=subtitle, style="CardMuted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

    def _input_card(self):
        border, content = card(self, padding=(16, 8))
        border.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        content.columnconfigure(0, weight=1)
        ttk.Label(content, text="Belge numarası", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 7))
        self.number_entry = ttk.Entry(content, textvariable=self.input_var)
        self.number_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.number_entry.bind("<Return>", lambda _event: self.callbacks["add"]())
        self.add_button = ttk.Button(content, text="+  Ekle", style="Accent.TButton", command=self.callbacks["add"])
        self.add_button.grid(row=1, column=1, padx=(0, 8))
        self.bulk_button = ttk.Button(content, text="Toplu ekle", command=self.callbacks["bulk"])
        self.bulk_button.grid(row=1, column=2, padx=(0, 8))
        self.import_button = ttk.Button(content, text="Dosyadan al", command=self.callbacks["import"])
        self.import_button.grid(row=1, column=3)

    def _table_card(self):
        border, content = card(self, padding=0)
        border.grid(row=3, column=0, sticky="nsew")
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(content, style="Card.TFrame", padding=(14, 7))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, text="Filtre", style="CardMuted.TLabel").grid(row=0, column=0, padx=(0, 8))
        self.search_entry = ttk.Entry(toolbar, textvariable=self.search_var, width=18)
        self.search_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        self.filter_box = ttk.Combobox(toolbar, textvariable=self.filter_var, state="readonly", width=17,
                                      values=("Tüm belgeler", "Bekleyen", "Tamamlanan", "Sorunlu", "Seçim gerekli"))
        self.filter_box.grid(row=0, column=2, padx=(0, 8))
        self.list_menu = tk.Menu(toolbar, tearoff=False)
        self.list_menu.add_command(label="Listeyi dışa aktar…", command=self.callbacks["export"])
        self.list_menu.add_command(label="Sonuç raporunu dışa aktar…", command=self.callbacks["report"])
        self.list_menu.add_separator()
        self.list_menu.add_command(label="Sorunluları yeniden dene", command=self.callbacks["retry"])
        self.list_menu.add_command(label="Son liste işlemini geri al    Ctrl+Z", command=self.callbacks["undo"])
        self.list_menu.add_separator()
        self.list_menu.add_command(label="Tüm listeyi temizle…", command=self.callbacks["clear"])
        self.menu_button = ttk.Menubutton(toolbar, text="Liste işlemleri", menu=self.list_menu)
        self.menu_button.grid(row=0, column=3)
        self.table_area = ttk.Frame(content, style="Card.TFrame")
        self.table_area.grid(row=1, column=0, sticky="nsew")
        self.table_area.columnconfigure(0, weight=1)
        self.table_area.rowconfigure(0, weight=1)
        self._data_columns = ("number", "title", "revision", "status", "size")
        self.tree = ttk.Treeview(self.table_area, columns=("index", *self._data_columns),
                                 displaycolumns=self._data_columns,
                                 show="headings", selectmode="extended", height=5)
        for col, text, width, minimum, stretch in [
            ("index", "Index", 110, 75, False),
            ("number", "BELGE NUMARASI", 160, 110, False),
            ("title", "BELGE ADI / AÇIKLAMA", 300, 140, True),
            ("revision", "REVİZYON", 100, 80, False),
            ("status", "DURUM", 130, 110, False),
            ("size", "BOYUT", 80, 65, False),
        ]:
            anchor = "w" if col in {"index", "title"} else "center"
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, minwidth=minimum, stretch=stretch, anchor=anchor)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(self.table_area, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.horizontal_scrollbar = ttk.Scrollbar(self.table_area, orient="horizontal", command=self.tree.xview)
        self.horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self.horizontal_scrollbar.grid_remove()
        self.tree.configure(xscrollcommand=self._update_horizontal_scroll)
        self.tree.bind("<Configure>", self._fit_title_column)
        for state in STATUS_LABELS:
            color = GREEN if state in SUCCESS else RED if state == "error" else AMBER if state in {"not_found", "ambiguous", "folder_ambiguous"} else BLUE if state in {"searching", "downloading"} else MUTED
            self.tree.tag_configure(state, foreground=color)
        self.tree.bind("<<TreeviewSelect>>", lambda _: self.callbacks["selection"]())
        self.tree.bind("<Delete>", lambda _: self.callbacks["remove"]())
        self.tree.bind("<Control-a>", self._select_all)
        self.tree.bind("<Control-c>", lambda _: self.callbacks["copy"]())
        self.tree.bind("<Control-z>", lambda _: self.callbacks["undo"]())
        self.tree.bind("<Up>", lambda _: self._change_hierarchy("up"))
        self.tree.bind("<Down>", lambda _: self._change_hierarchy("down"))
        self.tree.bind("<Right>", lambda _: self._change_hierarchy("indent"))
        self.tree.bind("<Left>", lambda _: self._change_hierarchy("outdent"))
        modifiers = ("Shift", "Control", "Alt", "Meta")
        if self.tk.call("tk", "windowingsystem") == "aqua":
            modifiers += ("Command", "Option")
        # Tk resolves platform modifiers; these bindings continue to native navigation.
        for key in ("Up", "Down", "Right", "Left"):
            for modifier in modifiers:
                self.tree.bind(f"<{modifier}-{key}>", lambda _: None)
        self.context_menu = tk.Menu(self.tree, tearoff=False)
        self.context_menu.add_command(label="Seçileni indir", command=self.callbacks["selected"])
        self.context_menu.add_command(label="Seçileni kaldır", command=self.callbacks["remove"])
        self.context_menu.add_command(label="Belge numarasını düzenle…", command=self.callbacks["edit"])
        self.tree.bind("<Button-3>", self._show_context_menu)
        if self.tk.call("tk", "windowingsystem") == "aqua":
            self.tree.bind("<Button-2>", self._show_context_menu)
            self.tree.bind("<Control-Button-1>", self._show_context_menu)
        self.tree.bind("<Double-1>", lambda _: self.callbacks["open_file"]())
        self.empty = ttk.Frame(self.table_area, style="Card.TFrame", padding=14)
        ttk.Label(self.empty, text="Belge listeniz burada görünecek", style="Section.TLabel").pack(pady=(0, 8))
        ttk.Label(self.empty, text="Bir belge numarası ekleyin veya listenizi toplu yapıştırın.",
                  style="CardMuted.TLabel").pack()
        self.empty.place(relx=0.5, rely=0.57, anchor="center")
        self._detail_bar(content)

    def set_manual_hierarchy(self, enabled):
        self.manual_hierarchy = bool(enabled)
        columns = ("index", *self._data_columns) if enabled else self._data_columns
        self.tree.configure(displaycolumns=columns)
        self._fit_title_column()

    def _fit_title_column(self, _event=None):
        available = self.tree.winfo_width() - 2
        if available <= 0:
            return
        columns = self.tree["displaycolumns"]
        fixed_width = sum(self.tree.column(column, "width") for column in columns if column != "title")
        width = max(self.tree.column("title", "minwidth"), available - fixed_width)
        if self.tree.column("title", "width") != width:
            self.tree.column("title", width=width)

    def _update_horizontal_scroll(self, first, last):
        self.horizontal_scrollbar.set(first, last)
        if float(first) > 0 or float(last) < 1:
            self.horizontal_scrollbar.grid()
        else:
            self.horizontal_scrollbar.grid_remove()

    def _show_context_menu(self, event):
        key = self.tree.identify_row(event.y)
        if not key or self.tree.identify_region(event.x, event.y) not in ("tree", "cell"):
            return "break"
        if key not in self.tree.selection():
            self.tree.selection_set(key)
        self.tree.focus(key)
        self.tree.focus_set()
        self.callbacks["selection"]()
        try:
            self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()
        return "break"

    def _change_hierarchy(self, direction):
        if direction in ("up", "down") or self.manual_hierarchy:
            self.callbacks["hierarchy"](direction)
            return "break"

    def _detail_bar(self, content):
        detail = ttk.Frame(content, style="Card.TFrame", padding=(14, 6))
        detail.grid(row=2, column=0, sticky="ew")
        detail.columnconfigure(0, weight=1)
        ttk.Separator(detail).grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 5))
        ttk.Label(detail, textvariable=self.selection_var, style="Card.TLabel").grid(row=1, column=0, sticky="w")
        self.detail_label = ttk.Label(detail, textvariable=self.detail_var, style="CardMuted.TLabel", wraplength=550)
        self.detail_label.grid(row=2, column=0, sticky="w", pady=(4, 0))
        detail.bind("<Configure>", lambda e: self.detail_label.configure(wraplength=max(280, e.width - 220)))
        self.choose_button = ttk.Button(detail, text="Eşleşmeyi seç", command=self.callbacks["choose"])
        self.choose_button.grid(row=1, column=1, rowspan=2, padx=(12, 6))
        self.choose_button.grid_remove()
        self.open_file_button = ttk.Button(detail, text="Dosyayı aç", command=self.callbacks["open_file"])
        self.open_file_button.grid(row=1, column=2, rowspan=2, padx=(6, 0))
        self.open_file_button.state(["disabled"])

    def _footer(self):
        area = ttk.Frame(self)
        area.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        area.columnconfigure(0, weight=1)
        row = ttk.Frame(area)
        row.grid(row=0, column=0, sticky="ew")
        row.columnconfigure(0, weight=1)
        ttk.Label(row, textvariable=self.progress_var, style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.cancel_button = ttk.Button(row, text="Durdur", style="Danger.TButton", command=self.callbacks["cancel"])
        self.cancel_button.grid(row=0, column=1, padx=(10, 6))
        self.start_button = ttk.Button(row, text="Listeyi indir", style="Accent.TButton", command=self.callbacks["start"])
        self.start_button.grid(row=0, column=2)
        self.progress = ttk.Progressbar(area, mode="determinate", maximum=1)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(7, 6))
        folder_row = ttk.Frame(area)
        folder_row.grid(row=2, column=0, sticky="ew")
        folder_row.columnconfigure(0, weight=1)
        self.folder_label = ttk.Label(folder_row, textvariable=self.path_var, style="Small.TLabel")
        self.folder_label.grid(row=0, column=0, sticky="w")
        ttk.Button(folder_row, text="Klasörü aç", style="Link.TButton", command=self.callbacks["open_folder"]).grid(row=0, column=1)
        self.cancel_button.state(["disabled"])
        self.start_button.state(["disabled"])

    def _select_all(self, _event):
        self.tree.selection_set(self.tree.get_children())
        return "break"

    def _resize(self, event):
        compact = event.height < 720
        if compact == self.compact:
            return
        self.compact = compact
        if compact:
            self.metrics_area.grid_remove()
        else:
            self.metrics_area.grid()
        self.refresh_compact_summary()

    def refresh_compact_summary(self):
        if self.compact:
            self.header_hint.configure(text=f"{self.total_var.get()} belge  ·  {self.done_var.get()} tamamlanan  ·  {self.waiting_var.get()} işlem bekleyen")
            self.header_hint.grid()
        else:
            self.header_hint.grid_remove()

    def set_busy(self, value):
        self.busy = value
        for widget in (self.number_entry, self.add_button, self.bulk_button, self.import_button,
                       self.menu_button, self.start_button):
            widget.state(["disabled"] if value else ["!disabled"])
        self.cancel_button.state(["!disabled"] if value else ["disabled"])
        self.choose_button.state(["disabled"] if value else ["!disabled"])
        self._refresh_context_actions(len(self.tree.selection()))

    def _refresh_context_actions(self, selected_count):
        enabled = selected_count > 0 and not self.busy
        for index in (0, 1):
            self.context_menu.entryconfigure(index, state="normal" if enabled else "disabled")
        self.context_menu.entryconfigure(2, state="normal" if enabled and selected_count == 1 else "disabled")

    def refresh_actions(self, count, selected_count):
        self.start_button.state(["!disabled"] if count and not self.busy else ["disabled"])
        self._refresh_context_actions(selected_count)
        if count:
            self.empty.place_forget()
        elif not self.search_var.get() and self.filter_var.get() == "Tüm belgeler":
            self.empty.place(relx=0.5, rely=0.57, anchor="center")
        else:
            self.empty.place_forget()
