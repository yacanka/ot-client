"""Real filesystem coverage for document folder matching and containment."""

from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from otClient import Document, OTError
from ot_app.storage import FolderAmbiguityError, resolve_document_folder


class DocumentFolderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name).resolve()
        self.root = self.parent / "output"
        self.root.mkdir()
        self.document = Document("1", "ABC.pdf", "A document", "", 3)

    def resolve(self, match="exact", *, folder_format="{numara}", document=None, root=None):
        return resolve_document_folder(
            root or self.root, document or self.document, folder_format, match
        )

    def test_no_match_creates_generated_child_in_missing_root(self):
        self.root = self.root / "new"
        target = self.resolve()
        self.assertEqual(target, self.root / "ABC")
        self.assertTrue(target.is_dir())

    def test_exact_match_reuses_case_insensitive_directory(self):
        existing = self.root / "aBc"
        existing.mkdir()
        self.assertEqual(self.resolve(), existing)
        self.assertEqual(list(self.root.iterdir()), [existing])

    def test_contains_uses_generated_name_as_case_insensitive_substring(self):
        existing = self.root / "Archive aBc approved"
        existing.mkdir()
        self.assertEqual(self.resolve("contains"), existing)
        self.assertEqual(list(self.root.iterdir()), [existing])

    def test_exact_match_wins_over_multiple_partial_matches(self):
        for name in ("ABC", "old ABC", "ABC approved"):
            (self.root / name).mkdir()
        for match in ("exact", "contains"):
            with self.subTest(match=match):
                self.assertEqual(self.resolve(match), self.root / "ABC")

    def test_exact_mode_ignores_partial_matches(self):
        (self.root / "old ABC").mkdir()
        self.assertEqual(self.resolve(), self.root / "ABC")

    def test_matching_is_limited_to_immediate_children(self):
        nested = self.root / "archive" / "ABC"
        nested.mkdir(parents=True)
        self.assertEqual(self.resolve("contains"), self.root / "ABC")

    def test_multiple_partial_directories_are_ambiguous_without_creating_a_folder(self):
        for name in ("old ABC", "ABC approved"):
            (self.root / name).mkdir()
        with self.assertRaises(FolderAmbiguityError):
            self.resolve("contains")
        self.assertFalse((self.root / "ABC").exists())

    def test_case_equivalent_exact_entries_are_ambiguous(self):
        paths = [self.root / "ABC", self.root / "abc"]
        paths[0].mkdir()
        # A case-insensitive host cannot create these two distinct entries.
        # Feed both observed names to the resolver while keeping real directories.
        with mock.patch.object(Path, "iterdir", return_value=iter(paths)):
            with self.assertRaises(FolderAmbiguityError):
                self.resolve()

    def test_same_name_file_is_rejected_even_with_partial_directory_match(self):
        (self.root / "aBc").write_bytes(b"keep")
        (self.root / "old ABC").mkdir()
        with self.assertRaises(OTError):
            self.resolve("contains")
        self.assertEqual((self.root / "aBc").read_bytes(), b"keep")

    def test_partial_matching_files_are_not_directory_candidates(self):
        (self.root / "old ABC.txt").write_bytes(b"keep")
        self.assertEqual(self.resolve("contains"), self.root / "ABC")

    def test_matching_links_outside_root_are_rejected_without_creating_folder(self):
        outside = self.parent / "outside"
        outside.mkdir()
        for name, match in (("ABC", "exact"), ("old ABC", "contains")):
            with self.subTest(name=name):
                link = self.root / name
                link.symlink_to(outside, target_is_directory=True)
                try:
                    with self.assertRaises(OTError):
                        self.resolve(match)
                    self.assertEqual(list(outside.iterdir()), [])
                    self.assertEqual(list(self.root.iterdir()), [link])
                finally:
                    link.unlink()

    def test_broken_matching_link_cannot_be_hidden_as_no_match(self):
        link = self.root / "old ABC"
        link.symlink_to(self.parent / "missing", target_is_directory=True)
        with self.assertRaises((OTError, OSError)):
            self.resolve("contains")
        self.assertEqual(list(self.root.iterdir()), [link])

    def test_broken_junction_candidate_cannot_be_hidden_as_no_match(self):
        link = self.root / "old ABC"
        link.symlink_to(self.parent / "missing", target_is_directory=True)
        original_lstat = Path.lstat

        def junction_stat(path):
            if path == link:
                return SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return original_lstat(path)

        # Python 3.11 junctions can be non-directory, non-symlink reparse points.
        with mock.patch.object(Path, "is_symlink", return_value=False), \
                mock.patch.object(Path, "lstat", junction_stat):
            with self.assertRaises((OTError, OSError)):
                self.resolve("contains")
        self.assertEqual(list(self.root.iterdir()), [link])

    def test_directory_created_after_scan_is_checked_for_escape(self):
        outside = self.parent / "outside"
        outside.mkdir()
        original_mkdir = Path.mkdir

        def create_link_instead(path, *args, **kwargs):
            if path == self.root / "ABC":
                path.symlink_to(outside, target_is_directory=True)
                return None
            return original_mkdir(path, *args, **kwargs)

        with mock.patch.object(Path, "mkdir", create_link_instead):
            with self.assertRaises(OTError):
                self.resolve()
        self.assertEqual(list(outside.iterdir()), [])

    def test_link_inside_root_returns_resolved_target(self):
        target = self.root / "actual"
        target.mkdir()
        (self.root / "ABC").symlink_to(target, target_is_directory=True)
        self.assertEqual(self.resolve(), target)

    def test_explicit_root_link_is_resolved_like_existing_download_root(self):
        alias = self.parent / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.assertEqual(self.resolve(root=alias), self.root / "ABC")

    def test_metadata_is_sanitized_without_document_id_for_shared_folders(self):
        first = Document("1", "A.pdf", "../CON:shared", "", 0)
        second = Document("2", "B.pdf", "../CON:shared", "", 0)
        first_path = self.resolve(folder_format="{ad}", document=first)
        second_path = self.resolve(folder_format="{ad}", document=second)
        self.assertEqual(first_path, second_path)
        self.assertEqual(first_path.parent, self.root)
        self.assertNotIn(":", first_path.name)
        self.assertEqual(list(self.root.iterdir()), [first_path])

    def test_invalid_match_policy_cannot_create_a_folder(self):
        with self.assertRaises(ValueError):
            self.resolve("prefix")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_index_template_reuses_or_creates_the_node_index_folder(self):
        existing = self.root / "2.1 - ABC"
        existing.mkdir()
        self.assertEqual(resolve_document_folder(
            self.root, self.document, "{index} - {numara}", index="2.1"
        ), existing)
        self.assertEqual(resolve_document_folder(
            self.root, self.document, "{index} - {numara}", index="3"
        ), self.root / "3 - ABC")

    def test_index_template_without_context_cannot_create_a_folder(self):
        with self.assertRaises(ValueError):
            resolve_document_folder(self.root, self.document, "{index}")
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
