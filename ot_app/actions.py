"""User-initiated document list actions, kept separate from the Tk shell."""
from itertools import chain
from pathlib import Path
from tkinter import filedialog, messagebox

from .dialogs import BulkInputDialog, CandidateDialog
from .documents import merge_document_numbers, parse_document_text, read_document_file, write_csv_report, write_document_file
from .hierarchy import HierarchyEntry, HierarchyError, move_hierarchy, remove_hierarchy, validate_hierarchy
from .queue_model import QueueRow
from .views import STATUS_LABELS


class DocumentActions:
    def _hierarchy_entries(self):
        return tuple(HierarchyEntry(row.key, row.parent_key) for row in self.rows.values())

    def _hierarchy_numbers(self):
        return {
            row.number: self.rows[row.parent_key].number if row.parent_key is not None else None
            for row in self.rows.values()
        }

    def _remember_structure(self):
        # Row objects retain live results; the immutable links preserve old ancestry.
        self._undo = (tuple(self.rows.values()), self._hierarchy_entries())

    def _apply_hierarchy(self, entries):
        rows = {entry.key: self.rows[entry.key] for entry in entries}
        for entry in entries:
            rows[entry.key].parent_key = entry.parent_key
        self.rows = rows

    def change_hierarchy(self, direction):
        view = self.documents_view
        if self.busy or not view.manual_hierarchy:
            return "break"
        if view.search_var.get().strip() or view.filter_var.get() != "Tüm belgeler":
            self.set_notice("Hiyerarşiyi düzenlemek için arama ve durum filtrelerini temizleyin.", "warning")
            return "break"
        entries = self._hierarchy_entries()
        try:
            changed = move_hierarchy(entries, view.tree.selection(), direction)
        except HierarchyError as error:
            self.set_notice(str(error), "warning")
            return "break"
        if changed != entries:
            self._remember_structure()
            self._apply_hierarchy(changed)
            self.schedule_document_save()
            self.refresh_table()
            focus = view.tree.focus()
            if focus:
                view.tree.see(focus)
            self.set_notice("Klasör hiyerarşisi güncellendi. Ctrl+Z ile geri alabilirsiniz.")
        return "break"

    def numbers(self):
        return [row.number for row in self.rows.values()]

    def selected_rows(self):
        return [self.rows[key] for key in self.documents_view.tree.selection() if key in self.rows]

    def add_numbers(self, numbers):
        if self.busy:
            return
        existing = self.numbers()
        merged = merge_document_numbers(existing, numbers)
        new_numbers = merged[len(existing):]
        for number in new_numbers:
            row = QueueRow(number)
            self.rows[row.key] = row
        if new_numbers:
            self.schedule_document_save()
        self.refresh_table()
        self.set_notice(f"{len(new_numbers)} belge eklendi. Listede {len(self.rows)} belge var.")
        return len(new_numbers)

    def add_entry(self):
        if self.busy:
            return
        raw = self.documents_view.input_var.get()
        try:
            numbers = parse_document_text(raw)
            if not numbers:
                self.set_notice("Önce bir belge numarası girin.", "warning")
                self.documents_view.number_entry.focus_set()
                return
            self.add_numbers(numbers)
        except ValueError as exc:
            self.set_notice(str(exc), "error")
            return
        self.documents_view.input_var.set("")
        self.documents_view.number_entry.focus_set()

    def bulk_add(self):
        if not self.busy:
            dialog = BulkInputDialog(self)
            if dialog.result is not None:
                try:
                    self.add_numbers(dialog.result)
                except ValueError as exc:
                    self.set_notice(str(exc), "error")

    def import_documents(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self, title="Belge numaralarını içe aktar",
                                          filetypes=[("Belge listeleri", "*.txt *.csv *.tsv *.json"), ("Tüm dosyalar", "*.*")])
        if not path:
            return
        try:
            numbers = read_document_file(path)
            self.add_numbers(numbers)
        except (OSError, ValueError, UnicodeError) as exc:
            messagebox.showerror("Liste okunamadı", str(exc), parent=self)

    def remove_selected(self):
        if self.busy:
            return
        keys = self.documents_view.tree.selection()
        if not keys:
            return
        changed = remove_hierarchy(self._hierarchy_entries(), keys)
        self._remember_structure()
        self._apply_hierarchy(changed)
        self.schedule_document_save()
        self.refresh_table()
        self.set_notice(f"{len(keys)} belge kaldırıldı. Liste işlemleri → Geri al veya Ctrl+Z ile geri getirebilirsiniz.")

    def clear_documents(self):
        if self.busy or not self.rows:
            return
        if not messagebox.askyesno("Belge listesini temizle", f"Listedeki {len(self.rows)} belge numarası kaldırılsın mı?\n\nİndirilen dosyalar silinmez.", parent=self):
            return
        self._remember_structure()
        self.rows.clear()
        self.schedule_document_save()
        self.refresh_table()
        self.set_notice("Belge listesi temizlendi. Son liste işlemini geri alabilirsiniz.")

    def undo_remove(self):
        if self.busy or not self._undo:
            return
        current = dict(self.rows)
        by_number = {row.number: row for row in current.values()}
        old_rows, old_entries = self._undo
        old_by_key = {row.key: row for row in old_rows}
        restored = {}
        seen = set()
        for old in old_rows:
            row = by_number.get(old.number, old)
            if row.number not in seen:
                restored[row.key] = row
                seen.add(row.number)
        for key, row in current.items():
            if row.number not in seen:
                restored[key] = row
                seen.add(row.number)
        restored_by_number = {row.number: row.key for row in restored.values()}
        parents = {}
        for entry in old_entries:
            number = old_by_key[entry.key].number
            parent_number = old_by_key[entry.parent_key].number if entry.parent_key is not None else None
            parents[restored_by_number[number]] = restored_by_number.get(parent_number)
        entries = tuple(HierarchyEntry(key, parents.get(key)) for key in restored)
        try:
            merge_document_numbers([], [row.number for row in restored.values()])
            validate_hierarchy(entries)
        except ValueError as exc:
            self.set_notice(f"Geri alınamadı: {exc} Önce listede yer açın.", "warning")
            return
        self.rows = restored
        self._apply_hierarchy(entries)
        self._undo = None
        self.schedule_document_save()
        self.refresh_table()
        self.set_notice("Son liste işlemi geri alındı.")

    def copy_selected(self):
        rows = self.selected_rows()
        if rows:
            self.clipboard_clear()
            self.clipboard_append("\n".join(row.number for row in rows))
            self.set_notice(f"{len(rows)} belge numarası kopyalandı.")
        return "break"

    def export_documents(self):
        rows = self.selected_rows() or list(self.rows.values())
        if not rows:
            self.set_notice("Dışa aktarmak için önce belge ekleyin.", "warning")
            return
        path = filedialog.asksaveasfilename(parent=self, title=f"{len(rows)} belge numarasını dışa aktar",
                                            initialfile="OT_belge_listesi.txt", defaultextension=".txt",
                                            filetypes=[("Metin listesi", "*.txt"), ("JSON metin dizisi", "*.json"), ("CSV (Excel)", "*.csv")])
        if path:
            try:
                write_document_file(path, [row.number for row in rows])
                self.set_notice(f"{len(rows)} belge numarası dışa aktarıldı: {Path(path).name}")
            except (OSError, ValueError) as exc:
                messagebox.showerror("Liste kaydedilemedi", str(exc), parent=self)

    def export_report(self):
        rows = self.selected_rows() or list(self.rows.values())
        if not rows:
            self.set_notice("Raporlamak için önce belge ekleyin.", "warning")
            return
        path = filedialog.asksaveasfilename(parent=self, title="İşlem sonuçlarını dışa aktar",
                                            initialfile="OT_islem_sonuclari.csv", defaultextension=".csv",
                                            filetypes=[("CSV (Excel)", "*.csv")])
        if not path:
            return
        try:
            header = ["Belge numarası", "Belge adı", "Durum", "Açıklama", "Dosya"]
            values = (
                [row.number, row.document.title if row.document else "",
                 STATUS_LABELS.get(row.status, row.status), row.message, row.path]
                for row in rows
            )
            write_csv_report(path, chain([header], values))
            self.set_notice(f"İşlem raporu kaydedildi: {Path(path).name}")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Rapor kaydedilemedi", str(exc), parent=self)

    def choose_candidate(self):
        rows = self.selected_rows()
        if self.busy or len(rows) != 1 or not rows[0].candidates:
            return
        row = rows[0]
        dialog = CandidateDialog(self, row.number, list(row.candidates))
        if dialog.result is not None:
            row.document = dialog.result
            row.chosen = True
            row.status = "pending"
            row.message = "Eşleşme seçildi. Seçileni indir ile devam edin."
            row.candidates = ()
            self.refresh_table()
            self.documents_view.tree.selection_set(row.key)
            self.set_notice(f"{row.number} için eşleşme seçildi. İndirmek için Seçileni indir düğmesini kullanın.")
