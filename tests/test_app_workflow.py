"""Controller boundaries that do not require a display or real server."""
import queue
import threading
import unittest

from ot_app.app import Application
from ot_app.settings import AppSettings


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


if __name__ == "__main__":
    unittest.main()
