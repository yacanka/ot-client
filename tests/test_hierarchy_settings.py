"""Hierarchy settings and bounded queue metadata persistence regressions."""

import hashlib
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

from ot_app.settings import (
    AppSettings, DOCUMENTS_VALUE, MAX_CONFIG_CHARACTERS, PASSWORD_VALUE,
    REG_MULTI_SZ, REG_SZ, SETTINGS_VALUE, RegistryStore, SettingsError,
)
from tests.test_settings import FakeProtector, FakeRegistry


HIERARCHY_VALUE = "DocumentHierarchy"


def metadata(documents, parents):
    sequence = json.dumps(documents, ensure_ascii=False, separators=(",", ":"))
    return json.dumps({"version": 1, "documents_sha256": hashlib.sha256(sequence.encode("utf-8")).hexdigest(), "parents": parents}, separators=(",", ":"))


class HierarchySettingsTests(unittest.TestCase):
    def test_manual_mode_is_strict_boolean_and_exclusive(self):
        self.assertIs(getattr(AppSettings(), "manual_folder_hierarchy_enabled", None), False)
        for value in (None, 0, 1, "false"):
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                AppSettings(manual_folder_hierarchy_enabled=value).validate()
            self.assertEqual(caught.exception.field, "manual_folder_hierarchy_enabled")
        with self.assertRaises(ValueError):
            AppSettings(manual_folder_hierarchy_enabled=True, document_subfolder_enabled=True).validate()

    def test_manual_mode_validates_shared_folder_format(self):
        settings = AppSettings(document_subfolder_format="{unfinished")
        settings.validate()
        with self.assertRaises(ValueError) as caught:
            replace(settings, manual_folder_hierarchy_enabled=True).validate()
        self.assertEqual(caught.exception.field, "document_subfolder_format")

    def test_corrupt_both_modes_preserves_legacy_mode_regardless_of_json_order(self):
        for pairs in (("manual_folder_hierarchy_enabled", "document_subfolder_enabled"), ("document_subfolder_enabled", "manual_folder_hierarchy_enabled")):
            registry = FakeRegistry()
            registry.values[SETTINGS_VALUE] = (json.dumps({name: True for name in pairs}), REG_SZ)
            store = RegistryStore(registry, FakeProtector())
            settings, _ = store.load()
            self.assertTrue(settings.document_subfolder_enabled)
            self.assertFalse(settings.manual_folder_hierarchy_enabled)
            self.assertTrue(store.warning)


class HierarchyPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry()
        self.protector = FakeProtector()
        self.store = RegistryStore(self.registry, self.protector)
        self.documents = ["A", "B", "C", "D"]
        self.parents = {"A": None, "B": "A", "C": "B", "D": None}

    def test_missing_metadata_is_roots_without_warning(self):
        self.assertEqual(self.store.load_hierarchy(self.documents), dict.fromkeys(self.documents))
        self.assertEqual(self.store.warning, "")

    def test_roundtrip_all_save_routes_and_toggle_preserves_structure(self):
        for session_only in (False, True):
            for full_save in (False, True):
                with self.subTest(session_only=session_only, full_save=full_save):
                    store = RegistryStore(platform="linux") if session_only else self.store
                    if full_save:
                        store.save(AppSettings(manual_folder_hierarchy_enabled=True), self.documents, hierarchy=self.parents)
                    else:
                        store.save_documents(self.documents, hierarchy=self.parents)
                    self.assertEqual(store.load()[1], self.documents)
                    self.assertEqual(store.load_hierarchy(self.documents), self.parents)
                    store.save(AppSettings(manual_folder_hierarchy_enabled=False))
                    store.save(AppSettings(manual_folder_hierarchy_enabled=True))
                    self.assertTrue(store.load()[0].manual_folder_hierarchy_enabled)
                    self.assertEqual(store.load_hierarchy(self.documents), self.parents)
                    copied = store.load_hierarchy(self.documents)
                    copied["B"] = None
                    self.assertEqual(store.load_hierarchy(self.documents), self.parents)

    def test_compact_versioned_parent_vector_and_canonical_document_digest(self):
        documents = [" A ", "B", "A", "C", "D"]
        self.store.save_documents(documents, hierarchy=self.parents)
        value, kind = self.registry.values[HIERARCHY_VALUE]
        self.assertEqual(kind, REG_SZ)
        self.assertEqual(json.loads(value), json.loads(metadata(self.documents, [None, 0, 1, None])))
        self.assertEqual([call for call in self.registry.calls if call[0] == "write"], [("write", DOCUMENTS_VALUE), ("write", HIERARCHY_VALUE)])
        self.assertFalse(any(name == PASSWORD_VALUE for _, name in self.registry.calls))
        self.assertEqual(self.protector.calls, [])

    def test_empty_mapping_means_all_roots_and_empty_queue_roundtrips(self):
        self.store.save_documents(self.documents, hierarchy={})
        self.assertEqual(self.store.load_hierarchy(self.documents), dict.fromkeys(self.documents))
        self.store.save_documents([], hierarchy={})
        self.assertEqual(self.store.load_hierarchy([]), {})
        self.assertEqual(json.loads(self.registry.values[HIERARCHY_VALUE][0])["parents"], [])

    def test_invalid_hierarchy_fails_before_any_writes_or_secret_protection(self):
        for hierarchy in ({"unknown": None}, {"A": "unknown"}, {"A": "B"}, {"A": "A"}, {"A": None, "B": None, "C": "A"}, {"A": 1}, []):
            with self.subTest(hierarchy=hierarchy):
                self.registry.calls.clear()
                with self.assertRaises(ValueError):
                    self.store.save(AppSettings(password="example"), self.documents, hierarchy=hierarchy)
                self.assertFalse(any(call[0] in ("write", "delete") for call in self.registry.calls))
                self.assertEqual(self.protector.calls, [])
        with self.assertRaises(ValueError):
            self.store.save(AppSettings(), hierarchy={})

    def test_session_store_validates_before_mutating_settings_or_queue(self):
        store = RegistryStore(platform="linux")
        store.save(AppSettings(username="original"), self.documents, hierarchy=self.parents)
        with self.assertRaises(ValueError):
            store.save(AppSettings(username="replacement"), ["other"], hierarchy=self.parents)
        self.assertEqual(store.load()[0].username, "original")
        self.assertEqual(store.load()[1], self.documents)
        self.assertEqual(store.load_hierarchy(self.documents), self.parents)

    def test_session_store_copies_supplied_hierarchy(self):
        store = RegistryStore(platform="linux")
        supplied = dict(self.parents)
        store.save_documents(self.documents, hierarchy=supplied)
        supplied["B"] = None
        self.assertEqual(store.load_hierarchy(self.documents), self.parents)

    def test_invalid_metadata_recovers_roots_without_rewriting(self):
        valid = json.loads(metadata(self.documents, [None, 0, 1, None]))
        cases = ["{", "[]", json.dumps({**valid, "version": True}), json.dumps({**valid, "version": 2}),
                 json.dumps({**valid, "documents_sha256": "bad"}),
                 *[json.dumps({**valid, "parents": parents}) for parents in ([None], [None, True, None, None], [None, 2, None, None], [None, None, 0, None], [None, -1, None, None], [None, "0", None, None])],
                 " " * (MAX_CONFIG_CHARACTERS + 1)]
        for value in cases:
            with self.subTest(value=value[:80]):
                self.registry.values[HIERARCHY_VALUE] = (value, REG_SZ)
                self.registry.calls.clear()
                self.assertEqual(self.store.load_hierarchy(self.documents), dict.fromkeys(self.documents))
                self.assertTrue(self.store.warning)
                self.assertFalse(any(call[0] == "write" for call in self.registry.calls))

    def test_mismatched_sequence_and_read_failure_recover_roots(self):
        self.store.save_documents(self.documents, hierarchy=self.parents)
        self.assertEqual(self.store.load_hierarchy(list(reversed(self.documents))), dict.fromkeys(reversed(self.documents)))
        self.registry.fail_read.add(HIERARCHY_VALUE)
        self.assertEqual(self.store.load_hierarchy(self.documents), dict.fromkeys(self.documents))
        self.assertTrue(self.store.warning)

    def test_invalid_registry_type_or_nontext_record_recovers_roots(self):
        for record in ((None, REG_SZ), (metadata(self.documents, [None, 0, 1, None]), REG_MULTI_SZ)):
            with self.subTest(record=record):
                self.registry.values[HIERARCHY_VALUE] = record
                self.assertEqual(self.store.load_hierarchy(self.documents), dict.fromkeys(self.documents))
                self.assertTrue(self.store.warning)

    def test_omitted_hierarchy_preserves_corrupt_metadata_and_warning(self):
        self.registry.values[HIERARCHY_VALUE] = ("broken", REG_SZ)
        self.store.load_hierarchy(self.documents)
        warning = self.store.warning
        self.store.save_documents(self.documents)
        self.store.save(AppSettings(), self.documents)
        self.store.save(AppSettings())
        self.assertEqual(self.registry.values[HIERARCHY_VALUE], ("broken", REG_SZ))
        self.assertEqual(self.store.warning, warning)
        self.registry.calls.clear()
        self.store.save(AppSettings())
        self.assertFalse(any(name in (DOCUMENTS_VALUE, HIERARCHY_VALUE) for _, name in self.registry.calls))

    def test_partial_write_failure_keeps_warning_and_secret_untouched(self):
        self.registry.values[HIERARCHY_VALUE] = ("broken", REG_SZ)
        self.store.load_hierarchy(self.documents)
        self.registry.fail_write.add(HIERARCHY_VALUE)
        with self.assertRaises(SettingsError):
            self.store.save(AppSettings(remember_password=False), self.documents, hierarchy=self.parents)
        self.assertEqual(self.registry.values[DOCUMENTS_VALUE], (self.documents, REG_MULTI_SZ))
        self.assertEqual(self.registry.values[HIERARCHY_VALUE], ("broken", REG_SZ))
        self.assertFalse(any(name == PASSWORD_VALUE for _, name in self.registry.calls))
        self.assertTrue(self.store.warning)
        with self.assertRaises(SettingsError):
            self.store.save_documents(self.documents, hierarchy=self.parents)
        self.assertTrue(self.store.warning)

    def test_queue_write_failure_preserves_existing_hierarchy(self):
        self.store.save_documents(self.documents, hierarchy=self.parents)
        original = self.registry.values[HIERARCHY_VALUE]
        self.registry.calls.clear()
        self.registry.fail_write.add(DOCUMENTS_VALUE)
        with self.assertRaises(SettingsError):
            self.store.save_documents(self.documents, hierarchy={})
        self.assertEqual(self.registry.values[HIERARCHY_VALUE], original)
        self.assertEqual(self.registry.calls, [("write", DOCUMENTS_VALUE)])

    def test_full_save_changes_secret_only_after_queue_and_hierarchy(self):
        self.store.save(AppSettings(password="example"), self.documents, hierarchy=self.parents)
        self.assertEqual([call for call in self.registry.calls if call[0] == "write"], [
            ("write", SETTINGS_VALUE), ("write", DOCUMENTS_VALUE),
            ("write", HIERARCHY_VALUE), ("write", PASSWORD_VALUE),
        ])
        self.assertEqual(len(self.protector.calls), 1)

    def test_maximum_queue_with_long_numbers_uses_small_metadata(self):
        documents = [str(index).zfill(4) + "x" * 495 for index in range(10_000)]
        self.store.save_documents(documents, hierarchy={})
        value = self.registry.values[HIERARCHY_VALUE][0]
        self.assertLess(len(value), 100_000)
        self.assertEqual(self.store.load_hierarchy(documents), dict.fromkeys(documents))

    def test_metadata_size_is_validated_before_writes(self):
        with patch("ot_app.settings.MAX_CONFIG_CHARACTERS", 10):
            with self.assertRaises(ValueError):
                self.store.save_documents(self.documents, hierarchy=self.parents)
        self.assertEqual(self.registry.calls, [])


if __name__ == "__main__":
    unittest.main()
