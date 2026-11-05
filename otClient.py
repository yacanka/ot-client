"""OT HTTP client used by the desktop application.

Importing this module does not read credentials or make network requests. A
connector owns one requests session and is intended for use by one worker at a
time. Public operations raise OTError with user-facing, nonsecret messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import Message
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path, PureWindowsPath
import re
import tempfile
import threading
import time
from typing import Any, Callable, Literal
import unicodedata
from urllib.parse import unquote, urljoin, urlsplit, quote

import requests


_CHUNK_SIZE = 64 * 1024
_HTML_PROBE_LIMIT = 128 * 1024
_AUTH_PROBE = "OT-DESKTOP-CONNECTION-CHECK"
_MAX_FILENAME_UNITS = 180
_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RESERVED_WINDOWS_NAME = re.compile(
    r"^(?:CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])$",
    re.IGNORECASE,
)
_MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.template": ".dotx",
    "application/vnd.ms-word.document.macroenabled.12": ".docm",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel.sheet.macroenabled.12": ".xlsm",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/rtf": ".rtf",
    "application/json": ".json",
    "application/xml": ".xml",
    "application/zip": ".zip",
    "application/octet-stream": ".bin",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/html": ".html",
    "text/xml": ".xml",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tif",
}
_KNOWN_FILE_EXTENSIONS = frozenset(_MIME_EXTENSIONS.values()) | {
    ".7z", ".avi", ".bat", ".bin", ".bmp", ".bz2", ".cfg", ".cmd", ".dat",
    ".dll", ".dot", ".dotm", ".dwg", ".dxf", ".eml", ".exe", ".gif", ".gz",
    ".htm", ".ico", ".ini", ".jpeg", ".log", ".mkv", ".mov", ".mp3", ".mp4",
    ".mpp", ".msi", ".msg", ".odg", ".odp", ".ods", ".odt", ".pptm", ".ps1",
    ".py", ".rar", ".sh", ".sql", ".svg", ".tar", ".tiff", ".toml", ".tsv",
    ".vsd", ".vsdx", ".wav", ".webp", ".wmv", ".xlsb", ".xlt", ".xltx",
    ".xz", ".yaml", ".yml",
}


class OTError(Exception):
    """An actionable OT, transport, response-format or local-file error."""


class DownloadCancelled(OTError):
    """The caller cancelled before a complete download was committed."""


@dataclass(frozen=True)
class Document:
    id: str
    name: str
    title: str
    author: str
    revision: int

    def __str__(self) -> str:
        title = self.title[:50] + "..." if len(self.title) > 50 else self.title
        return f"[{self.name}] {title}"


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    status: Literal["downloaded", "updated", "unchanged"]
    # Bytes committed to the destination. An unchanged file has zero writes,
    # even though its remote content was received for the SHA256 comparison.
    bytes_written: int


def _check_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelled("İndirme iptal edildi; mevcut dosya korundu.")


def get_local_file_sha256(
    file_path: str | os.PathLike[str], *, cancel_event: threading.Event | None = None
) -> str | None:
    """Return a file's SHA256 using bounded memory, or None if it is absent."""
    _check_cancelled(cancel_event)
    try:
        stream = open(file_path, "rb")
    except FileNotFoundError:
        return None
    with stream:
        digest = hashlib.sha256()
        while True:
            _check_cancelled(cancel_event)
            chunk = stream.read(_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def get_key_value(data: Any, target_key: str) -> Any:
    """Compatibility helper: find matching dictionary keys recursively."""
    results: list[Any] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                if key == target_key:
                    results.append(nested)
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(data)
    if not results:
        return None
    return results[0] if len(results) == 1 else results


def _utf16_units(value: str) -> int:
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def _truncate_units(value: str, maximum: int) -> str:
    result: list[str] = []
    used = 0
    for character in value:
        width = _utf16_units(character)
        if used + width > maximum:
            break
        result.append(character)
        used += width
    return "".join(result)


def _add_filename_tag(name: str, tag: str) -> str:
    extension = PureWindowsPath(name).suffix
    # An exceptionally long dotted suffix cannot be kept inside Windows' name
    # limit. Treat it as part of the base; ordinary file extensions are retained.
    if _utf16_units(extension) > 40:
        extension = ""
    stem = name[:-len(extension)] if extension else name
    suffix = f"__{tag}"
    available = _MAX_FILENAME_UNITS - _utf16_units(extension + suffix)
    stem = _truncate_units(stem, available).rstrip(" .") or "belge"
    return f"{stem}{suffix}{extension}"


def safe_windows_filename(name: str, document_id: str = "") -> str:
    """Clean a single filename, retaining normal names and their extensions.

    Changes that can collapse different names (including truncation) receive a
    stable digest of the original name and document ID. This helper performs no
    I/O; download_document also checks destination ownership and case collisions.
    """
    if not isinstance(name, str):
        raise OTError("Dosya adı metin olmalıdır.")
    original = name
    cleaned = unicodedata.normalize("NFC", name)
    cleaned = _INVALID_WINDOWS_CHARS.sub("_", cleaned).strip(" .")
    if not cleaned:
        cleaned = "belge"
    # Device names stay reserved even when followed by a file extension.
    device_part = cleaned.split(".", 1)[0].rstrip(" .")
    if _RESERVED_WINDOWS_NAME.fullmatch(device_part):
        cleaned = "_" + cleaned
    changed = cleaned != original or _utf16_units(cleaned) > _MAX_FILENAME_UNITS
    if changed:
        tag = hashlib.sha256(
            f"{document_id}\0{original}".encode("utf-8", errors="surrogatepass")
        ).hexdigest()[:12]
        cleaned = _add_filename_tag(cleaned, tag)
    return cleaned


def _validated_base_url(base_url: str) -> str:
    if not isinstance(base_url, str):
        raise OTError("Sunucu adresi http:// veya https:// ile başlayan bir adres olmalıdır.")
    candidate = base_url.strip().rstrip("/")
    try:
        parsed = urlsplit(candidate)
        valid = (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not any(character.isspace() for character in candidate)
            and "\\" not in candidate
        )
        _ = parsed.port  # Validate the optional numeric port without resolving DNS.
    except ValueError:
        valid = False
    if not valid:
        raise OTError(
            "Sunucu adresini kontrol edin: http:// veya https:// ile başlamalı; "
            "kullanıcı bilgisi, sorgu veya # bölümü içermemelidir."
        )
    return candidate


def _transport_error(error: BaseException, operation: str) -> OTError:
    # Never interpolate requests exceptions: they may include URLs, credentials,
    # proxy secrets or server response text.
    if isinstance(error, requests.exceptions.SSLError):
        detail = "TLS sertifikası doğrulanamadı. Kurumun CA sertifikası ayarını kontrol edin."
    elif isinstance(error, requests.exceptions.Timeout):
        detail = "İstek zaman aşımına uğradı. Bağlantıyı ve zaman aşımı süresini kontrol edin."
    elif isinstance(error, requests.exceptions.ConnectionError):
        detail = "Sunucuya bağlanılamadı. Sunucu adresini, ağı, VPN ve proxy ayarlarını kontrol edin."
    elif isinstance(error, OSError):
        detail = "Bağlantı veya CA sertifika dosyası açılamadı. Sertifika yolunu ve erişim iznini kontrol edin."
    else:
        detail = "HTTP isteği tamamlanamadı. Sunucu adresini ve bağlantıyı kontrol edin."
    return OTError(f"{operation}: {detail}")


class HttpClient:
    """Small transport wrapper retaining the original client's public shape."""

    def __init__(
        self,
        base_url: str,
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int | float = 30,
        verify: bool | str = True,
    ):
        self.base_url = _validated_base_url(base_url)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise OTError("Zaman aşımı pozitif bir sayı olmalıdır.")
        if not math.isfinite(timeout) or timeout <= 0:
            raise OTError("Zaman aşımı pozitif ve sonlu bir sayı olmalıdır.")
        if not isinstance(verify, (bool, str)) or (isinstance(verify, str) and not verify.strip()):
            raise OTError("TLS doğrulaması açık/kapalı veya bir CA sertifika dosyasının yolu olmalıdır.")
        self.timeout = timeout
        self.verify = verify
        self.session = requests.Session()
        if headers:
            self.session.headers.update(headers)
        if cookies:
            self.session.cookies.update(cookies)

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            # Do not accidentally forward a session to a different origin.
            if urlsplit(path).netloc.lower() != urlsplit(self.base_url).netloc.lower():
                raise OTError("İstek adresi yapılandırılan OT sunucusuna ait değil.")
            if urlsplit(path).scheme != urlsplit(self.base_url).scheme:
                raise OTError("İstek adresinin bağlantı türü yapılandırılan sunucuyla eşleşmiyor.")
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        allow_redirect_response: bool = False,
        **kwargs: Any,
    ) -> requests.Response:
        try:
            response = getattr(self.session, method)(
                self._url(path),
                timeout=self.timeout,
                verify=self.verify,
                # A 307/308 must never resend the login form to another host.
                allow_redirects=False,
                **kwargs,
            )
        except (requests.exceptions.RequestException, OSError) as error:
            raise _transport_error(error, operation) from None

        status = response.status_code
        if 200 <= status < 300 or (allow_redirect_response and 300 <= status < 400):
            return response
        response.close()
        if status in (401, 403):
            detail = "Oturum veya erişim izni doğrulanamadı. Kullanıcı bilgilerini ve belge yetkisini kontrol edin."
        elif 300 <= status < 400:
            detail = "Sunucu isteği başka bir sayfaya yönlendirdi. Oturum açmayı ve sunucu adresini kontrol edin."
        elif status == 404:
            detail = "İstenen OT adresi veya belge bulunamadı. Sunucu adresini ve belge kimliğini kontrol edin."
        elif status >= 500:
            detail = "OT sunucusu isteği işleyemedi. Daha sonra yeniden deneyin."
        else:
            detail = "OT sunucusu isteği kabul etmedi. Giriş bilgilerini ve yapılandırmayı kontrol edin."
        raise OTError(f"{operation}: {detail} (HTTP {status})")

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        stream: bool = False,
        *,
        operation: str = "OT isteği",
    ) -> requests.Response:
        return self._request("get", path, operation=operation, params=params, headers=headers, stream=stream)

    def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
        *,
        operation: str = "OT isteği",
        allow_redirect_response: bool = False,
    ) -> requests.Response:
        return self._request(
            "post", path, operation=operation, allow_redirect_response=allow_redirect_response,
            data=data, json=json, headers=headers,
        )

    def close(self) -> None:
        self.session.close()


def _looks_like_login_html(text: str) -> bool:
    bounded = text[:_HTML_PROBE_LIMIT].lstrip("\ufeff \t\r\n").lower()
    # A PDF, JSON field or other document may legitimately quote a login form.
    # Only a response that actually starts with markup can be a login page.
    if not bounded.startswith("<"):
        return False
    if not re.search(r"<form\b", bounded):
        return False
    return bool(
        re.search(r"\btype\s*=\s*['\"]?password\b", bounded)
        or re.search(r"\bname\s*=\s*['\"]?j_(?:username|password)\b", bounded)
        or re.search(r"\baction\s*=\s*['\"][^'\"]*j_spring_security_check", bounded)
    )


def _failed_login_redirect(location: str) -> bool:
    try:
        parsed = urlsplit(location)
    except ValueError:
        raise OTError("Oturum açma: Sunucu geçersiz bir yönlendirme adresi döndürdü.") from None
    path = parsed.path.lower()
    query = parsed.query.lower()
    return bool(
        re.search(r"(?:^|/)(?:login|logon|signin|sign-in|j_spring_security_check)(?:[./;]|$)", path)
        or re.search(r"(?:^|&)(?:error|login_error|auth_error|authenticationfailed|loginfailed)(?:=|&|$)", query)
    )


def _entries(payload: dict[str, Any], operation: str) -> list[dict[str, Any]]:
    if "entries" not in payload:
        raise OTError(f"{operation}: Sunucu yanıtında beklenen 'entries' listesi bulunamadı.")
    entries = payload["entries"]
    if not isinstance(entries, list) or any(not isinstance(item, dict) for item in entries):
        raise OTError(f"{operation}: Sunucu yanıtındaki 'entries' alanı geçerli bir kayıt listesi değil.")
    return entries


def _required_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OTError(f"{label} boş olmayan bir metin olmalıdır.")
    return value.strip()


def _document_id(value: Any) -> str:
    document_id = _required_identifier(value, "Belge kimliği")
    if document_id in (".", ".."):
        raise OTError("Belge kimliği geçersiz; bir dosya yolu bileşeni olamaz.")
    return document_id


def _content_disposition_filename(header: str) -> str | None:
    # RFC 5987's UTF-8 filename* takes precedence over a legacy filename.
    extended = re.search(r"(?:^|;)\s*filename\*\s*=\s*(?:\"([^\"]*)\"|([^;]*))", header, re.IGNORECASE)
    if extended:
        value = (extended.group(1) if extended.group(1) is not None else extended.group(2)).strip()
        pieces = value.split("'", 2)
        if len(pieces) == 3:
            encoding, _, encoded = pieces
            try:
                return unquote(encoded, encoding=encoding or "utf-8", errors="replace")
            except LookupError:
                return unquote(encoded, encoding="utf-8", errors="replace")
    message = Message()
    message["Content-Disposition"] = header
    filename = message.get_filename()
    return filename.strip() if isinstance(filename, str) and filename.strip() else None


def _download_filename(response: requests.Response, document_id: str, requested: str | None) -> str:
    disposition = _content_disposition_filename(response.headers.get("Content-Disposition", ""))
    if requested is not None and not isinstance(requested, str):
        raise OTError("Dosya adı metin olmalıdır.")
    name = requested if requested and requested.strip() else disposition or document_id
    current_extension = PureWindowsPath(name.rstrip(" .")).suffix
    extension = PureWindowsPath(disposition.rstrip(" .")).suffix if disposition else ""
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,16}", extension) or extension[1:].isdigit():
        extension = ""
    if not extension:
        mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        extension = _MIME_EXTENSIONS.get(mime) or mimetypes.guess_extension(mime, strict=False) or ""
    # Document numbers such as POL.001 contain dots but have no file extension.
    # Known actual extensions always win. An unknown suffix is retained in the
    # base if a server-provided type gives stronger evidence of the real format.
    if not current_extension or current_extension[1:].isdigit():
        name += extension or ".bin"
    elif current_extension.lower() not in _KNOWN_FILE_EXTENSIONS:
        if extension and extension != ".bin" and extension.lower() != current_extension.lower():
            name += extension
    return safe_windows_filename(name, document_id)


def _validate_media_headers(
    response: requests.Response, requested: str | None, resolved: str
) -> tuple[bool, bool]:
    """Require a complete file response and positive evidence for JSON/HTML."""
    mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    # This client never sends Range and cannot reconstruct a partial resource.
    # Other successful statuses such as 204 are not successful file downloads.
    if response.status_code != 200 or "Content-Range" in response.headers or mime == "multipart/byteranges":
        raise OTError(
            f"Belge indirme: Sunucu tam bir dosya yanıtı döndürmedi (HTTP {response.status_code}); mevcut dosya korundu."
        )
    header = response.headers.get("Content-Disposition", "")
    attachment = header.split(";", 1)[0].strip().lower() == "attachment"
    attachment_name = _content_disposition_filename(header) if attachment else None
    requested_extension = PureWindowsPath((requested or "").rstrip(" .")).suffix.lower()
    attachment_extension = PureWindowsPath((attachment_name or "").rstrip(" .")).suffix.lower()
    resolved_extension = PureWindowsPath(resolved).suffix.lower()
    html_extensions = {".html", ".htm", ".xhtml"}
    # A suffix inferred solely from an API's MIME type is not evidence that its
    # response is a document. An explicit caller name or named attachment is.
    allow_json = resolved_extension == ".json" and ".json" in (requested_extension, attachment_extension)
    allow_html = resolved_extension in html_extensions and bool(
        html_extensions.intersection((requested_extension, attachment_extension))
    )
    if mime in ("application/problem+json", "application/problem+xml"):
        raise OTError("Belge indirme: Sunucu dosya yerine bir servis hata yanıtı döndürdü; mevcut dosya korundu.")
    if (mime in ("application/json", "text/json") or mime.endswith("+json")) and not allow_json:
        raise OTError("Belge indirme: Sunucu beklenen dosya yerine JSON yanıtı döndürdü. Oturumu ve belge erişimini kontrol edin.")
    if mime in ("text/html", "application/xhtml+xml") and not allow_html:
        raise OTError("Belge indirme: Sunucu beklenen dosya yerine HTML sayfası döndürdü. Oturumu ve belge erişimini kontrol edin.")
    return allow_json, allow_html


def _validate_media_prefix(prefix: bytearray, allow_json: bool, allow_html: bool) -> None:
    """Catch recognizable service bodies even when their MIME is mislabeled."""
    text = prefix.decode("utf-8", errors="ignore").lstrip("\ufeff \t\r\n")
    if _looks_like_login_html(text):
        raise OTError("Belge indirme: Sunucu dosya yerine giriş formunu döndürdü. Yeniden oturum açın.")
    if not allow_html and re.match(r"(?:<!doctype\s+html\b|<(?:html|head|body)\b)", text, re.IGNORECASE):
        raise OTError("Belge indirme: Sunucu beklenen dosya yerine HTML sayfası döndürdü; mevcut dosya korundu.")
    if not allow_json and text.startswith(("{", "[")):
        try:
            payload, _ = json.JSONDecoder().raw_decode(text)
        except ValueError:
            return  # A later streamed chunk may complete this bounded prefix.
        if isinstance(payload, (dict, list)):
            raise OTError("Belge indirme: Sunucu beklenen dosya yerine JSON yanıtı döndürdü; mevcut dosya korundu.")


def _content_length(response: requests.Response) -> int | None:
    # requests yields decoded content. A compressed wire length cannot be used
    # as the decoded byte total. Chunked transfer also has no fixed wire length.
    encoding = response.headers.get("Content-Encoding", "").strip().lower()
    transfer = response.headers.get("Transfer-Encoding", "").strip().lower()
    if encoding not in ("", "identity") or transfer not in ("", "identity"):
        return None
    value = response.headers.get("Content-Length")
    if value is None:
        return None
    try:
        length = int(value)
    except (TypeError, ValueError):
        raise OTError("İndirme: Sunucu geçersiz bir dosya boyutu (Content-Length) bildirdi.") from None
    if length < 0:
        raise OTError("İndirme: Sunucu negatif bir dosya boyutu bildirdi.")
    return length


class _ProgressReporter:
    def __init__(self, callback: Callable[[int, int | None], None] | None, total: int | None):
        self.callback = callback
        self.total = total
        self.last_time = 0.0
        self.last_done: int | None = None

    def emit(self, done: int, *, force: bool = False) -> None:
        if self.callback is None or done == self.last_done:
            return
        now = time.monotonic()
        if not force and self.last_done is not None and now - self.last_time < 0.1:
            return
        self.last_time = now
        self.last_done = done
        try:
            self.callback(done, self.total)
        except Exception:
            # Progress is best effort: a presentation callback must not turn a
            # successfully committed document into a reported download failure.
            pass


class OTConnector:
    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        timeout: int | float = 30,
        verify: bool | str = True,
        folder_id: str = "",
    ):
        if not isinstance(username, str) or not isinstance(password, str):
            raise OTError("Kullanıcı adı ve parola normal metin değerleri olmalıdır.")
        if not isinstance(folder_id, str):
            raise OTError("Klasör kimliği metin olmalıdır.")
        self.username = username
        self.password = password
        self.folder_id = folder_id
        self.client = HttpClient(
            base_url=base_url,
            headers={"User-Agent": "OTDesktop/1.0", "Accept": "application/json"},
            timeout=timeout,
            verify=verify,
        )
        self.base_url = self.client.base_url
        self._authenticated = False
        self._path_owners: dict[tuple[str, str], str] = {}

    def login(self) -> bool:
        """Authenticate once and verify access with the protected search API.

        A normal login redirect is accepted only provisionally; HTTP 200 alone
        never establishes success. Authentication POSTs are never retried.
        """
        self._authenticated = False
        if not self.username.strip() or not self.password:
            raise OTError("Oturum açmak için kullanıcı adı ve parola gereklidir.")
        # A previous successful session must not conceal incorrect new inputs.
        self.client.session.cookies.clear()
        response = self.client.post(
            "/TDS/j_spring_security_check",
            data={"j_username": self.username, "j_password": self.password},
            operation="Oturum açma",
            allow_redirect_response=True,
        )
        try:
            location = response.headers.get("Location", "")
            if 300 <= response.status_code < 400:
                if not location or _failed_login_redirect(location):
                    raise OTError("Oturum açma başarısız. Kullanıcı adı ve parolayı kontrol edin.")
                redirect = urlsplit(urljoin(self.base_url + "/", location))
                configured = urlsplit(self.base_url)
                if (redirect.scheme, redirect.netloc.lower()) != (configured.scheme, configured.netloc.lower()):
                    raise OTError("Oturum açma başka bir sunucuya yönlendirildi. OT sunucu adresini kontrol edin.")
            if _looks_like_login_html(response.text):
                raise OTError("Oturum açma başarısız; sunucu giriş formunu döndürdü. Kullanıcı bilgilerini kontrol edin.")
            if "json" in response.headers.get("Content-Type", "").lower():
                try:
                    auth_payload = response.json()
                except ValueError:
                    raise OTError("Oturum açma: Sunucu geçerli bir JSON yanıtı döndürmedi.") from None
                if isinstance(auth_payload, dict) and (
                    auth_payload.get("success") is False
                    or auth_payload.get("authenticated") is False
                    or bool(auth_payload.get("error"))
                ):
                    raise OTError("Oturum açma başarısız. Kullanıcı bilgilerini ve erişim yetkisini kontrol edin.")
        finally:
            response.close()
        self.search_documents(_AUTH_PROBE)
        self._authenticated = True
        return True

    def test_connection(self) -> bool:
        """Verify the supplied credentials and authenticated API access."""
        return self.login()

    def _get_json(
        self, path: str, *, operation: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self.client.get(path, params=params, operation=operation)
        try:
            if _looks_like_login_html(response.text):
                raise OTError(f"{operation}: Sunucu giriş formunu döndürdü. Yeniden oturum açın.")
            try:
                payload = response.json()
            except ValueError:
                raise OTError(
                    f"{operation}: Sunucu geçerli JSON döndürmedi. Oturumu ve OT sunucu adresini kontrol edin."
                ) from None
            if not isinstance(payload, dict):
                raise OTError(f"{operation}: Sunucu yanıtı beklenen JSON nesnesi biçiminde değil.")
            return payload
        finally:
            response.close()

    def search_document(self, document_number: str) -> dict[str, Any]:
        """Return the original response object for compatibility."""
        number = _required_identifier(document_number, "Belge numarası")
        return self._get_json(
            "/TDS/realtime-queries/tds_search_documents",
            params={"inline": True, "input_name": number},
            operation="Belge araması",
        )

    def search_documents(self, document_number: str) -> list[Document]:
        """Return every match; leave exact/ambiguous selection to the caller."""
        payload = self.search_document(document_number)
        documents: list[Document] = []
        for index, item in enumerate(_entries(payload, "Belge araması"), 1):
            content = item.get("content")
            properties = content.get("properties") if isinstance(content, dict) else None
            if not isinstance(properties, dict):
                raise OTError(f"Belge araması: {index}. kaydın content.properties alanı eksik veya bozuk.")
            document_id = properties.get("id")
            name = properties.get("object_name")
            if not isinstance(document_id, str) or not document_id.strip() or not isinstance(name, str) or not name.strip():
                raise OTError(f"Belge araması: {index}. kaydın kimliği veya belge adı eksik ya da geçersiz.")
            title = properties.get("title", "")
            authors = properties.get("authors", [])
            revision = properties.get("revision", 0)
            if title is None:
                title = ""
            if authors is None:
                authors = []
            if not isinstance(title, str):
                raise OTError(f"Belge araması: {index}. kaydın başlığı metin biçiminde değil.")
            if isinstance(authors, str):
                author = " ".join(authors.split())
            elif isinstance(authors, list) and all(isinstance(item, str) for item in authors):
                author = ", ".join(" ".join(item.split()) for item in authors if item.strip())
            else:
                raise OTError(f"Belge araması: {index}. kaydın yazar bilgisi geçersiz.")
            documents.append(Document(document_id.strip(), name.strip(), " ".join(title.split()), author, revision))
        return documents

    def get_document_by_id(self, id: str) -> dict[str, Any]:
        document_id = _document_id(id)
        return self._get_json(
            f"/TDS/contents/tds_document/{quote(document_id, safe='')}",
            operation="Belge bilgisi",
        )

    def get_document_titles(self, folder_id: str | None = None) -> list[dict[str, Any]]:
        folder = _required_identifier(self.folder_id if folder_id is None else folder_id, "Klasör kimliği")
        payload = self._get_json(
            "/TDS/dql-queries/tds_folder_list",
            params={"inline": True, "input_folder_id": folder},
            operation="Klasör listesi",
        )
        return [
            {key: value for key, value in item.items() if key not in ("content", "summary")}
            for item in _entries(payload, "Klasör listesi")
        ]

    @staticmethod
    def _check_target(target: Path) -> None:
        if target.is_symlink():
            raise OTError("İndirme hedefi bir dosya bağlantısı. Farklı bir dosya adı veya klasör seçin.")
        if target.exists() and not target.is_file():
            raise OTError("İndirme hedefinde aynı adlı bir klasör veya özel dosya var. Farklı bir ad seçin.")

    def _target_path(self, folder: Path, filename: str, document_id: str) -> Path:
        folder_key = str(folder).casefold()
        candidate = filename
        sequence = 0
        while True:
            key = (folder_key, candidate.casefold())
            owner = self._path_owners.get(key)
            if owner is None or owner == document_id:
                break
            sequence += 1
            tag = hashlib.sha256(f"{document_id}\0{filename}\0{sequence}".encode("utf-8")).hexdigest()[:12]
            candidate = _add_filename_tag(filename, tag)
        # Casefold on every platform so Linux tests exercise Windows collisions.
        matches = [path for path in folder.iterdir() if path.name.casefold() == candidate.casefold()]
        if len(matches) > 1:
            raise OTError("Hedef klasörde yalnızca harf büyüklüğü farklı olan birden fazla dosya var. Dosya adlarını düzeltin.")
        target = matches[0] if matches else folder / candidate
        self._check_target(target)
        return target

    def download_document(
        self,
        id: str,
        folder_path: str | os.PathLike[str],
        file_name: str | None = None,
        overwrite: bool = False,
        *,
        cancel_event: threading.Event | None = None,
        progress: Callable[[int, int | None], None] | None = None,
    ) -> DownloadResult:
        """Stream, validate, SHA256-compare, and atomically commit one document.

        Existing contents survive request failures and cooperative cancellation.
        Progress reports received bytes and a decoded total when available, at
        most ten intermediate notifications per second plus start and finish.
        A cancel requested after the atomic replacement cannot undo the commit.
        """
        document_id = _document_id(id)
        _check_cancelled(cancel_event)
        response: requests.Response | None = None
        temporary_path: Path | None = None
        try:
            folder = Path(folder_path).expanduser()
            folder.mkdir(parents=True, exist_ok=True)
            folder = folder.resolve()
            response = self.client.get(
                f"/TDS/contents/tds_document/{quote(document_id, safe='')}/media",
                headers={"Accept": "*/*", "Accept-Encoding": "identity"},
                stream=True,
                operation="Belge indirme",
            )
            _check_cancelled(cancel_event)
            filename = _download_filename(response, document_id, file_name)
            allow_json, allow_html = _validate_media_headers(response, file_name, filename)
            target = self._target_path(folder, filename, document_id)
            total = _content_length(response)
            reporter = _ProgressReporter(progress, total)
            reporter.emit(0, force=True)
            digest = hashlib.sha256()
            received = 0
            html_probe = bytearray()
            with tempfile.NamedTemporaryFile(mode="wb", prefix=".OT-", suffix=".part", dir=folder, delete=False) as output:
                temporary_path = Path(output.name)
                for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                    _check_cancelled(cancel_event)
                    if not chunk:
                        continue
                    if not isinstance(chunk, bytes):
                        raise OTError("Belge indirme: Sunucu beklenmeyen dosya verisi döndürdü.")
                    received += len(chunk)
                    if total is not None and received > total:
                        raise OTError("Belge indirme: Alınan veri sunucunun bildirdiği dosya boyutunu aştı; mevcut dosya korundu.")
                    if len(html_probe) < _HTML_PROBE_LIMIT:
                        html_probe.extend(chunk[:_HTML_PROBE_LIMIT - len(html_probe)])
                        _validate_media_prefix(html_probe, allow_json, allow_html)
                    output.write(chunk)
                    digest.update(chunk)
                    reporter.emit(received)
                _check_cancelled(cancel_event)
                if total is not None and received != total:
                    raise OTError("Belge indirme: Dosya eksik alındı; mevcut dosya korundu. Yeniden deneyin.")
                output.flush()
                os.fsync(output.fileno())

            _check_cancelled(cancel_event)
            self._check_target(target)
            existed = target.exists()
            if existed and not overwrite:
                old_hash = get_local_file_sha256(target, cancel_event=cancel_event)
                _check_cancelled(cancel_event)
                if old_hash == digest.hexdigest():
                    self._path_owners[(str(folder).casefold(), target.name.casefold())] = document_id
                    reporter.emit(received, force=True)
                    return DownloadResult(target, "unchanged", 0)
            _check_cancelled(cancel_event)
            os.replace(temporary_path, target)
            temporary_path = None
            self._path_owners[(str(folder).casefold(), target.name.casefold())] = document_id
            reporter.emit(received, force=True)
            return DownloadResult(target, "updated" if existed else "downloaded", received)
        except requests.exceptions.RequestException as error:
            raise _transport_error(error, "Belge indirme") from None
        except OSError:
            raise OTError(
                "Dosya kaydedilemedi. Hedef klasör izinlerini, boş disk alanını, dosya yolunun uzunluğunu "
                "ve dosyanın başka bir uygulamada açık olup olmadığını kontrol edin."
            ) from None
        finally:
            if response is not None:
                response.close()
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    raise OTError("İndirme geçici dosyası temizlenemedi. Hedef klasörün erişim izinlerini kontrol edin.") from None

    def close(self) -> None:
        self._authenticated = False
        self.client.close()

    def __enter__(self) -> OTConnector:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()
