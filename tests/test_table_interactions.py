"""Table reordering and outside-click selection behavior against real Tk."""
import os
import sys
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ot_app.app import Application
from ot_app.settings import RegistryStore


@unittest.skipUnless(os.name == "nt" or sys.platform == "darwin" or os.environ.get("DISPLAY"),
                     "A graphical display is required")
class TableInteractionTests(unittest.TestCase):
    def setUp(self):
        self.store = RegistryStore(platform="darwin")
        self.app = Application(store=self.store)
        self.app.add_numbers(("A", "B", "C", "D", "E"))
        self.app.flush_document_save()
        self.app.update()
        self.view = self.app.documents_view
        self.tree = self.view.tree
        self.keys = {row.number: row.key for row in self.app.rows.values()}

    def tearDown(self):
        self.app.destroy()

    def select(self, *numbers):
        keys = [self.keys[number] for number in numbers]
        self.tree.selection_set(keys)
        self.tree.focus(keys[0] if keys else "")
        self.app.update()

    def key(self, sequence):
        self.tree.focus_force()
        self.app.update()
        self.tree.event_generate(sequence)
        self.app.update()

    def test_plain_vertical_arrows_reorder_in_both_modes_and_preserve_selection(self):
        for enabled in (False, True):
            with self.subTest(manual=enabled):
                self.view.set_manual_hierarchy(enabled)
                self.select("B", "C")
                self.key("<Up>")
                self.assertEqual(self.app.numbers(), ["B", "C", "A", "D", "E"])
                self.assertEqual(set(self.tree.selection()), {self.keys["B"], self.keys["C"]})
                self.assertEqual(self.tree.focus(), self.keys["B"])
                self.assertTrue(self.tree.bbox(self.keys["B"]))
                self.assertTrue(self.app._documents_dirty)
                self.app.undo_remove()
                self.assertEqual(self.app.numbers(), ["A", "B", "C", "D", "E"])
                self.app.flush_document_save()

    def test_dormant_hierarchy_moves_whole_subtrees_and_survives_restart(self):
        self.view.set_manual_hierarchy(True)
        self.select("C")
        self.app.change_hierarchy("indent")
        self.view.set_manual_hierarchy(False)
        self.select("B", "C")
        self.key("<Down>")
        self.assertEqual(self.app.numbers(), ["A", "D", "B", "C", "E"])
        self.assertEqual(self.app.rows[self.keys["C"]].parent_key, self.keys["B"])
        self.assertEqual(set(self.tree.selection()), {self.keys["B"], self.keys["C"]})
        self.app.flush_document_save()
        self.app.destroy()
        self.app = Application(store=self.store)
        self.assertEqual(self.app.numbers(), ["A", "D", "B", "C", "E"])
        self.assertEqual(self.store.load_hierarchy(self.app.numbers()),
                         {"A": None, "D": None, "B": None, "C": "B", "E": None})

    def test_boundaries_empty_invalid_filter_and_busy_are_atomic_noops(self):
        for selected, direction in (("A", "up"), ("E", "down"), (None, "up")):
            with self.subTest(selected=selected, direction=direction):
                self.select(*([selected] if selected else []))
                self.key(f"<{direction.title()}>")
                self.assertEqual(self.app.numbers(), ["A", "B", "C", "D", "E"])
                self.assertEqual(self.tree.selection(), (self.keys[selected],) if selected else ())
                self.assertIsNone(self.app._undo)
                self.assertFalse(self.app._documents_dirty)
        self.select("B", "D")
        self.key("<Up>")
        self.assertEqual(set(self.tree.selection()), {self.keys["B"], self.keys["D"]})
        self.assertIsNone(self.app._undo)
        self.assertFalse(self.app._documents_dirty)
        self.assertEqual(self.app.numbers(), ["A", "B", "C", "D", "E"])
        self.view.search_var.set("B")
        self.app.refresh_table()
        self.select("B")
        self.key("<Down>")
        self.assertFalse(self.app._documents_dirty)
        self.view.search_var.set("")
        self.view.filter_var.set("Bekleyen")
        self.app.refresh_table()
        self.key("<Down>")
        self.assertFalse(self.app._documents_dirty)
        self.view.filter_var.set("Tüm belgeler")
        self.app.refresh_table()
        self.app.set_busy(True)
        self.key("<Down>")
        self.assertFalse(self.app._documents_dirty)
        self.assertIsNone(self.app._undo)
        self.assertEqual(self.app.numbers(), ["A", "B", "C", "D", "E"])

    def test_modified_arrows_keep_native_selection_navigation_without_reordering(self):
        self.view.set_manual_hierarchy(True)
        self.select("B")
        self.key("<Shift-Down>")
        self.assertEqual(self.tree.focus(), self.keys["C"])
        self.assertIn(self.keys["C"], self.tree.selection())
        self.assertEqual(self.app.numbers(), ["A", "B", "C", "D", "E"])
        self.key("<Control-Up>")
        self.assertEqual(self.tree.focus(), self.keys["B"])
        self.assertEqual(self.app.numbers(), ["A", "B", "C", "D", "E"])
        self.key("<Shift-Right>")
        self.key("<Control-Left>")
        self.assertTrue(all(row.parent_key is None for row in self.app.rows.values()))
        self.assertFalse(self.app._documents_dirty)
        self.assertIsNone(self.app._undo)

    def test_horizontal_arrows_remain_manual_only(self):
        self.select("B")
        self.key("<Right>")
        self.assertIsNone(self.app.rows[self.keys["B"]].parent_key)
        self.view.set_manual_hierarchy(True)
        self.key("<Right>")
        self.assertEqual(self.app.rows[self.keys["B"]].parent_key, self.keys["A"])
        self.key("<Left>")
        self.assertIsNone(self.app.rows[self.keys["B"]].parent_key)

    def test_alt_meta_and_platform_modifiers_do_not_edit_structure(self):
        modifiers = ["Alt", "Meta"]
        if self.app.tk.call("tk", "windowingsystem") == "aqua":
            modifiers.extend(("Command", "Option"))
        self.view.set_manual_hierarchy(True)
        for modifier in modifiers:
            for direction in ("Up", "Down", "Right", "Left"):
                with self.subTest(modifier=modifier, direction=direction):
                    self.select("B")
                    self.key(f"<{modifier}-{direction}>")
                    self.assertEqual(self.app.numbers(), ["A", "B", "C", "D", "E"])
                    self.assertTrue(all(row.parent_key is None for row in self.app.rows.values()))
                    self.assertFalse(self.app._documents_dirty)
                    self.assertIsNone(self.app._undo)

    def test_caps_and_num_lock_states_do_not_disable_plain_reordering(self):
        # Tk maps Num to Mod3 on Aqua and NumLock/ScrollLock to Mod1/Mod3 on Windows.
        system = self.app.tk.call("tk", "windowingsystem")
        states = (0x02, 0x22) if system == "aqua" else (0x02, 0x2A) if system == "win32" else (0x02,)
        for state in states:
            with self.subTest(system=system, state=state):
                self.select("B")
                self.tree.focus_force()
                self.app.update()
                self.tree.event_generate("<Up>", state=state)
                self.app.update()
                self.assertEqual(self.app.numbers(), ["B", "A", "C", "D", "E"])
                self.app.undo_remove()

    def test_outside_clicks_clear_selection_focus_and_actions_without_saving(self):
        for widget in (self.view.number_entry, self.view.search_entry, self.view.filter_box,
                       self.app.sidebar, self.view.detail_label, self.view.header_hint):
            with self.subTest(widget=widget):
                self.select("B")
                self.assertIsNone(self.app.clear_selection_outside(SimpleNamespace(widget=widget)))
                self.assertEqual(self.tree.selection(), ())
                self.assertEqual(self.tree.focus(), "")
                self.assertEqual(self.view.context_menu.entrycget(0, "state"), "disabled")
                self.assertEqual(self.view.context_menu.entrycget(1, "state"), "disabled")
                self.assertNotIn("seçili", self.view.selection_var.get())
                self.assertFalse(self.app._documents_dirty)
                self.assertIsNone(self.app._undo)

    def test_table_selection_actions_and_their_descendants_preserve_selection(self):
        child = tk.Label(self.view.open_file_button, text="nested")
        widgets = (self.view.table_area, *self.view.table_area.winfo_children(),
                   child, self.view.context_menu,
                   self.view.open_file_button, self.view.choose_button,
                   self.view.menu_button, self.view.list_menu)
        self.select("B")
        for widget in widgets:
            with self.subTest(widget=widget):
                self.assertIsNone(self.app.clear_selection_outside(SimpleNamespace(widget=widget)))
                self.assertEqual(self.tree.selection(), (self.keys["B"],))
                self.assertEqual(self.tree.focus(), self.keys["B"])

    def test_other_toplevel_clicks_do_not_clear_main_window_selection(self):
        dialog = tk.Toplevel(self.app)
        label = tk.Label(dialog, text="Dialog")
        label.pack()
        self.select("B")
        self.app.clear_selection_outside(SimpleNamespace(widget=label))
        self.assertEqual(self.tree.selection(), (self.keys["B"],))
        self.assertEqual(self.tree.focus(), self.keys["B"])
        dialog.destroy()

    def test_all_three_mouse_buttons_clear_selection_through_main_window_bindings(self):
        for button in (1, 2, 3):
            with self.subTest(button=button):
                self.select("B")
                self.view.header_hint.event_generate(f"<Button-{button}>", x=2, y=2)
                self.app.update()
                self.assertEqual(self.tree.selection(), ())
                self.assertEqual(self.tree.focus(), "")

    def context_click(self, number, sequence="<Button-3>"):
        bounds = self.tree.bbox(self.keys[number])
        self.assertTrue(bounds)
        x, y, _, height = bounds
        self.tree.event_generate(sequence, x=x + 8, y=y + height // 2)
        self.app.update()

    def test_context_click_selected_row_preserves_multiselection_until_remove(self):
        self.select("B", "C")
        with patch.object(self.view.context_menu, "tk_popup"):
            self.context_click("C")
        self.assertEqual(set(self.tree.selection()), {self.keys["B"], self.keys["C"]})
        self.assertEqual(self.view.context_menu.entrycget(2, "state"), "disabled")
        self.view.context_menu.invoke(1)
        self.app.update()
        self.assertEqual(self.app.numbers(), ["A", "D", "E"])
        self.app.undo_remove()
        self.assertEqual(self.app.numbers(), ["A", "B", "C", "D", "E"])

    def test_context_click_unselected_row_selects_only_target_and_enables_edit(self):
        self.select("A", "B")
        with patch.object(self.view.context_menu, "tk_popup"):
            self.context_click("C")
        self.assertEqual(self.tree.selection(), (self.keys["C"],))
        self.assertEqual(self.tree.focus(), self.keys["C"])
        self.assertEqual(self.view.context_menu.entrycget(2, "state"), "normal")
        self.assertEqual(self.view.context_menu.entrycget(2, "label"), "Belge numarasını düzenle…")

    def test_context_click_blank_or_header_keeps_selection_without_menu(self):
        self.select("B", "C")
        self.app.geometry("1280x1000")
        self.app.update()
        last = self.tree.bbox(self.keys["E"])
        for y in (2, last[1] + last[3] + 8):
            with self.subTest(y=y), patch.object(self.view.context_menu, "tk_popup") as popup:
                self.tree.event_generate("<Button-3>", x=8, y=y)
                self.app.update()
                self.assertEqual(set(self.tree.selection()), {self.keys["B"], self.keys["C"]})
                popup.assert_not_called()

    def test_context_menu_busy_state_disables_all_actions(self):
        self.select("B")
        self.app.set_busy(True)
        with patch.object(self.view.context_menu, "tk_popup"):
            self.context_click("B")
        for index in range(3):
            self.assertEqual(self.view.context_menu.entrycget(index, "state"), "disabled")
            self.view.context_menu.invoke(index)
        self.assertEqual(self.app.numbers(), ["A", "B", "C", "D", "E"])
        self.app.set_busy(False)
        for index in range(3):
            self.assertEqual(self.view.context_menu.entrycget(index, "state"), "normal")

    def test_aqua_secondary_and_control_click_keep_existing_multiselection(self):
        if self.app.tk.call("tk", "windowingsystem") != "aqua":
            self.skipTest("Aqua-specific context click bindings")
        for sequence in ("<Button-2>", "<Control-Button-1>"):
            with self.subTest(sequence=sequence):
                self.select("B", "C")
                with patch.object(self.view.context_menu, "tk_popup"):
                    self.context_click("C", sequence)
                self.assertEqual(set(self.tree.selection()), {self.keys["B"], self.keys["C"]})

    def test_minimum_window_fits_four_full_rows_and_manual_columns(self):
        self.app.geometry("1050x710")
        self.view.set_manual_hierarchy(True)
        self.app.update()
        for key in list(self.keys.values())[:4]:
            bounds = self.tree.bbox(key)
            self.assertTrue(bounds)
            self.assertLessEqual(bounds[1] + bounds[3], self.tree.winfo_height())
        self.assertEqual(self.tree.xview(), (0.0, 1.0))
        self.assertFalse(self.view.horizontal_scrollbar.winfo_ismapped())
        self.assertFalse(hasattr(self.view, "remove_button"))
        self.assertFalse(hasattr(self.view, "selected_button"))

    def test_title_uses_remaining_width_and_scrollbar_only_appears_for_overflow(self):
        self.app.geometry("1280x880")
        self.app.update()
        flat_width = self.tree.column("title", "width")
        self.view.set_manual_hierarchy(True)
        self.app.update()
        self.assertLess(self.tree.column("title", "width"), flat_width)
        self.assertEqual(self.tree.xview(), (0.0, 1.0))
        self.assertFalse(self.view.horizontal_scrollbar.winfo_ismapped())
        self.tree.column("number", width=2000)
        self.view.set_manual_hierarchy(False)
        self.app.update()
        self.assertTrue(self.view.horizontal_scrollbar.winfo_ismapped())
        self.tree.column("number", width=160)
        self.view.set_manual_hierarchy(False)
        self.app.update()
        self.assertFalse(self.view.horizontal_scrollbar.winfo_ismapped())
        self.assertEqual(self.tree.xview(), (0.0, 1.0))


if __name__ == "__main__":
    unittest.main()
