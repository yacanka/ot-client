"""Manual document titles remain independent of server metadata."""
import os
import sys
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from otClient import Document
from ot_app.filename_format import format_document_filename, format_document_folder
from ot_app.settings import RegistryStore
from tests.test_settings import FakeRegistry, FakeProtector
from tests.test_document_edit import EditController


class CustomTitleTests(unittest.TestCase):
    def test_templates_use_custom_title_without_changing_number_or_extension(self):
        document = Document("id", "DOC.pdf", "Server", "", 2)
        self.assertEqual(format_document_filename("{numara} - {ad}", document, custom_title="Manual"), "DOC - Manual.pdf")
        self.assertEqual(format_document_folder("{ad}", document, custom_title="Manual"), "Manual")
        self.assertEqual(format_document_filename("{numara}", document, custom_title="Manual"), "DOC.pdf")
        self.assertEqual(document.title, "Server")

    def test_empty_title_keeps_existing_fallback_and_tags_are_literal(self):
        document = Document("id", "DOC.pdf", "Server", "")
        self.assertEqual(format_document_filename("{ad}", document, custom_title=" "), "Server.pdf")
        self.assertEqual(format_document_filename("{ad}", document, custom_title="{numara}"), "{numara}.pdf")

    def test_title_registry_roundtrip_and_omitted_values_preserve_record(self):
        registry = FakeRegistry()
        store = RegistryStore(registry, FakeProtector())
        store.save_documents(["DOC"], title_overrides={"DOC": "Manual"})
        store.save_documents(["DOC"])
        self.assertEqual(store.load_title_overrides(["DOC"]), {"DOC": "Manual"})
        store.save_documents(["DOC"], title_overrides={})
        self.assertEqual(store.load_title_overrides(["DOC"]), {})

    def test_legacy_and_session_only_storage(self):
        store = RegistryStore(platform="darwin")
        self.assertEqual(store.load_title_overrides(["DOC"]), {})
        store.save_documents(["DOC"], title_overrides={"DOC": "Manual"})
        self.assertEqual(store.load_title_overrides(["DOC"]), {"DOC": "Manual"})

    def test_edit_title_preserves_results_and_undo(self):
        controller = EditController()
        before = replace(controller.rows["child"])
        with patch("ot_app.actions.DocumentEditDialog", return_value=SimpleNamespace(result=("OLD", " Manual "))):
            controller.edit_document()
        self.assertEqual(controller.rows["child"], replace(before, custom_title="Manual"))
        controller.rows["child"].message = "New result"
        controller.undo_remove()
        self.assertEqual(controller.rows["child"].custom_title, "")
        self.assertEqual(controller.rows["child"].message, "New result")

    def test_invalid_title_does_not_mutate_queue(self):
        controller = EditController()
        for title in ("x" * 1025, "bad\x00name", "bad\nname", "\ud800"):
            with self.subTest(title=repr(title)):
                with patch("ot_app.actions.DocumentEditDialog", return_value=SimpleNamespace(result=("OLD", title))):
                    controller.edit_document()
                self.assertFalse(controller.rows["child"].custom_title)
                self.assertFalse(controller.saved)

    def test_combined_number_edit_keeps_manual_title_and_undo_restores_both(self):
        controller = EditController()
        controller.rows["child"].custom_title = "Old manual"
        original = replace(controller.rows["child"])
        with patch("ot_app.actions.DocumentEditDialog", return_value=SimpleNamespace(result=("NEW", "Old manual"))):
            controller.edit_document()
        row = controller.rows["child"]
        self.assertEqual((row.number, row.custom_title, row.parent_key), ("NEW", "Old manual", "parent"))
        self.assertIsNone(row.document)
        controller.undo_remove()
        self.assertEqual(controller.rows["child"], original)

    def test_corrupt_stale_and_oversized_records_do_not_change_saved_data(self):
        from ot_app.settings import TITLES_VALUE, REG_SZ, MAX_CONFIG_CHARACTERS
        registry = FakeRegistry()
        store = RegistryStore(registry, FakeProtector())
        store.save_documents(["DOC"], title_overrides={"DOC": "Manual"})
        before = dict(registry.values)
        self.assertEqual(store.load_title_overrides(["OTHER"]), {})
        self.assertTrue(store.warning)
        self.assertEqual(registry.values, before)
        for record in ("bad json", "[]", "x" * (MAX_CONFIG_CHARACTERS + 1)):
            registry.values[TITLES_VALUE] = (record, REG_SZ)
            self.assertEqual(store.load_title_overrides(["DOC"]), {})
            self.assertEqual(registry.values[TITLES_VALUE], (record, REG_SZ))

    def test_full_settings_save_and_validation_preserve_existing_records(self):
        from ot_app.settings import AppSettings
        registry = FakeRegistry()
        store = RegistryStore(registry, FakeProtector())
        store.save(AppSettings(), ["DOC"], title_overrides={"DOC": "Manual"})
        store.save(AppSettings())
        self.assertEqual(store.load_title_overrides(["DOC"]), {"DOC": "Manual"})
        before = dict(registry.values)
        for titles in ({"OTHER": "Wrong"}, {"DOC": "bad\x00name"}):
            with self.assertRaises(ValueError):
                store.save_documents(["DOC"], title_overrides=titles)
            self.assertEqual(registry.values, before)

    def test_noop_cancel_busy_or_multiselection_preserves_undo(self):
        controller = EditController()
        controller._remember_structure()
        undo = controller._undo
        for result in (None, ("OLD", " ")):
            with patch("ot_app.actions.DocumentEditDialog", return_value=SimpleNamespace(result=result)):
                controller.edit_document()
            self.assertIs(controller._undo, undo)
            self.assertFalse(controller.saved)
        for busy, selected in ((True, ("child",)), (False, ()), (False, ("parent", "child"))):
            controller.busy, controller.selected = busy, selected
            with patch("ot_app.actions.DocumentEditDialog", side_effect=AssertionError("Unexpected modal")):
                controller.edit_document()

    def test_failed_title_write_can_be_retried_without_touching_credentials(self):
        from ot_app.settings import TITLES_VALUE, PASSWORD_VALUE, SettingsError
        registry = FakeRegistry()
        store = RegistryStore(registry, FakeProtector())
        store.save_documents(["DOC"], title_overrides={"DOC": "Old"})
        registry.fail_write.add(TITLES_VALUE)
        registry.calls.clear()
        with self.assertRaises(SettingsError):
            store.save_documents(["DOC"], title_overrides={"DOC": "New"})
        self.assertEqual(store.load_title_overrides(["DOC"]), {"DOC": "Old"})
        self.assertFalse(any(call[1] == PASSWORD_VALUE for call in registry.calls))
        registry.fail_write.clear()
        store.save_documents(["DOC"], title_overrides={"DOC": "New"})
        self.assertEqual(store.load_title_overrides(["DOC"]), {"DOC": "New"})


@unittest.skipUnless(os.name == "nt" or sys.platform == "darwin" or os.environ.get("DISPLAY"), "A graphical display is required")
class CustomTitleUITests(unittest.TestCase):
    def setUp(self):
        from ot_app.app import Application
        self.store = RegistryStore(platform="darwin")
        self.app = Application(store=self.store)
        self.app.add_numbers(["DOC"])
        self.row = next(iter(self.app.rows.values()))
        self.row.document = Document("id", "DOC.pdf", "Server", "")
        self.app.documents_view.tree.selection_set(self.row.key)
        self.app.update()
        self.errors = []
        self.app.report_callback_exception = lambda *error: self.errors.append(error)

    def tearDown(self):
        self.app.destroy()
        self.assertFalse(self.errors)

    def edit(self, action):
        from ot_app.dialogs import DocumentEditDialog
        def interact():
            dialog = next(widget for widget in self.app.winfo_children() if isinstance(widget, DocumentEditDialog))
            try:
                action(dialog)
            finally:
                if dialog.winfo_exists():
                    dialog._cancel()
        self.app.after(80, interact)
        self.app.edit_document()

    def test_dialog_validation_save_table_search_and_restart(self):
        def save(dialog):
            self.assertEqual(dialog.custom_title_var.get(), "")
            dialog.custom_title_var.set("x" * 1025)
            dialog.save_button.invoke()
            self.assertTrue(dialog.error_var.get())
            dialog.custom_title_var.set(" Manual ")
            dialog.save_button.invoke()
        self.edit(save)
        self.assertEqual(self.row.custom_title, "Manual")
        self.assertEqual(self.app._row_values(self.row)[1], "Manual")
        self.app.documents_view.search_var.set("Manual")
        self.assertTrue(self.app._is_visible(self.row))
        self.assertTrue(self.app.flush_document_save())
        from ot_app.app import Application
        restarted = Application(store=self.store)
        try:
            self.assertEqual(next(iter(restarted.rows.values())).custom_title, "Manual")
        finally:
            restarted.destroy()

    def test_reset_cancel_and_save_fall_back_to_server_name(self):
        self.row.custom_title = "Manual"
        def reset(dialog):
            dialog.reset_title_button.invoke()
            self.assertEqual(dialog.custom_title_var.get(), "")
        self.edit(reset)
        self.assertEqual(self.row.custom_title, "Manual")
        def save_reset(dialog):
            dialog.reset_title_button.invoke()
            dialog.save_button.invoke()
        self.edit(save_reset)
        self.assertEqual(self.row.custom_title, "")
        self.assertEqual(self.app._row_values(self.row)[1], "Server")

    def test_long_server_title_keeps_controls_inside_dialog(self):
        self.row.document = replace(self.row.document, title="Very long server title " * 200)
        def inspect(dialog):
            dialog.update_idletasks()
            for control in (dialog.title_entry, dialog.reset_title_button, dialog.save_button):
                self.assertLessEqual(control.winfo_rooty() + control.winfo_height(),
                                     dialog.winfo_rooty() + dialog.winfo_height())
        self.edit(inspect)
