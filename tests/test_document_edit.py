"""Document number edits preserve queue identity and provide validated undo."""

import os
import sys
import traceback
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from otClient import Document
from ot_app.actions import DocumentActions
from ot_app.queue_model import QueueRow


class EditController(DocumentActions):
    def __init__(self):
        parent = QueueRow("PARENT", key="parent")
        child = QueueRow(
            "OLD", key="child", parent_key="parent", status="downloaded",
            document=Document("source", "OLD.pdf", "Old title", "", 4),
            candidates=(Document("candidate", "OLD.pdf", "Other", ""),),
            message="Old result", path="/old/file.pdf", size=2048, chosen=True,
        )
        leaf = QueueRow("LEAF", key="leaf", parent_key="child")
        self.rows = {row.key: row for row in (parent, child, leaf)}
        self.selected = ("child",)
        self.documents_view = SimpleNamespace(tree=SimpleNamespace(selection=lambda: self.selected))
        self.busy = False
        self._undo = None
        self.saved = []
        self.rendered = []
        self.notice = ""

    def schedule_document_save(self):
        self.saved.append((self.numbers(), self._hierarchy_numbers()))

    def refresh_table(self):
        self.rendered.append(tuple(replace(row) for row in self.rows.values()))

    def set_notice(self, message, _kind="info"):
        self.notice = message

    def edit(self, result):
        with patch("ot_app.actions.DocumentNumberDialog", return_value=SimpleNamespace(result=result), create=True):
            self.edit_document_number()


class DocumentEditTests(unittest.TestCase):
    def setUp(self):
        self.controller = EditController()

    def test_edit_treats_separators_literally_and_resets_results_without_changing_structure(self):
        controller = self.controller
        controller.edit('  DOC,A;B ["C"]  ')
        self.assertEqual(list(controller.rows), ["parent", "child", "leaf"])
        self.assertEqual(controller.rows["child"], QueueRow('DOC,A;B ["C"]', key="child", parent_key="parent"))
        self.assertEqual(controller.rows["leaf"].parent_key, "child")
        self.assertEqual(controller.saved[-1], (
            ["PARENT", 'DOC,A;B ["C"]', "LEAF"],
            {"PARENT": None, 'DOC,A;B ["C"]': "PARENT", "LEAF": 'DOC,A;B ["C"]'},
        ))
        self.assertEqual(controller.rendered[-1][1], controller.rows["child"])

    def test_edit_requires_exactly_one_selection_and_an_idle_queue(self):
        controller = self.controller
        before = tuple(replace(row) for row in controller.rows.values())
        for selection, busy in (((), False), (("parent", "child"), False), (("child",), True)):
            with self.subTest(selection=selection, busy=busy):
                controller.selected, controller.busy = selection, busy
                with patch("ot_app.actions.DocumentNumberDialog", side_effect=AssertionError("Unexpected modal"), create=True):
                    controller.edit_document_number()
                self.assertEqual(tuple(controller.rows.values()), before)
                self.assertEqual(controller.saved, [])
                self.assertIsNone(controller._undo)

    def test_cancel_or_unchanged_number_preserves_results_and_previous_undo(self):
        controller = self.controller
        controller._remember_structure()
        undo = controller._undo
        before = replace(controller.rows["child"])
        for result in (None, "OLD", "  OLD  "):
            with self.subTest(result=result):
                controller.edit(result)
                self.assertEqual(controller.rows["child"], before)
                self.assertIs(controller._undo, undo)
                self.assertEqual(controller.saved, [])
                self.assertEqual(controller.rendered, [])

    def test_invalid_number_or_exact_duplicate_does_not_mutate_queue(self):
        controller = self.controller
        before = replace(controller.rows["child"])
        for result in (" ", " PARENT ", "bad\x00number", "\ud800", "x" * 1025):
            with self.subTest(result=repr(result)):
                controller.edit(result)
                self.assertEqual(controller.rows["child"], before)
                self.assertIsNone(controller._undo)
                self.assertEqual(controller.saved, [])
                self.assertTrue(controller.notice)
        controller.edit("parent")
        self.assertEqual(controller.rows["child"].number, "parent")

    def test_edit_validates_prospective_total_size_and_document_count(self):
        for limit, value in (("MAX_INPUT_CHARACTERS", 14), ("MAX_DOCUMENTS", 2)):
            with self.subTest(limit=limit):
                controller = EditController()
                with patch("ot_app.documents." + limit, value):
                    controller.edit("LONGER")
                self.assertEqual(controller.numbers(), ["PARENT", "OLD", "LEAF"])
                self.assertEqual(controller.saved, [])
                self.assertIsNone(controller._undo)

    def test_undo_restores_original_results_and_preserves_added_rows(self):
        controller = self.controller
        original = replace(controller.rows["child"])
        controller.edit("NEW")
        controller.rows["child"].status = "error"
        controller.add_numbers(["ADDED"])
        added_key = next(key for key, row in controller.rows.items() if row.number == "ADDED")
        controller.undo_remove()
        self.assertEqual(controller.rows["child"], original)
        self.assertEqual(list(controller.rows), ["parent", "child", "leaf", added_key])
        self.assertEqual(controller.saved[-1][0], ["PARENT", "OLD", "LEAF", "ADDED"])
        self.assertIsNone(controller._undo)

    def test_undo_rejects_collision_without_losing_the_snapshot(self):
        controller = self.controller
        controller.edit("NEW")
        controller.add_numbers(["OLD"])
        undo = controller._undo
        before = tuple(replace(row) for row in controller.rows.values())
        saves = len(controller.saved)
        controller.undo_remove()
        self.assertEqual(tuple(controller.rows.values()), before)
        self.assertEqual(len(controller.saved), saves)
        self.assertIs(controller._undo, undo)
        self.assertIn("Geri alınamadı", controller.notice)

    def test_undo_validates_limits_and_retains_snapshot_on_failure(self):
        controller = self.controller
        controller.edit("X")
        undo = controller._undo
        for limit, value in (("MAX_INPUT_CHARACTERS", 11), ("MAX_DOCUMENTS", 2)):
            with self.subTest(limit=limit):
                with patch("ot_app.documents." + limit, value):
                    controller.undo_remove()
                self.assertEqual(controller.numbers(), ["PARENT", "X", "LEAF"])
                self.assertIs(controller._undo, undo)
                self.assertEqual(len(controller.saved), 1)

    def test_busy_undo_does_not_restore_or_discard_edit_snapshot(self):
        controller = self.controller
        controller.edit("NEW")
        undo = controller._undo
        controller.busy = True
        controller.undo_remove()
        self.assertEqual(controller.rows["child"].number, "NEW")
        self.assertIs(controller._undo, undo)

    def test_structural_undo_after_edit_restores_the_edited_row(self):
        controller = self.controller
        controller.edit("NEW")
        controller.remove_selected()
        self.assertEqual(controller.numbers(), ["PARENT", "LEAF"])
        controller.undo_remove()
        self.assertEqual(controller.numbers(), ["PARENT", "NEW", "LEAF"])
        self.assertEqual(controller.rows["leaf"].parent_key, "child")
        self.assertEqual(controller.rows["child"].status, "pending")


@unittest.skipUnless(os.name == "nt" or sys.platform == "darwin" or os.environ.get("DISPLAY"),
                     "A graphical display is required")
class DocumentEditUITests(unittest.TestCase):
    def setUp(self):
        from ot_app.app import Application
        from ot_app.settings import RegistryStore

        self.store = RegistryStore(platform="darwin")
        self.app = Application(store=self.store)
        self.app.add_numbers(["PARENT", "OLD", "LEAF"])
        self.keys = tuple(self.app.rows)
        self.app.rows[self.keys[1]].parent_key = self.keys[0]
        self.app.rows[self.keys[2]].parent_key = self.keys[1]
        self.app.documents_view.tree.selection_set(self.keys[1])
        self.errors = []

        def report(exception_type, exception, tb):
            self.errors.append("".join(traceback.format_exception(exception_type, exception, tb)))
            for child in self.app.winfo_children():
                if child.winfo_class() == "Toplevel":
                    child.destroy()

        self.app.report_callback_exception = report
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        if self.errors:
            self.fail("Tk callback failed:\n" + "\n".join(self.errors))

    def edit_with(self, action):
        from ot_app.dialogs import DocumentNumberDialog

        def run_action():
            dialog = next(child for child in self.app.winfo_children()
                          if isinstance(child, DocumentNumberDialog))
            action(dialog)

        def watchdog():
            self.errors.append("Document-number modal did not finish its test action.")
            for child in self.app.winfo_children():
                if isinstance(child, DocumentNumberDialog):
                    child.destroy()

        self.app.after(80, run_action)
        timeout = self.app.after(3000, watchdog)
        self.app.edit_document_number()
        self.app.after_cancel(timeout)

    def test_modal_inline_validation_then_enter_saves_and_undo_persists_hierarchy(self):
        def action(dialog):
            self.assertEqual(dialog.number_var.get(), "OLD")
            for invalid in (" ", "PARENT"):
                dialog.number_var.set(invalid)
                dialog.save_button.invoke()
                self.assertTrue(dialog.winfo_exists())
                self.assertTrue(dialog.error_var.get())
                self.assertEqual(self.app.numbers(), ["PARENT", "OLD", "LEAF"])
            dialog.number_var.set("  NEW,A;B  ")
            dialog.entry.focus_force()
            dialog.entry.event_generate("<Return>")

        self.edit_with(action)
        self.assertEqual(self.app.numbers(), ["PARENT", "NEW,A;B", "LEAF"])
        self.assertEqual(self.app.documents_view.tree.selection(), (self.keys[1],))
        self.assertTrue(self.app.flush_document_save())
        self.assertEqual(self.store.load()[1], ["PARENT", "NEW,A;B", "LEAF"])
        self.assertEqual(self.store.load_hierarchy(self.app.numbers()),
                         {"PARENT": None, "NEW,A;B": "PARENT", "LEAF": "NEW,A;B"})
        self.app.undo_remove()
        self.assertTrue(self.app.flush_document_save())
        self.assertEqual(self.store.load()[1], ["PARENT", "OLD", "LEAF"])
        self.assertEqual(self.store.load_hierarchy(self.app.numbers()),
                         {"PARENT": None, "OLD": "PARENT", "LEAF": "OLD"})

    def test_escape_and_cancel_button_leave_number_and_undo_unchanged(self):
        self.app._remember_structure()
        undo = self.app._undo
        for escape in (False, True):
            with self.subTest(escape=escape):
                def action(dialog):
                    dialog.number_var.set("CHANGED")
                    if escape:
                        dialog.entry.focus_force()
                        dialog.entry.event_generate("<Escape>")
                    else:
                        dialog.cancel_button.invoke()

                self.edit_with(action)
                self.assertEqual(self.app.numbers(), ["PARENT", "OLD", "LEAF"])
                self.assertIs(self.app._undo, undo)


if __name__ == "__main__":
    unittest.main()
