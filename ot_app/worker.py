"""Cancellable background downloads, with no dependency on Tk.

The worker snapshots its settings and item list before it starts. All communication
back to the main thread consists of queue events; callbacks never access widgets.
``processed`` counts attempted items that reached a terminal outcome, including an
active item interrupted by cancellation. Unstarted cancelled rows receive a status
event, but do not increase that count.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import queue
import threading
import time
from typing import Callable, Iterable

from otClient import (
    Document,
    DownloadCancelled,
    otConnector,
    otError,
    safe_windows_filename,
)

from .settings import AppSettings


@dataclass(frozen=True)
class JobItem:
    key: str
    number: str
    document: Document | None = None


@dataclass(frozen=True)
class WorkerEvent:
    kind: str
    key: str = ""
    payload: object = None


def _unique_documents(candidates: Iterable[Document]) -> list[Document]:
    """Collapse duplicate search rows that refer to the same document ID."""
    unique: dict[str, Document] = {}
    for candidate in candidates:
        unique.setdefault(str(candidate.id), candidate)
    return list(unique.values())


def select_document(number: str, candidates: Iterable[Document]) -> Document | None:
    """Select a unique exact name match, otherwise a single unique candidate.

    Compare the trimmed requested number to each full server name with casefold.
    Extensions remain significant: ``ABC.pdf`` and ``ABC.docx`` do not become
    equally exact matches for ``ABC``. Duplicate rows for one document ID count
    once; multiple distinct exact matches, or multiple nonexact results, require
    an explicit user selection. An empty result also returns ``None``; the caller
    distinguishes it from an ambiguous result before invoking this function.
    """
    candidates = list(candidates)
    requested = number.strip().casefold()
    exact = _unique_documents(
        candidate for candidate in candidates if candidate.name.casefold() == requested
    )
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    unique = _unique_documents(candidates)
    return unique[0] if len(unique) == 1 else None


class _ThrottledProgress:
    """Emit at most ten intermediate updates per second, plus final progress."""

    def __init__(self, publish: Callable[[int, int | None], None]) -> None:
        self._publish = publish
        self._latest: tuple[int, int | None] | None = None
        self._emitted: tuple[int, int | None] | None = None
        self._last_time = 0.0

    def __call__(self, downloaded: int, total: int | None) -> None:
        self._latest = (downloaded, total)
        now = time.monotonic()
        # Do not infer completion from a declared size: a wrong or changing
        # Content-Length would otherwise let every chunk bypass throttling.
        # The caller explicitly flushes on every terminal outcome.
        if self._emitted is None or now - self._last_time >= 0.1:
            self.flush(now)

    def flush(self, now: float | None = None) -> None:
        if self._latest is not None and self._latest != self._emitted:
            self._publish(*self._latest)
            self._emitted = self._latest
            self._last_time = time.monotonic() if now is None else now

    def finish(self, fallback_bytes: int) -> None:
        # An unchanged result commits zero bytes, but the progress callback may
        # have reported the full comparison download. Never regress that count.
        if self._latest is None:
            self._latest = (fallback_bytes, fallback_bytes)
        self.flush()


class DownloadWorker(threading.Thread):
    """One authenticated session for a batch, with cooperative cancellation.

    Expected request/filesystem errors apply to an individual row and allow the
    batch to continue. Login/configuration failures and unexpected programming
    errors stop the batch with a clear ``fatal`` event. The connector is always
    closed, and ``finished`` is always the last event.
    """

    def __init__(
        self,
        settings: AppSettings,
        items: list[JobItem],
        events: queue.Queue,
        cancel: threading.Event,
        force: bool = False,
        connector_factory=otConnector,
    ) -> None:
        super().__init__(name="ot-download-worker", daemon=True)
        self._settings = replace(settings)
        self._items = tuple(items)
        self._events = events
        self._cancel = cancel
        self._force = force
        self._connector_factory = connector_factory

    def _emit(self, kind: str, key: str = "", **payload: object) -> None:
        self._events.put(WorkerEvent(kind, key, payload))

    def _status(self, item: JobItem, status: str, message: str, **details: object) -> None:
        self._emit("status", item.key, status=status, message=message, **details)

    def _message(self, error: Exception, *, unexpected: bool = False) -> str:
        message = str(error).strip() or type(error).__name__
        if unexpected:
            message = f"Beklenmeyen {type(error).__name__} hatası: {message}"
        # Client errors are already sanitized. Keep an injected connector or an
        # unexpected exception from disclosing the configured password in the UI.
        if isinstance(self._settings.password, str) and self._settings.password:
            message = message.replace(self._settings.password, "[gizlendi]")
        return message

    def _check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise DownloadCancelled("İşlem iptal edildi.")

    def _cancel_pending(self, items: Iterable[JobItem]) -> None:
        for item in items:
            self._status(item, "cancelled", "İşlem başlamadan iptal edildi.")

    def _process_item(self, connector, item: JobItem, filenames: dict[str, str]) -> None:
        selected = item.document
        if selected is None:
            self._status(item, "searching", "Belge aranıyor…")
            candidates = list(connector.search_documents(item.number))
            self._check_cancelled()
            if not candidates:
                self._status(item, "not_found", "Bu numara için belge bulunamadı.")
                return
            selected = select_document(item.number, candidates)
            if selected is None:
                unique = tuple(_unique_documents(candidates))
                self._status(
                    item,
                    "ambiguous",
                    f"{len(unique)} aday bulundu. İndirilecek belgeyi seçin.",
                    candidates=unique,
                )
                return

        self._check_cancelled()
        target_name = safe_windows_filename(selected.name, selected.id)
        normalized = target_name.casefold()
        document_id = str(selected.id)
        owner = filenames.get(normalized)
        if owner is not None and owner != document_id:
            raise otError(
                f"Farklı belgeler aynı dosya adını kullanıyor: {target_name}. "
                "Önceki dosya korundu. Bu belgeyi ayrı bir hedef klasöre indirin."
            )
        # Reserve before downloading: even a failed attempt must not let another
        # document overwrite a same-named file already present in this batch.
        filenames[normalized] = document_id
        self._status(item, "downloading", "Belge indiriliyor…", document=selected)
        progress = _ThrottledProgress(
            lambda downloaded, total: self._emit(
                "progress", item.key, downloaded=downloaded, total=total
            )
        )
        try:
            result = connector.download_document(
                selected.id,
                self._settings.output_dir,
                file_name=selected.name,
                overwrite=self._force,
                cancel_event=self._cancel,
                progress=progress,
            )
        finally:
            # Retain the last received byte count on both failure and cancellation.
            progress.flush()
        messages = {
            "downloaded": "Belge indirildi.",
            "updated": "Yerel belge güncellendi.",
            "unchanged": "Yerel belge zaten güncel.",
        }
        if result.status not in messages:
            raise ValueError(f"Geçersiz indirme sonucu: {result.status!r}")
        progress.finish(result.bytes_written)
        self._status(
            item,
            result.status,
            messages[result.status],
            document=selected,
            path=str(result.path),
        )

    def run(self) -> None:
        connector = None
        processed = 0
        total = len(self._items)
        cancelled = False
        fatal_reported = False
        filenames: dict[str, str] = {}
        self._emit("advance", done=0, total=total)
        try:
            if not total:
                return
            self._check_cancelled()
            try:
                self._settings.validate(require_connection=True)
            except ValueError as error:
                raise otError(f"Bağlantı ayarlarını kontrol edin: {error}") from error
            self._check_cancelled()
            self._emit("session", state="connecting")
            verify = (self._settings.ca_bundle or True) if self._settings.verify_tls else False
            connector = self._connector_factory(
                self._settings.base_url,
                username=self._settings.username,
                password=self._settings.password,
                timeout=self._settings.timeout,
                verify=verify,
                folder_id=self._settings.folder_id,
            )
            self._check_cancelled()
            if connector.login() is not True:
                raise otError("Oturum doğrulanamadı. Bağlantı ayarlarını kontrol edin.")
            self._check_cancelled()
            self._emit("session", state="connected")
            for item in self._items:
                self._check_cancelled()
                try:
                    self._process_item(connector, item, filenames)
                except DownloadCancelled:
                    self._status(item, "cancelled", "İşlem iptal edildi.")
                    processed += 1
                    self._emit("advance", done=processed, total=total)
                    raise
                except (otError, OSError) as error:
                    self._status(item, "error", self._message(error))
                except Exception as error:
                    self._status(item, "error", self._message(error, unexpected=True))
                    processed += 1
                    self._emit("advance", done=processed, total=total)
                    raise
                processed += 1
                self._emit("advance", done=processed, total=total)
        except DownloadCancelled:
            cancelled = True
            self._cancel_pending(self._items[processed:])
        except Exception as error:
            fatal_reported = True
            self._emit(
                "fatal",
                message=self._message(
                    error, unexpected=not isinstance(error, (otError, OSError))
                ),
            )
        finally:
            try:
                if connector is not None:
                    connector.close()
            except Exception as error:
                if not fatal_reported:
                    self._emit(
                        "fatal",
                        message="Bağlantı kapatılırken hata oluştu: "
                        + self._message(error, unexpected=True),
                    )
            finally:
                self._emit(
                    "finished",
                    cancelled=cancelled or self._cancel.is_set(),
                    processed=processed,
                    total=total,
                )
