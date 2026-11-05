# Verification record — 2026-10-05

- Runtime: Python 3.12.14, requests 2.34.2, Tk 9.0.4 on Linux.
- Command: python -m unittest discover -s tests -q, executed with a real authenticated Xvfb display.
- Result: 169 tests; 168 passed, 1 skipped (native Windows current-user DPAPI roundtrip).
- Real loopback HTTP integration covered authentication-cookie persistence and truncated media preservation.
- Full UI workflow covered button-triggered worker, queue events, per-row success/not-found outcomes, and return to idle.
- Visual inspection: main workspace at1280×930; compact workspace at1050×710; settings and dialogs.
- All source files compile. Python3.10 grammar compatibility is checked separately from execution on3.12.
- Source checked for removed base64/dotenv/tabulate imports and import-time network calls.
- Independent review findings fixed with regressions: late close declined after save failure stopping polling; unexpected JSON media overwriting a PDF; no-content/partial media overwriting a complete file; closing/config-only saves overwriting an unread queue; undo exceeding queue limits.
- Remaining platform boundary: actual Windows registry/DPAPI and CMD execution, native Windows appearance/DPI, and corporate OT authentication/redirect variations cannot be confirmed in this Linux environment.
- No corporate endpoint or user credentials were used. Preview rows are synthetic examples in a memory-only store.
