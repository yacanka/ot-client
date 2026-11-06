"""Tk main-thread controller. Network activity belongs to worker.py."""
from dataclasses import replace
from pathlib import Path
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from otClient import OTConnector, OTError
from .actions import DocumentActions
from .hierarchy import hierarchy_indices
from .queue_model import QueueRow
from .settings import AppSettings, RegistryStore, SettingsError
from .settings_view import SettingsView
from .storage_view import StorageView
from .theme import AMBER, BG, BLUE, MUTED, NAV, NAV_ACTIVE, RED, apply_theme, human_bytes
from .views import DocumentsView, PROBLEMS, STATUS_LABELS, SUCCESS
from .worker import DownloadWorker, JobItem, WorkerEvent, safe_error_message


class Application(DocumentActions, tk.Tk):
    def __init__(self, store=None, *, connector_factory=OTConnector):
        super().__init__()
        self.title("OT Desktop — Belge Merkezi")
        self.minsize(1050, 710)
        width, height = min(1280, self.winfo_screenwidth() - 40), min(880, self.winfo_screenheight() - 70)
        self.geometry(f"{max(width, 1050)}x{max(height, 710)}")
        self.family = apply_theme(self)
        self.store = store if store is not None else RegistryStore()
        self.connector_factory = connector_factory
        self.rows = {}
        self._documents_dirty = False
        self._undo = None
        self._save_after = self._refresh_after = self._poll_after = None
        self._tree_keys = set()
        self._closing = False
        self.busy = False
        self._job_failed = False
        self.active_worker = None
        self.cancel_event = threading.Event()
        self.events = queue.Queue()
        self.settings = AppSettings()
        startup_warning = ""
        try:
            self.settings, documents = self.store.load()
            for number in documents:
                row = QueueRow(number)
                self.rows[row.key] = row
            hierarchy = self.store.load_hierarchy(documents)
            by_number = {row.number: row.key for row in self.rows.values()}
            for row in self.rows.values():
                row.parent_key = by_number.get(hierarchy.get(row.number))
            startup_warning = getattr(self.store, "warning", "")
        except (SettingsError, ValueError, OSError) as exc:
            startup_warning = f"Kayıtlı ayarlar okunamadı: {exc}"
        self._last_saved_settings = replace(self.settings)
        self._rebuild_hierarchy_indices()
        self._build_shell()
        self._build_views()
        self.show_view("documents")
        self.refresh_table()
        self.refresh_settings_summary()
        self.set_notice(startup_warning or "Belge numaralarını ekleyin; ardından Listeyi indir ile başlayın.",
                        "warning" if startup_warning else "info")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Control-f>", self.focus_filter)
        self._poll_after = self.after(80, self.poll_events)

    def _build_shell(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.sidebar = tk.Frame(self, bg=NAV, width=204)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)
        self.sidebar.columnconfigure(0, weight=1)
        self.sidebar.rowconfigure(6, weight=1)
        brand = tk.Frame(self.sidebar, bg=NAV)
        brand.grid(row=0, column=0, sticky="ew", padx=22, pady=(30, 32))
        logo = tk.Canvas(brand, width=38, height=40, bg=NAV, highlightthickness=0)
        logo.pack(side="left", padx=(0, 10))
        logo.create_rectangle(1, 1, 37, 39, fill=BLUE, outline=BLUE)
        logo.create_line(12, 9, 12, 29, 27, 29, fill="white", width=2)
        logo.create_line(17, 12, 28, 12, fill="white", width=2)
        logo.create_line(17, 18, 28, 18, fill="white", width=2)
        tk.Label(brand, text="OT", fg="white", bg=NAV, font=(self.family, 20, "bold")).pack(anchor="w")
        tk.Label(brand, text="BELGE MERKEZİ", fg="#92A5BF", bg=NAV, font=(self.family, 8)).pack(anchor="w")
        tk.Label(self.sidebar, text="ÇALIŞMA ALANI", fg="#8195B1", bg=NAV,
                 font=(self.family, 8, "bold")).grid(row=1, column=0, sticky="w", padx=22, pady=(0, 12))
        self.nav_buttons = {}
        for index, (name, label) in enumerate((("documents", "Belgeler"), ("storage", "Depolama"), ("settings", "Bağlantı")), 2):
            button = tk.Button(self.sidebar, text=label, command=lambda value=name: self.show_view(value),
                               anchor="w", bg=NAV, fg="#CCD8E9", activebackground=NAV_ACTIVE,
                               activeforeground="white", relief="flat", borderwidth=0, padx=16, pady=13,
                               font=(self.family, 10), cursor="hand2", highlightthickness=1,
                               highlightbackground=NAV, highlightcolor="#7B9CE3")
            button.grid(row=index, column=0, sticky="ew", padx=12, pady=3)
            self.nav_buttons[name] = button
        note = tk.Frame(self.sidebar, bg="#182840", padx=14, pady=14)
        note.grid(row=7, column=0, sticky="ew", padx=16, pady=(8, 16))
        self.nav_status = tk.Label(note, text="Kurulum gerekli", bg="#182840", fg="#BBCBE0",
                                   anchor="w", font=(self.family, 9, "bold"))
        self.nav_status.pack(anchor="w")
        tk.Label(note, text="Ayarlar ve belge listesi Windows kullanıcınıza özel olarak saklanır.", bg="#182840",
                 fg="#92A5BF", justify="left", anchor="w", wraplength=140,
                 font=(self.family, 8)).pack(anchor="w", pady=(8, 0))
        tk.Label(self.sidebar, text="OT DESKTOP  /  1.0", fg="#7084A1", bg=NAV,
                 font=(self.family, 8)).grid(row=8, column=0, sticky="w", padx=22, pady=(0, 22))
        main = ttk.Frame(self, padding=(24, 22, 24, 10))
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=1)
        self.content = ttk.Frame(main)
        self.content.grid(row=0, column=0, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)
        self.notice = tk.Label(main, text="", anchor="w", justify="left", bg=BG,
                               fg=MUTED, font=(self.family, 9), pady=9, wraplength=920)
        self.notice.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        main.bind("<Configure>", lambda e: self.notice.configure(wraplength=max(300, e.width - 60)))

    def _build_views(self):
        callbacks = {
            "add": self.add_entry, "bulk": self.bulk_add, "import": self.import_documents,
            "remove": self.remove_selected, "undo": self.undo_remove, "clear": self.clear_documents,
            "export": self.export_documents, "report": self.export_report, "retry": self.retry_failed,
            "filter": self.schedule_refresh, "selection": self.on_selection, "copy": self.copy_selected,
            "start": self.start_all, "selected": self.start_selected, "cancel": self.cancel_job,
            "settings": lambda: self.show_view("settings"), "choose": self.choose_candidate,
            "open_file": self.open_selected_file, "open_folder": self.open_output_folder,
            "hierarchy": self.change_hierarchy,
        }
        self.documents_view = DocumentsView(self.content, callbacks)
        self.settings_view = SettingsView(self.content, self.settings, self.save_settings, self.test_connection)
        self.storage_view = StorageView(self.content, self.settings, self.save_settings)
        self.storage_view.manual_folder_hierarchy_enabled_var.trace_add("write", self._hierarchy_mode_changed)
        self.documents_view.set_manual_hierarchy(self.settings.manual_folder_hierarchy_enabled)
        self._views = {"documents": self.documents_view, "storage": self.storage_view, "settings": self.settings_view}
        for view in self._views.values():
            view.grid(row=0, column=0, sticky="nsew")

    def show_view(self, name):
        self.current_view = name
        self._views[name].tkraise()
        for key, button in self.nav_buttons.items():
            button.configure(bg=NAV_ACTIVE if key == name else NAV, fg="white" if key == name else "#CCD8E9",
                             font=(self.family, 10, "bold" if key == name else "normal"))

    def set_notice(self, text, kind="info"):
        self.notice.configure(text=text, fg=RED if kind == "error" else AMBER if kind == "warning" else MUTED)

    def focus_filter(self, _event=None):
        self.show_view("documents")
        self.documents_view.search_entry.focus_set()
        self.documents_view.search_entry.selection_range(0, "end")
        return "break"

    def schedule_refresh(self):
        if self._refresh_after:
            self.after_cancel(self._refresh_after)
        self._refresh_after = self.after(120, self.refresh_table)

    def _is_visible(self, row):
        view = self.documents_view
        query = view.search_var.get().strip().casefold()
        text = f"{row.number} {row.document.title if row.document else ''} {row.message}".casefold()
        if query and query not in text:
            return False
        selected_filter = view.filter_var.get()
        return (selected_filter == "Tüm belgeler" or
                selected_filter == "Bekleyen" and row.status in {"pending", "searching", "downloading"} or
                selected_filter == "Tamamlanan" and row.status in SUCCESS or
                selected_filter == "Sorunlu" and row.status in PROBLEMS or
                selected_filter == "Seçim gerekli" and (row.status == "ambiguous" or bool(row.candidates)))

    def _row_values(self, row):
        title = row.document.title or row.document.name if row.document else "İşlem sırasında doldurulacak"
        revision = row.document.revision if row.document else "—"
        return row.number, title, revision, STATUS_LABELS.get(row.status, row.status), human_bytes(row.size)

    def _rebuild_hierarchy_indices(self):
        self._index_values = hierarchy_indices(self._hierarchy_entries())

    def _table_values(self, row):
        index = self._index_values.get(row.key, "")
        return ("  " * index.count(".") + index, *self._row_values(row))

    def _hierarchy_mode_changed(self, *_):
        self.documents_view.set_manual_hierarchy(self.storage_view.manual_folder_hierarchy_enabled_var.get())
        self.refresh_table()

    def refresh_table(self):
        if self._refresh_after:
            self.after_cancel(self._refresh_after)
        self._refresh_after = None
        view = self.documents_view
        tree = view.tree
        old_selection = set(tree.selection())
        old_focus = tree.focus()
        for key in self._tree_keys - self.rows.keys():
            tree.delete(key)
        self._tree_keys.intersection_update(self.rows)
        visible = []
        for key, row in self.rows.items():
            if key not in self._tree_keys:
                tree.insert("", "end", iid=key, values=self._table_values(row), tags=(row.status,))
                self._tree_keys.add(key)
            else:
                tree.item(key, values=self._table_values(row), tags=(row.status,))
            if self._is_visible(row):
                visible.append(key)
                tree.move(key, "", "end")
            else:
                tree.detach(key)
        tree.selection_set([key for key in visible if key in old_selection])
        if old_focus in visible:
            tree.focus(old_focus)
        done = sum(row.status in SUCCESS for row in self.rows.values())
        view.total_var.set(str(len(self.rows)))
        view.done_var.set(str(done))
        view.waiting_var.set(str(len(self.rows) - done))
        view.refresh_compact_summary()
        view.refresh_actions(len(self.rows), len(tree.selection()))
        self.on_selection()

    def on_selection(self):
        view = self.documents_view
        selected = self.selected_rows()
        visible = len(view.tree.get_children())
        view.selection_var.set(f"{visible} / {len(self.rows)} belge" + (f"  ·  {len(selected)} seçili" if selected else ""))
        view.refresh_actions(len(self.rows), len(selected))
        view.choose_button.grid_remove()
        view.open_file_button.state(["disabled"])
        if len(selected) == 1:
            row = selected[0]
            view.detail_var.set(row.message + (f"  ·  {row.path}" if row.path else ""))
            if row.candidates:
                view.choose_button.grid()
            if row.path:
                view.open_file_button.state(["!disabled"])
        elif selected:
            view.detail_var.set("Seçili belgeleri indirebilir, kaldırabilir veya Ctrl+C ile kopyalayabilirsiniz.")
        else:
            view.detail_var.set("Ctrl / Shift ile çoklu seçim yapın. Ctrl+A tüm görünen belgeleri seçer.")
        if view.manual_hierarchy:
            hint = ("Hiyerarşiyi düzenlemek için filtreleri temizleyin." if
                    view.search_var.get().strip() or view.filter_var.get() != "Tüm belgeler" else
                    "← Üst seviye / → Alt seviye / Ctrl+Z Geri al")
            view.detail_var.set((view.detail_var.get() + "  ·  " if selected else "Ctrl / Shift: çoklu seçim.  ") + hint)

    def schedule_document_save(self):
        self._rebuild_hierarchy_indices()
        self._documents_dirty = True
        if self._save_after:
            self.after_cancel(self._save_after)
        self._save_after = self.after(450, self.flush_document_save)

    def flush_document_save(self):
        if self._save_after:
            self.after_cancel(self._save_after)
            self._save_after = None
        if not self._documents_dirty:
            return True
        try:
            self.store.save_documents(self.numbers(), hierarchy=self._hierarchy_numbers())
            self._documents_dirty = False
            return True
        except (SettingsError, ValueError, OSError) as exc:
            self.set_notice(f"Belge listesi kaydedilemedi: {exc}", "error")
            return False

    def read_settings(self, require_connection=False):
        try:
            settings = self.settings_view.read_settings(self.settings)
            settings = self.storage_view.read_settings(settings)
            settings.validate(require_connection=require_connection)
        except ValueError as error:
            self._show_settings_error(error)
            raise
        return settings

    def _show_settings_error(self, error):
        field = getattr(error, "field", "base_url")
        storage_fields = {"output_dir", "filename_format", "document_subfolder_enabled",
                          "manual_folder_hierarchy_enabled",
                          "document_subfolder_format", "document_subfolder_match",
                          "download_related_forms", "download_related_attachments"}
        name = "storage" if field in storage_fields else "settings"
        self.show_view(name)
        view = self._views[name]
        view.set_status(str(error), False)
        view.focus_field(field)

    def _mark_settings_saved(self):
        self.settings_view.mark_saved()
        self.storage_view.mark_saved()

    def _persist_settings(self, settings):
        documents = self.numbers() if self._documents_dirty else None
        hierarchy = self._hierarchy_numbers() if self._documents_dirty else None
        self.store.save(settings, documents, hierarchy=hierarchy)

    def save_settings(self):
        if self.busy:
            return False
        try:
            settings = self.read_settings()
            self._persist_settings(settings)
        except (SettingsError, ValueError, OSError) as exc:
            view = self.storage_view if self.current_view == "storage" else self.settings_view
            view.set_status(str(exc), False)
            self.set_notice(f"Ayarlar kaydedilemedi: {exc}", "error")
            return False
        self.settings = settings
        self._last_saved_settings = replace(settings)
        self._documents_dirty = False
        self._mark_settings_saved()
        self.refresh_settings_summary()
        warning = getattr(self.store, "warning", "")
        self.set_notice(warning or "Ayarlar kaydedildi.", "warning" if warning else "info")
        return True

    def refresh_settings_summary(self):
        ready = bool(self.settings.base_url and self.settings.username and self.settings.password)
        self.documents_view.connection_button.configure(text="Bağlantı ayarları" if ready else "Bağlantıyı ayarla")
        self.nav_status.configure(text="Ayarlar hazır" if ready else "Kurulum gerekli", fg="#BBCBE0")
        path = self.settings.output_dir
        self.documents_view.path_var.set(f"Hedef: {path}" if len(path) < 85 else f"Hedef: …{path[-78:]}")

    def set_busy(self, value):
        self.busy = value
        self.documents_view.set_busy(value)
        self.settings_view.set_busy(value)
        self.storage_view.set_busy(value)
        self.documents_view.refresh_actions(len(self.rows), len(self.selected_rows()))

    def _job_settings(self):
        try:
            settings = self.read_settings(require_connection=True)
        except ValueError as exc:
            self.set_notice(str(exc), "warning")
            return None
        try:
            self._persist_settings(settings)
            self._last_saved_settings = replace(settings)
            self._documents_dirty = False
            self._mark_settings_saved()
        except (SettingsError, ValueError, OSError) as exc:
            self.set_notice(f"Ayarlar kaydedilemedi; bu işlemde girdiğiniz değerler kullanılacak. {exc}", "warning")
        self.settings = settings
        self.refresh_settings_summary()
        return replace(settings)

    def start_all(self):
        self.start_rows(list(self.rows.values()))

    def start_selected(self):
        self.start_rows(self.selected_rows())

    def retry_failed(self):
        self.start_rows([row for row in self.rows.values() if row.status in PROBLEMS and row.status != "ambiguous"])

    def start_rows(self, rows):
        if self.busy:
            return
        if not rows:
            self.set_notice("İşlem yapılacak belge yok. Belge ekleyin veya listeden seçim yapın.", "warning")
            return
        settings = self._job_settings()
        if settings is None:
            return
        self.cancel_event = threading.Event()
        self._job_failed = False
        requested = {row.key for row in rows}
        rows = [row for row in self.rows.values() if row.key in requested]
        hierarchy = tuple(
            JobItem(row.key, row.number, row.document if row.chosen else None, row.parent_key)
            for row in self.rows.values()
        ) if settings.manual_folder_hierarchy_enabled else None
        items = ([item for item in hierarchy if item.key in requested] if hierarchy is not None else
                 [JobItem(row.key, row.number, row.document if row.chosen else None) for row in rows])
        for row in rows:
            row.status, row.message, row.size = "pending", "İşlem sırasına alındı.", None
            row.candidates = ()
        self.documents_view.progress.configure(maximum=len(items), value=0)
        self.documents_view.progress_var.set(f"0 / {len(items)} belge  ·  Bağlanılıyor…")
        self.set_busy(True)
        self.refresh_table()
        self.active_worker = DownloadWorker(settings, items, self.events, self.cancel_event,
                                             connector_factory=self.connector_factory, hierarchy=hierarchy)
        self.active_worker.start()

    def test_connection(self):
        if self.busy:
            return
        settings = self._job_settings()
        if settings is None:
            return
        self.cancel_event = threading.Event()
        self._job_failed = False
        self.set_busy(True)
        self.settings_view.set_connection_status("Oturum ve belge erişimi kontrol ediliyor…")
        self.documents_view.progress_var.set("Bağlantı kontrol ediliyor…")
        self.active_worker = threading.Thread(target=self._test_connection_worker, args=(settings,), daemon=True)
        self.active_worker.start()

    def _test_connection_worker(self, settings):
        connector = None
        try:
            if self.cancel_event.is_set():
                return
            connector = self.connector_factory(settings.base_url, settings.username, settings.password,
                                                timeout=settings.timeout, verify=settings.tls_verify,
                                                folder_id=settings.folder_id)
            if connector.test_connection() is not True:
                raise OTError("Oturum ve belge erişimi doğrulanamadı.")
            if not self.cancel_event.is_set():
                self.events.put(WorkerEvent("connection_result", payload={"success": True, "message": "Bağlantı başarılı. Belge arama servisine erişim doğrulandı."}))
        except Exception as exc:
            text = safe_error_message(exc, settings.password)
            self.events.put(WorkerEvent("connection_result", payload={"success": False, "message": text}))
        finally:
            if connector is not None:
                try:
                    connector.close()
                except Exception:
                    pass
            self.events.put(WorkerEvent("finished", payload={"test": True, "cancelled": self.cancel_event.is_set(), "processed": 0, "total": 0}))

    def cancel_job(self):
        if self.busy:
            self.cancel_event.set()
            self.documents_view.cancel_button.state(["disabled"])
            self.documents_view.progress_var.set("Durduruluyor…")
            self.set_notice("Durdurma istendi. Devam eden isteğin yanıtı veya zaman aşımı bekleniyor.")

    def poll_events(self):
        self._poll_after = None
        handled = 0
        while handled < 180:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            handled += 1
            self._handle_event(event)
        if self._closing and not self.busy:
            if self.finish_close():
                return
        self._poll_after = self.after(60 if handled else 100, self.poll_events)

    def _handle_event(self, event):
        data = event.payload or {}
        view = self.documents_view
        if event.kind == "session":
            if data.get("state") == "connected":
                self.nav_status.configure(text="Bağlantı doğrulandı", fg="#89D5BD")
        elif event.kind == "status" and event.key in self.rows:
            row = self.rows[event.key]
            for name in ("status", "message", "document", "candidates", "path"):
                if name in data:
                    setattr(row, name, data[name])
            self.schedule_refresh()
        elif event.kind == "hierarchy_resolution" and event.key in self.rows:
            row = self.rows[event.key]
            for name in ("document", "candidates", "message"):
                if name in data:
                    setattr(row, name, data[name])
            self.schedule_refresh()
        elif event.kind == "progress" and event.key in self.rows:
            row = self.rows[event.key]
            row.size = data.get("downloaded")
            total = f" / {human_bytes(data['total'])}" if data.get("total") else ""
            view.progress_var.set(f"{row.number}  ·  {human_bytes(row.size)}{total}")
            if event.key in self._tree_keys:
                view.tree.item(event.key, values=self._table_values(row), tags=(row.status,))
        elif event.kind == "advance":
            view.progress.configure(value=data.get("done", 0))
            view.progress_var.set(f"{data.get('done', 0)} / {data.get('total', 0)} belge işlendi")
        elif event.kind == "fatal":
            self._job_failed = True
            self.nav_status.configure(text="Bağlantı sorunu", fg="#F0ACAA")
            self.set_notice(data.get("message", "İşlem başlatılamadı."), "error")
            self.settings_view.set_connection_status(data.get("message", "Bağlantı başarısız."), False)
        elif event.kind == "connection_result":
            success = data.get("success", False)
            self._job_failed = not success
            self.settings_view.set_connection_status(data.get("message", ""), success)
            self.nav_status.configure(text="Bağlantı doğrulandı" if success else "Bağlantı sorunu",
                                      fg="#89D5BD" if success else "#F0ACAA")
            self.set_notice(data.get("message", ""), "info" if success else "error")
        elif event.kind == "finished":
            self.active_worker = None
            self.set_busy(False)
            self.refresh_table()
            if data.get("test"):
                view.progress_var.set("Bağlantı kontrolü durduruldu" if data.get("cancelled") else
                                      "Bağlantı kontrolü başarısız" if self._job_failed else "Bağlantı kontrolü tamamlandı")
            else:
                prefix = "Durduruldu" if data.get("cancelled") else "İşlem durdu" if self._job_failed else "İşlem tamamlandı"
                view.progress_var.set(f"{prefix}  ·  {data.get('processed', 0)} / {data.get('total', 0)} belge işlendi")

    def open_selected_file(self):
        selected = self.selected_rows()
        if len(selected) == 1:
            if selected[0].candidates and not self.busy:
                self.choose_candidate()
            elif selected[0].path:
                self._open_path(Path(selected[0].path))

    def open_output_folder(self):
        directory = self.storage_view.output_dir_var.get().strip() or self.settings.output_dir
        try:
            path = Path(directory).expanduser()
        except (ValueError, RuntimeError):
            self.set_notice("İndirme klasörü yolu okunamadı.", "warning")
            return
        if not path.exists():
            self.set_notice("İndirme klasörü ilk indirmede oluşturulur.")
            return
        self._open_path(path)

    def _open_path(self, path):
        if not path.exists():
            self.set_notice("Dosya veya klasör bu konumda artık bulunmuyor.", "warning")
        elif os.name == "nt":
            try:
                os.startfile(str(path.resolve()))
            except OSError as exc:
                messagebox.showerror("Açılamadı", str(exc), parent=self)
        else:
            self.set_notice(f"Konum: {path.resolve()}")

    def on_close(self):
        if self.busy:
            if not messagebox.askyesno("Devam eden işlem", "İşlemi durdurup uygulamayı kapatmak istiyor musunuz?\n\nDevam eden ağ isteğinin bitmesi beklenecek.", parent=self):
                return
            self._closing = True
            self.cancel_job()
            return
        self.finish_close()

    def finish_close(self):
        try:
            draft = self.read_settings()
            if draft != self._last_saved_settings:
                self._persist_settings(draft)
                self._last_saved_settings = replace(draft)
                self._documents_dirty = False
        except (SettingsError, ValueError, OSError) as exc:
            self.set_notice(f"Son ayarlar kaydedilemedi: {exc}", "error")
            if not messagebox.askyesno("Ayarlar kaydedilemedi", f"{exc}\n\nSon ayar değişikliklerini kaydetmeden kapatılsın mı?", parent=self):
                self._closing = False
                return False
        if not self.flush_document_save():
            if not messagebox.askyesno("Liste kaydedilemedi", "Son belge listesi kaydedilemedi. Yine de kapatılsın mı?", parent=self):
                self._closing = False
                return False
        self.destroy()
        return True

    def destroy(self):
        for name in ("_save_after", "_refresh_after", "_poll_after"):
            timer = getattr(self, name, None)
            if timer:
                try:
                    self.after_cancel(timer)
                except tk.TclError:
                    pass
                setattr(self, name, None)
        super().destroy()


def main():
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    Application().mainloop()


if __name__ == "__main__":
    main()
