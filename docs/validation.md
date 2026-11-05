# Verification record — 2026-11-05

## Filename format and table alignment update

- Command: `python -B -m unittest discover -s tests -v`, using the existing isolated test environment.
- Result: **212 tests; 211 passed, 1 skipped** (native Windows current-user DPAPI).
- All 21 real Tk interaction tests passed, including filename tag insertion, selected-text replacement, live preview, validation and compact-window scrolling.
- Additional regressions cover saved/legacy filename formats, revision zero, repeated extensions, metadata traversal characters, formatted-name collisions and worker settings snapshots.
- Custom filenames retain source/response extension evidence. Renamed JSON/HTML titles cannot authorize service responses; explicitly identified JSON documents remain supported.
- All 25 Python/PYW files compile in memory and pass Python 3.10 grammar checks. Ruff `E9,F` and `git diff --check` pass.
- Live Tk widget checks confirmed centered number/revision/status/size columns, left-aligned titles, and settings save/reload. Native screenshot capture was unavailable; widget geometry and interaction tests were used for layout validation.
- No dependencies changed. Native Windows integration and live corporate OT remain untested; the earlier dependency audit below was not rerun.

## Earlier review

- Runtime: macOS, Python 3.11.15, requests 2.34.2, Tk 9.0.4.
- Isolated test environment outside the repository; no runtime dependency changes.
- Command: `python -B -m unittest discover -s tests -v`.
- Result: **187 tests; 186 passed, 1 skipped**. The skipped test requires native Windows current-user DPAPI.
- All 19 real Tk interaction tests passed, including dialogs, worker completion, cancellation, queue persistence, filtering and window layout.
- Real loopback HTTP tests passed; they use only a temporary server on `127.0.0.1`.
- New regressions cover revision columns, implicit netrc authentication, arbitrary exception disclosure, credential/context mismatch, partial secret writes, CA path expansion, disabled-TLS settings reload, atomic report failure and UTF-16/UTF-32 login-page rejection.
- All 22 Python/PYW source and test files compile in memory and pass `ast.parse(..., feature_version=(3, 10))`. This checks Python 3.10 grammar, not execution under Python 3.10.
- `ruff check --no-cache --select E9,F .` passed; `git diff --check` passed.
- Broad Ruff checks still report style/design advisories, including import ordering and deliberate exception boundaries. `ruff format --check .` reports 20 files requiring formatting. These checks are **not clean**; no repository-wide formatting or unrelated refactoring was applied.
- `pip-audit -r requirements.txt` reported **0 known vulnerabilities** for requests 2.34.2, charset-normalizer 3.5.2, idna 3.20, urllib3 2.8.0 and certifi 2026.10.23. This is the dependency resolution observed during this review, not a transitive lockfile or a guarantee against unknown vulnerabilities.
- Source review, credential-pattern scanning of 41 historical Git blobs, and inspection of 1,141 decoded bytecode string constants found no confirmed real embedded credential. Test fixtures contain synthetic values. A pattern scan cannot prove the absence of every secret.
- Initial default Python lacked Tkinter; an existing Tk-capable Python was used in the isolated environment. Sandbox networking/display restrictions were resolved for loopback tests, native UI tests and dependency auditing.
- Not executed: native Windows registry/DPAPI, Windows CMD scripts, Windows DPI behavior, and live corporate OT authentication. No corporate endpoint or real credentials were used.

See the [review report](review-2026-11-05.md) for changes and remaining maintenance candidates. This record supersedes the earlier delivery's test claims for the current checkout.
