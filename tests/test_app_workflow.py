"""Controller boundaries that do not require a display or real server."""
import queue
import threading
import unittest

from ot_app.app import Application
from ot_app.settings import AppSettings
from ot_app.queue_model import QueueRow
from otClient import Document


class ConnectionProbeTests(unittest.TestCase):
    def run_probe(self, settings, action=lambda: True, cancelled=False):
        from types import SimpleNamespace
        calls = []
        class Connector:
            def __init__(self, *args, **kwargs):
                calls.append(kwargs)
            def test_connection(self):
                return action()
            def close(self):
                pass
        controller = SimpleNamespace(events=queue.Queue(), cancel_event=threading.Event(), connector_factory=Connector)
        if cancelled:
            controller.cancel_event.set()
        Application._test_connection_worker(controller, settings)
        events = []
        while not controller.events.empty():
            events.append(controller.events.get_nowait())
        return calls, events

    def test_disabled_tls_takes_priority_over_retained_certificate_path(self):
        settings = AppSettings(verify_tls=False, ca_bundle="previous-certificate.pem")
        calls, _ = self.run_probe(settings)
        self.assertIs(calls[0]["verify"], False)

    def test_false_probe_does_not_become_success(self):
        _, events = self.run_probe(AppSettings(), action=lambda: False)
        result = next(event for event in events if event.kind == "connection_result")
        self.assertFalse(result.payload["success"])

    def test_exception_does_not_disclose_password_in_ui(self):
        def fail():
            raise RuntimeError("Failed with secret: private-password")
        _, events = self.run_probe(AppSettings(password="private-password"), action=fail)
        result = next(event for event in events if event.kind == "connection_result")
        self.assertNotIn("private-password", result.payload["message"])

    def test_already_cancelled_probe_makes_no_connection(self):
        calls, events = self.run_probe(AppSettings(), cancelled=True)
        self.assertEqual(calls, [])
        self.assertEqual(events[-1].kind, "finished")

    def test_unexpected_error_details_are_not_exposed(self):
        detail = "synthetic upstream token and private URL"
        def fail():
            raise RuntimeError(detail)
        _, events = self.run_probe(AppSettings(), action=fail)
        result = next(event for event in events if event.kind == "connection_result")
        self.assertFalse(result.payload["success"])
        self.assertNotIn(detail, result.payload["message"])
        self.assertIn("RuntimeError", result.payload["message"])

    def test_certificate_home_directory_is_expanded_for_probe(self):
        from pathlib import Path
        calls, _ = self.run_probe(AppSettings(ca_bundle="~/test-ca.pem"))
        self.assertEqual(calls[0]["verify"], str(Path.home() / "test-ca.pem"))


class RowPresentationTests(unittest.TestCase):
    def test_revision_status_and_size_have_separate_columns(self):
        row = QueueRow("DOC", document=Document("1", "DOC", "Title", "", 7),
                       status="downloaded", size=1024)
        self.assertEqual(Application._row_values(None, row),
                         ("DOC", "Title", 7, "İndirildi", "1.0 KB"))

    def test_pending_row_has_five_values_and_no_revision(self):
        values = Application._row_values(None, QueueRow("DOC"))
        self.assertEqual(len(values), 5)
        self.assertEqual(values[2:], ("—", "Bekliyor", "—"))


class ReportExportTests(unittest.TestCase):
    def test_folder_ambiguity_report_explains_skipped_document_without_old_path(self):
        import csv
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from ot_app.actions import DocumentActions

        row = QueueRow("DOC-001", status="folder_ambiguous",
                       message="Birden fazla klasör eşleşti; belge atlandı.", path="")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.csv"
            controller = SimpleNamespace(selected_rows=lambda: [row], set_notice=lambda *args: None)
            with patch("ot_app.actions.filedialog.asksaveasfilename", return_value=str(path)):
                DocumentActions.export_report(controller)
            with path.open(encoding="utf-8-sig", newline="") as stream:
                cells = list(csv.reader(stream, delimiter=";"))
            self.assertEqual(cells[1][2:], ["Klasör belirsiz", row.message, ""])

    def test_failed_report_replace_preserves_existing_report(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from ot_app.actions import DocumentActions

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.csv"
            path.write_bytes(b"previous report")
            controller = SimpleNamespace(
                selected_rows=lambda: [QueueRow("DOC")],
                set_notice=lambda *args: None,
            )
            with patch("ot_app.actions.filedialog.asksaveasfilename", return_value=str(path)), \
                    patch("ot_app.actions.messagebox.showerror"), \
                    patch("ot_app.documents.os.replace", side_effect=PermissionError("locked")):
                DocumentActions.export_report(controller)
            self.assertEqual(path.read_bytes(), b"previous report")
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_report_cells_are_escaped_without_changing_queue(self):
        import csv
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        from ot_app.actions import DocumentActions

        row = QueueRow("=1+1", document=Document("1", "DOC", "+title", ""),
                       message="\t@message", path="-file")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.csv"
            controller = SimpleNamespace(selected_rows=lambda: [row], set_notice=lambda *args: None)
            with patch("ot_app.actions.filedialog.asksaveasfilename", return_value=str(path)):
                DocumentActions.export_report(controller)
            with path.open(encoding="utf-8-sig", newline="") as stream:
                cells = list(csv.reader(stream, delimiter=";"))
            self.assertEqual(cells[1], ["'=1+1", "'+title", "Bekliyor", "'\t@message", "'-file"])
            self.assertEqual(row.number, "=1+1")


if __name__ == "__main__":
    unittest.main()
