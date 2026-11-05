"""Strict, bounded document-list import and lossless text/JSON export.

CSV export escapes spreadsheet formulas in the exported copy. Prefer TXT or
JSON when the file will later be imported and every identifier must roundtrip.
"""

from __future__ import annotations

import codecs
import csv
import io
import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

MAX_DOCUMENTS = 10_000
MAX_IDENTIFIER_LENGTH = 1_024
MAX_INPUT_CHARACTERS = 5 * 1024 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024


class DocumentInputError(ValueError):
    """An input cannot be safely interpreted as a document-number list."""


def _canonical_number(value: str) -> str:
    if not isinstance(value, str):
        raise DocumentInputError("Belge numaralarının tamamı metin olmalıdır.")
    number = value.strip()
    if "\x00" in number:
        raise DocumentInputError("Belge numarası NUL karakteri içeremez.")
    if len(number) > MAX_IDENTIFIER_LENGTH:
        raise DocumentInputError(
            f"Bir belge numarası en fazla {MAX_IDENTIFIER_LENGTH} karakter olabilir."
        )
    try:
        number.encode("utf-8")
    except UnicodeEncodeError:
        raise DocumentInputError("Belge numarası geçerli Unicode metni olmalıdır.") from None
    return number


def merge_document_numbers(existing: Iterable[str], incoming: Iterable[str]) -> list[str]:
    """Trim and deduplicate exact identifiers, preserving first occurrence order."""
    result: list[str] = []
    seen: set[str] = set()
    character_count = 0
    for source in (existing, incoming):
        if isinstance(source, (str, bytes)):
            raise DocumentInputError("Belge numaraları bir metin listesi olmalıdır.")
        try:
            iterator = iter(source)
        except TypeError:
            raise DocumentInputError("Belge numaraları bir metin listesi olmalıdır.") from None
        for value in iterator:
            number = _canonical_number(value)
            if not number or number in seen:
                continue
            if len(result) >= MAX_DOCUMENTS:
                raise DocumentInputError(f"Bir listede en fazla {MAX_DOCUMENTS:,} belge olabilir.")
            character_count += len(number)
            if character_count > MAX_INPUT_CHARACTERS:
                raise DocumentInputError(f"Belge listesi toplam {MAX_INPUT_CHARACTERS:,} karakter sınırını aşıyor.")
            seen.add(number)
            result.append(number)
    return result


def _delimited_cells(text: str) -> Iterable[str]:
    """Parse mixed clipboard separators without splitting quoted multiline cells."""
    field: list[str] = []
    quoted = False
    closed_quote = False
    at_field_start = True
    index = 0
    while index < len(text):
        character = text[index]
        if quoted:
            if character == '"':
                if index + 1 < len(text) and text[index + 1] == '"':
                    field.append('"')
                    index += 2
                    continue
                quoted = False
                closed_quote = True
            else:
                field.append(character)
        elif character in ",;\t\r\n":
            yield "".join(field)
            field = []
            closed_quote = False
            at_field_start = True
            if character == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                index += 1
        elif closed_quote:
            if not character.isspace():
                raise DocumentInputError("Kapanan tırnaktan sonra yalnızca ayırıcı veya boşluk olabilir.")
        elif character == '"' and at_field_start:
            field = []
            quoted = True
            at_field_start = False
        else:
            field.append(character)
            if not character.isspace():
                at_field_start = False
        index += 1
    if quoted:
        raise DocumentInputError("Tırnak içindeki bir belge numarasının kapanış tırnağı eksik.")
    yield "".join(field)


def _parse_json_array(content: str) -> list[str]:
    try:
        values = json.loads(content)
    except (ValueError, RecursionError):
        raise DocumentInputError("JSON geçersiz. Yalnızca metinlerden oluşan bir JSON dizisi kullanın.") from None
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise DocumentInputError("JSON yalnızca metinlerden oluşan bir dizi olmalıdır.")
    return merge_document_numbers([], values)


def parse_document_text(text: str) -> list[str]:
    """Accept plain lines, mixed Excel/CSV separators, or a JSON string array."""
    if not isinstance(text, str):
        raise DocumentInputError("İçe aktarılacak içerik metin olmalıdır.")
    if len(text) > MAX_INPUT_CHARACTERS:
        raise DocumentInputError(f"İçe aktarılacak metin {MAX_INPUT_CHARACTERS:,} karakter sınırını aşıyor.")
    content = text.removeprefix("\ufeff").strip()
    if not content:
        return []
    if content.startswith(("[", "{")):
        return _parse_json_array(content)
    return merge_document_numbers([], _delimited_cells(content))


def _decode_file(data: bytes) -> str:
    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        raise DocumentInputError("UTF-32 desteklenmiyor; dosyayı UTF-8 veya UTF-16 olarak kaydedin.")
    try:
        if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return data.decode("utf-16")
        if b"\x00" in data and len(data) >= 4 and len(data) % 2 == 0:
            # A common Excel export has UTF-16 without a BOM. Only infer its
            # byte order when alternating NUL bytes provide strong evidence.
            pairs = len(data) // 2
            even_nuls = data[0::2].count(0) / pairs
            odd_nuls = data[1::2].count(0) / pairs
            if odd_nuls >= 0.4 and even_nuls <= 0.05:
                return data.decode("utf-16-le")
            if even_nuls >= 0.4 and odd_nuls <= 0.05:
                return data.decode("utf-16-be")
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentInputError("Dosya okunamadı. UTF-8 veya BOM işaretli UTF-16 kodlaması kullanın.") from None


def read_document_file(path: str | os.PathLike[str]) -> list[str]:
    """Read a bounded UTF-8/UTF-16 list; decoding errors never replace characters."""
    file_path = Path(path)
    if file_path.stat().st_size > MAX_FILE_BYTES:
        raise DocumentInputError("İçe aktarılacak dosya boyutu sınırını aşıyor (10 MiB).")
    with file_path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise DocumentInputError("İçe aktarılacak dosya boyutu sınırını aşıyor (10 MiB).")
    text = _decode_file(data)
    if len(text) > MAX_INPUT_CHARACTERS:
        raise DocumentInputError(f"İçe aktarılacak metin {MAX_INPUT_CHARACTERS:,} karakter sınırını aşıyor.")
    if file_path.suffix.lower() == ".json":
        content = text.removeprefix("\ufeff").strip()
        return _parse_json_array(content) if content else []
    return parse_document_text(text)


def _text_cell(number: str) -> str:
    # Quote every supported separator and a JSON-looking first character. This
    # keeps ordinary TXT files readable while preserving uncommon identifiers.
    if any(character in number for character in ',;\t\r\n"') or number.startswith(("[", "{", "\ufeff")):
        return '"' + number.replace('"', '""') + '"'
    return number


def write_document_file(path: str | os.PathLike[str], numbers: Iterable[str]) -> None:
    """Atomically export TXT, JSON, or a spreadsheet-safe CSV copy.

    CSV prefixes cells beginning with =, +, -, or @ with an apostrophe. The
    canonical input list is unchanged; that explicit prefix is retained if the
    CSV is reimported. TXT and JSON are the lossless interchange formats.
    """
    canonical = merge_document_numbers([], numbers)
    file_path = Path(path)
    extension = file_path.suffix.lower()
    if extension == ".json":
        text = json.dumps(canonical, ensure_ascii=False, indent=2) + "\n"
        encoding = "utf-8"
    else:
        exported = canonical
        encoding = "utf-8"
        if extension == ".csv":
            exported = ["'" + number if number.startswith(("=", "+", "-", "@")) else number for number in canonical]
            encoding = "utf-8-sig"
        text = "".join(_text_cell(number) + "\n" for number in exported)
    # Build and encode everything before touching the destination. A failed
    # replace (including an Excel lock on Windows) leaves the old file intact.
    if len(text) > MAX_INPUT_CHARACTERS:
        raise DocumentInputError(f"Dışa aktarılacak dosya {MAX_INPUT_CHARACTERS:,} karakter sınırını aşıyor.")
    data = text.encode(encoding)
    if len(data) > MAX_FILE_BYTES:
        raise DocumentInputError("Dışa aktarılacak dosya boyutu sınırını aşıyor (10 MiB).")
    _atomic_write(file_path, data)


def write_csv_report(path: str | os.PathLike[str], rows: Iterable[Iterable[object]]) -> None:
    """Atomically write a BOM-prefixed report with spreadsheet-safe cells."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    for row in rows:
        cells = []
        for value in row:
            text = "" if value is None else str(value)
            if text.lstrip().startswith(("=", "+", "-", "@")):
                text = "'" + text
            cells.append(text)
        writer.writerow(cells)
    _atomic_write(Path(path), output.getvalue().encode("utf-8-sig"))


def _atomic_write(file_path: Path, data: bytes) -> None:
    """Keep the destination intact until a complete export is flushed to disk."""
    temporary_path: str | None = None
    try:
        descriptor, temporary_path = tempfile.mkstemp(prefix=f".{file_path.name}.", suffix=".tmp", dir=file_path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, file_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
