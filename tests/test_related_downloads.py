"""Related downloads through the real worker/client, with synthetic HTTP only."""
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from otClient import Document, OTConnector
from ot_app.settings import AppSettings
from ot_app.worker import DownloadWorker, JobItem
from tests.test_client import FakeResponse, FakeSession


class RoutedSession(FakeSession):
    def __init__(self):
        super().__init__()
        self.routes = {}

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        path = urlsplit(url).path
        if path not in self.routes:
            raise AssertionError(f"Unexpected request: {path}")
        return self.routes[path]()


class RelatedDownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.settings = AppSettings(base_url="https://ot.example.test", username="test-user",
                                    password="synthetic-password", output_dir=str(self.root))
        self.session = RoutedSession()
        self.cancel = threading.Event()
        self.document = Document("doc", "DOC.pdf", "Main", "", 2)
        self.details = {"forms": ["form"], "attachments": ["attachment"]}
        self.session.routes[self.path("tds_document", "doc")] = lambda: FakeResponse({"properties": self.details})
        self.media("tds_document", "doc", b"%PDF-main")
        self.related("tds_form", "form", "FORM.pdf", "Form title", 3)
        self.related("tds_attachment", "attachment", "ATT.pdf", "Attachment title", 4)

    @staticmethod
    def path(kind, identifier):
        return f"/TDS/contents/{kind}/{identifier}"

    def media(self, kind, identifier, content):
        self.session.routes[self.path(kind, identifier) + "/media"] = lambda: FakeResponse(
            chunks=[content], headers={"Content-Type": "application/pdf", "Content-Length": str(len(content))})

    def related(self, kind, identifier, name, title="", revision=0):
        properties = {"id": identifier, "object_name": name, "title": title,
                      "authors": [], "revision": revision}
        self.session.routes[self.path(kind, identifier)] = lambda: FakeResponse({"properties": properties})
        self.media(kind, identifier, b"%PDF-" + identifier.encode())

    def run_worker(self, forms=True, attachments=True, items=None, hierarchy=None):
        self.settings.download_related_forms = forms
        self.settings.download_related_attachments = attachments
        events = queue.Queue()
        with patch("otClient.requests.Session", return_value=self.session), patch.object(OTConnector, "login", return_value=True):
            worker = DownloadWorker(self.settings, items or [JobItem("row", "DOC", self.document)],
                                    events, self.cancel, hierarchy=hierarchy)
            worker.run()
        result = []
        while not events.empty():
            result.append(events.get_nowait())
        self.assertEqual(result[-1].kind, "finished")
        self.assertFalse(any(event.kind == "fatal" for event in result), result)
        return result

    def last_status(self, events, key="row"):
        return [event.payload for event in events if event.kind == "status" and event.key == key][-1]

    def paths(self):
        return [urlsplit(url).path for _, url, _ in self.session.calls]

    def test_options_control_each_category_and_default_path_has_no_extra_request(self):
        for forms, attachments in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(forms=forms, attachments=attachments):
                self.session.calls.clear()
                events = self.run_worker(forms, attachments)
                expected = [self.path("tds_document", "doc") + "/media"]
                if forms or attachments:
                    expected += [self.path("tds_document", "doc")]
                if forms:
                    expected += [self.path("tds_form", "form"), self.path("tds_form", "form") + "/media"]
                    self.assertEqual((self.root / "FORM.pdf").read_bytes(), b"%PDF-form")
                if attachments:
                    expected += [self.path("tds_attachment", "attachment"), self.path("tds_attachment", "attachment") + "/media"]
                    self.assertEqual((self.root / "ATT.pdf").read_bytes(), b"%PDF-attachment")
                self.assertEqual(self.paths(), expected)
                self.assertIn(self.last_status(events)["status"], ("downloaded", "unchanged"))

    def test_related_files_use_parent_resolved_folder_and_their_own_metadata(self):
        self.settings.filename_format = "{numara} - {ad} - R{revizyon}"
        self.settings.document_subfolder_enabled = True
        self.settings.document_subfolder_match = "contains"
        folder = self.root / "Existing DOC folder"
        folder.mkdir()
        events = self.run_worker()
        self.assertEqual(sorted(path.name for path in folder.iterdir()),
                         ["ATT - Attachment title - R4.pdf", "DOC - Main - R2.pdf", "FORM - Form title - R3.pdf"])
        self.assertEqual(list(self.root.iterdir()), [folder])
        status = self.last_status(events)
        self.assertEqual(status["document"], self.document)
        self.assertEqual(status["path"], str(folder / "DOC - Main - R2.pdf"))
        progress = [event.payload for event in events if event.kind == "progress"]
        self.assertEqual(progress[-1]["downloaded"], len(b"%PDF-main"))

    def test_related_files_use_owning_flat_row_index_and_their_own_metadata(self):
        self.settings.filename_format = "{index}-{numara}-{ad}-R{revizyon}"
        self.settings.document_subfolder_enabled = True
        self.settings.document_subfolder_format = "{index}-{numara}"
        events = self.run_worker(items=[JobItem("row", "DOC", self.document, row_index="7")])
        folder = self.root / "7-DOC"
        self.assertEqual(sorted(path.name for path in folder.iterdir()),
                         ["7-ATT-Attachment title-R4.pdf", "7-DOC-Main-R2.pdf", "7-FORM-Form title-R3.pdf"])
        self.assertEqual(self.last_status(events)["path"], str(folder / "7-DOC-Main-R2.pdf"))
        self.assertEqual(list(self.root.iterdir()), [folder])

    def test_related_leaf_files_use_complete_hierarchy_index_and_parent_destination(self):
        self.settings.manual_folder_hierarchy_enabled = True
        self.settings.filename_format = "{index}-{numara}-{ad}-R{revizyon}"
        self.settings.document_subfolder_format = "{index}-{numara}"
        ancestor = JobItem("ancestor", "PARENT", Document("parent", "PARENT.pdf", "Parent", ""))
        sibling = JobItem("sibling", "SIBLING", None, "ancestor")
        selected = JobItem("row", "DOC", self.document, "ancestor")
        events = self.run_worker(items=[selected], hierarchy=(ancestor, sibling, selected))
        folder = self.root / "1-PARENT"
        self.assertEqual(sorted(path.name for path in folder.iterdir()),
                         ["1.2-ATT-Attachment title-R4.pdf", "1.2-DOC-Main-R2.pdf", "1.2-FORM-Form title-R3.pdf"])
        self.assertEqual(self.last_status(events)["path"], str(folder / "1.2-DOC-Main-R2.pdf"))
        self.assertEqual(list(self.root.iterdir()), [folder])
        self.assertFalse(any("parent/media" in path or "SIBLING" in path for path in self.paths()))

    def test_absent_null_and_empty_relationships_need_no_child_requests(self):
        for details in ({}, {"forms": None, "attachments": []}, {"forms": [], "attachments": None}):
            with self.subTest(details=details):
                self.details = details
                self.session.calls.clear()
                events = self.run_worker()
                self.assertEqual(len(self.paths()), 2)
                self.assertIn(self.last_status(events)["status"], ("downloaded", "unchanged"))

    def test_duplicate_ids_are_processed_once_per_type(self):
        self.details = {"forms": ["form", " form ", "form"], "attachments": ["form"]}
        self.related("tds_attachment", "form", "OTHER.pdf")
        self.run_worker()
        self.assertEqual(self.paths().count(self.path("tds_form", "form")), 1)
        self.assertEqual(self.paths().count(self.path("tds_attachment", "form")), 1)
        self.assertTrue((self.root / "OTHER.pdf").is_file())

    def test_bad_ids_report_failure_but_valid_ids_and_other_category_continue(self):
        self.details["forms"] = [None, "", 12, "..", "form"]
        events = self.run_worker()
        self.assertEqual(self.last_status(events)["status"], "error")
        self.assertTrue((self.root / "FORM.pdf").is_file())
        self.assertTrue((self.root / "ATT.pdf").is_file())

    def test_invalid_unicode_in_related_id_is_a_recoverable_error(self):
        self.details["forms"] = ["\ud800", "form"]
        events = self.run_worker()
        status = self.last_status(events)
        self.assertEqual(status["status"], "error")
        status["message"].encode("utf-8")
        self.assertTrue((self.root / "FORM.pdf").is_file())
        self.assertTrue((self.root / "ATT.pdf").is_file())

    def test_invalid_unicode_in_related_filename_is_a_recoverable_error(self):
        self.related("tds_form", "form", "bad\ud800.pdf")
        events = self.run_worker()
        status = self.last_status(events)
        self.assertEqual(status["status"], "error")
        status["message"].encode("utf-8")
        self.assertTrue((self.root / "ATT.pdf").is_file())

    def test_malformed_category_does_not_prevent_other_category(self):
        self.details["forms"] = "form"
        events = self.run_worker()
        self.assertEqual(self.last_status(events)["status"], "error")
        self.assertTrue((self.root / "ATT.pdf").is_file())
        self.assertNotIn(self.path("tds_form", "form"), self.paths())

    def test_unselected_malformed_category_is_ignored(self):
        self.details["forms"] = 123
        events = self.run_worker(forms=False)
        self.assertEqual(self.last_status(events)["status"], "downloaded")
        self.assertTrue((self.root / "ATT.pdf").is_file())

    def test_missing_parent_properties_is_reported_and_main_path_is_retained(self):
        self.session.routes[self.path("tds_document", "doc")] = lambda: FakeResponse({})
        events = self.run_worker()
        status = self.last_status(events)
        self.assertEqual(status["status"], "error")
        self.assertEqual(status["path"], str(self.root / "DOC.pdf"))
        self.assertEqual((self.root / "DOC.pdf").read_bytes(), b"%PDF-main")

    def test_failed_child_keeps_main_and_continues_to_next_child_and_document(self):
        self.session.routes[self.path("tds_form", "form") + "/media"] = lambda: FakeResponse(status=403)
        self.media("tds_document", "next", b"%PDF-next")
        self.session.routes[self.path("tds_document", "next")] = lambda: FakeResponse({"properties": {}})
        events = self.run_worker(items=[JobItem("row", "DOC", self.document),
                                       JobItem("next", "NEXT", Document("next", "NEXT.pdf", "", ""))])
        status = self.last_status(events)
        self.assertEqual(status["status"], "error")
        self.assertIn("form", status["message"])
        self.assertEqual(status["path"], str(self.root / "DOC.pdf"))
        self.assertTrue((self.root / "ATT.pdf").is_file())
        self.assertEqual(self.last_status(events, "next")["status"], "downloaded")

    def test_invalid_child_metadata_does_not_download_media(self):
        for properties in ({"id": "form"}, {"id": "different", "object_name": "FORM.pdf"},
                           {"id": "form", "object_name": "FORM.pdf", "title": 42}):
            with self.subTest(properties=properties):
                self.session.calls.clear()
                self.session.routes[self.path("tds_form", "form")] = lambda: FakeResponse({"properties": properties})
                events = self.run_worker()
                self.assertEqual(self.last_status(events)["status"], "error")
                self.assertNotIn(self.path("tds_form", "form") + "/media", self.paths())
                self.assertTrue((self.root / "ATT.pdf").is_file())

    def test_metadata_failure_continues_same_category_and_retry_recovers(self):
        self.details["forms"].append("second")
        self.related("tds_form", "second", "SECOND.pdf")
        self.session.routes[self.path("tds_form", "form")] = lambda: FakeResponse(status=404)
        events = self.run_worker()
        self.assertEqual(self.last_status(events)["status"], "error")
        self.assertTrue((self.root / "SECOND.pdf").is_file())
        self.related("tds_form", "form", "FORM.pdf")
        events = self.run_worker()
        self.assertEqual(self.last_status(events)["status"], "unchanged")
        self.assertTrue((self.root / "FORM.pdf").is_file())
        self.assertIn("2 form, 1 ek", self.last_status(events)["message"])

    def test_shared_form_is_saved_in_each_parent_folder(self):
        self.settings.document_subfolder_enabled = True
        self.media("tds_document", "next", b"%PDF-next")
        self.session.routes[self.path("tds_document", "next")] = lambda: FakeResponse({"properties": self.details})
        events = self.run_worker(items=[JobItem("row", "DOC", self.document),
                                       JobItem("next", "NEXT", Document("next", "NEXT.pdf", "", ""))])
        for folder in ("DOC", "NEXT"):
            self.assertEqual((self.root / folder / "FORM.pdf").read_bytes(), b"%PDF-form")
            self.assertEqual((self.root / folder / "ATT.pdf").read_bytes(), b"%PDF-attachment")
        self.assertEqual(self.last_status(events, "next")["status"], "downloaded")

    def test_related_ids_are_encoded_as_a_single_endpoint_component(self):
        self.details = {"forms": ["a/b?x"]}
        self.session.routes[self.path("tds_form", "a%2Fb%3Fx")] = lambda: FakeResponse({
            "properties": {"id": "a/b?x", "object_name": "ENCODED.pdf"}})
        self.media("tds_form", "a%2Fb%3Fx", b"%PDF-encoded")
        events = self.run_worker()
        self.assertEqual(self.last_status(events)["status"], "downloaded")
        self.assertEqual((self.root / "ENCODED.pdf").read_bytes(), b"%PDF-encoded")

    def test_retry_reads_fresh_relationships_even_when_main_is_unchanged(self):
        self.run_worker()
        old_stat = (self.root / "FORM.pdf").stat()
        self.details["attachments"].append("new")
        self.related("tds_attachment", "new", "NEW.pdf")
        self.session.calls.clear()
        events = self.run_worker()
        self.assertEqual(self.last_status(events)["status"], "unchanged")
        self.assertEqual((self.root / "FORM.pdf").stat().st_mtime_ns, old_stat.st_mtime_ns)
        self.assertTrue((self.root / "NEW.pdf").is_file())
        self.assertEqual(self.paths().count(self.path("tds_document", "doc")), 1)

    def test_name_collision_preserves_main_and_continues_other_category(self):
        self.related("tds_form", "form", "doc.PDF")
        events = self.run_worker()
        self.assertEqual(self.last_status(events)["status"], "error")
        self.assertEqual((self.root / "DOC.pdf").read_bytes(), b"%PDF-main")
        self.assertTrue((self.root / "ATT.pdf").is_file())

    def test_main_failure_does_not_fetch_relationships(self):
        self.session.routes[self.path("tds_document", "doc") + "/media"] = lambda: FakeResponse(status=403)
        events = self.run_worker()
        self.assertEqual(self.last_status(events)["status"], "error")
        self.assertEqual(self.paths(), [self.path("tds_document", "doc") + "/media"])

    def test_primary_form_or_attachment_does_not_expand_relationships(self):
        for kind in ("tds_form", "tds_attachment"):
            with self.subTest(kind=kind):
                self.media(kind, "doc", b"%PDF-main")
                self.session.calls.clear()
                events = self.run_worker(items=[JobItem("row", "DOC", Document("doc", "DOC.pdf", "", "", content_type=kind))])
                self.assertIn(self.last_status(events)["status"], ("downloaded", "unchanged"))
                self.assertEqual(self.paths(), [self.path(kind, "doc") + "/media"])

    def test_cancel_during_related_media_retains_main_and_removes_partial_file(self):
        def cancel_chunk():
            self.cancel.set()
            return b"%PDF-partial"
        self.session.routes[self.path("tds_form", "form") + "/media"] = lambda: FakeResponse(
            chunks=[cancel_chunk], headers={"Content-Type": "application/pdf"})
        events = self.run_worker()
        status_events = [event.payload for event in events if event.kind == "status"]
        self.assertEqual(status_events[-1]["status"], "cancelled")
        self.assertIn(str(self.root / "DOC.pdf"), [status.get("path") for status in status_events])
        self.assertEqual(list(self.root.iterdir()), [self.root / "DOC.pdf"])
        self.assertNotIn(self.path("tds_attachment", "attachment"), self.paths())
        self.assertTrue(events[-1].payload["cancelled"])
