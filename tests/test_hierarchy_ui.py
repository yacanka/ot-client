"""Manual hierarchy interactions against real Tk and the session store."""
import os
import sys
import unittest
from unittest.mock import patch

from otClient import Document
from ot_app.app import Application
from ot_app.settings import RegistryStore, SettingsError
from ot_app.worker import WorkerEvent


@unittest.skipUnless(os.name == "nt" or sys.platform == "darwin" or os.environ.get("DISPLAY"),
                     "A graphical display is required")
class HierarchyUITests(unittest.TestCase):
    def setUp(self):
        self.store = RegistryStore(platform="darwin")
        self.app = Application(store=self.store)
        self.app.update()

    def tearDown(self):
        self.app.destroy()

    def enable(self, numbers=("A", "B", "C")):
        self.app.add_numbers(numbers)
        self.app.storage_view.manual_folder_hierarchy_enabled_button.invoke()
        self.app.update()

    def select(self, *numbers):
        keys = [row.key for row in self.app.rows.values() if row.number in numbers]
        self.app.documents_view.tree.selection_set(keys)
        self.app.documents_view.tree.focus(keys[0])
        self.app.update()

    def indices(self):
        tree = self.app.documents_view.tree
        return [tree.set(key, "index").strip() for key in tree.get_children()]

    def test_mode_toggles_share_format_and_remain_independent(self):
        view = self.app.storage_view
        self.assertNotIn("index", self.app.documents_view.tree["displaycolumns"])
        view.manual_folder_hierarchy_enabled_button.invoke()
        self.assertIn("index", self.app.documents_view.tree["displaycolumns"])
        self.assertNotIn("disabled", view.document_subfolder_enabled_button.state())
        self.assertNotIn("disabled", view.document_subfolder_format_entry.state())
        view.document_subfolder_format_var.set("{numara} - {ad}")
        view.document_subfolder_match_var.set("contains")
        self.app.set_busy(True)
        self.assertIn("disabled", view.manual_folder_hierarchy_enabled_button.state())
        self.app.set_busy(False)
        self.assertNotIn("disabled", view.document_subfolder_enabled_button.state())
        view.document_subfolder_enabled_button.invoke()
        self.assertNotIn("disabled", view.manual_folder_hierarchy_enabled_button.state())
        self.assertTrue(view.read_settings().document_subfolder_enabled)
        self.assertTrue(view.read_settings().manual_folder_hierarchy_enabled)
        self.assertEqual(view.read_settings().document_subfolder_format, "{numara} - {ad}")
        self.assertEqual(view.read_settings().document_subfolder_match, "contains")

    def test_arrows_follow_requested_indices_and_keep_selection(self):
        self.enable()
        self.assertEqual(self.indices(), ["1", "2", "3"])
        self.select("B")
        self.app.change_hierarchy("indent")
        self.assertEqual(self.indices(), ["1", "1.1", "2"])
        self.select("C")
        self.app.change_hierarchy("indent")
        self.assertEqual(self.indices(), ["1", "1.1", "1.2"])
        self.app.change_hierarchy("indent")
        self.assertEqual(self.indices(), ["1", "1.1", "1.1.1"])
        self.assertEqual([row.number for row in self.app.selected_rows()], ["C"])
        self.app.change_hierarchy("outdent")
        self.assertEqual(self.indices(), ["1", "1.1", "1.2"])

    def test_keyboard_bindings_move_only_when_table_has_focus(self):
        self.enable()
        self.select("B")
        tree = self.app.documents_view.tree
        tree.focus_force()
        self.app.update()
        tree.event_generate("<Right>")
        self.app.update()
        self.assertEqual(self.indices(), ["1", "1.1", "2"])
        tree.event_generate("<Left>")
        self.app.update()
        self.assertEqual(self.indices(), ["1", "2", "3"])

    def test_multiselect_moves_block_and_invalid_selection_is_atomic(self):
        self.enable(("A", "B", "C", "D"))
        self.select("B", "C")
        self.app.change_hierarchy("indent")
        self.assertEqual(self.indices(), ["1", "1.1", "1.2", "2"])
        self.select("B", "D")
        self.app.change_hierarchy("outdent")
        self.assertEqual(self.indices(), ["1", "1.1", "1.2", "2"])
        self.app.undo_remove()
        self.assertEqual(self.indices(), ["1", "2", "3", "4"])

    def test_remove_promotes_children_and_undo_remaps_readded_parent(self):
        self.enable()
        self.select("B", "C")
        self.app.change_hierarchy("indent")
        self.select("A")
        self.app.remove_selected()
        self.assertEqual(self.app.numbers(), ["B", "C"])
        self.assertEqual(self.indices(), ["1", "2"])
        self.app.add_numbers(["A", "D"])
        parent = next(row for row in self.app.rows.values() if row.number == "A")
        parent.status, parent.path = "downloaded", "/old/A.pdf"
        self.app.undo_remove()
        self.assertEqual(self.app.numbers(), ["A", "B", "C", "D"])
        self.assertEqual(self.indices(), ["1", "1.1", "1.2", "2"])
        self.assertIs(next(iter(self.app.rows.values())), parent)
        self.assertEqual(parent.path, "/old/A.pdf")

    def test_structure_survives_modes_saves_and_restart(self):
        self.enable()
        self.select("B")
        self.app.change_hierarchy("indent")
        self.app.storage_view.manual_folder_hierarchy_enabled_button.invoke()
        self.assertTrue(self.app.save_settings())
        self.app.destroy()
        self.app = Application(store=self.store)
        self.assertNotIn("index", self.app.documents_view.tree["displaycolumns"])
        self.app.storage_view.manual_folder_hierarchy_enabled_button.invoke()
        self.assertEqual(self.indices(), ["1", "1.1", "2"])

    def test_filter_and_busy_guard_keep_global_indices(self):
        self.enable()
        self.select("B")
        self.app.change_hierarchy("indent")
        self.app.documents_view.search_var.set("B")
        self.app.refresh_table()
        self.select("B")
        self.assertEqual(self.indices(), ["1.1"])
        self.app.change_hierarchy("outdent")
        self.assertEqual(self.indices(), ["1.1"])
        self.app.documents_view.search_var.set("")
        self.app.refresh_table()
        self.app.set_busy(True)
        self.app.change_hierarchy("outdent")
        self.assertEqual(self.indices(), ["1", "1.1", "2"])

    def test_progress_does_not_rebuild_indices_or_hide_index(self):
        self.enable()
        self.select("B")
        self.app.change_hierarchy("indent")
        key = self.app.selected_rows()[0].key
        with patch("ot_app.app.hierarchy_indices", side_effect=AssertionError("Unexpected rebuild")):
            self.app._handle_event(WorkerEvent("progress", key, {"downloaded": 1024, "total": 2048}))
            self.app.refresh_table()
        self.assertEqual(self.indices(), ["1", "1.1", "2"])
        self.assertEqual(self.app.documents_view.tree.set(key, "size"), "1.0 KB")

    def test_ancestor_resolution_preserves_download_history_and_enables_choice(self):
        self.enable()
        row = next(iter(self.app.rows.values()))
        row.status, row.path, row.size = "downloaded", "/old/A.pdf", 12
        candidate = Document("candidate", "A", "Title", "")
        self.app._handle_event(WorkerEvent("hierarchy_resolution", row.key, {
            "candidates": (candidate,), "message": "Üst belge eşleşmesini seçin.",
        }))
        self.select("A")
        self.assertEqual((row.status, row.path, row.size), ("downloaded", "/old/A.pdf", 12))
        self.assertEqual(row.candidates, (candidate,))
        self.assertFalse(row.chosen)
        self.assertTrue(self.app.documents_view.choose_button.winfo_ismapped())

    def test_choice_filter_shows_ancestor_until_resolution_without_changing_history(self):
        self.enable()
        self.select("B")
        self.app.change_hierarchy("indent")
        ancestor, ambiguous = list(self.app.rows.values())[:2]
        ancestor.status, ancestor.path, ancestor.size = "downloaded", "/old/A.pdf", 12
        ambiguous.status = "ambiguous"
        candidate = Document("candidate", "A", "Title", "")
        view = self.app.documents_view
        view.filter_var.set("Seçim gerekli")
        self.app._handle_event(WorkerEvent("hierarchy_resolution", ancestor.key, {
            "candidates": (candidate,), "message": "Üst belge eşleşmesini seçin.",
        }))
        self.app.refresh_table()
        self.assertEqual(view.tree.get_children(), (ancestor.key, ambiguous.key))
        self.select("A")
        self.assertTrue(view.choose_button.winfo_ismapped())
        self.assertEqual((ancestor.status, ancestor.path, ancestor.size),
                         ("downloaded", "/old/A.pdf", 12))

        self.app._handle_event(WorkerEvent("hierarchy_resolution", ancestor.key, {
            "document": candidate, "candidates": (), "message": "Üst belge eşleşmesi çözüldü.",
        }))
        self.app.refresh_table()
        self.assertEqual(view.tree.get_children(), (ambiguous.key,))
        self.assertFalse(view.choose_button.winfo_ismapped())
        self.assertEqual((ancestor.status, ancestor.path, ancestor.size),
                         ("downloaded", "/old/A.pdf", 12))

    def test_selected_job_captures_full_hierarchy_and_only_explicit_choices(self):
        self.enable()
        self.select("B")
        self.app.change_hierarchy("indent")
        self.app.settings_view.base_url_var.set("https://example.invalid")
        self.app.settings_view.username_var.set("test-user")
        self.app.settings_view.password_var.set("synthetic-password")
        parent = next(iter(self.app.rows.values()))
        parent.document = Document("old", "A", "Old title", "")
        with patch("ot_app.app.DownloadWorker") as worker:
            self.app.start_selected()
        args, kwargs = worker.call_args
        self.assertEqual([item.number for item in args[1]], ["B"])
        self.assertEqual([item.number for item in kwargs["hierarchy"]], ["A", "B", "C"])
        self.assertIsNone(kwargs["hierarchy"][0].document)
        self.assertEqual(kwargs["hierarchy"][1].parent_key, parent.key)

    def test_failed_structure_save_remains_dirty_and_retry_saves_tree(self):
        self.enable()
        self.select("B")
        self.app.change_hierarchy("indent")
        with patch.object(self.store, "save_documents", side_effect=SettingsError("Synthetic failure")):
            self.assertFalse(self.app.flush_document_save())
        self.assertTrue(self.app._documents_dirty)
        self.assertTrue(self.app.flush_document_save())
        self.assertEqual(self.store.load_hierarchy(self.app.numbers()), {"A": None, "B": "A", "C": None})

    def test_close_saves_hierarchy_and_compact_layout_remains_usable(self):
        self.enable()
        self.select("B")
        self.app.change_hierarchy("indent")
        self.app.geometry("1050x710")
        self.app.update()
        self.assertGreaterEqual(self.app.documents_view.tree.winfo_height(), 150)
        with patch.object(self.app, "destroy"):
            self.assertTrue(self.app.finish_close())
        self.assertEqual(self.store.load_hierarchy(self.app.numbers()), {"A": None, "B": "A", "C": None})


if __name__ == "__main__":
    unittest.main()
