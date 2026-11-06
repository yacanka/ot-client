"""Validate and expand literal document filename and folder templates."""

from __future__ import annotations

import re

from otClient import Document, document_file_extension

DEFAULT_FILENAME_FORMAT = "{numara}"
_TAG = re.compile(r"\{(numara|ad|revizyon)\}")
_INVALID_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


def _validate_format(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} formatını girin.")
    if len(value) > 256:
        raise ValueError(f"{label} formatı en fazla 256 karakter olabilir.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{label} formatı geçerli Unicode metni olmalıdır.") from None
    if _INVALID_CHARACTERS.search(value):
        raise ValueError(f'{label} formatı yol ayırıcı, kontrol karakteri veya <>:"/\\|?* içeremez.')
    remainder = _TAG.sub("", value)
    if "{" in remainder or "}" in remainder or not _TAG.search(value):
        raise ValueError(f"{label} formatında {{numara}}, {{ad}} veya {{revizyon}} etiketlerini kullanın.")


def validate_filename_format(value: str) -> None:
    """Reject paths, unknown tags and formatting expressions before saving."""
    _validate_format(value, "Dosya adı")


def validate_folder_format(value: str) -> None:
    """Accept one folder component using the same literal metadata tags."""
    _validate_format(value, "Alt klasör adı")


def _expand_metadata(value: str, document: Document, extension: str) -> str:
    number = document.name[:-len(extension)] if extension else document.name
    values = {
        "numara": number,
        "ad": document.title.strip() or number,
        "revizyon": str(document.revision),
    }
    return _TAG.sub(lambda match: values[match.group(1)], value).strip()


def format_document_filename(value: str, document: Document) -> str:
    """Expand metadata once, keeping a known source extension at the end.

    ``numara`` is the server's name; ``ad`` is its descriptive title (falling
    back to the number when absent). Missing extensions are resolved by the
    download client from response headers. The client also sanitizes metadata
    for Windows and checks destination ownership before any file is committed.
    """
    validate_filename_format(value)
    if value.strip() == DEFAULT_FILENAME_FORMAT:
        return document.name
    extension = document_file_extension(document.name)
    name = _expand_metadata(value, document, extension)
    if extension and not name.casefold().endswith(extension.casefold()):
        name += extension
    return name


def format_document_folder(value: str, document: Document) -> str:
    """Expand metadata once without appending the source file extension.

    The storage resolver sanitizes the expanded component for Windows without a
    document ID, so documents producing the same folder name can share it.
    """
    validate_folder_format(value)
    return _expand_metadata(value, document, document_file_extension(document.name))
