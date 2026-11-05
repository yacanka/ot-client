# OT Desktop design

## Goal
Turn the attached OTClient.py into a lightweight Windows desktop application for entering a document-number list and downloading corporate OT documents. All runtime configuration is editable from the UI and retained per Windows user. The user authorized implementation and targeted client improvements.

## UX
A corporate light interface with a compact navy sidebar, generous spacing and Turkish labels. Two views: Belgeler and Bağlantı / Ayarlar. The main view contains a document-number field with Enter-to-add, a bulk paste dialog, TXT/CSV import, multi-select remove, undo last removal, list export, filter/search, row status/details, totals, progress, start/selected start and cancellation. Clipboard input accepts newline, tab, comma/semicolon-separated identifiers or a JSON string array. Deduplicate exact trimmed identifiers in insertion order; case variants are distinct.

Settings: base URL, username, masked password with reveal toggle and remember option, output directory picker, request timeout, optional folder ID for the existing folder-list method, optional CA certificate bundle, and an explicit TLS validation toggle (default on). Save settings and test connection. Autosave document changes using a short debounce. Settings are only saved on explicit Save or starting a job. On first launch, retain an empty queue and show clear setup guidance.

## Architecture
Python 3.10+ and Tkinter/ttk, requests as the only external runtime dependency. No web server, browser runtime, cloud service or telemetry. Separate HTTP client, Windows settings, document parsing, worker, and presentation modules. No network access during imports. Tk widgets are touched only on the main thread; a single worker reports immutable events through queue.Queue and cooperative cancellation uses threading.Event. Downloads stream to a unique temporary file in the target directory, validate byte count where possible, compare SHA256 and atomically replace only on complete success. Preserve a local file if cancellation or error interrupts download. Preserve server extensions and clean Windows filenames. Report unambiguous exact matches; ambiguous results require user selection.

## Persistence
HKCU\Software\OTDesktop, no elevation. Settings JSON as REG_SZ, document identifiers as REG_MULTI_SZ, password protected with current-user Windows DPAPI as REG_BINARY. No Base64, dotenv, hardcoded account, plaintext secret in registry, credentials in exports or logs. Remember-password disabled removes the stored encrypted secret. Unsupported OS uses explicit nonpersistent mode for development; never a silently insecure file fallback. Registry errors are visible and current UI values remain usable for the session.

## Compatibility and verification
Preserve supplied OT endpoint paths and login form fields. Credentials are ordinary strings. Preserve original public helper names where useful, and Document(id, name, title, author). Login checks error redirects and HTML login forms rather than treating every HTTP 200 as authenticated; a protected search request validates access. Non-JSON API replies receive a useful error. No automatic retries of authentication POST. HTTP errors must avoid echoing credentials or full response bodies. Test client behavior with fake transports / local HTTP server; test document input and registry failures via injected fake native services. Run headless Tk interaction and capture real UI screenshots if a display service is available. Clearly distinguish tests from a live corporate-server/Windows test, which is unavailable here.
