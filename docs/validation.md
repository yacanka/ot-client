# Verification record — 2026-11-06

## Manual folder hierarchy

- Full command: `/private/tmp/ot-client-review-venv/bin/python -B -m unittest discover -s tests -q`.
- Final result: **380 tests; 379 passed, 1 skipped** (native Windows current-user DPAPI). Real Tk and loopback HTTP tests ran with native GUI/socket access. Initial restricted runs could not access macOS graphical services or bind the loopback test server.
- Added 72 tests across the hierarchy model, persistence, worker/storage, and real Tk integration. They cover dynamic dotted indices, subtree and sibling-block moves, atomic invalid selections, promotion/removal/undo/re-added identities, filtering/busy guards, draft mode changes, all save routes, corrupted/stale hierarchy recovery, partial writes, selected-child downloads, ancestor caching/failure isolation, cancellation, nested matching and safe paths, related files, and filename collisions.
- Independent model/persistence review approved the implementation. Final integration review found that unselected ancestors needing a candidate choice were missing from the choice-required filter. A regression reproduced the issue; the filter now includes candidate-bearing rows while preserving prior download history. The final complete suite above includes this fix.
- All **35** Python/PYW files compile in memory and pass Python 3.10 grammar checks. Ruff `E9,F` and `git diff --check` pass. No dependencies changed.
- Performance observations on this macOS/Python 3.11 environment: typical 10,000-entry model indexing median **3.67 ms**, two-subtree move **3.81 ms** (25 runs). A 10,000-row Tk table populated in **87 ms**; indent including widget updates median **79.3 ms** (5 runs, withdrawn window, excluding display painting/network/disk). These are local measurements, not cross-platform latency guarantees.
- Existing workspace changes to the client and related-download tests were preserved. No existing downloaded files were moved or removed; list import/export formats and the public connector API remain unchanged.
- Not executed: a live corporate OT connection or native Windows registry/DPAPI/junction/UI verification. Registry/secret and filesystem boundaries have injected tests; existing path-based concurrent-directory-replacement limitations remain.

## Related forms and attachments

- Full command: `/private/tmp/ot-client-review-venv/bin/python -B -m unittest discover -s tests -q`.
- Result: **308 tests; 307 passed, 1 skipped** (native Windows current-user DPAPI). Real Tk and loopback HTTP tests ran outside the restricted sandbox; the initial restricted Tk run could not access the native graphical services.
- Twenty new worker/client integration tests use synthetic HTTP responses and real temporary files. They cover all checkbox combinations; exact detail/media endpoints and ID encoding; parent folders and child naming metadata; absent/null/empty/malformed arrays; per-type deduplication; invalid metadata and Unicode; partial failures, retries, unchanged parents, shared children in distinct folders, filename collisions, primary failure, nonrecursive behavior, and cancellation cleanup.
- Settings/UI regressions cover default-off and legacy values, strict boolean validation, independent persistence, both save routes, dirty state, and busy-state controls. Existing source-specific search/download and storage regressions remain green.
- All **30** Python/PYW files compile in memory and pass Python 3.10 grammar checks. Ruff `E9,F` and `git diff --check` pass. No dependencies changed.
- A read-only independent review found a malformed-Unicode child isolation issue. Focused regressions reproduced it; a scoped child error handler fixed it. Final review reported no remaining actionable findings.
- Not executed: a live corporate OT connection or native Windows registry/DPAPI/filesystem/UI verification. Detail fixtures follow the specified root `properties` response shape; live server compatibility remains unverified.

# Verification record — 2026-11-05

## Storage tab and document folders

- Full command: `/private/tmp/ot-client-review-venv/bin/python -B -m unittest discover -s tests -v`.
- Result: **265 tests; 264 passed, 1 skipped** (native Windows current-user DPAPI). The final quiet rerun used the same suite after the UI copy/layout refinements.
- Runtime remains macOS, Python 3.11.15, requests 2.34.2 and Tk 9.0.4. Real Tk and loopback HTTP tests ran outside the restricted sandbox; initial restricted attempts could not access native GUI/socket services.
- Storage tests cover legacy defaults and independent registry recovery; inactive unfinished templates; literal folder tags without file extensions; exact/contains matching with exact precedence; multiple-match skips; case folding; immediate-child scope; matching files, broken links, escaping links and post-creation containment; and resolved-folder filename ownership.
- Real Tk/controller tests cover both tabs' drafts through either Save button, download job settings and close; unchanged saved queues; save failure; typed previews; busy/checkbox restoration; validation routing and compact-window scrolling. Folder ambiguity is checked in retry, problem filtering and CSV reports.
- Existing client tests still verify SHA comparison/update, media validation, cancellation and atomic writes. `otClient.py` and its public API are unchanged.
- All **29** Python/PYW files compile in memory and pass Python 3.10 grammar checks. Ruff `E9,F` and `git diff --check` pass. No new dependencies; no dependency audit was needed or rerun.
- Independent backend and final integration reviews found no required fixes.
- Native screenshot inspection was unavailable because the computer-use service failed to start; real Tk interactions and widget geometry were verified instead.
- Not executed: native Windows registry/DPAPI and actual Windows junctions/DPI, Windows CMD scripts, or a live corporate OT connection. Junction detection has simulated reparse-point coverage on macOS. The existing path-based client does not provide a security boundary against hostile concurrent directory replacement.

## Filename format and table alignment update

- Command: `python -B -m unittest discover -s tests -v`, using the existing isolated test environment.
- Result: **212 tests; 211 passed, 1 skipped** (native Windows current-user DPAPI).
- All 21 real Tk interaction tests passed, including typed filename templates, live preview, validation and compact-window scrolling.
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
