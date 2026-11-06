"""Cancellable background downloads, with no dependency on Tk.

The worker snapshots its settings and item list before it starts. All communication
back to the main thread consists of queue events; callbacks never access widgets.
``processed`` counts attempted items that reached a terminal outcome, including an
active item interrupted by cancellation. Unstarted cancelled rows receive a status
event, but do not increase that count.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import queue
import threading
import time
from typing import Callable, Iterable

from otClient import (
    Document,
    DownloadCancelled,
    OTConnector,
    OTError,
    safe_windows_filename,
)

from .filename_format import DEFAULT_FILENAME_FORMAT, format_document_filename
from .hierarchy import HierarchyEntry, validate_hierarchy
from .settings import AppSettings
from .storage import FolderAmbiguityError, resolve_document_folder


def safe_error_message(error: Exception, password: str = "") -> str:
    """Expose only sanitized client errors; arbitrary exceptions may hold secrets."""
    if isinstance(error, OTError):
        message = str(error).strip() or "OT işlemi tamamlanamadı."
        return message.replace(password, "[gizlendi]") if password else message
    if isinstance(error, OSError):
        return "Dosya veya bağlantı işlemi tamamlanamadı. Erişim izinlerini ve bağlantıyı kontrol edin."
    return f"Beklenmeyen {type(error).__name__} hatası. İşlem tamamlanamadı."


@dataclass(frozen=True)
class JobItem:
    key: str
    number: str
    document: Document | None = None
    parent_key: str | None = None


@dataclass(frozen=True)
class WorkerEvent:
    kind: str
    key: str = ""
    payload: object = None


@dataclass(frozen=True)
class _HierarchyResolution:
    """Metadata/folder outcome, independent of any attempted media download."""

    document: Document | None = None
    folder: Path | None = None
    failure_key: str | None = None
    status: str = ""
    message: str = ""
    candidates: tuple[Document, ...] = ()


def _unique_documents(candidates: Iterable[Document]) -> list[Document]:
    """Collapse duplicate search rows that refer to the same source and document ID."""
    unique: dict[tuple[str, str], Document] = {}
    for candidate in candidates:
        unique.setdefault((candidate.content_type, str(candidate.id)), candidate)
    return list(unique.values())


def select_document(number: str, candidates: Iterable[Document]) -> Document | None:
    """Select a unique exact name match, otherwise a single unique candidate.

    Compare the trimmed requested number to each full server name with casefold.
    Extensions remain significant: ``ABC.pdf`` and ``ABC.docx`` do not become
    equally exact matches for ``ABC``. Duplicate rows for one source and document ID count
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
        connector_factory=OTConnector,
        *,
        hierarchy: tuple[JobItem, ...] | None = None,
    ) -> None:
        super().__init__(name="ot-download-worker", daemon=True)
        self._settings = replace(settings)
        self._items = tuple(items)
        self._events = events
        self._cancel = cancel
        self._force = force
        self._connector_factory = connector_factory
        self._explicit_hierarchy = hierarchy is not None
        self._hierarchy = tuple(hierarchy) if hierarchy is not None else self._items
        self._hierarchy_items: dict[str, JobItem] = {}
        self._hierarchy_cache: dict[str, _HierarchyResolution] = {}
        self._selected_keys = {item.key for item in self._items}

    def _emit(self, kind: str, key: str = "", **payload: object) -> None:
        self._events.put(WorkerEvent(kind, key, payload))

    def _status(self, item: JobItem, status: str, message: str, **details: object) -> None:
        self._emit("status", item.key, status=status, message=message, **details)

    def _message(self, error: Exception) -> str:
        return safe_error_message(error, self._settings.password)

    def _check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise DownloadCancelled("İşlem iptal edildi.")

    def _cancel_pending(self, items: Iterable[JobItem]) -> None:
        for item in items:
            self._status(item, "cancelled", "İşlem başlamadan iptal edildi.")

    def _validate_hierarchy(self) -> None:
        """Reject broken snapshots before settings path checks or connection I/O."""
        if not self._explicit_hierarchy and any(item.parent_key is not None for item in self._items):
            raise OTError("Alt satır indirmek için tam klasör hiyerarşisi gereklidir.")
        try:
            validate_hierarchy(tuple(HierarchyEntry(item.key, item.parent_key)
                                     for item in self._hierarchy))
        except ValueError as error:
            raise OTError(f"Klasör hiyerarşisi geçersiz: {error}") from None
        self._hierarchy_items = {item.key: item for item in self._hierarchy}
        positions = {item.key: index for index, item in enumerate(self._hierarchy)}
        previous = -1
        for item in self._items:
            if self._hierarchy_items.get(item.key) != item or positions[item.key] <= previous:
                raise OTError("İndirme satırları tam klasör hiyerarşisi ve sırası ile eşleşmiyor.")
            previous = positions[item.key]

    def _resolve_hierarchy_node(self, connector, node: JobItem, parent: Path) -> _HierarchyResolution:
        """Resolve one node once, retaining expected failures for this batch."""
        selected = node.document
        candidates: tuple[Document, ...] = ()
        try:
            self._check_cancelled()
            if selected is None:
                if node.key in self._selected_keys:
                    self._status(node, "searching", "Belge aranıyor…")
                found = list(connector.search_documents(node.number))
                self._check_cancelled()
                if not found:
                    return _HierarchyResolution(failure_key=node.key, status="not_found",
                                                message="Bu numara için belge bulunamadı.")
                selected = select_document(node.number, found)
                if selected is None:
                    candidates = tuple(_unique_documents(found))
                    return _HierarchyResolution(failure_key=node.key, status="ambiguous",
                                                message=f"{len(candidates)} aday bulundu. İndirilecek belgeyi seçin.",
                                                candidates=candidates)
            folder = resolve_document_folder(
                parent, selected, self._settings.document_subfolder_format,
                self._settings.document_subfolder_match, strict_descendant=True,
            )
            self._check_cancelled()
            return _HierarchyResolution(document=selected, folder=folder)
        except DownloadCancelled:
            raise
        except (OTError, OSError) as error:
            return _HierarchyResolution(
                document=selected, failure_key=node.key,
                status="folder_ambiguous" if isinstance(error, FolderAmbiguityError) else "error",
                message=self._message(error), candidates=candidates,
            )

    def _resolve_hierarchy(self, connector, item: JobItem) -> _HierarchyResolution:
        """Walk only required ancestors iteratively; never fetch their media."""
        pending: list[JobItem] = []
        node = item
        while node.key not in self._hierarchy_cache:
            self._check_cancelled()
            pending.append(node)
            if node.parent_key is None:
                break
            node = self._hierarchy_items[node.parent_key]
        for node in reversed(pending):
            self._check_cancelled()
            parent_result = self._hierarchy_cache.get(node.parent_key)
            if parent_result is not None and parent_result.failure_key is not None:
                self._hierarchy_cache[node.key] = parent_result
                continue
            parent = parent_result.folder if parent_result else Path(self._settings.output_dir)
            result = self._resolve_hierarchy_node(connector, node, parent)
            self._hierarchy_cache[node.key] = result
            if node.key not in self._selected_keys:
                details: dict[str, object] = {
                    "candidates": result.candidates,
                    "message": result.message or "Klasör hiyerarşisi çözümlendi.",
                }
                if result.document is not None:
                    details["document"] = result.document
                self._emit("hierarchy_resolution", node.key, **details)
        return self._hierarchy_cache[item.key]

    def _hierarchy_failure(self, item: JobItem, result: _HierarchyResolution) -> None:
        status, message = result.status, result.message
        details: dict[str, object] = {}
        if result.failure_key != item.key:
            ancestor = self._hierarchy_items[result.failure_key]
            status = "folder_ambiguous" if status == "folder_ambiguous" else "error"
            message = f"Üst satır {ancestor.number}: {message}"
        else:
            if result.document is not None:
                details.update(document=result.document, path="")
            if result.candidates:
                details["candidates"] = result.candidates
        self._status(item, status, message, **details)

    def _process_item(self, connector, item: JobItem, filenames: dict[tuple[str, str], tuple[str, str]]) -> None:
        if self._settings.manual_folder_hierarchy_enabled:
            result = self._resolve_hierarchy(connector, item)
            if result.failure_key is not None:
                self._hierarchy_failure(item, result)
                return
            self._download_item(connector, item, result.document, result.folder, filenames)
            return
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
        output_dir: str | Path = self._settings.output_dir
        if self._settings.document_subfolder_enabled:
            try:
                output_dir = resolve_document_folder(
                    output_dir,
                    selected,
                    self._settings.document_subfolder_format,
                    self._settings.document_subfolder_match,
                )
            except FolderAmbiguityError as error:
                self._status(
                    item, "folder_ambiguous", self._message(error),
                    document=selected, path="",
                )
                return
        self._check_cancelled()
        self._download_item(connector, item, selected, output_dir, filenames)

    def _download_item(self, connector, item: JobItem, selected: Document,
                       output_dir: str | Path, filenames) -> None:
        self._check_cancelled()
        file_name, source_name = self._reserve_filename(selected, output_dir, filenames)
        self._status(item, "downloading", "Belge indiriliyor…", document=selected)
        progress = _ThrottledProgress(
            lambda downloaded, total: self._emit(
                "progress", item.key, downloaded=downloaded, total=total
            )
        )
        try:
            result = connector.download_document(
                selected.id,
                output_dir,
                file_name=file_name,
                source_name=source_name,
                content_type=selected.content_type,
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
        message = messages[result.status]
        status = result.status
        if selected.content_type == "tds_document" and (
            self._settings.download_related_forms or self._settings.download_related_attachments
        ):
            # Publish the committed primary path before any child request can fail
            # or be cancelled. Child metadata/progress must not replace this row.
            self._status(item, "downloading", "İlgili belgeler kontrol ediliyor…",
                         document=selected, path=str(result.path))
            summary, failed = self._download_related(connector, item, selected, result.path.parent, filenames)
            message += " " + summary
            if failed:
                status = "error"
        self._status(item, status, message, document=selected, path=str(result.path))

    def _reserve_filename(self, selected, output_dir, filenames) -> tuple[str, str | None]:
        file_name = format_document_filename(self._settings.filename_format, selected)
        source_name = selected.name if self._settings.filename_format.strip() != DEFAULT_FILENAME_FORMAT else None
        target_name = safe_windows_filename(file_name, selected.id)
        normalized = (str(Path(output_dir).expanduser().resolve()).casefold(), target_name.casefold())
        document_key = (selected.content_type, str(selected.id))
        owner = filenames.get(normalized)
        if owner is not None and owner != document_key:
            raise OTError(
                f"Farklı belgeler aynı dosya adını kullanıyor: {target_name}. "
                "Önceki dosya korundu. Bu belgeyi ayrı bir hedef klasöre indirin."
            )
        # Reserve before downloading: even a failed attempt must not let another
        # document overwrite a same-named file already present in this batch.
        filenames[normalized] = document_key
        return file_name, source_name

    def _download_related(self, connector, item, selected, output_dir, filenames) -> tuple[str, bool]:
        self._check_cancelled()
        try:
            details = connector.get_document_by_id(selected.id, content_type="tds_document")
            self._check_cancelled()
            properties = details.get("properties")
            if not isinstance(properties, dict):
                raise OTError("Belge bilgisi: properties alanı eksik veya bozuk.")
        except DownloadCancelled:
            raise
        except (OTError, OSError) as error:
            return "İlgili belgeler alınamadı: " + self._message(error), True

        counts = {"forms": 0, "attachments": 0}
        errors: list[str] = []
        for field, content_type, label, enabled in (
            ("forms", "tds_form", "Form", self._settings.download_related_forms),
            ("attachments", "tds_attachment", "Ek", self._settings.download_related_attachments),
        ):
            if not enabled:
                continue
            counts[field], failures = self._download_related_category(
                connector, item, properties.get(field), content_type, label, output_dir, filenames
            )
            errors.extend(failures)
        summary = f"İlgili dosyalar: {counts['forms']} form, {counts['attachments']} ek tamamlandı."
        if errors:
            # Keep table/report messages bounded even for a large malformed list.
            summary += f" {len(errors)} hata: " + " | ".join(errors[:5])
            if len(errors) > 5:
                summary += " | Diğer hatalar için yeniden deneyin."
        return summary, bool(errors)

    def _download_related_category(self, connector, item, identifiers, content_type, label,
                                   output_dir, filenames) -> tuple[int, list[str]]:
        if identifiers is None:
            return 0, []
        if not isinstance(identifiers, list):
            return 0, [f"{label} kimlikleri metin dizisi olmalıdır."]
        completed = 0
        errors: list[str] = []
        seen: set[str] = set()
        for index, identifier in enumerate(identifiers, 1):
            self._check_cancelled()
            if not isinstance(identifier, str) or not identifier.strip():
                errors.append(f"{label}: {index}. kimlik geçersiz.")
                continue
            identifier = identifier.strip()
            if identifier in seen:
                continue
            seen.add(identifier)
            try:
                self._status(item, "downloading", f"{label} indiriliyor ({index}/{len(identifiers)})…")
                self._download_related_file(connector, identifier, content_type, output_dir, filenames)
                completed += 1
            except DownloadCancelled:
                raise
            except UnicodeError:
                # JSON may contain lone surrogates. Do not echo these into Tk
                # or let one malformed child abort the remaining downloads.
                errors.append(f"{label}: {index}. kaydın kimliği veya belge bilgisi geçerli Unicode değil.")
            except (OTError, OSError) as error:
                # Sanitize the identifier as well as the transport error.
                errors.append(self._message(OTError(f"{label} {identifier}: {self._message(error)}")))
        return completed, errors

    def _download_related_file(self, connector, identifier, content_type, output_dir, filenames) -> None:
        self._check_cancelled()
        details = connector.get_document_by_id(identifier, content_type=content_type)
        self._check_cancelled()
        related = Document.from_properties(details.get("properties"), content_type=content_type)
        if related.id != identifier:
            raise OTError("İlgili belge bilgisi istenen kimlikle eşleşmiyor.")
        file_name, source_name = self._reserve_filename(related, output_dir, filenames)
        self._check_cancelled()
        connector.download_document(
            related.id, output_dir, file_name=file_name, source_name=source_name,
            content_type=content_type, overwrite=self._force, cancel_event=self._cancel,
        )

    def run(self) -> None:
        connector = None
        processed = 0
        total = len(self._items)
        cancelled = False
        fatal_reported = False
        filenames: dict[tuple[str, str], tuple[str, str]] = {}
        self._emit("advance", done=0, total=total)
        try:
            if not total:
                return
            self._check_cancelled()
            if self._settings.manual_folder_hierarchy_enabled:
                self._validate_hierarchy()
            try:
                self._settings.validate(require_connection=True)
            except ValueError as error:
                raise OTError(f"Bağlantı ayarlarını kontrol edin: {error}") from error
            self._check_cancelled()
            self._emit("session", state="connecting")
            connector = self._connector_factory(
                self._settings.base_url,
                username=self._settings.username,
                password=self._settings.password,
                timeout=self._settings.timeout,
                verify=self._settings.tls_verify,
                folder_id=self._settings.folder_id,
            )
            self._check_cancelled()
            if connector.login() is not True:
                raise OTError("Oturum doğrulanamadı. Bağlantı ayarlarını kontrol edin.")
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
                except (OTError, OSError) as error:
                    self._status(item, "error", self._message(error))
                except Exception as error:
                    self._status(item, "error", self._message(error))
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
                message=self._message(error),
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
                        + self._message(error),
                    )
            finally:
                self._emit(
                    "finished",
                    cancelled=cancelled or self._cancel.is_set(),
                    processed=processed,
                    total=total,
                )
