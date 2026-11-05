import ctypes
import json
import math
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from OT_app.settings import (
    AppSettings,
    DOCUMENTS_VALUE,
    PASSWORD_VALUE,
    REG_BINARY,
    REG_MULTI_SZ,
    REG_SZ,
    SETTINGS_VALUE,
    RegistryStore,
    SettingsError,
)
from OT_app.win_secrets import DPAPIError, DPAPIProtector, _DataBlob


class FakeRegistry:
    def __init__(self):
        self.values = {}
        self.calls = []
        self.fail_read = set()
        self.fail_write = set()
        self.fail_delete = set()

    def read(self, name):
        self.calls.append(("read", name))
        if name in self.fail_read:
            raise PermissionError("denied")
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name]

    def write(self, name, value, kind):
        self.calls.append(("write", name))
        if name in self.fail_write:
            raise PermissionError("denied")
        self.values[name] = (value, kind)

    def delete(self, name):
        self.calls.append(("delete", name))
        if name in self.fail_delete:
            raise PermissionError("denied")
        self.values.pop(name, None)


class FakeProtector:
    def __init__(self):
        self.fail_protect = False
        self.fail_unprotect = False
        self.calls = []

    def protect(self, value):
        self.calls.append(("protect", value))
        if self.fail_protect:
            raise OSError("secret native detail")
        return b"protected:" + value[::-1]

    def unprotect(self, value):
        self.calls.append(("unprotect", value))
        if self.fail_unprotect or not value.startswith(b"protected:"):
            raise OSError("secret native detail")
        return value[len(b"protected:"):][::-1]


class AppSettingsTests(unittest.TestCase):
    def test_defaults_allow_setup_and_password_is_hidden_in_repr(self):
        settings = AppSettings(password="never-print-this")
        settings.validate()
        self.assertNotIn("never-print-this", repr(settings))
        self.assertTrue(settings.verify_tls)
        self.assertTrue(settings.remember_password)
        self.assertTrue(settings.output_dir.endswith("OT Documents"))

    def test_connection_requires_url_username_and_password(self):
        valid = AppSettings(base_url="https://OT.example.test/app", username="user", password="secret")
        valid.validate(require_connection=True)
        for field in ("base_url", "username", "password"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(valid, **{field: ""}).validate(require_connection=True)

    def test_url_rejects_unsafe_or_malformed_components(self):
        for url in ("ftp://example.test", "example.test", "https://", "https://user:pass@example.test", "https://example.test/?x=1", "https://example.test/#x", "https://example.test:invalid", "https://example .test", "https://example.test:99999"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                AppSettings(base_url=url).validate()

    def test_password_is_never_trimmed(self):
        settings = AppSettings(base_url="https://example.test", username="a", password="  p\t\n ")
        settings.validate(require_connection=True)
        self.assertEqual(settings.password, "  p\t\n ")

    def test_timeout_rejects_bools_nonfinite_nonpositive_and_excessive_values(self):
        for timeout in (True, False, 0, -1, math.nan, math.inf, "30", None, 3601):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                AppSettings(timeout=timeout).validate()
        AppSettings(timeout=0.5).validate()
        AppSettings(timeout=3600).validate()

    def test_boolean_and_text_fields_are_not_coerced(self):
        for values in ({"verify_tls": "false"}, {"remember_password": 1}, {"username": None}, {"output_dir": " "}, {"folder_id": []}, {"password": 12}, {"output_dir": "A\x00B"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                AppSettings(**values).validate()

    def test_ca_bundle_and_output_directory_types(self):
        with tempfile.TemporaryDirectory() as directory:
            certificate = Path(directory) / "ca.pem"
            certificate.write_text("test", encoding="utf-8")
            AppSettings(ca_bundle=str(certificate), output_dir=directory).validate()
            with self.assertRaises(ValueError):
                AppSettings(ca_bundle=str(Path(directory) / "missing.pem")).validate()
            with self.assertRaises(ValueError):
                AppSettings(output_dir=str(certificate)).validate()


class RegistryStoreTests(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry()
        self.protector = FakeProtector()
        self.store = RegistryStore(registry=self.registry, protector=self.protector)
        self.settings = AppSettings(base_url="https://OT.example.test", username="ordinary-user", password=" s3cret-İ! ", folder_id="04", timeout=45)

    def test_missing_key_returns_clean_defaults(self):
        settings, numbers = self.store.load()
        self.assertEqual(settings.base_url, "")
        self.assertEqual(numbers, [])
        self.assertEqual(self.store.warning, "")

    def test_roundtrip_uses_expected_registry_types_and_no_secret_json(self):
        self.store.save(self.settings, ["001", "Ab", "001", "ab"])
        config, kind = self.registry.values[SETTINGS_VALUE]
        self.assertEqual(kind, REG_SZ)
        self.assertNotIn(self.settings.password, config)
        self.assertNotIn("password", json.loads(config))
        self.assertEqual(self.registry.values[DOCUMENTS_VALUE], (["001", "Ab", "ab"], REG_MULTI_SZ))
        self.assertEqual(self.registry.values[PASSWORD_VALUE][1], REG_BINARY)
        restored, documents = self.store.load()
        self.assertEqual(restored, self.settings)
        self.assertEqual(documents, ["001", "Ab", "ab"])
        self.assertEqual(self.store.warning, "")

    def test_remember_false_deletes_secret_only_on_explicit_save(self):
        self.store.save(self.settings, ["old"])
        secret = self.registry.values[PASSWORD_VALUE]
        self.store.save_documents(["new"])
        self.assertEqual(self.registry.values[PASSWORD_VALUE], secret)
        self.store.save(replace(self.settings, remember_password=False), ["new"])
        self.assertNotIn(PASSWORD_VALUE, self.registry.values)
        restored, _ = self.store.load()
        self.assertEqual(restored.password, "")
        self.assertFalse(restored.remember_password)

    def test_queue_autosave_never_reads_or_writes_settings_or_secret(self):
        self.store.save(self.settings, ["old"])
        config = self.registry.values[SETTINGS_VALUE]
        secret = self.registry.values[PASSWORD_VALUE]
        self.registry.calls.clear()
        self.protector.calls.clear()
        self.store.save_documents(["new", "new", "002"])
        self.assertEqual(self.registry.calls, [("write", DOCUMENTS_VALUE)])
        self.assertEqual(self.protector.calls, [])
        self.assertEqual(self.registry.values[SETTINGS_VALUE], config)
        self.assertEqual(self.registry.values[PASSWORD_VALUE], secret)

    def test_config_only_save_preserves_unread_documents_and_their_warning(self):
        self.store.save(self.settings, ["unread-001", "unread-002"])
        persisted_documents = self.registry.values[DOCUMENTS_VALUE]
        self.registry.fail_read.add(DOCUMENTS_VALUE)
        restored, documents = self.store.load()
        self.assertEqual(documents, [])
        warning = self.store.warning
        self.assertTrue(warning)
        self.registry.calls.clear()
        self.store.save(replace(restored, username="updated-user"), None)
        self.assertEqual(self.registry.values[DOCUMENTS_VALUE], persisted_documents)
        self.assertFalse(any(name == DOCUMENTS_VALUE for _, name in self.registry.calls))
        self.assertEqual(self.store.warning, warning)
        self.assertEqual(json.loads(self.registry.values[SETTINGS_VALUE][0])["username"], "updated-user")

    def test_omitting_documents_saves_settings_and_secret_without_touching_queue(self):
        self.store.save(self.settings, ["001"])
        self.registry.calls.clear()
        self.store.save(replace(self.settings, remember_password=False))
        self.assertEqual(self.registry.values[DOCUMENTS_VALUE], (["001"], REG_MULTI_SZ))
        self.assertNotIn(PASSWORD_VALUE, self.registry.values)
        self.assertFalse(any(name == DOCUMENTS_VALUE for _, name in self.registry.calls))

    def test_config_only_save_validates_settings_before_any_native_changes(self):
        self.store.save(self.settings, ["001"])
        before = dict(self.registry.values)
        self.registry.calls.clear()
        self.protector.calls.clear()
        with self.assertRaises(ValueError):
            self.store.save(replace(self.settings, timeout=0), None)
        self.assertEqual(self.registry.values, before)
        self.assertEqual(self.registry.calls, [])
        self.assertEqual(self.protector.calls, [])

    def test_config_only_save_preserves_an_unresolved_queue_write_warning(self):
        self.registry.fail_write.add(DOCUMENTS_VALUE)
        with self.assertRaises(SettingsError):
            self.store.save_documents(["new"])
        warning = self.store.warning
        self.store.save(self.settings, None)
        self.assertEqual(self.store.warning, warning)

    def test_corrupt_json_does_not_hide_documents_or_decryptable_secret(self):
        self.store.save(self.settings, ["001"])
        self.registry.values[SETTINGS_VALUE] = ("{bad", REG_SZ)
        restored, documents = self.store.load()
        self.assertEqual(restored.base_url, "")
        self.assertEqual(restored.password, self.settings.password)
        self.assertEqual(documents, ["001"])
        self.assertTrue(self.store.warning)

    def test_invalid_json_field_keeps_healthy_fields(self):
        config = {"base_url": self.settings.base_url, "username": "still-usable", "timeout": "bad", "verify_tls": "false", "password": "must-ignore"}
        self.registry.values[SETTINGS_VALUE] = (json.dumps(config), REG_SZ)
        restored, _ = self.store.load()
        self.assertEqual(restored.base_url, self.settings.base_url)
        self.assertEqual(restored.username, "still-usable")
        self.assertEqual(restored.timeout, 30)
        self.assertTrue(restored.verify_tls)
        self.assertEqual(restored.password, "")
        self.assertTrue(self.store.warning)
        self.assertNotIn("must-ignore", self.store.warning)

    def test_corrupt_password_survives_load_queue_save_and_blank_full_save(self):
        self.store.save(self.settings, ["old"])
        damaged = (b"not-decryptable", REG_BINARY)
        self.registry.values[PASSWORD_VALUE] = damaged
        restored, _ = self.store.load()
        self.assertEqual(restored.password, "")
        self.assertTrue(self.store.warning)
        self.assertEqual(self.registry.values[PASSWORD_VALUE], damaged)
        self.store.save_documents(["new"])
        self.store.save(restored, ["new"])
        self.assertEqual(self.registry.values[PASSWORD_VALUE], damaged)
        self.assertTrue(self.store.warning)
        self.store.save(replace(restored, password="replacement"), ["new"])
        recovered, _ = self.store.load()
        self.assertEqual(recovered.password, "replacement")
        self.assertEqual(self.store.warning, "")

    def test_password_read_denied_is_not_destroyed_by_blank_save(self):
        self.store.save(self.settings, [])
        secret = self.registry.values[PASSWORD_VALUE]
        self.registry.fail_read.add(PASSWORD_VALUE)
        restored, _ = self.store.load()
        self.store.save(restored, [])
        self.assertEqual(self.registry.values[PASSWORD_VALUE], secret)
        self.assertTrue(self.store.warning)

    def test_protection_failure_changes_no_persisted_values(self):
        self.store.save(self.settings, ["old"])
        before = dict(self.registry.values)
        self.protector.fail_protect = True
        with self.assertRaises(SettingsError) as caught:
            self.store.save(replace(self.settings, username="changed"), ["new"])
        self.assertEqual(self.registry.values, before)
        self.assertNotIn("secret native detail", str(caught.exception))
        self.assertTrue(self.store.warning)

    def test_queue_autosave_does_not_hide_an_unresolved_settings_save_failure(self):
        self.protector.fail_protect = True
        with self.assertRaises(SettingsError):
            self.store.save(self.settings, ["old"])
        warning = self.store.warning
        self.store.save_documents(["new"])
        self.assertEqual(self.store.warning, warning)

    def test_present_but_null_registry_values_warn_instead_of_looking_absent(self):
        self.registry.values[SETTINGS_VALUE] = (None, REG_SZ)
        self.registry.values[DOCUMENTS_VALUE] = (None, REG_MULTI_SZ)
        self.registry.values[PASSWORD_VALUE] = (None, REG_BINARY)
        settings, documents = self.store.load()
        self.assertEqual(settings.password, "")
        self.assertEqual(documents, [])
        self.assertTrue(self.store.warning)

    def test_invalid_settings_or_documents_change_no_persisted_values(self):
        self.store.save(self.settings, ["old"])
        before = dict(self.registry.values)
        with self.assertRaises(ValueError):
            self.store.save(replace(self.settings, timeout=0), ["new"])
        with self.assertRaises(ValueError):
            self.store.save_documents(["A\x00B"])
        self.assertEqual(self.registry.values, before)

    def test_wrong_registry_types_warn_and_preserve_other_usable_values(self):
        self.store.save(self.settings, ["001"])
        self.registry.values[SETTINGS_VALUE] = (b"wrong", REG_BINARY)
        self.registry.values[PASSWORD_VALUE] = ("wrong", REG_SZ)
        restored, documents = self.store.load()
        self.assertEqual(restored.password, "")
        self.assertEqual(documents, ["001"])
        self.assertTrue(self.store.warning)
        secret = self.registry.values[PASSWORD_VALUE]
        self.store.save_documents(["002"])
        self.assertEqual(self.registry.values[PASSWORD_VALUE], secret)

    def test_healthy_documents_survive_a_corrupt_registry_member(self):
        self.registry.values[DOCUMENTS_VALUE] = (["001", None, "A\x00B", "002", "001"], REG_MULTI_SZ)
        _, documents = self.store.load()
        self.assertEqual(documents, ["001", "002"])
        self.assertTrue(self.store.warning)

    def test_write_and_delete_permission_failures_are_visible(self):
        self.store.save(self.settings, ["old"])
        self.registry.fail_write.add(DOCUMENTS_VALUE)
        with self.assertRaises(SettingsError):
            self.store.save_documents(["new"])
        self.assertTrue(self.store.warning)
        self.registry.fail_write.clear()
        self.registry.fail_delete.add(PASSWORD_VALUE)
        with self.assertRaises(SettingsError):
            self.store.save(replace(self.settings, remember_password=False), ["old"])
        self.assertIn(PASSWORD_VALUE, self.registry.values)
        self.assertTrue(self.store.warning)

    def test_missing_key_read_permission_failure_is_visible(self):
        self.registry.fail_read.add(SETTINGS_VALUE)
        restored, documents = self.store.load()
        self.assertEqual(restored.base_url, "")
        self.assertEqual(documents, [])
        self.assertTrue(self.store.warning)

    def test_nonwindows_mode_is_explicit_and_session_only(self):
        store = RegistryStore(platform="linux")
        self.assertTrue(store.warning)
        store.save(self.settings, ["001"])
        restored, documents = store.load()
        self.assertEqual(restored, self.settings)
        self.assertEqual(documents, ["001"])
        restored.username = "not-mutating-store"
        documents.append("002")
        self.assertEqual(store.load()[0].username, self.settings.username)
        self.assertEqual(store.load()[1], ["001"])
        other = RegistryStore(platform="linux")
        self.assertEqual(other.load()[0].password, "")
        self.assertEqual(other.load()[1], [])

    def test_session_config_only_save_preserves_queue_and_copies_new_settings(self):
        store = RegistryStore(platform="linux")
        store.save(self.settings, ["001", "002"])
        updated = replace(self.settings, username="new-user")
        store.save(updated, None)
        updated.username = "later-mutation"
        restored, documents = store.load()
        self.assertEqual(restored.username, "new-user")
        self.assertEqual(documents, ["001", "002"])
        store.save(replace(restored, username="omitted-documents"))
        self.assertEqual(store.load()[1], ["001", "002"])


class FakeNativeFunction:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class DPAPIBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.buffers = []
        self.freed = []
        self.received = []
        self.success = True
        self.response = b"native-output"

        def transform(source, description, entropy, reserved, prompt, flags, destination):
            source_blob = ctypes.cast(source, ctypes.POINTER(_DataBlob)).contents
            self.received.append((ctypes.string_at(source_blob.pbData, source_blob.cbData), description, entropy, reserved, prompt, flags))
            buffer = ctypes.create_string_buffer(self.response)
            self.buffers.append(buffer)
            destination_blob = ctypes.cast(destination, ctypes.POINTER(_DataBlob)).contents
            destination_blob.cbData = len(self.response)
            destination_blob.pbData = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
            return int(self.success)

        self.crypt32 = SimpleNamespace(CryptProtectData=FakeNativeFunction(transform), CryptUnprotectData=FakeNativeFunction(transform))
        self.kernel32 = SimpleNamespace(LocalFree=FakeNativeFunction(lambda pointer: self.freed.append(pointer.value)))
        self.protector = DPAPIProtector(crypt32=self.crypt32, kernel32=self.kernel32)

    def test_native_output_is_copied_then_freed_with_pointer_sized_signatures(self):
        self.assertEqual(self.protector.protect(b"input\x00bytes"), self.response)
        self.assertEqual(self.received[0][0], b"input\x00bytes")
        self.assertEqual(self.received[0][2:5], (None, None, None))
        self.assertEqual(self.received[0][5], 1)  # UI forbidden; no machine-scope flag.
        self.assertEqual(self.freed, [ctypes.addressof(self.buffers[0])])
        self.assertEqual(self.kernel32.LocalFree.argtypes, [ctypes.c_void_p])
        self.assertEqual(self.kernel32.LocalFree.restype, ctypes.c_void_p)
        self.assertEqual(len(self.crypt32.CryptProtectData.argtypes), 7)

    def test_unprotect_does_not_allocate_an_unused_description(self):
        self.assertEqual(self.protector.unprotect(b"ciphertext"), self.response)
        self.assertIsNone(self.received[0][1])
        self.assertEqual(len(self.freed), 1)

    def test_native_failure_frees_any_returned_buffer_and_hides_input(self):
        self.success = False
        with patch("OT_app.win_secrets.ctypes.get_last_error", return_value=5, create=True):
            with self.assertRaises(DPAPIError) as caught:
                self.protector.protect(b"must-never-appear")
        self.assertNotIn("must-never-appear", str(caught.exception))
        self.assertEqual(len(self.freed), 1)


@unittest.skipUnless(os.name == "nt", "Requires native Windows current-user DPAPI")
class NativeDPAPITests(unittest.TestCase):
    def test_current_user_native_roundtrip(self):
        protector = DPAPIProtector()
        cleartext = "DPAPI test — İŞ-42".encode("utf-8")
        protected = protector.protect(cleartext)
        self.assertNotEqual(protected, cleartext)
        self.assertEqual(protector.unprotect(protected), cleartext)


if __name__ == "__main__":
    unittest.main()
