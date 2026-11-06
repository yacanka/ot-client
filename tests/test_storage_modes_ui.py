"""Independent storage modes, live index previews and compact settings layout."""

import os
import sys
import unittest
from tkinter import ttk

from ot_app.app import Application
from ot_app.settings import RegistryStore
from ot_app.theme import BLUE_PALE
from tests.test_settings import FakeProtector, FakeRegistry


@unittest.skipUnless(os.name == "nt" or sys.platform == "darwin" or os.environ.get("DISPLAY"),
                     "A graphical display is required")
class StorageModesUITests(unittest.TestCase):
    def setUp(self):
        self.store = RegistryStore(FakeRegistry(), FakeProtector())
        self.app = Application(store=self.store)
        self.app.show_view("storage")
        self.app.update()

    def tearDown(self):
        self.app.destroy()

    def test_all_four_modes_keep_toggles_independent_and_share_busy_controls(self):
        view = self.app.storage_view
        toggles = (view.document_subfolder_enabled_button,
                   view.manual_folder_hierarchy_enabled_button)
        shared = (view.document_subfolder_format_entry, *view._folder_match_buttons)
        for individual, manual in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(individual=individual, manual=manual):
                view.document_subfolder_enabled_var.set(individual)
                view.manual_folder_hierarchy_enabled_var.set(manual)
                for button in toggles:
                    self.assertNotIn("disabled", button.state())
                for widget in shared:
                    self.assertEqual("disabled" in widget.state(), not (individual or manual))
                self.app.set_busy(True)
                for widget in (*toggles, *shared):
                    self.assertIn("disabled", widget.state())
                for button in toggles:
                    button.invoke()
                self.assertEqual(view.document_subfolder_enabled_var.get(), individual)
                self.assertEqual(view.manual_folder_hierarchy_enabled_var.get(), manual)
                self.app.set_busy(False)
                for button in toggles:
                    self.assertNotIn("disabled", button.state())
                for widget in shared:
                    self.assertEqual("disabled" in widget.state(), not (individual or manual))

    def test_both_activation_orders_and_save_buttons_restore_both_modes(self):
        fields = ("document_subfolder_enabled", "manual_folder_hierarchy_enabled")
        for order in (fields, tuple(reversed(fields))):
            for page in ("storage", "settings"):
                with self.subTest(order=order, page=page):
                    view = self.app.storage_view
                    for field in fields:
                        getattr(view, field + "_var").set(False)
                    for field in order:
                        getattr(view, field + "_button").invoke()
                    view.document_subfolder_format_var.set("{numara} - {ad}")
                    view.document_subfolder_match_var.set("contains")
                    self.app.show_view(page)
                    getattr(self.app, page + "_view").save_button.invoke()
                    settings, _ = self.store.load()
                    self.assertTrue(settings.document_subfolder_enabled)
                    self.assertTrue(settings.manual_folder_hierarchy_enabled)
                    self.assertEqual(self.store.warning, "")
                    self.app.destroy()
                    self.app = Application(store=self.store)
                    restored = self.app.storage_view
                    self.assertTrue(restored.document_subfolder_enabled_var.get())
                    self.assertTrue(restored.manual_folder_hierarchy_enabled_var.get())
                    self.assertEqual(restored.document_subfolder_format_var.get(), "{numara} - {ad}")
                    self.assertEqual(restored.document_subfolder_match_var.get(), "contains")

    def test_inactive_unfinished_folder_template_is_retained_by_both_save_buttons(self):
        view = self.app.storage_view
        view.document_subfolder_format_var.set("  {unfinished  ")
        for page in ("storage", "settings"):
            with self.subTest(page=page):
                getattr(self.app, page + "_view").save_button.invoke()
                self.assertEqual(self.store.load()[0].document_subfolder_format, "  {unfinished  ")
                self.assertEqual(view.document_subfolder_format_var.get(), "  {unfinished  ")
                self.assertEqual(self.store.warning, "")

    def test_mode_changes_refresh_both_index_previews(self):
        view = self.app.storage_view
        view.filename_format_var.set("{index} - {numara}")
        view.document_subfolder_format_var.set("{index} - {numara}")
        for individual, manual, index in (
            (False, False, "1"), (True, False, "1"),
            (True, True, "1.1"), (False, True, "1.1"), (False, False, "1"),
        ):
            with self.subTest(individual=individual, manual=manual):
                view.document_subfolder_enabled_var.set(individual)
                view.manual_folder_hierarchy_enabled_var.set(manual)
                self.assertEqual(view.filename_preview_var.get(), f"Örnek: {index} - PR-001.pdf")
                self.assertEqual(view.folder_preview_var.get(), f"Örnek: {index} - PR-001")

    def test_hierarchy_card_scrolls_between_output_and_folder_cards_at_minimum_size(self):
        self.app.geometry("1050x710")
        self.app.update()
        view = self.app.storage_view
        output_card = view.output_dir_entry.master.master
        hierarchy_card = view.manual_folder_hierarchy_enabled_button.master
        folder_card = view.document_subfolder_enabled_button.master
        self.assertIsNot(hierarchy_card, folder_card)
        self.assertEqual(hierarchy_card.master, view._scroll_frame)
        self.assertLess(output_card.winfo_y(), hierarchy_card.winfo_y())
        self.assertLess(hierarchy_card.winfo_y(), folder_card.winfo_y())
        style = ttk.Style(view)
        self.assertEqual(style.lookup(hierarchy_card.cget("style"), "background"), BLUE_PALE)
        footer_y = view.save_button.winfo_rooty()
        for field in ("manual_folder_hierarchy_enabled", "download_related_attachments"):
            view.focus_field(field)
            self.app.update()
            widget = view._field_widgets[field]
            self.assertGreaterEqual(widget.winfo_rooty(), view._canvas.winfo_rooty())
            self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(),
                                 view._canvas.winfo_rooty() + view._canvas.winfo_height())
            self.assertEqual(view.save_button.winfo_rooty(), footer_y)
        self.assertLessEqual(footer_y + view.save_button.winfo_height(),
                             self.app.winfo_rooty() + self.app.winfo_height())
        for card in (output_card, hierarchy_card, folder_card):
            self.assertLessEqual(card.winfo_width(), view._canvas.winfo_width())
        for label in view._wrap_labels:
            self.assertLessEqual(label.winfo_width(), view._canvas.winfo_width())


if __name__ == "__main__":
    unittest.main()
