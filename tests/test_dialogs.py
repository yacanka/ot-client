"""Display-driven checks for settings editing and deliberate modal actions."""

import os
import tempfile
import traceback
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "A graphical display is required")
class SettingsAndDialogTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from tkinter import ttk

        from ot_app.theme import apply_theme

        self.root = tk.Tk()
        self.root.geometry("1180x800")
        apply_theme(self.root)
        self.sidebar = tk.Frame(self.root, width=204, background="#111E33")
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self.host = ttk.Frame(self.root, padding=(24, 22, 24, 10))
        self.host.pack(side="left", fill="both", expand=True)
        self._callback_errors = []

        def report(exception_type, exception, tb):
            self._callback_errors.append("".join(traceback.format_exception(exception_type, exception, tb)))
            for child in self.root.winfo_children():
                if isinstance(child, tk.Toplevel):
                    child.destroy()

        self.root.report_callback_exception = report
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        if self._callback_errors:
            self.fail("Tk callback failed:\n" + "\n".join(self._callback_errors))

    def _settings_view(self, settings=None, on_save=lambda: None, on_test=lambda: None):
        from ot_app.settings import AppSettings
        from ot_app.settings_view import SettingsView

        view = SettingsView(self.host, settings or AppSettings(), on_save, on_test)
        view.pack(fill="both", expand=True)
        self.root.update()
        return view

    def _modal(self, dialog_class, action, *args, **kwargs):
        def run_action():
            dialog = next(child for child in self.root.winfo_children() if isinstance(child, dialog_class))
            action(dialog)

        def watchdog():
            self._callback_errors.append("The modal dialog did not finish its test action.")
            for child in self.root.winfo_children():
                if isinstance(child, dialog_class):
                    child.destroy()

        self.root.after(100, run_action)
        timeout = self.root.after(4000, watchdog)
        result = dialog_class(self.root, *args, **kwargs)
        self.root.after_cancel(timeout)
        return result

    def test_settings_roundtrip_callbacks_password_toggle_and_busy_state(self):
        from ot_app.settings import AppSettings

        with tempfile.TemporaryDirectory() as directory:
            certificate = Path(directory) / "corporate-ca.pem"
            certificate.write_text("test certificate placeholder", encoding="utf-8")
            original = AppSettings(
                base_url="https://example.invalid/ot", username="test-user",
                password="  example secret  ", output_dir=directory, timeout=31,
                folder_id="folder-22", ca_bundle=str(certificate), verify_tls=True,
                remember_password=False,
            )
            calls = []
            view = self._settings_view(
                original, on_save=lambda: calls.append("save"), on_test=lambda: calls.append("test")
            )
            self.assertEqual(view.read_settings(), original)
            view.timeout_var.set("12,5")
            edited = view.read_settings()
            edited.validate(require_connection=True)
            self.assertEqual(edited.timeout, 12.5)
            self.assertEqual(edited.password, original.password)
            self.assertEqual(edited.folder_id, original.folder_id)
            self.assertEqual(edited.ca_bundle, original.ca_bundle)
            self.assertFalse(edited.remember_password)
            self.assertEqual(original.timeout, 31)

            self.assertTrue(view.password_entry.cget("show"))
            view._show_password_button.invoke()
            self.assertEqual(view.password_entry.cget("show"), "")
            view._show_password_button.invoke()
            self.assertTrue(view.password_entry.cget("show"))

            view.set_busy(True)
            for widget in (*view._editable, view.save_button, view.test_button):
                self.assertIn("disabled", widget.state())
            view.save_button.invoke()
            view.test_button.invoke()
            self.assertEqual(calls, [])
            view.set_busy(False)
            view.save_button.invoke()
            view.test_button.invoke()
            self.assertEqual(calls, ["save", "test"])
            view.mark_saved()
            self.assertEqual(view._status_var.get(), "Ayarlar kaydedildi.")

    def test_compact_settings_scroll_to_invalid_timeout_and_keep_actions_visible(self):
        self.root.geometry("780x540")
        view = self._settings_view()
        self.assertTrue(view._stacked_fields)
        self.assertEqual(view._password_field.grid_info()["row"], 1)
        view.timeout_var.set("not a number")
        with self.assertRaisesRegex(ValueError, "geçerli bir sayı"):
            view.read_settings()
        self.root.update()
        self.assertTrue(view._advanced_open)
        self.assertEqual(view._folder_field.grid_info()["row"], 1)
        self.assertGreater(view._canvas.winfo_height(), 100)
        canvas_top = view._canvas.winfo_rooty()
        canvas_bottom = canvas_top + view._canvas.winfo_height()
        timeout_top = view.timeout_entry.winfo_rooty()
        self.assertGreaterEqual(timeout_top, canvas_top)
        self.assertLessEqual(timeout_top + view.timeout_entry.winfo_height(), canvas_bottom)
        view_bottom = view.winfo_rooty() + view.winfo_height()
        self.assertLessEqual(view.save_button.winfo_rooty() + view.save_button.winfo_height(), view_bottom)
        self.assertLessEqual(view.test_button.winfo_rootx() + view.test_button.winfo_width(),
                             view.winfo_rootx() + view.winfo_width())
        for value in ("NaN", "inf", "0", "-1", "3601"):
            view.timeout_var.set(value)
            with self.assertRaises(ValueError):
                view.read_settings()
        view.timeout_var.set("30")
        self.assertEqual(view.read_settings().timeout, 30)
        view.focus_connection()
        self.root.update()
        self.assertAlmostEqual(view._canvas.yview()[0], 0.0)

    def test_bulk_accepts_unique_documents_and_return_remains_multiline(self):
        from ot_app.dialogs import BulkInputDialog

        def action(dialog):
            self.assertGreaterEqual(int(dialog.text.cget("width")), 70)
            self.assertGreaterEqual(int(dialog.text.cget("height")), 15)
            dialog.text.insert("1.0", "DOC-01\nDOC-01,DOC-02\tdoc-02;DOC-03")
            dialog._update_preview()
            self.assertIsNone(dialog.result)
            dialog.text.mark_set("insert", "end-1c")
            dialog.text.focus_force()
            dialog.text.event_generate("<Return>")
            self.assertTrue(dialog.winfo_exists())
            self.assertTrue(dialog.text.get("1.0", "end-1c").endswith("\n"))
            dialog.add_button.invoke()

        dialog = self._modal(BulkInputDialog, action)
        self.assertEqual(dialog.result, ["DOC-01", "DOC-02", "doc-02", "DOC-03"])

    def test_bulk_debounced_preview_rejects_nonstring_json_and_can_be_cancelled(self):
        from ot_app.dialogs import BulkInputDialog

        def action(dialog):
            self.assertIn("disabled", dialog.add_button.state())
            self.assertIsNotNone(dialog._parse_error)
            dialog.text.delete("1.0", "end")
            dialog.text.insert("1.0", '["DOC-01", "DOC-02", "DOC-01"]')

            def after_debounce():
                self.assertIsNone(dialog._parse_error)
                self.assertEqual(dialog._parsed, ["DOC-01", "DOC-02"])
                self.assertIn("2 benzersiz", dialog._count_var.get())
                self.assertNotIn("disabled", dialog.add_button.state())
                dialog.cancel_button.invoke()

            dialog.after(300, after_debounce)

        dialog = self._modal(BulkInputDialog, action, initial='["DOC-01", 2]')
        self.assertIsNone(dialog.result)

    def test_candidate_requires_confirmation_and_returns_selected_object(self):
        from otClient import Document
        from ot_app.dialogs import CandidateDialog

        candidates = [
            Document("id-1", "DOC-001", "First document", "Test author"),
            Document("id-2", "DOC-001", "Long title " * 150, "Second author"),
        ]

        def action(dialog):
            self.assertIsNone(dialog.result)
            self.assertEqual(dialog.tree.selection(), ("0",))
            dialog.tree.selection_set("1")
            dialog.tree.event_generate("<<TreeviewSelect>>")
            self.root.update_idletasks()
            details = dialog._details_text.get("1.0", "end-1c")
            self.assertIn("id-2", details)
            self.assertIn(candidates[1].title, details)
            self.assertGreater(dialog.tree.winfo_height(), 100)
            self.assertLessEqual(dialog.use_button.winfo_rooty() + dialog.use_button.winfo_height(),
                                 dialog.winfo_rooty() + dialog.winfo_height())
            self.assertIsNone(dialog.result)
            dialog.use_button.invoke()

        dialog = self._modal(CandidateDialog, action, "DOC-001", candidates)
        self.assertIs(dialog.result, candidates[1])

    def test_candidate_escape_cancels_without_using_visual_selection(self):
        from otClient import Document
        from ot_app.dialogs import CandidateDialog

        def action(dialog):
            self.assertEqual(dialog.tree.selection(), ("0",))
            dialog.tree.focus_force()
            dialog.tree.event_generate("<Escape>")

        dialog = self._modal(
            CandidateDialog, action, "DOC-001", [Document("id-1", "DOC-001", "Title", "Author")]
        )
        self.assertIsNone(dialog.result)


if __name__ == "__main__":
    unittest.main()
