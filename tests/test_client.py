"""Protocol and filesystem safety tests; never contact a real OT server."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import requests

from otClient import (
    Document,
    DownloadCancelled,
    OTConnector,
    OTError,
    get_local_file_sha256,
    safe_windows_filename,
)


class FakeResponse:
    def __init__(self, payload=None, *, status=200, headers=None, text="", chunks=None):
        self.payload = payload
        self.status_code = status
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})
        self.text = text
        self.chunks = chunks or []
        self.closed = False

    @property
    def content(self):
        raise AssertionError("Downloads must stream, without accessing response.content")

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        if self.payload is None:
            raise ValueError("not JSON")
        return self.payload

    def iter_content(self, chunk_size):
        for chunk in self.chunks:
            if callable(chunk):
                chunk = chunk()
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.cookies = {}
        self.responses = []
        self.calls = []
        self.closed = False

    def _call(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected HTTP request")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def get(self, url, **kwargs):
        return self._call("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._call("POST", url, **kwargs)

    def close(self):
        self.closed = True


def entry(document_id="090001", name="POL.001", title="A title", authors=None):
    return {
        "content": {
            "properties": {
                "id": document_id,
                "object_name": name,
                "title": title,
                "authors": ["A. Author"] if authors is None else authors,
            }
        }
    }


class ClientTestCase(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.patch_session = patch("otClient.requests.Session", return_value=self.session)
        self.patch_session.start()
        self.addCleanup(self.patch_session.stop)
        self.client = OTConnector(
            "https://OT.example", "test-user", "private-test-password", timeout=17
        )
        self.addCleanup(self.client.close)


class ClientTests(ClientTestCase):
    def test_constructor_does_not_make_requests(self):
        self.assertEqual(self.session.calls, [])

    def test_invalid_connection_settings_are_rejected(self):
        for url in ("", "ftp://host", "https://", "https://user:secret@host", "https://host/?x=1", "https://host/?", "https://host/#", "\x00https://host", "https://host/\x01"):
            with self.subTest(url=url), self.assertRaises(OTError):
                OTConnector(url)
        for timeout in (0, -1, True, float("nan"), float("inf"), "30", 10 ** 1000):
            with self.subTest(timeout=timeout), self.assertRaises(OTError):
                OTConnector("https://host", timeout=timeout)

    def test_empty_credentials_do_not_make_authentication_request(self):
        with self.assertRaises(OTError):
            OTConnector("https://host").login()
        self.assertFalse(self.session.calls)

    def test_login_200_password_form_is_a_failure(self):
        response = FakeResponse(
            text='<html><form action="j_spring_security_check"><input name="j_password" type="password"></form></html>',
            headers={"Content-Type": "text/html"},
        )
        self.session.responses = [response]
        with self.assertRaises(OTError):
            self.client.login()
        self.assertEqual(len(self.session.calls), 1)
        self.assertTrue(response.closed)

    def test_login_error_redirect_is_a_failure(self):
        self.session.responses = [
            FakeResponse(status=302, headers={"Location": "/TDS/login.jsp?login_error=1"})
        ]
        with self.assertRaises(OTError):
            self.client.login()
        self.assertEqual(len(self.session.calls), 1)

    def test_login_never_resends_credentials_to_redirected_host(self):
        response = FakeResponse(status=307, headers={"Location": "https://other.example/receive"})
        self.session.responses = [response]
        with self.assertRaises(OTError):
            self.client.login()
        self.assertEqual(len(self.session.calls), 1)
        self.assertFalse(self.session.calls[0][2]["allow_redirects"])
        self.assertTrue(response.closed)

    def test_malformed_login_redirect_gives_safe_error(self):
        self.session.responses = [FakeResponse(status=302, headers={"Location": "https://[invalid"})]
        with self.assertRaises(OTError):
            self.client.login()

    def test_login_probes_protected_endpoint_and_posts_plain_strings(self):
        self.session.responses = [
            FakeResponse(status=302, headers={"Location": "/TDS/"}),
            FakeResponse({"entries": []}),
        ]
        self.assertTrue(self.client.login())
        self.assertEqual(self.session.calls[0][0], "POST")
        self.assertEqual(self.session.calls[0][1], "https://OT.example/TDS/j_spring_security_check")
        self.assertEqual(
            self.session.calls[0][2]["data"],
            {"j_username": "test-user", "j_password": "private-test-password"},
        )
        for _, _, kwargs in self.session.calls:
            self.assertEqual(kwargs["timeout"], 17)
            self.assertIs(kwargs["verify"], True)
            self.assertIs(kwargs["allow_redirects"], False)
        self.assertTrue(self.session.calls[1][1].endswith("/TDS/realtime-queries/tds_search_documents"))

    def test_test_connection_performs_real_authentication_probe(self):
        self.session.responses = [FakeResponse(), FakeResponse({"entries": []})]
        self.assertTrue(self.client.test_connection())
        self.assertEqual([call[0] for call in self.session.calls], ["POST", "GET"])

    def test_login_cannot_succeed_when_probe_returns_login_html(self):
        self.session.responses = [
            FakeResponse(status=302, headers={"Location": "/TDS/"}),
            FakeResponse(text='<form><input type="password"></form>', headers={"Content-Type": "text/html"}),
        ]
        with self.assertRaises(OTError):
            self.client.login()

    def test_login_cannot_succeed_for_arbitrary_json_object(self):
        self.session.responses = [FakeResponse(), FakeResponse({"message": "please authenticate"})]
        with self.assertRaises(OTError):
            self.client.login()

    def test_protected_redirect_is_not_followed(self):
        self.session.responses = [FakeResponse(status=302, headers={"Location": "https://other.example/login"})]
        with self.assertRaises(OTError):
            self.client.search_documents("POL.001")
        self.assertFalse(self.session.calls[0][2]["allow_redirects"])

    def test_custom_ca_and_tls_choice_reach_transport(self):
        for verify in ("C:/Certificates/corporate-ca.pem", False):
            with self.subTest(verify=verify):
                self.session.responses = [FakeResponse({"entries": []})]
                client = OTConnector("https://OT.example", verify=verify)
                client.search_documents("POL.001")
                self.assertEqual(self.session.calls[-1][2]["verify"], verify)

    def test_transport_errors_are_actionable_and_do_not_expose_secrets(self):
        for error, expected in (
            (requests.exceptions.Timeout("private-test-password URL"), "zaman"),
            (requests.exceptions.ConnectionError("test-user private-test-password"), "bağlan"),
            (requests.exceptions.SSLError("private-test-password"), "sertifika"),
        ):
            with self.subTest(error=type(error).__name__):
                self.session.responses = [error]
                with self.assertRaises(OTError) as caught:
                    self.client.search_documents("POL.001")
                message = str(caught.exception)
                self.assertIn(expected, message.lower())
                self.assertNotIn("private-test-password", message)
                self.assertNotIn("test-user", message)

    def test_http_error_has_status_without_response_body(self):
        response = FakeResponse(status=503, text="private-test-password upstream diagnostic body")
        self.session.responses = [response]
        with self.assertRaises(OTError) as caught:
            self.client.search_documents("POL.001")
        self.assertIn("503", str(caught.exception))
        self.assertNotIn("private-test-password", str(caught.exception))
        self.assertTrue(response.closed)

    def test_invalid_json_is_a_useful_error(self):
        self.session.responses = [FakeResponse(ValueError("secret response text"))]
        with self.assertRaises(OTError) as caught:
            self.client.search_documents("POL.001")
        self.assertIn("JSON", str(caught.exception))
        self.assertNotIn("secret response text", str(caught.exception))

    def test_search_returns_all_candidates_with_metadata(self):
        self.session.responses = [
            FakeResponse({"entries": [entry(title="  A \n document  ", authors=[" Ada  Kaya ", "Can"]), entry("090002", "POL.002")]}),
        ]
        documents = self.client.search_documents("POL")
        self.assertEqual(len(documents), 2)
        self.assertEqual(documents[0], Document("090001", "POL.001", "A document", "Ada Kaya, Can"))
        self.assertEqual(documents[1].id, "090002")
        self.assertEqual(self.session.calls[0][2]["params"], {"inline": True, "input_name": "POL"})

    def test_empty_entries_mean_no_matches(self):
        self.session.responses = [FakeResponse({"entries": []})]
        self.assertEqual(self.client.search_documents("missing"), [])

    def test_missing_or_malformed_search_schema_is_an_error(self):
        malformed = [[], {}, {"entries": None}, {"entries": {}}, {"entries": [None]}, {"entries": [{}]}]
        for field, value in (("id", ""), ("object_name", None), ("title", 7), ("authors", {"x": "y"})):
            bad = entry()
            bad["content"]["properties"][field] = value
            malformed.append({"entries": [bad]})
        for payload in malformed:
            with self.subTest(payload=payload):
                self.session.responses = [FakeResponse(payload)]
                with self.assertRaises(OTError):
                    self.client.search_documents("POL.001")

    def test_optional_metadata_can_be_absent(self):
        self.session.responses = [FakeResponse({"entries": [{"content": {"properties": {"id": "1", "object_name": "POL"}}}]})]
        self.assertEqual(self.client.search_documents("POL"), [Document("1", "POL", "", "")])

    def test_compatibility_raw_search_and_encoded_document_id(self):
        payload = {"entries": [], "other": "retained"}
        self.session.responses = [FakeResponse(payload), FakeResponse({"id": "one"})]
        self.assertIs(self.client.search_document("POL.001"), payload)
        self.assertEqual(self.client.get_document_by_id("id/with?path"), {"id": "one"})
        self.assertTrue(self.session.calls[-1][1].endswith("/id%2Fwith%3Fpath"))

    def test_dot_segment_document_ids_are_rejected(self):
        for document_id in (".", ".."):
            with self.subTest(document_id=document_id), self.assertRaises(OTError):
                self.client.get_document_by_id(document_id)
        self.assertEqual(self.session.calls, [])

    def test_folder_listing_returns_filtered_data_with_configurable_folder(self):
        self.client.folder_id = "configured-folder"
        self.session.responses = [FakeResponse({"entries": [{"id": "1", "title": "Folder", "content": {}, "summary": "omit"}]})]
        self.assertEqual(self.client.get_document_titles(), [{"id": "1", "title": "Folder"}])
        self.assertEqual(self.session.calls[-1][2]["params"]["input_folder_id"], "configured-folder")
        self.session.responses = [FakeResponse({"entries": []})]
        self.assertEqual(self.client.get_document_titles("override"), [])
        self.assertEqual(self.session.calls[-1][2]["params"]["input_folder_id"], "override")

    def test_close_releases_session(self):
        self.client.close()
        self.assertTrue(self.session.closed)


class CredentialIsolationTests(unittest.TestCase):
    def test_session_does_not_send_implicit_netrc_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            netrc = Path(directory) / "netrc"
            netrc.write_text("default login synthetic-user password synthetic-value\n")
            with patch.dict(os.environ, {"NETRC": str(netrc)}):
                with OTConnector("https://example.test") as connector:
                    request = connector.client.session.prepare_request(
                        requests.Request("GET", "https://example.test/TDS/")
                    )
                    self.assertNotIn("Authorization", request.headers)

    def test_proxy_and_ca_environment_remain_supported(self):
        with patch.dict(os.environ, {
            "HTTPS_PROXY": "http://proxy.example.test:8080",
            "REQUESTS_CA_BUNDLE": "/synthetic/ca.pem", "NO_PROXY": "",
        }, clear=True):
            with OTConnector("https://example.test") as connector:
                options = connector.client.session.merge_environment_settings(
                    "https://example.test", {}, False, True, None
                )
                self.assertEqual(options["proxies"]["https"], "http://proxy.example.test:8080")
                self.assertEqual(options["verify"], "/synthetic/ca.pem")


class DownloadTests(ClientTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name).resolve()

    def response(self, chunks, *, mime="application/pdf", filename=None, length=None):
        headers = {"Content-Type": mime}
        if filename:
            headers["Content-Disposition"] = filename
        if length is not None:
            headers["Content-Length"] = str(length)
        response = FakeResponse(headers=headers, chunks=chunks)
        self.session.responses = [response]
        return response

    def test_utf16_login_page_cannot_replace_existing_document(self):
        target = self.folder / "report.pdf"
        target.write_bytes(b"existing document")
        body = '<html><form><input type="password"></form></html>'
        for encoding in ("utf-16", "utf-32"):
            with self.subTest(encoding=encoding):
                self.response([body.encode(encoding)], mime="application/octet-stream")
                with self.assertRaises(OTError):
                    self.client.download_document("1", self.folder, target.name)
                self.assertEqual(target.read_bytes(), b"existing document")
                self.assertEqual(list(self.folder.iterdir()), [target])

    def test_streams_bytes_preserves_pdf_extension_and_reports_progress(self):
        response = self.response([b"abc", b"", b"def"], length=6)
        progress = []
        result = self.client.download_document("1", self.folder, "Report.PDF", progress=lambda done, total: progress.append((done, total)))
        self.assertEqual(result.path, self.folder / "Report.PDF")
        self.assertEqual(result.status, "downloaded")
        self.assertEqual(result.bytes_written, 6)
        self.assertEqual(result.path.read_bytes(), b"abcdef")
        self.assertEqual(progress[0], (0, 6))
        self.assertEqual(progress[-1], (6, 6))
        self.assertTrue(all(0 <= done <= total for done, total in progress))
        self.assertTrue(self.session.calls[-1][2]["stream"])
        self.assertEqual(self.session.calls[-1][2]["headers"]["Accept-Encoding"], "identity")
        self.assertTrue(response.closed)
        self.assertEqual(list(self.folder.iterdir()), [result.path])

    def test_matching_sha_skips_replace_and_changed_sha_updates_atomically(self):
        target = self.folder / "Report.pdf"
        target.write_bytes(b"same")
        previous_mtime = target.stat().st_mtime_ns
        self.response([b"sa", b"me"], length=4)
        result = self.client.download_document("1", self.folder, target.name)
        self.assertEqual(result.status, "unchanged")
        self.assertEqual(result.bytes_written, 0)
        self.assertEqual(target.stat().st_mtime_ns, previous_mtime)
        self.response([b"new"], length=3)
        result = self.client.download_document("1", self.folder, target.name)
        self.assertEqual(result.status, "updated")
        self.assertEqual(result.bytes_written, 3)
        self.assertEqual(target.read_bytes(), b"new")

    def test_overwrite_forces_replacement_even_when_identical(self):
        target = self.folder / "Report.pdf"
        target.write_bytes(b"same")
        self.response([b"same"])
        self.assertEqual(self.client.download_document("1", self.folder, target.name, overwrite=True).status, "updated")

    def test_stream_error_preserves_existing_file_and_removes_temporary(self):
        target = self.folder / "Report.pdf"
        target.write_bytes(b"old complete version")
        response = self.response([b"partial", requests.exceptions.ConnectionError("private-test-password")])
        with self.assertRaises(OTError) as caught:
            self.client.download_document("1", self.folder, target.name)
        self.assertNotIn("private-test-password", str(caught.exception))
        self.assertEqual(target.read_bytes(), b"old complete version")
        self.assertEqual(list(self.folder.iterdir()), [target])
        self.assertTrue(response.closed)

    def test_cancellation_preserves_existing_file_and_removes_temporary(self):
        target = self.folder / "Report.pdf"
        target.write_bytes(b"old")
        cancel = threading.Event()

        def cancel_during_read():
            cancel.set()
            return b"partial"

        response = self.response([b"first", cancel_during_read])
        with self.assertRaises(DownloadCancelled):
            self.client.download_document("1", self.folder, target.name, cancel_event=cancel)
        self.assertEqual(target.read_bytes(), b"old")
        self.assertEqual(list(self.folder.iterdir()), [target])
        self.assertTrue(response.closed)

    def test_cancelled_before_start_does_not_make_request(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(DownloadCancelled):
            self.client.download_document("1", self.folder, "Report.pdf", cancel_event=cancel)
        self.assertEqual(self.session.calls, [])

    def test_incomplete_content_length_never_replaces_existing_file(self):
        for chunks, length in (([b"short"], 20), ([b"longer"], 2)):
            with self.subTest(length=length):
                target = self.folder / "Report.pdf"
                target.write_bytes(b"old")
                self.response(chunks, length=length)
                with self.assertRaises(OTError):
                    self.client.download_document("1", self.folder, target.name)
                self.assertEqual(target.read_bytes(), b"old")
                self.assertEqual(list(self.folder.iterdir()), [target])

    def test_failed_atomic_replace_preserves_existing_file_and_cleans_temporary(self):
        target = self.folder / "Report.pdf"
        target.write_bytes(b"old")
        self.response([b"new"])
        with patch("otClient.os.replace", side_effect=PermissionError("private-test-password")):
            with self.assertRaises(OTError):
                self.client.download_document("1", self.folder, target.name)
        self.assertEqual(target.read_bytes(), b"old")
        self.assertEqual(list(self.folder.iterdir()), [target])

    def test_disposition_utf8_filename_is_used_and_mime_fills_missing_extension(self):
        self.response([b"pdf"], filename="attachment; filename=old.pdf; filename*=UTF-8''T%C3%BCrk%C3%A7e%20belge.pdf")
        result = self.client.download_document("1", self.folder)
        self.assertEqual(result.path.name, "Türkçe belge.pdf")
        self.response([b"xlsx"], mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        result = self.client.download_document("2", self.folder, "Table")
        self.assertEqual(result.path.name, "Table.xlsx")

    def test_explicit_extension_is_never_replaced_or_given_extra_docx(self):
        self.response([b"zip"], mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename='attachment; filename="server.docx"')
        result = self.client.download_document("1", self.folder, "archive.zip")
        self.assertEqual(result.path.name, "archive.zip")

    def test_numeric_document_number_gets_server_file_extension(self):
        self.response([b"pdf"], mime="application/pdf")
        result = self.client.download_document("1", self.folder, "POL.001")
        self.assertEqual(result.path.name, "POL.001.pdf")

    def test_unknown_nonnumeric_suffix_is_preserved_without_server_type_evidence(self):
        self.response([b"unknown"], mime="application/octet-stream")
        result = self.client.download_document("1", self.folder, "document.custom")
        self.assertEqual(result.path.name, "document.custom")

    def test_unknown_suffix_retained_in_stem_when_server_identifies_file_type(self):
        self.response([b"pdf"], mime="application/pdf")
        result = self.client.download_document("1", self.folder, "POL.REV")
        self.assertEqual(result.path.name, "POL.REV.pdf")

    def test_known_extension_wins_over_conflicting_server_mime(self):
        self.response([b"pdf"], mime="application/msword")
        result = self.client.download_document("1", self.folder, "Report.pdf")
        self.assertEqual(result.path.name, "Report.pdf")

    def test_unknown_type_uses_binary_extension_and_id_fallback(self):
        self.response([b"unknown"], mime="application/octet-stream")
        result = self.client.download_document("090001", self.folder)
        self.assertEqual(result.path.name, "090001.bin")

    def test_traversal_and_windows_device_names_stay_inside_target(self):
        for number, name in enumerate(("../../outside.pdf", "C:\\outside.pdf", "NUL.pdf", "CON", "name?.pdf", " report. ")):
            with self.subTest(name=name):
                self.response([b"safe"])
                result = self.client.download_document(str(number), self.folder, name)
                self.assertEqual(result.path.parent, self.folder)
                self.assertFalse(any(char in result.path.name for char in '<>:"/\\|?*'))
                self.assertNotIn(result.path.stem.upper(), {"CON", "PRN", "AUX", "NUL"})
                self.assertEqual(result.path.read_bytes(), b"safe")

    def test_different_ids_with_same_or_collapsed_windows_names_do_not_overwrite(self):
        for first, second in (("Report.pdf", "report.pdf"), ("a/b.pdf", "a?b.pdf")):
            with self.subTest(names=(first, second)):
                self.response([b"first"])
                one = self.client.download_document("id-one", self.folder, first)
                self.response([b"second"])
                two = self.client.download_document("id-two", self.folder, second)
                self.assertNotEqual(one.path.name.casefold(), two.path.name.casefold())
                self.assertEqual(one.path.read_bytes(), b"first")
                self.assertEqual(two.path.read_bytes(), b"second")
                self.response([b"second"])
                again = self.client.download_document("id-two", self.folder, second)
                self.assertEqual(again.path, two.path)
                self.assertEqual(again.status, "unchanged")

    def test_existing_case_variant_is_updated_without_creating_windows_duplicate(self):
        original = self.folder / "REPORT.pdf"
        original.write_bytes(b"old")
        self.response([b"new"])
        result = self.client.download_document("1", self.folder, "report.pdf")
        self.assertEqual(result.path, original)
        self.assertEqual(result.status, "updated")
        self.assertEqual(list(self.folder.iterdir()), [original])

    def test_long_names_are_shortened_with_distinct_stable_suffixes(self):
        first = safe_windows_filename("x" * 260 + "a.pdf", "same-id")
        second = safe_windows_filename("x" * 260 + "b.pdf", "same-id")
        self.assertLessEqual(len(first.encode("utf-16-le")) // 2, 180)
        self.assertNotEqual(first.casefold(), second.casefold())
        self.assertTrue(first.endswith(".pdf"))

    def test_media_login_html_is_rejected_and_never_saved(self):
        self.response([b'<html><form><input type="password" name="j_password"></form></html>'], mime="text/html")
        with self.assertRaises(OTError):
            self.client.download_document("1", self.folder, "Report.pdf")
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_json_or_html_service_media_never_replaces_existing_pdf(self):
        for mime, content in (
            ("application/json", b'{"error":"private-test-password","status":401}'),
            ("application/problem+json", b'{"title":"Unauthorized","status":401}'),
            ("application/vnd.example+json", b'{"error":"unauthorized"}'),
            ("text/html", b"<html><h1>Service unavailable</h1></html>"),
            ("application/xhtml+xml", b"<html><h1>Access denied</h1></html>"),
        ):
            with self.subTest(mime=mime):
                target = self.folder / "POL.001.pdf"
                target.write_bytes(b"%PDF-complete-original")
                response = self.response([content], mime=mime, length=len(content))
                with self.assertRaises(OTError) as caught:
                    self.client.download_document("1", self.folder, target.name)
                self.assertNotIn("private-test-password", str(caught.exception))
                self.assertEqual(target.read_bytes(), b"%PDF-complete-original")
                self.assertEqual(list(self.folder.iterdir()), [target])
                self.assertTrue(response.closed)

    def test_mime_alone_cannot_turn_an_api_response_into_a_document(self):
        for filename in (None, "POL.001", "Policy"):
            for mime, content in (("application/json", b'{"entries":[]}'), ("text/html", b"<html>Service reply</html>")):
                with self.subTest(filename=filename, mime=mime):
                    self.response([content], mime=mime)
                    with self.assertRaises(OTError):
                        self.client.download_document("1", self.folder, filename)
                    self.assertEqual(list(self.folder.iterdir()), [])

    def test_explicit_json_and_html_documents_remain_downloadable(self):
        for filename, mime, content in (
            ("policy.json", "application/json", b'{"document":"policy"}'),
            ("policy.html", "text/html", b"<html><h1>Policy document</h1></html>"),
            ("policy.htm", "text/html", b"<html><h1>Policy document</h1></html>"),
        ):
            with self.subTest(filename=filename):
                self.response([content], mime=mime)
                result = self.client.download_document(filename, self.folder, filename)
                self.assertEqual(result.path.name, filename)
                self.assertEqual(result.path.read_bytes(), content)

    def test_attachment_filename_can_identify_a_json_or_html_document(self):
        for filename, mime, content in (
            ("policy.json", "application/json", b'{"document":"policy"}'),
            ("policy.html", "text/html", b"<html><h1>Policy document</h1></html>"),
        ):
            with self.subTest(filename=filename):
                self.response([content], mime=mime, filename=f'attachment; filename="{filename}"')
                result = self.client.download_document(filename, self.folder)
                self.assertEqual(result.path.name, filename)
                self.assertEqual(result.path.read_bytes(), content)

    def test_inline_json_filename_does_not_prove_a_document_attachment(self):
        self.response([b'{"error":"unauthorized"}'], mime="application/json", filename='inline; filename="response.json"')
        with self.assertRaises(OTError):
            self.client.download_document("1", self.folder)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_mislabeled_service_error_content_does_not_replace_a_pdf(self):
        for content in (
            b'{"error":"unauthorized","status":401}',
            b"<!doctype html><html><h1>Service unavailable</h1></html>",
        ):
            with self.subTest(content=content):
                target = self.folder / "POL.001.pdf"
                target.write_bytes(b"%PDF-original")
                self.response([content[:8], content[8:]], mime="application/octet-stream")
                with self.assertRaises(OTError):
                    self.client.download_document("1", self.folder, target.name)
                self.assertEqual(target.read_bytes(), b"%PDF-original")
                self.assertEqual(list(self.folder.iterdir()), [target])

    def test_media_requires_full_http_200_without_range_metadata(self):
        for status, content_range in ((204, None), (205, None), (206, None), (206, "bytes 0-3/100"), (200, "bytes 0-3/100")):
            with self.subTest(status=status, content_range=content_range):
                target = self.folder / "POL.001.pdf"
                target.write_bytes(b"%PDF-complete-original")
                content = b"part" if status not in (204, 205) else b""
                response = self.response([content], length=len(content))
                response.status_code = status
                if content_range is not None:
                    response.headers["Content-Range"] = content_range
                with self.assertRaises(OTError):
                    self.client.download_document("1", self.folder, target.name)
                self.assertEqual(target.read_bytes(), b"%PDF-complete-original")
                self.assertEqual(list(self.folder.iterdir()), [target])
                self.assertTrue(response.closed)

    def test_binary_document_with_embedded_html_example_is_not_a_login_page(self):
        content = b'%PDF-fixture containing <form><input type="password"></form> example text'
        self.response([content], mime="application/pdf")
        result = self.client.download_document("1", self.folder, "Report.pdf")
        self.assertEqual(result.path.read_bytes(), content)

    def test_progress_is_rate_limited_and_compression_length_is_not_misused(self):
        response = self.response([b"x"] * 1000, length=10)
        response.headers["Content-Encoding"] = "gzip"
        progress = []
        with patch("otClient.time.monotonic", return_value=1.0):
            result = self.client.download_document("1", self.folder, "Report.pdf", progress=lambda done, total: progress.append((done, total)))
        self.assertEqual(result.bytes_written, 1000)
        self.assertLessEqual(len(progress), 3)
        self.assertEqual(progress[-1], (1000, None))

    def test_hash_helper_hashes_file_incrementally(self):
        target = self.folder / "sample"
        target.write_bytes(b"payload")
        self.assertEqual(get_local_file_sha256(target), hashlib.sha256(b"payload").hexdigest())
        self.assertIsNone(get_local_file_sha256(self.folder / "missing"))


class LoopbackProtocolTests(unittest.TestCase):
    """Exercise requests cookies/redirects against an isolated local fixture."""

    def setUp(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send_body(self, body, content_type, status=200, headers=None):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path != "/TDS/j_spring_security_check":
                    self.send_body(b"", "text/plain", status=404)
                    return
                form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode("utf-8"))
                self.server.last_form = form
                if form == {"j_username": ["ordinary-user"], "j_password": ["ordinary-password"]}:
                    self.send_body(b"", "text/html", status=302, headers={"Location": "/TDS/", "Set-Cookie": "JSESSIONID=fixture-session; Path=/TDS; HttpOnly"})
                else:
                    # Deliberately uninformative HTTP 200: the protected probe,
                    # rather than page text or a stale cookie, must expose it.
                    self.send_body(b"<html>Authentication reply</html>", "text/html")

            def do_GET(self):
                if self.headers.get("Cookie") != "JSESSIONID=fixture-session":
                    self.send_body(b"", "text/html", status=302, headers={"Location": "/TDS/login.jsp"})
                    return
                parsed = urlsplit(self.path)
                if parsed.path == "/TDS/realtime-queries/tds_search_documents":
                    number = parse_qs(parsed.query).get("input_name", [""])[0]
                    entries = [entry(name="POL.001")] if number == "POL.001" else []
                    self.send_body(json.dumps({"entries": entries}).encode("utf-8"), "application/json")
                elif parsed.path == "/TDS/contents/tds_document/090001/media":
                    self.send_body(b"%PDF-fixture", "application/pdf")
                elif parsed.path == "/TDS/contents/tds_document/broken/media":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Length", "100")
                    self.end_headers()
                    self.wfile.write(b"truncated")
                    self.close_connection = True
                else:
                    self.send_body(b"", "text/plain", status=404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.05), daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.client = OTConnector(
            f"http://127.0.0.1:{self.httpd.server_port}", "ordinary-user", "ordinary-password", timeout=2
        )
        # Local test traffic must never be sent to a machine's configured proxy.
        self.client.client.session.trust_env = False
        self.addCleanup(self.client.close)

    def stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    def test_cookie_on_unfollowed_login_redirect_authenticates_probe_and_download(self):
        self.assertTrue(self.client.login())
        self.assertEqual(self.httpd.last_form["j_password"], ["ordinary-password"])
        documents = self.client.search_documents("POL.001")
        self.assertEqual(len(documents), 1)
        with tempfile.TemporaryDirectory() as temporary:
            result = self.client.download_document(documents[0].id, temporary, documents[0].name)
            self.assertEqual(result.path.name, "POL.001.pdf")
            self.assertEqual(result.path.read_bytes(), b"%PDF-fixture")
        self.client.password = "incorrect-password"
        with self.assertRaises(OTError):
            self.client.login()

    def test_real_requests_truncated_body_preserves_old_file(self):
        self.client.login()
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "Report.pdf"
            target.write_bytes(b"original")
            with self.assertRaises(OTError):
                self.client.download_document("broken", temporary, target.name)
            self.assertEqual(target.read_bytes(), b"original")
            self.assertEqual(list(Path(temporary).iterdir()), [target])


if __name__ == "__main__":
    unittest.main()
