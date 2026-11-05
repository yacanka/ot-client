"""Failure-focused tests for the network worker without Tk or live requests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest import mock

from otClient import (
    Document,
    DownloadCancelled,
    DownloadResult,
    otError,
    safe_windows_filename,
)
from ot_app.settings import AppSettings
from ot_app.worker import DownloadWorker, JobItem, WorkerEvent, select_document


def document(identifier: str = "1", name: str = "ABC.pdf") -> Document:
    return Document(identifier, name, "A document", "An author")


class FakeConnector:
    """A deterministic connector that records calls and can fail at each boundary."""

    def __init__(self) -> None:
        self.constructed = 0
        self.arguments = None
        self.login_calls = 0
        self.login_result = True
        self.login_error = None
        self.login_hook = None
        self.results = {}
        self.searches = []
        self.downloads = []
        self.download_errors = {}
        self.download_hook = None
        self.result_status = "downloaded"
        self.close_calls = 0
        self.close_error = None
        self.thread_ids = []

    def factory(self, base_url, **kwargs):
        self.constructed += 1
        self.arguments = {"base_url": base_url, **kwargs}
        return self

    def login(self):
        self.thread_ids.append(threading.get_ident())
        self.login_calls += 1
        if self.login_hook:
            self.login_hook()
        if self.login_error:
            raise self.login_error
        return self.login_result

    def search_documents(self, number):
        self.searches.append(number)
        result = self.results.get(number, [])
        if isinstance(result, Exception):
            raise result
        if callable(result):
            return result()
        return result

    def download_document(
        self,
        identifier,
        folder_path,
        file_name=None,
        overwrite=False,
        *,
        cancel_event=None,
        progress=None,
    ):
        self.downloads.append(
            {
                "id": identifier,
                "folder_path": folder_path,
                "file_name": file_name,
                "overwrite": overwrite,
                "cancel_event": cancel_event,
            }
        )
        if identifier in self.download_errors:
            raise self.download_errors[identifier]
        if self.download_hook:
            return self.download_hook(
                identifier, folder_path, file_name, overwrite, cancel_event, progress
            )
        content = ("document " + str(identifier)).encode("utf-8")
        path = Path(folder_path) / safe_windows_filename(file_name, identifier)
        path.write_bytes(content)
        if progress:
            progress(len(content), len(content))
        return DownloadResult(path, self.result_status, len(content))

    def close(self):
        self.close_calls += 1
        if self.close_error:
            raise self.close_error


class MatchPolicyTests(unittest.TestCase):
    def test_equal_exact_names_with_distinct_ids_are_ambiguous(self):
        self.assertIsNone(
            select_document(" ABC.pdf ", [document("1"), document("2", "abc.PDF")])
        )

    def test_multiple_nonexact_results_are_ambiguous(self):
        self.assertIsNone(
            select_document("ABC", [document("1"), document("2", "ABC.docx")])
        )

    def test_full_casefolded_name_wins_over_partial_results(self):
        exact = document("2", "abc.PDF")
        self.assertIs(
            select_document(" ABC.pdf ", [document("1", "ABC.pdf old"), exact]),
            exact,
        )

    def test_extension_is_significant_when_multiple_candidates_exist(self):
        self.assertIsNone(
            select_document("ABC", [document("1", "ABC.pdf"), document("2", "ABC.txt")])
        )

    def test_single_unique_candidate_is_accepted(self):
        candidate = document("1", "A server-provided filename.pdf")
        self.assertIs(select_document("ABC", [candidate]), candidate)

    def test_duplicate_results_for_same_id_are_one_candidate(self):
        candidate = document("1")
        self.assertIs(select_document("ABC", [candidate, document("1")]), candidate)

    def test_duplicate_id_does_not_hide_an_exact_name(self):
        exact = document("1", "ABC.pdf")
        self.assertIs(
            select_document("ABC.pdf", [document("1", "old name"), exact]), exact
        )

    def test_empty_result_has_no_selection(self):
        self.assertIsNone(select_document("ABC", []))


class DownloadWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.settings = AppSettings(
            base_url="https://ot.example",
            username="alice",
            password="private-value-934",
            output_dir=self.temporary.name,
        )
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.client = FakeConnector()

    def make_worker(self, items=None, **kwargs):
        if items is None:
            items = [JobItem("row-1", "ABC")]
        return DownloadWorker(
            self.settings,
            items,
            self.events,
            self.cancel,
            connector_factory=self.client.factory,
            **kwargs,
        )

    def collect(self):
        result = []
        while True:
            try:
                result.append(self.events.get_nowait())
            except queue.Empty:
                return result

    def statuses(self, events, key=None):
        return [
            event.payload["status"]
            for event in events
            if event.kind == "status" and (key is None or event.key == key)
        ]

    def finished(self, events):
        finished = [event for event in events if event.kind == "finished"]
        self.assertEqual(len(finished), 1)
        self.assertIs(events[-1], finished[0])
        return finished[0].payload

    def test_login_failure_is_fatal_and_never_marks_pending_items_successful(self):
        self.client.login_error = otError("Oturum açılamadı")
        self.make_worker([JobItem("1", "ABC"), JobItem("2", "DEF")]).run()
        events = self.collect()
        self.assertEqual(len([event for event in events if event.kind == "fatal"]), 1)
        self.assertEqual(self.client.searches, [])
        self.assertEqual(self.client.downloads, [])
        self.assertEqual(self.client.close_calls, 1)
        self.assertNotIn("downloaded", self.statuses(events))
        self.assertEqual(
            self.finished(events), {"cancelled": False, "processed": 0, "total": 2}
        )

    def test_false_login_result_is_fatal(self):
        self.client.login_result = False
        self.make_worker().run()
        events = self.collect()
        self.assertTrue(any(event.kind == "fatal" for event in events))
        self.assertEqual(self.client.searches, [])
        self.assertEqual(self.client.close_calls, 1)
        self.assertEqual(self.finished(events)["processed"], 0)

    def test_cancel_before_start_never_constructs_a_connector(self):
        self.cancel.set()
        self.make_worker().run()
        events = self.collect()
        self.assertEqual(self.client.constructed, 0)
        self.assertEqual(self.statuses(events), ["cancelled"])
        self.assertEqual(
            self.finished(events), {"cancelled": True, "processed": 0, "total": 1}
        )

    def test_cancel_after_login_stops_before_search(self):
        self.client.login_hook = self.cancel.set
        self.make_worker().run()
        events = self.collect()
        self.assertEqual(self.client.searches, [])
        self.assertEqual(self.client.close_calls, 1)
        self.assertEqual(self.statuses(events), ["cancelled"])
        self.assertEqual(self.finished(events)["processed"], 0)

    def test_cancel_after_search_prevents_download(self):
        def search():
            self.cancel.set()
            return [document()]

        self.client.results["ABC"] = search
        self.make_worker().run()
        events = self.collect()
        self.assertEqual(self.client.downloads, [])
        self.assertEqual(self.statuses(events), ["searching", "cancelled"])
        self.assertTrue(self.finished(events)["cancelled"])
        self.assertEqual(self.finished(events)["processed"], 1)

    def test_cancel_mid_download_stops_remaining_items_and_flushes_progress(self):
        self.client.results = {"ABC": [document()], "DEF": [document("2", "DEF.pdf")]}

        def cancel_download(identifier, folder, name, overwrite, cancel_event, progress):
            progress(1, 100)
            progress(7, 100)
            cancel_event.set()
            raise DownloadCancelled("İndirme iptal edildi")

        self.client.download_hook = cancel_download
        with mock.patch("ot_app.worker.time.monotonic", return_value=10.0):
            self.make_worker([JobItem("1", "ABC"), JobItem("2", "DEF")]).run()
        events = self.collect()
        self.assertEqual(self.client.searches, ["ABC"])
        self.assertEqual(self.statuses(events, "1")[-1], "cancelled")
        self.assertEqual(self.statuses(events, "2"), ["cancelled"])
        progress = [event for event in events if event.kind == "progress"]
        self.assertEqual(progress[-1].payload, {"downloaded": 7, "total": 100})
        self.assertFalse(any(event.kind == "fatal" for event in events))
        self.assertEqual(self.client.close_calls, 1)
        self.assertEqual(
            self.finished(events), {"cancelled": True, "processed": 1, "total": 2}
        )

    def test_recoverable_search_error_allows_later_items_to_finish(self):
        self.client.results = {
            "ABC": otError("Arama başarısız"),
            "DEF": [document("2", "DEF.pdf")],
        }
        self.make_worker([JobItem("1", "ABC"), JobItem("2", "DEF")]).run()
        events = self.collect()
        self.assertEqual(self.statuses(events, "1")[-1], "error")
        self.assertEqual(self.statuses(events, "2")[-1], "downloaded")
        self.assertFalse(any(event.kind == "fatal" for event in events))
        self.assertEqual(self.finished(events)["processed"], 2)
        self.assertEqual(self.client.close_calls, 1)

    def test_recoverable_download_error_allows_later_items_to_finish(self):
        self.client.results = {"ABC": [document()], "DEF": [document("2", "DEF.pdf")]}
        self.client.download_errors["1"] = otError("İndirme başarısız")
        self.make_worker([JobItem("1", "ABC"), JobItem("2", "DEF")]).run()
        events = self.collect()
        self.assertEqual(self.statuses(events, "1")[-1], "error")
        self.assertEqual(self.statuses(events, "2")[-1], "downloaded")
        self.assertEqual(self.finished(events)["processed"], 2)

    def test_programming_error_is_explicitly_fatal_and_does_not_continue(self):
        self.client.results = {
            "ABC": RuntimeError("broken invariant"),
            "DEF": [document("2", "DEF.pdf")],
        }
        self.make_worker([JobItem("1", "ABC"), JobItem("2", "DEF")]).run()
        events = self.collect()
        fatal = [event for event in events if event.kind == "fatal"]
        self.assertEqual(len(fatal), 1)
        self.assertIn("RuntimeError", fatal[0].payload["message"])
        self.assertEqual(self.statuses(events, "1")[-1], "error")
        self.assertEqual(self.client.searches, ["ABC"])
        self.assertEqual(self.client.close_calls, 1)
        self.assertEqual(self.finished(events)["processed"], 1)

    def test_connector_construction_failure_still_finishes(self):
        def bad_factory(*args, **kwargs):
            raise otError("Bağlantı oluşturulamadı")

        worker = DownloadWorker(
            self.settings, [JobItem("1", "ABC")], self.events, self.cancel,
            connector_factory=bad_factory,
        )
        worker.run()
        events = self.collect()
        self.assertTrue(any(event.kind == "fatal" for event in events))
        self.assertEqual(self.finished(events)["processed"], 0)

    def test_close_failure_is_reported_and_finished_is_still_last(self):
        self.client.close_error = RuntimeError("could not close")
        self.make_worker().run()
        events = self.collect()
        fatal = [event for event in events if event.kind == "fatal"]
        self.assertEqual(len(fatal), 1)
        self.assertIn("RuntimeError", fatal[0].payload["message"])
        self.assertEqual(self.finished(events)["processed"], 1)

    def test_no_results_is_not_found_without_downloading(self):
        self.make_worker().run()
        events = self.collect()
        self.assertEqual(self.statuses(events), ["searching", "not_found"])
        self.assertEqual(self.client.downloads, [])
        self.assertEqual(self.finished(events)["processed"], 1)

    def test_ambiguous_results_include_candidates_and_are_not_downloaded(self):
        candidates = [document("1", "ABC.pdf"), document("2", "ABC.docx")]
        self.client.results["ABC"] = candidates
        self.make_worker().run()
        events = self.collect()
        ambiguous = next(
            event for event in events
            if event.kind == "status" and event.payload["status"] == "ambiguous"
        )
        self.assertEqual(ambiguous.payload["candidates"], tuple(candidates))
        self.assertEqual(self.client.downloads, [])
        self.assertEqual(self.finished(events)["processed"], 1)

    def test_explicitly_selected_candidate_skips_search(self):
        selected = document("chosen", "A different name.pdf")
        self.make_worker([JobItem("chosen-row", "ABC", selected)]).run()
        events = self.collect()
        self.assertEqual(self.client.searches, [])
        self.assertEqual(self.client.downloads[0]["id"], "chosen")
        self.assertEqual(self.client.downloads[0]["file_name"], selected.name)
        self.assertEqual(self.statuses(events), ["downloading", "downloaded"])

    def test_same_name_from_distinct_documents_never_overwrites_first_download(self):
        items = [
            JobItem("1", "ABC", document("1", "Same.pdf")),
            JobItem("2", "DEF", document("2", "Same.pdf")),
        ]
        self.make_worker(items).run()
        events = self.collect()
        self.assertEqual(len(self.client.downloads), 1)
        self.assertEqual(self.statuses(events, "2"), ["error"])
        self.assertEqual((Path(self.temporary.name) / "Same.pdf").read_bytes(), b"document 1")
        self.assertEqual(self.finished(events)["processed"], 2)

    def test_collision_check_is_case_insensitive_for_windows(self):
        items = [
            JobItem("1", "ABC", document("1", "Same.pdf")),
            JobItem("2", "DEF", document("2", "same.PDF")),
        ]
        self.make_worker(items, force=True).run()
        events = self.collect()
        self.assertEqual(len(self.client.downloads), 1)
        self.assertEqual(self.statuses(events, "2"), ["error"])

    def test_same_document_can_be_downloaded_again_under_its_normal_name(self):
        selected = document("1", "Same.pdf")
        self.make_worker([JobItem("1", "ABC", selected), JobItem("2", "DEF", selected)]).run()
        events = self.collect()
        self.assertEqual(len(self.client.downloads), 2)
        self.assertEqual(self.statuses(events, "2")[-1], "downloaded")
        self.assertFalse(any(event.kind == "fatal" for event in events))

    def test_success_carries_result_status_path_and_document(self):
        selected = document()
        self.client.results["ABC"] = [selected]
        self.client.result_status = "updated"
        self.make_worker(force=True).run()
        events = self.collect()
        status = next(
            event for event in events
            if event.kind == "status" and event.payload["status"] == "updated"
        )
        self.assertEqual(status.payload["document"], selected)
        self.assertEqual(status.payload["path"], str(Path(self.temporary.name) / "ABC.pdf"))
        self.assertTrue(self.client.downloads[0]["overwrite"])
        self.assertIs(self.client.downloads[0]["cancel_event"], self.cancel)
        self.assertEqual(
            [event.payload["state"] for event in events if event.kind == "session"],
            ["connecting", "connected"],
        )
        advance = [event.payload for event in events if event.kind == "advance"]
        self.assertEqual(advance[-1], {"done": 1, "total": 1})
        self.assertEqual(
            self.finished(events), {"cancelled": False, "processed": 1, "total": 1}
        )

    def test_unchanged_result_is_not_reported_as_downloaded(self):
        self.client.results["ABC"] = [document()]
        self.client.result_status = "unchanged"
        self.make_worker().run()
        events = self.collect()
        self.assertEqual(self.statuses(events)[-1], "unchanged")
        self.assertNotIn("downloaded", self.statuses(events))

    def test_progress_is_throttled_and_terminal_update_is_retained(self):
        self.client.results["ABC"] = [document()]

        def download(identifier, folder, name, overwrite, cancel_event, progress):
            for count in range(1001):
                progress(count, 1000)
            return DownloadResult(Path(folder) / name, "downloaded", 1000)

        self.client.download_hook = download
        with mock.patch("ot_app.worker.time.monotonic", return_value=10.0):
            self.make_worker().run()
        events = self.collect()
        progress = [event for event in events if event.kind == "progress"]
        self.assertGreaterEqual(len(progress), 1)
        self.assertLessEqual(len(progress), 3)
        self.assertEqual(progress[-1].payload, {"downloaded": 1000, "total": 1000})

    def test_unknown_length_download_flushes_last_progress(self):
        self.client.results["ABC"] = [document()]

        def download(identifier, folder, name, overwrite, cancel_event, progress):
            progress(1, None)
            progress(13, None)
            return DownloadResult(Path(folder) / name, "downloaded", 13)

        self.client.download_hook = download
        with mock.patch("ot_app.worker.time.monotonic", return_value=10.0):
            self.make_worker().run()
        progress = [event for event in self.collect() if event.kind == "progress"]
        self.assertEqual(progress[-1].payload, {"downloaded": 13, "total": None})

    def test_wrong_declared_size_does_not_bypass_progress_throttling(self):
        self.client.results["ABC"] = [document()]

        def download(identifier, folder, name, overwrite, cancel_event, progress):
            for count in range(1001):
                progress(count, 0)
            return DownloadResult(Path(folder) / name, "downloaded", 1000)

        self.client.download_hook = download
        with mock.patch("ot_app.worker.time.monotonic", return_value=10.0):
            self.make_worker().run()
        progress = [event for event in self.collect() if event.kind == "progress"]
        self.assertLessEqual(len(progress), 3)
        self.assertEqual(progress[-1].payload, {"downloaded": 1000, "total": 0})

    def test_settings_and_item_list_are_snapshotted(self):
        selected = document()
        items = [JobItem("1", "ABC", selected)]
        self.settings.timeout = 47
        self.settings.folder_id = "folder"
        worker = self.make_worker(items)
        items.clear()
        self.settings.username = "changed-after-start"
        worker.run()
        self.assertEqual(self.client.arguments["username"], "alice")
        self.assertEqual(self.client.arguments["timeout"], 47)
        self.assertEqual(self.client.arguments["folder_id"], "folder")
        self.assertTrue(self.client.arguments["verify"])
        self.assertEqual(len(self.client.downloads), 1)

    def test_credentials_are_redacted_from_failure_events(self):
        self.client.login_error = otError("Secret: " + self.settings.password)
        self.make_worker().run()
        events = self.collect()
        self.assertNotIn(self.settings.password, repr(events))
        self.assertTrue(any(event.kind == "fatal" for event in events))

    def test_empty_job_does_not_contact_server(self):
        self.make_worker([]).run()
        events = self.collect()
        self.assertEqual(self.client.constructed, 0)
        self.assertEqual(
            self.finished(events), {"cancelled": False, "processed": 0, "total": 0}
        )

    def test_thread_is_daemon_and_runs_connector_off_the_main_thread(self):
        worker = self.make_worker()
        self.assertTrue(worker.daemon)
        worker.start()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertNotEqual(self.client.thread_ids[0], threading.get_ident())
        self.finished(self.collect())

    def test_job_items_and_event_envelopes_are_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            JobItem("1", "ABC").number = "changed"
        with self.assertRaises(FrozenInstanceError):
            WorkerEvent("finished").kind = "changed"


if __name__ == "__main__":
    unittest.main()
