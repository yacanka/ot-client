"""Manual queue hierarchy downloads without a GUI or live service."""
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch

from otClient import Document, OTError
from ot_app.settings import AppSettings
from ot_app.storage import resolve_document_folder
from ot_app.worker import DownloadWorker, JobItem
from tests.test_worker import FakeConnector


def doc(key):
    return Document(key, key.upper() + ".pdf", "", "")


class HierarchyWorkerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.settings = AppSettings(base_url="https://ot.example", username="test",
                                    password="test", output_dir=str(self.root))
        self.settings.manual_folder_hierarchy_enabled = True
        self.client = FakeConnector()
        self.cancel = threading.Event()
        self.events = queue.Queue()

    def item(self, key, parent=None, selected=True):
        return JobItem(key, key.upper(), doc(key) if selected else None, parent)

    def run_worker(self, items, hierarchy=None):
        worker = DownloadWorker(self.settings, items, self.events, self.cancel,
                                connector_factory=self.client.factory, hierarchy=hierarchy)
        worker.run()
        return self.collect()

    def collect(self):
        events = []
        while not self.events.empty():
            events.append(self.events.get_nowait())
        return events

    def last(self, events, key):
        return [event.payload for event in events if event.kind == "status" and event.key == key][-1]

    def test_job_item_has_immutable_optional_parent_and_preserves_old_constructor(self):
        self.assertIn("parent_key", {field.name for field in fields(JobItem)})
        item = JobItem("a", "A", doc("a"))
        self.assertIsNone(item.parent_key)
        self.assertIsNone(item.row_index)
        self.assertEqual(JobItem("b", "B", doc("b"), "a").parent_key, "a")
        with self.assertRaises(FrozenInstanceError):
            item.parent_key = "b"
        with self.assertRaises(FrozenInstanceError):
            item.row_index = "2"

    def test_folder_options_cover_all_four_combinations(self):
        items = [self.item("a"), self.item("b", "a"), self.item("c", "b")]
        for manual, individual, expected, calls in (
            (False, False, ("A.pdf", "B.pdf", "C.pdf"), 0),
            (False, True, ("A/A.pdf", "B/B.pdf", "C/C.pdf"), 3),
            (True, False, ("A/A.pdf", "A/B/B.pdf", "A/B/C.pdf"), 2),
            (True, True, ("A/A.pdf", "A/B/B.pdf", "A/B/C/C.pdf"), 3),
        ):
            with self.subTest(manual=manual, individual=individual):
                output = self.root / f"{manual}-{individual}"
                output.mkdir()
                self.settings.output_dir = str(output)
                self.settings.manual_folder_hierarchy_enabled = manual
                self.settings.document_subfolder_enabled = individual
                with patch("ot_app.worker.resolve_document_folder", wraps=resolve_document_folder) as resolver:
                    events = self.run_worker(items, tuple(items))
                self.assertEqual(resolver.call_count, calls)
                for item, path in zip(items, expected):
                    self.assertEqual(self.last(events, item.key)["status"], "downloaded")
                    self.assertEqual(self.last(events, item.key)["path"], str(output / path))
                    self.assertTrue((output / path).is_file())

    def test_parent_only_selection_uses_children_from_complete_hierarchy(self):
        a, b = self.item("a"), self.item("b", "a", selected=False)
        with patch("ot_app.worker.resolve_document_folder", wraps=resolve_document_folder) as resolver:
            events = self.run_worker([a], (a, b))
        self.assertEqual(resolver.call_count, 1)
        self.assertEqual(self.last(events, "a")["path"], str(self.root / "A/A.pdf"))
        self.assertEqual([call["id"] for call in self.client.downloads], ["a"])
        self.assertEqual(self.client.searches, [])
        self.assertFalse((self.root / "A/B").exists())

    def test_parent_folders_only_resolve_shared_ancestors_once_without_their_media(self):
        hierarchy = (self.item("a", selected=False), self.item("b", "a", False),
                     self.item("c", "b"), self.item("d", "b"))
        self.client.results = {"A": [doc("a")], "B": [doc("b")]}
        with patch("ot_app.worker.resolve_document_folder", wraps=resolve_document_folder) as resolver:
            events = self.run_worker(list(hierarchy[2:]), hierarchy)
        self.assertEqual(resolver.call_count, 2)
        self.assertEqual(self.client.searches, ["A", "B"])
        self.assertEqual([call["id"] for call in self.client.downloads], ["c", "d"])
        self.assertEqual(self.last(events, "c")["path"], str(self.root / "A/B/C.pdf"))
        self.assertEqual(self.last(events, "d")["path"], str(self.root / "A/B/D.pdf"))

    def test_leaf_skips_folder_resolution_even_when_matching_directories_exist(self):
        a, b = self.item("a"), self.item("b", "a")
        for match, directories in (("exact", ("B",)), ("contains", ("first B", "second B"))):
            with self.subTest(match=match):
                output = self.root / match
                parent = output / "A"
                parent.mkdir(parents=True)
                for name in directories:
                    (parent / name).mkdir()
                self.settings.output_dir = str(output)
                self.settings.document_subfolder_match = match
                with patch("ot_app.worker.resolve_document_folder", wraps=resolve_document_folder) as resolver:
                    events = self.run_worker([b], (a, b))
                self.assertEqual(resolver.call_count, 1)
                self.assertEqual(resolver.call_args.args[1].id, "a")
                self.assertEqual(self.last(events, "b")["path"], str(parent / "B.pdf"))
                self.assertTrue(all(not list((parent / name).iterdir()) for name in directories))

    def test_root_leaf_downloads_directly_without_resolving_any_folder(self):
        (self.root / "first A").mkdir()
        (self.root / "second A").mkdir()
        self.settings.document_subfolder_match = "contains"
        with patch("ot_app.worker.resolve_document_folder", wraps=resolve_document_folder) as resolver:
            events = self.run_worker([self.item("a")])
        resolver.assert_not_called()
        self.assertEqual(self.last(events, "a")["path"], str(self.root / "A.pdf"))

    def test_parent_folders_still_reject_self_and_escaping_links(self):
        a, b = self.item("a"), self.item("b", "a")
        with tempfile.TemporaryDirectory() as outside:
            for target in (self.root, Path(outside)):
                with self.subTest(target=target):
                    link = self.root / "A"
                    link.symlink_to(target, target_is_directory=True)
                    try:
                        events = self.run_worker([b], (a, b))
                        self.assertEqual(self.last(events, "b")["status"], "error")
                        self.assertEqual(self.client.downloads, [])
                        self.assertEqual(list(Path(outside).iterdir()), [])
                    finally:
                        link.unlink()

    def test_manual_indices_use_complete_snapshot_and_each_ancestors_own_index(self):
        self.settings.filename_format = "{index}-{numara}"
        self.settings.document_subfolder_format = "{index}-{numara}"
        hierarchy = (self.item("a"), self.item("b", "a"), self.item("c", "b"),
                     self.item("d", "b"), self.item("e"))
        with patch("ot_app.worker.resolve_document_folder", wraps=resolve_document_folder) as resolver:
            events = self.run_worker([hierarchy[3]], hierarchy)
        self.assertEqual([call.kwargs["index"] for call in resolver.call_args_list], ["1", "1.1"])
        self.assertEqual(self.last(events, "d")["path"], str(self.root / "1-A/1.1-B/1.1.2-D.pdf"))
        self.assertEqual([call["id"] for call in self.client.downloads], ["d"])

    def test_explicit_manual_indices_override_fallback_without_rewriting_snapshot(self):
        self.settings.filename_format = "{index}-{numara}"
        self.settings.document_subfolder_format = "{index}-{numara}"
        a = replace(self.item("a"), row_index="4")
        b = replace(self.item("b", "a"), row_index="4.7")
        events = self.run_worker([b], (a, b))
        self.assertEqual(self.last(events, "b")["path"], str(self.root / "4-A/4.7-B.pdf"))
        self.assertEqual((a.row_index, b.row_index), ("4", "4.7"))

    def test_mismatched_explicit_index_fails_snapshot_validation_before_io(self):
        a, b = self.item("a"), self.item("b", "a")
        events = self.run_worker([replace(b, row_index="1.1")], (a, b))
        self.assertTrue(any(event.kind == "fatal" for event in events))
        self.assertEqual(self.client.constructed, 0)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_shared_root_leaves_preserve_first_document_on_filename_collision(self):
        a = JobItem("a", "A", Document("a", "same.pdf", "A", ""))
        b = JobItem("b", "B", Document("b", "SAME.pdf", "B", ""))
        events = self.run_worker([a, b], (a, b))
        self.assertEqual(self.last(events, "a")["status"], "downloaded")
        self.assertEqual(self.last(events, "b")["status"], "error")
        self.assertEqual([call["id"] for call in self.client.downloads], ["a"])
        self.assertEqual((self.root / "same.pdf").read_bytes(), b"document a")

    def test_parent_and_leaf_preserve_first_document_on_filename_collision(self):
        self.settings.document_subfolder_format = "{ad}"
        a = JobItem("a", "A", Document("a", "same.pdf", "A", ""))
        b = JobItem("b", "B", Document("b", "SAME.pdf", "B", ""), "a")
        events = self.run_worker([a, b], (a, b))
        self.assertEqual(self.last(events, "a")["status"], "downloaded")
        self.assertEqual(self.last(events, "b")["status"], "error")
        self.assertEqual([call["id"] for call in self.client.downloads], ["a"])
        self.assertEqual((self.root / "A/same.pdf").read_bytes(), b"document a")

    def test_three_levels_download_to_each_nested_folder(self):
        self.settings.document_subfolder_enabled = True
        items = [self.item("a"), self.item("b", "a"), self.item("c", "b")]
        events = self.run_worker(items, tuple(items))
        for key, folder in (("a", "A"), ("b", "A/B"), ("c", "A/B/C")):
            self.assertEqual(self.last(events, key)["status"], "downloaded")
            self.assertTrue((self.root / folder / (key.upper() + ".pdf")).is_file())

    def test_child_only_resolves_shared_ancestors_once_without_their_media(self):
        self.settings.document_subfolder_enabled = True
        hierarchy = (self.item("a", selected=False), self.item("b", "a", False),
                     self.item("c", "b"), self.item("d", "b"))
        self.client.results = {"A": [doc("a")], "B": [doc("b")]}
        events = self.run_worker(list(hierarchy[2:]), hierarchy)
        self.assertEqual(self.client.searches, ["A", "B"])
        self.assertEqual([call["id"] for call in self.client.downloads], ["c", "d"])
        self.assertEqual(self.last(events, "c")["path"], str(self.root / "A/B/C/C.pdf"))
        resolutions = [event for event in events if event.kind == "hierarchy_resolution"]
        self.assertEqual([event.key for event in resolutions], ["a", "b"])
        self.assertTrue(all(event.payload["candidates"] == () for event in resolutions))
        self.assertFalse(any(event.kind == "status" and event.key in ("a", "b") for event in events))

    def test_ambiguous_unselected_ancestor_publishes_candidates_and_blocks_descendant(self):
        ancestor, child = self.item("a", selected=False), self.item("b", "a")
        candidates = [doc("x"), doc("y")]
        self.client.results["A"] = candidates
        events = self.run_worker([child], (ancestor, child))
        resolution = [event for event in events if event.kind == "hierarchy_resolution"][0]
        self.assertEqual(resolution.key, "a")
        self.assertEqual(resolution.payload["candidates"], tuple(candidates))
        self.assertNotIn("document", resolution.payload)
        self.assertEqual(self.last(events, "b")["status"], "error")
        self.assertIn("A", self.last(events, "b")["message"])
        self.assertEqual(self.client.downloads, [])

    def test_missing_ancestor_is_cached_and_independent_root_downloads(self):
        a, b, c, d = self.item("a", selected=False), self.item("b", "a"), self.item("c", "a"), self.item("d")
        events = self.run_worker([b, c, d], (a, b, c, d))
        self.assertEqual(self.client.searches, ["A"])
        self.assertEqual(self.last(events, "b")["status"], "error")
        self.assertEqual(self.last(events, "c")["status"], "error")
        self.assertEqual(self.last(events, "d")["status"], "downloaded")

    def test_selected_parent_keeps_not_found_or_ambiguous_status(self):
        for results, status in (([], "not_found"), ([doc("x"), doc("y")], "ambiguous")):
            with self.subTest(status=status):
                self.client.results["A"] = results
                a, b = self.item("a", selected=False), self.item("b", "a")
                events = self.run_worker([a, b], (a, b))
                self.assertEqual(self.last(events, "a")["status"], status)
                self.assertEqual(self.last(events, "b")["status"], "error")
        self.assertEqual(self.client.searches, ["A", "A"])

    def test_parent_media_failure_does_not_block_child_metadata_and_folder(self):
        self.settings.document_subfolder_enabled = True
        a, b = self.item("a"), self.item("b", "a")
        self.client.download_errors["a"] = OTError("media failed")
        events = self.run_worker([a, b], (a, b))
        self.assertEqual(self.last(events, "a")["status"], "error")
        self.assertEqual(self.last(events, "b")["status"], "downloaded")
        self.assertTrue((self.root / "A/B/B.pdf").is_file())

    def test_expected_ancestor_search_error_is_cached_but_retry_is_fresh(self):
        a, b, c = self.item("a", selected=False), self.item("b", "a"), self.item("c", "a")
        self.client.results["A"] = OTError("search failed")
        events = self.run_worker([b, c], (a, b, c))
        self.assertEqual(self.client.searches, ["A"])
        self.assertEqual(self.last(events, "c")["status"], "error")
        self.client.results["A"] = [doc("a")]
        events = self.run_worker([b], (a, b, c))
        self.assertEqual(self.client.searches, ["A", "A"])
        self.assertEqual(self.last(events, "b")["status"], "downloaded")

    def test_folder_ambiguity_is_cached_and_descendants_use_folder_ambiguous(self):
        self.settings.document_subfolder_match = "contains"
        (self.root / "one A").mkdir()
        (self.root / "two A").mkdir()
        a, b, c = self.item("a"), self.item("b", "a"), self.item("c", "a")
        with patch("ot_app.worker.resolve_document_folder", wraps=resolve_document_folder) as resolver:
            events = self.run_worker([b, c], (a, b, c))
        self.assertEqual(resolver.call_count, 1)
        self.assertEqual(self.last(events, "b")["status"], "folder_ambiguous")
        self.assertEqual(self.last(events, "c")["status"], "folder_ambiguous")

    def test_snapshot_survives_input_and_settings_changes(self):
        self.settings.document_subfolder_enabled = True
        a, b = self.item("a"), self.item("b", "a")
        items, hierarchy = [b], [a, b]
        worker = DownloadWorker(self.settings, items, self.events, self.cancel,
                                connector_factory=self.client.factory, hierarchy=hierarchy)
        items.clear()
        hierarchy.clear()
        self.settings.manual_folder_hierarchy_enabled = False
        self.settings.document_subfolder_format = "changed"
        worker.run()
        self.assertTrue((self.root / "A/B/B.pdf").is_file())

    def test_invalid_or_incomplete_hierarchy_fails_before_any_io(self):
        a, b = self.item("a"), self.item("b", "a")
        for items, hierarchy in (([b], None), ([a, b], None), ([b], (a,)), ([a], (a, a)),
                                 ([b], (b, a)), ([a], (a, self.item("c"), b)),
                                 ([b], (a, self.item("b"))), ([a, a], (a,))):
            with self.subTest(items=items, hierarchy=hierarchy):
                with patch.object(Path, "mkdir") as mkdir:
                    events = self.run_worker(items, hierarchy)
                self.assertTrue(any(event.kind == "fatal" for event in events))
                mkdir.assert_not_called()
                self.assertEqual(self.client.constructed, 0)

    def test_roots_only_fallback_works_without_explicit_hierarchy(self):
        self.settings.document_subfolder_enabled = True
        events = self.run_worker([self.item("a")])
        self.assertEqual(self.last(events, "a")["status"], "downloaded")
        self.assertTrue((self.root / "A/A.pdf").is_file())

    def test_nested_contains_match_uses_actual_parent_directory(self):
        self.settings.document_subfolder_enabled = True
        parent = self.root / "old A"
        child = parent / "old B"
        child.mkdir(parents=True)
        (self.root / "B").mkdir()
        self.settings.document_subfolder_match = "contains"
        a, b = self.item("a"), self.item("b", "a")
        events = self.run_worker([b], (a, b))
        self.assertEqual(self.last(events, "b")["path"], str(child / "B.pdf"))

    def test_nested_contains_ambiguity_does_not_download_to_root_match(self):
        self.settings.document_subfolder_enabled = True
        parent = self.root / "A"
        (parent / "first B").mkdir(parents=True)
        (parent / "second B").mkdir()
        (self.root / "B").mkdir()
        self.settings.document_subfolder_match = "contains"
        a, b = self.item("a"), self.item("b", "a")
        events = self.run_worker([b], (a, b))
        self.assertEqual(self.last(events, "b")["status"], "folder_ambiguous")
        self.assertEqual(self.client.downloads, [])

    def test_unrequired_hierarchy_branch_is_not_resolved(self):
        a, b, c = self.item("a"), self.item("b", "a"), self.item("c", selected=False)
        events = self.run_worker([b], (a, b, c))
        self.assertEqual(self.last(events, "b")["status"], "downloaded")
        self.assertEqual(self.client.searches, [])
        self.assertFalse((self.root / "C").exists())

    def test_each_level_rejects_escape_or_self_link(self):
        self.settings.document_subfolder_enabled = True
        a, b = self.item("a"), self.item("b", "a")
        parent = self.root / "A"
        parent.mkdir()
        for target in (self.root, parent):
            with self.subTest(target=target):
                link = parent / "B"
                link.symlink_to(target, target_is_directory=True)
                try:
                    events = self.run_worker([b], (a, b))
                    self.assertEqual(self.last(events, "b")["status"], "error")
                    self.assertEqual(self.client.downloads, [])
                finally:
                    link.unlink()

    def test_root_node_rejects_self_link_in_manual_mode_only(self):
        self.settings.document_subfolder_enabled = True
        (self.root / "A").symlink_to(self.root, target_is_directory=True)
        events = self.run_worker([self.item("a")])
        self.assertEqual(self.last(events, "a")["status"], "error")
        self.settings.manual_folder_hierarchy_enabled = False
        self.settings.document_subfolder_enabled = True
        events = self.run_worker([self.item("a")])
        self.assertEqual(self.last(events, "a")["status"], "downloaded")

    def test_cancel_during_ancestor_search_stops_before_folder_and_media(self):
        a, b, c = self.item("a", selected=False), self.item("b", "a"), self.item("c")
        def cancel_search():
            self.cancel.set()
            return [doc("a")]
        self.client.results["A"] = cancel_search
        events = self.run_worker([b, c], (a, b, c))
        self.assertEqual(self.last(events, "b")["status"], "cancelled")
        self.assertEqual(self.last(events, "c")["status"], "cancelled")
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.client.downloads, [])

    def test_unexpected_ancestor_error_is_fatal_and_sanitized(self):
        a, b = self.item("a", selected=False), self.item("b", "a")
        self.client.results["A"] = RuntimeError("private server details")
        events = self.run_worker([b], (a, b))
        fatal = [event.payload["message"] for event in events if event.kind == "fatal"]
        self.assertEqual(len(fatal), 1)
        self.assertNotIn("private server details", fatal[0])

    def test_flat_mode_ignores_parent_links_and_preserves_existing_destination(self):
        self.settings.manual_folder_hierarchy_enabled = False
        b = self.item("b", "missing")
        events = self.run_worker([b])
        self.assertEqual(self.last(events, "b")["path"], str(self.root / "B.pdf"))

    def test_filename_collision_in_shared_nested_folder_keeps_first_document(self):
        self.settings.document_subfolder_enabled = True
        self.settings.document_subfolder_format = "{ad}"
        a = JobItem("a", "A", Document("a", "A.pdf", "shared", ""))
        b = JobItem("b", "B", Document("b", "same.pdf", "shared", ""), "a")
        c = JobItem("c", "C", Document("c", "same.pdf", "shared", ""), "a")
        events = self.run_worker([b, c], (a, b, c))
        self.assertEqual(self.last(events, "b")["status"], "downloaded")
        self.assertEqual(self.last(events, "c")["status"], "error")
        self.assertEqual((self.root / "shared/shared/same.pdf").read_bytes(), b"document b")

    def test_nested_related_media_stays_with_primary_document(self):
        self.settings.document_subfolder_enabled = True
        self.settings.download_related_forms = True
        self.settings.download_related_attachments = True
        a, b = self.item("a"), self.item("b", "a")
        def details(identifier, content_type):
            if identifier == "b":
                return {"properties": {"forms": ["form"], "attachments": ["attachment"]}}
            return {"properties": {"id": identifier, "object_name": identifier + ".pdf"}}
        self.client.get_document_by_id = details
        events = self.run_worker([b], (a, b))
        self.assertEqual(self.last(events, "b")["status"], "downloaded")
        self.assertEqual(sorted(path.name for path in (self.root / "A/B").iterdir()),
                         ["B.pdf", "attachment.pdf", "form.pdf"])
        self.assertEqual([call["content_type"] for call in self.client.downloads],
                         ["tds_document", "tds_form", "tds_attachment"])

    def test_deep_required_ancestors_are_resolved_iteratively(self):
        self.settings.document_subfolder_enabled = True
        hierarchy = tuple(self.item(str(index), str(index - 1) if index else None)
                          for index in range(1100))
        with patch("ot_app.worker.resolve_document_folder", return_value=self.root) as resolver:
            events = self.run_worker([hierarchy[-1]], hierarchy)
        self.assertEqual(resolver.call_count, 1100)
        self.assertEqual(self.last(events, "1099")["status"], "downloaded")
