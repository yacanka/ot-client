# OT Desktop Implementation Plan

> For agentic workers: execute assigned tasks in isolation and verify their outputs. Root coordinates shared interfaces and final review.

**Goal:** Deliver a runnable Windows document download application with persisted settings and a modern Turkish UI.
**Architecture:** Tk main loop + event queue + a background worker; original protocol isolated in otClient.py; registry and input parsing isolated in ot_app.
**Tech Stack:** Python 3.10+, Tkinter/ttk, requests, ctypes/winreg.
**Spec:** ../specs/2026-10-05-kdys-design.md

## Global constraints
- No Base64 or implicit environment configuration; no live corporate requests in development.
- Preserve user document identifiers and file contents on failure.
- All UI actions stay responsive; secret fields must not enter logs/exports.
- No external git repository; develop in a separate OT_Desktop directory and deliver source plus ZIP.

## Review focus
- 200 HTML authentication failure and invalid JSON must not look successful.
- Interrupted streamed downloads must not corrupt an existing file or leave temp files.
- Cancel/close while a worker is active must not create Tk thread errors.
- Registry corruption or DPAPI errors must not silently discard a saved password.
- Bulk documents, duplicates, empty inputs and large lists must behave predictably.

## Task 1 — HTTP client
Files: otClient.py, tests/test_client.py.
Produces: OTConnector(base_url, username="", password="", timeout=30, verify=True, folder_id=""), login(), test_connection(), search_documents(number)->list[Document], download_document(id, folder_path, file_name=None, overwrite=False, *, cancel_event=None, progress=None)->DownloadResult, close(). DownloadResult(path, status, bytes_written); status downloaded/updated/unchanged. Exceptions OTError and DownloadCancelled. Document(id, name, title, author). Preserve search_document raw response and get_document_by_id for compatibility.
- [x] Add failure-focused tests and confirm missing behavior.
- [x] Implement validated settings, useful HTTP/JSON errors, authenticated API check, safe streaming/atomic writes.
- [x] Run python -m unittest discover -s tests -p test_client.py -v; expected all tests pass.

## Task 2 — Settings and document inputs
Files: ot_app/settings.py, ot_app/documents.py, tests/test_settings.py, tests/test_documents.py.
Produces: AppSettings(base_url="", username="", password="", output_dir=<user Documents/OT Documents>, timeout=30, folder_id="", ca_bundle="", verify_tls=True, remember_password=True); .validate(require_connection=False)->None or ValueError; RegistryStore.load()->(AppSettings,list[str]), save(settings, documents)->None, .warning:str. SettingsError. parse_document_text(text)->list[str], merge_document_numbers(existing,incoming)->list[str], read_document_file(path)->list[str], write_document_file(path,numbers)->None.
- [x] Write tests for parsing, invalid settings, registry roundtrip with fake native boundary, secret removal and corrupt settings.
- [x] Implement registry / DPAPI and document list imports and exports.
- [x] Run python -m unittest discover -s tests -p test_settings.py -v and test_documents.py; expected all pass.

## Task 3 — UI and worker
Files: ot_app/app.py, theme.py, views.py, settings_view.py, dialogs.py, worker.py, ot_desktop.pyw, tests/test_worker.py, tests/test_ui.py.
Consumes interfaces above. Worker accepts immutable job items, copied settings and queue/events. Root owns these files. Implement testable matching policy and typed events; render queue states and give an ambiguity-selection action. Use ttk Treeview virtualized rows, progress and user-focused Turkish messages. Include keyboard navigation, initial empty state, useful validation and bulk edit preview.
- [x] Write tests for matching, cancellation and worker outcome events, then implement worker.
- [x] Build UI, create display-driven smoke checks and inspect real rendered screenshots where possible.
- [x] Run full unittest suite and compileall; expected no failures (Windows native tests may be explicitly skipped off Windows).

## Task 4 — Review and delivery
Files: README.md, requirements.txt, Baslat.cmd, Kurulum.cmd, docs/validation.md, OT_Desktop.zip.
- [x] Independent code review of complete application; correct substantial findings and run focused regression tests.
- [x] Include honest Linux/Windows/live-server validation boundaries and troubleshooting in Turkish README.
- [x] Save the updated otClient.py under its existing identity, and save ZIP plus preview artifacts.


Final validation: 169 tests, 168 passed and one native Windows DPAPI skip. Independent review fixes are recorded in ../../validation.md. No git commit or deployment was required; source delivered as files.
