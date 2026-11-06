"""Resolve document subfolders without ambiguous or escaping destinations."""

from __future__ import annotations

from pathlib import Path
import stat

from otClient import Document, OTError, safe_windows_filename

from .filename_format import format_document_folder


class FolderAmbiguityError(OTError):
    """Several immediate child folders match; the row can be retried later."""


def _resolve(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except RuntimeError:
        raise OTError("Alt klasör yolu çözülemedi. Klasör bağlantılarını kontrol edin.") from None


def _checked_directory(path: Path, root: Path) -> Path:
    resolved = _resolve(path)
    if not resolved.is_relative_to(root):
        raise OTError("Alt klasör bağlantısı indirme klasörünün dışına çıkıyor. Farklı bir klasör seçin.")
    if not resolved.is_dir():
        raise OTError("Alt klasör hedefinde aynı adlı bir dosya veya özel öğe var. Farklı bir ad seçin.")
    return resolved


def _directory_candidate(path: Path) -> bool:
    if path.is_dir() or path.is_symlink():
        return True
    # Include broken Windows junctions/reparse points too. Filtering them out
    # would silently turn an unsafe match into permission to create a new folder.
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def resolve_document_folder(
    output_dir: str | Path,
    document: Document,
    folder_format: str,
    match: str = "exact",
) -> Path:
    """Reuse one matching child directory or create a sanitized folder.

    Exact case-insensitive names always take precedence. ``contains`` also
    accepts directory names containing the generated name. Multiple matches
    raise ``FolderAmbiguityError`` before creating any child. Matching links
    must resolve inside the explicitly configured (and resolved) output root.
    The root itself follows the download client's existing expand/create/resolve
    behavior, so an explicitly selected root link remains supported.
    """
    if match not in ("exact", "contains"):
        raise ValueError("Alt klasör eşleştirme yöntemi exact veya contains olmalıdır.")
    name = safe_windows_filename(format_document_folder(folder_format, document))
    root = Path(output_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    root = _resolve(root)
    entries = list(root.iterdir())
    normalized = name.casefold()
    matches = [entry for entry in entries if entry.name.casefold() == normalized]
    if not matches and match == "contains":
        matches = [
            entry for entry in entries
            if normalized in entry.name.casefold() and _directory_candidate(entry)
        ]
    if len(matches) > 1:
        raise FolderAmbiguityError(
            "Birden fazla eşleşen alt klasör bulundu; bu satır atlandı. "
            "Klasör adlarını veya eşleştirme ayarını düzenleyip yeniden deneyin."
        )
    if matches:
        return _checked_directory(matches[0], root)
    target = root / name
    target.mkdir(exist_ok=True)
    # Recheck after mkdir: an entry may have appeared since the directory scan.
    return _checked_directory(target, root)
