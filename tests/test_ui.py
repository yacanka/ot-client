"""Real Tk interactions. Run with a display; no corporate network required."""
import os
import unittest


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "A graphical display is required")
class UserFlowTests(unittest.TestCase):
    def setUp(self):
        from ot_app.app import Application
        from ot_app.settings import AppSettings

        class MemoryStore:
            warning = ""

            def __init__(self):
                self.settings = AppSettings()
                self.documents = []

            def load(self):
                return self.settings, list(self.documents)

            def save(self, settings, documents=None):
                self.settings = settings
                if documents is not None:
                    self.documents = list(documents)

            def save_documents(self, documents):
                self.documents = list(documents)

        self.store = MemoryStore()
        self.app = Application(store=self.store)
        self.app.update()

    def tearDown(self):
        self.app.destroy()

    def test_add_deduplicate_remove_undo_and_persist(self):
        self.app.add_numbers(["DOC-001", "DOC-002", "DOC-001"])
        self.app.update()
        self.assertEqual([r.number for r in self.app.rows.values()], ["DOC-001", "DOC-002"])
        self.assertEqual(len(self.app.documents_view.tree.get_children()), 2)
        key = next(iter(self.app.rows))
        self.app.documents_view.tree.selection_set(key)
        self.app.remove_selected()
        self.assertEqual([r.number for r in self.app.rows.values()], ["DOC-002"])
        self.app.undo_remove()
        self.assertEqual([r.number for r in self.app.rows.values()], ["DOC-001", "DOC-002"])
        self.app.flush_document_save()
        self.assertEqual(self.store.documents, ["DOC-001", "DOC-002"])

    def test_filter_hides_rows_without_changing_queue(self):
        self.app.add_numbers(["DOC-001", "PLAN-050"])
        self.app.documents_view.search_var.set("plan")
        self.app.refresh_table()
        visible = self.app.documents_view.tree.get_children()
        self.assertEqual(len(visible), 1)
        self.assertEqual(self.app.rows[visible[0]].number, "PLAN-050")
        self.assertEqual(len(self.app.rows), 2)

    def test_settings_and_documents_navigation_preserves_input(self):
        self.app.add_numbers(["DOC-001"])
        self.app.show_view("settings")
        self.app.update()
        self.assertTrue(self.app.settings_view.winfo_ismapped())
        self.app.show_view("documents")
        self.app.update()
        self.assertTrue(self.app.documents_view.winfo_ismapped())
        self.assertEqual(len(self.app.rows), 1)

    def test_busy_state_keeps_cancel_available_and_blocks_mutation(self):
        self.app.add_numbers(["DOC-001"])
        self.app.set_busy(True)
        self.app.update()
        self.assertIn("disabled", self.app.documents_view.start_button.state())
        self.assertNotIn("disabled", self.app.documents_view.cancel_button.state())
        self.app.set_busy(False)

    def test_minimum_window_keeps_document_rows_visible(self):
        self.app.geometry("1050x710")
        self.app.add_numbers(["DOC-001", "DOC-002", "DOC-003"])
        self.app.update()
        self.assertGreaterEqual(self.app.documents_view.tree.winfo_height(), 150)

    def test_declining_close_after_save_error_keeps_event_polling(self):
        from unittest.mock import patch
        self.app.after_cancel(self.app._poll_after)
        self.app._poll_after = None
        self.app._closing = True
        with patch.object(self.app, "flush_document_save", return_value=False), patch("ot_app.app.messagebox.askyesno", return_value=False):
            self.app.poll_events()
        self.assertFalse(self.app._closing)
        self.assertIsNotNone(self.app._poll_after)

    def test_fatal_job_is_not_reported_as_completed(self):
        from ot_app.worker import WorkerEvent
        self.app._handle_event(WorkerEvent("fatal", payload={"message": "Oturum açılamadı."}))
        self.app._handle_event(WorkerEvent("finished", payload={"processed": 0, "total": 3}))
        self.assertIn("İşlem durdu", self.app.documents_view.progress_var.get())

    def test_unchanged_queue_is_not_written_on_close(self):
        from unittest.mock import patch
        with patch.object(self.store, "save_documents") as save, patch.object(self.app, "destroy"):
            self.app.finish_close()
        save.assert_not_called()

    def test_settings_save_does_not_replace_unchanged_queue(self):
        from unittest.mock import patch
        self.store.documents = ["PREVIOUSLY-UNREAD"]
        with patch.object(self.store, "save", wraps=self.store.save) as save:
            self.app.save_settings()
        self.assertEqual(self.store.documents, ["PREVIOUSLY-UNREAD"])
        self.assertIsNone(save.call_args.args[1])

    def test_valid_unsaved_settings_are_retained_on_close(self):
        from unittest.mock import patch
        from dataclasses import replace
        draft = replace(self.app.settings, username="edited-user")
        with patch.object(self.app.settings_view, "read_settings", return_value=draft), patch.object(self.app, "destroy"):
            self.app.finish_close()
        self.assertEqual(self.store.settings.username, "edited-user")

    def test_undo_does_not_exceed_document_limit_or_lose_current_rows(self):
        from unittest.mock import patch
        self.app.add_numbers(["A", "B", "C"])
        self.app.documents_view.tree.selection_set(next(iter(self.app.rows)))
        self.app.remove_selected()
        self.app.add_numbers(["D"])
        with patch("ot_app.documents.MAX_DOCUMENTS", 3):
            self.app.undo_remove()
        self.assertEqual(self.app.numbers(), ["B", "C", "D"])
        self.assertIsNotNone(self.app._undo)

    def test_download_action_updates_rows_and_returns_to_idle(self):
        import tempfile
        import time
        from pathlib import Path
        from unittest.mock import patch
        from otClient import Document, DownloadResult
        from ot_app.settings import AppSettings
        class Connector:
            def __init__(self, *args, **kwargs):
                pass
            def login(self):
                return True
            def search_documents(self, number):
                return [] if number == "MISSING" else [Document("id", number, "Örnek belge", "Kalite")]
            def download_document(self, document_id, output, file_name=None, **kwargs):
                path = Path(output) / "DOC-001.pdf"
                path.write_bytes(b"%PDF-example")
                kwargs["progress"](12, 12)
                return DownloadResult(path, "downloaded", 12)
            def close(self):
                pass
        self.app.connector_factory = Connector
        self.app.add_numbers(["DOC-001", "MISSING"])
        with tempfile.TemporaryDirectory() as output:
            settings = AppSettings(base_url="https://ot.example.com", username="demo", password="secret", output_dir=output)
            with patch.object(self.app.settings_view, "read_settings", return_value=settings):
                self.app.start_all()
                deadline = time.monotonic() + 3
                while self.app.busy and time.monotonic() < deadline:
                    self.app.update()
                    time.sleep(0.005)
            self.assertFalse(self.app.busy)
            rows = list(self.app.rows.values())
            self.assertEqual([r.status for r in rows], ["downloaded", "not_found"])
            self.assertTrue(Path(rows[0].path).is_file())
            self.assertEqual(self.app.documents_view.done_var.get(), "1")
            self.assertIn("2 / 2", self.app.documents_view.progress_var.get())

    def test_refresh_coalescing_does_not_leave_orphan_timers(self):
        self.app.schedule_refresh()
        scheduled = self.app._refresh_after
        self.app.refresh_table()
        self.assertNotIn(scheduled, self.app.tk.splitlist(self.app.tk.call("after", "info")))


if __name__ == "__main__":
    unittest.main()
