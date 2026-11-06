"""Manual hierarchy operations preserve whole subtrees and preorder."""

from dataclasses import FrozenInstanceError
import unittest

from ot_app.hierarchy import (
    HierarchyEntry,
    HierarchyError,
    hierarchy_indices,
    move_hierarchy,
    remove_hierarchy,
    validate_hierarchy,
)
from ot_app.queue_model import QueueRow


def entries(*pairs):
    return tuple(HierarchyEntry(*pair) for pair in pairs)


class HierarchyTests(unittest.TestCase):
    def test_numbering_and_sequential_indent_outdent(self):
        original = entries(("a",), ("b",), ("c",))
        self.assertEqual(hierarchy_indices(original), {"a": "1", "b": "2", "c": "3"})
        nested_b = move_hierarchy(original, ["b"], "indent")
        self.assertEqual(hierarchy_indices(nested_b), {"a": "1", "b": "1.1", "c": "2"})
        nested_c = move_hierarchy(nested_b, ["c"], "indent")
        self.assertEqual(hierarchy_indices(nested_c), {"a": "1", "b": "1.1", "c": "1.2"})
        deeper_c = move_hierarchy(nested_c, ["c"], "indent")
        self.assertEqual(hierarchy_indices(deeper_c), {"a": "1", "b": "1.1", "c": "1.1.1"})
        self.assertEqual(move_hierarchy(deeper_c, ["c"], "outdent"), nested_c)
        self.assertEqual(move_hierarchy(nested_c, ["c"], "outdent"), nested_b)
        self.assertEqual(move_hierarchy(nested_b, ["b"], "outdent"), original)

    def test_indent_moves_selected_parent_with_its_subtree_after_existing_children(self):
        original = entries(("a",), ("aa", "a"), ("b",), ("bb", "b"), ("c",))
        result = move_hierarchy(original, ["b"], "indent")
        self.assertEqual(result, entries(("a",), ("aa", "a"), ("b", "a"), ("bb", "b"), ("c",)))
        self.assertEqual(hierarchy_indices(result)["b"], "1.2")
        self.assertEqual(original[2].parent_key, None)

    def test_outdent_moves_subtree_after_remaining_parent_subtree(self):
        original = entries(("a",), ("b", "a"), ("bb", "b"), ("c", "a"), ("cc", "c"), ("d",))
        result = move_hierarchy(original, ["b"], "outdent")
        self.assertEqual(result, entries(("a",), ("c", "a"), ("cc", "c"), ("b",), ("bb", "b"), ("d",)))
        validate_hierarchy(result)

    def test_outdent_uses_grandparent_and_keeps_other_ancestors(self):
        original = entries(("a",), ("b", "a"), ("c", "b"), ("d", "b"), ("e", "a"))
        self.assertEqual(
            move_hierarchy(original, ["c"], "outdent"),
            entries(("a",), ("b", "a"), ("d", "b"), ("c", "a"), ("e", "a")),
        )

    def test_multiple_sibling_subtrees_move_as_one_block(self):
        original = entries(("a",), ("b",), ("bb", "b"), ("c",), ("cc", "c"), ("d",))
        result = move_hierarchy(original, iter(["c", "b", "b"]), "indent")
        self.assertEqual(result, entries(("a",), ("b", "a"), ("bb", "b"), ("c", "a"), ("cc", "c"), ("d",)))
        self.assertEqual(move_hierarchy(result, ["b", "c"], "outdent"), original)

    def test_outdent_block_passes_remaining_sibling_subtrees(self):
        original = entries(("a",), ("b", "a"), ("c", "a"), ("cc", "c"), ("d", "a"), ("e",))
        self.assertEqual(
            move_hierarchy(original, ["b", "c"], "outdent"),
            entries(("a",), ("d", "a"), ("b",), ("c",), ("cc", "c"), ("e",)),
        )

    def test_selected_descendants_are_normalized_before_sibling_validation(self):
        original = entries(("a",), ("b",), ("bb", "b"), ("bbb", "bb"), ("c",))
        self.assertEqual(
            move_hierarchy(original, ["bbb", "c", "b", "bb"], "indent"),
            entries(("a",), ("b", "a"), ("bb", "b"), ("bbb", "bb"), ("c", "a")),
        )

    def test_invalid_selection_is_atomic(self):
        original = entries(("a",), ("aa", "a"), ("ab", "a"), ("b",), ("c",))
        for selection in (["a", "c"], ["aa", "b"], ["missing"]):
            for direction in ("indent", "outdent"):
                with self.subTest(selection=selection, direction=direction):
                    with self.assertRaises(HierarchyError) as error:
                        move_hierarchy(original, selection, direction)
                    self.assertTrue(str(error.exception))
        self.assertEqual(original, entries(("a",), ("aa", "a"), ("ab", "a"), ("b",), ("c",)))

    def test_boundary_and_empty_selections_are_noops(self):
        original = entries(("a",), ("aa", "a"), ("b",))
        for selection, direction in ((["a"], "indent"), (["aa"], "indent"), (["b"], "outdent"), ([], "indent")):
            with self.subTest(selection=selection, direction=direction):
                self.assertEqual(move_hierarchy(original, selection, direction), original)
        self.assertEqual(move_hierarchy((), [], "outdent"), ())
        with self.assertRaises(HierarchyError):
            move_hierarchy(original, [], "right")

    def test_remove_only_selected_entries_and_promote_to_nearest_survivor(self):
        original = entries(("a",), ("b", "a"), ("c", "b"), ("d", "c"), ("e", "d"), ("f", "a"), ("g",))
        result = remove_hierarchy(original, ["b", "c", "f"])
        self.assertEqual(result, entries(("a",), ("d", "a"), ("e", "d"), ("g",)))
        self.assertEqual(remove_hierarchy(original, ["a", "b", "c"]), entries(("d",), ("e", "d"), ("f",), ("g",)))
        self.assertEqual(remove_hierarchy(original, []), original)
        self.assertEqual(remove_hierarchy(original, (entry.key for entry in original)), ())
        self.assertEqual(original[3].parent_key, "c")

    def test_remove_rejects_unknown_selected_keys(self):
        with self.assertRaises(HierarchyError):
            remove_hierarchy(entries(("a",)), ["missing"])

    def test_validator_rejects_invalid_graphs_and_noncontiguous_preorder(self):
        invalid = (
            entries(("a",), ("a",)),
            entries(("a", "missing")),
            entries(("a", "b"), ("b",)),
            entries(("a", "a")),
            entries(("a", "b"), ("b", "a")),
            entries(("a",), ("b",), ("aa", "a")),
            entries(("a",), ("b", "a"), ("c", "a"), ("bb", "b")),
        )
        for original in invalid:
            for operation in (
                lambda: validate_hierarchy(original),
                lambda: hierarchy_indices(original),
                lambda: move_hierarchy(original, [], "indent"),
                lambda: remove_hierarchy(original, []),
            ):
                with self.subTest(original=original), self.assertRaises(HierarchyError):
                    operation()

    def test_valid_empty_forest_and_indices_after_sibling_branches(self):
        self.assertIsNone(validate_hierarchy(()))
        self.assertEqual(hierarchy_indices(()), {})
        original = entries(("a",), ("b", "a"), ("c", "b"), ("d", "a"), ("e",), ("f", "e"))
        self.assertEqual(hierarchy_indices(original), {"a": "1", "b": "1.1", "c": "1.1.1", "d": "1.2", "e": "2", "f": "2.1"})

    def test_validator_rejects_non_string_keys_and_parents_as_hierarchy_errors(self):
        for invalid in (HierarchyEntry(1), HierarchyEntry([]), HierarchyEntry("a", 1), HierarchyEntry("a", [])):
            with self.subTest(entry=invalid), self.assertRaises(HierarchyError):
                validate_hierarchy((invalid,))

    def test_deep_hierarchy_is_iterative(self):
        original = tuple(HierarchyEntry(str(index), str(index - 1) if index else None) for index in range(1500))
        validate_hierarchy(original)
        self.assertEqual(hierarchy_indices(original)["1499"], ".".join(["1"] * 1500))
        result = move_hierarchy(original, ["1499"], "outdent")
        self.assertEqual(result[-1].parent_key, "1497")
        self.assertEqual(remove_hierarchy(original, (str(index) for index in range(1499))), entries(("1499",)))

    def test_ten_thousand_roots_support_block_moves(self):
        original = tuple(HierarchyEntry(str(index)) for index in range(10000))
        self.assertEqual(hierarchy_indices(original)["9999"], "10000")
        result = move_hierarchy(original, (str(index) for index in range(1, 10000)), "indent")
        self.assertEqual(hierarchy_indices(result)["9999"], "1.9999")
        self.assertEqual(move_hierarchy(result, (str(index) for index in range(1, 10000)), "outdent"), original)

    def test_entries_are_frozen_and_queue_parent_defaults_preserve_old_arguments(self):
        entry = HierarchyEntry("a")
        with self.assertRaises(FrozenInstanceError):
            entry.parent_key = "b"
        row = QueueRow("DOC", "key", "pending", None, (), "ready", "", None, True)
        self.assertTrue(row.chosen)
        self.assertIsNone(row.parent_key)
        self.assertEqual(QueueRow("DOC", parent_key="parent").parent_key, "parent")


if __name__ == "__main__":
    unittest.main()
