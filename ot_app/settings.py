"""Per-user settings and document queue, with independent corruption recovery.

Native services are injected through small ``read/write/delete`` registry and
``protect/unprotect`` byte-protector boundaries. Unsupported systems use only
an explicit in-memory session; passwords are never written to a fallback file.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from urllib.parse import urlsplit

from .documents import MAX_DOCUMENTS, MAX_INPUT_CHARACTERS, merge_document_numbers
from .filename_format import DEFAULT_FILENAME_FORMAT, validate_filename_format, validate_folder_format
from .hierarchy import HierarchyEntry, validate_hierarchy
from .win_secrets import DPAPIProtector, MAX_SECRET_BYTES

REGISTRY_PATH = r"Software\OTDesktop"
SETTINGS_VALUE = "Settings"
DOCUMENTS_VALUE = "Documents"
HIERARCHY_VALUE = "DocumentHierarchy"
PASSWORD_VALUE = "Password"
REG_SZ = 1
REG_BINARY = 3
REG_MULTI_SZ = 7
MAX_CONFIG_CHARACTERS = 1024 * 1024
_MISSING = object()


class SettingsError(RuntimeError):
    """Persistent settings could not be safely saved."""


class SettingsValidationError(ValueError):
    """Invalid setting, with its field name for routing focus to the right page."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


def _default_output_directory() -> str:
    return str(Path.home() / "Documents" / "OT Documents")


@dataclass
class AppSettings:
    base_url: str = ""
    username: str = ""
    password: str = field(default="", repr=False)
    output_dir: str = field(default_factory=_default_output_directory)
    timeout: float = 30
    folder_id: str = ""
    ca_bundle: str = ""
    verify_tls: bool = True
    remember_password: bool = True
    filename_format: str = DEFAULT_FILENAME_FORMAT
    document_subfolder_enabled: bool = False
    document_subfolder_format: str = "{numara}"
    document_subfolder_match: str = "exact"
    download_related_forms: bool = False
    download_related_attachments: bool = False
    manual_folder_hierarchy_enabled: bool = False

    @property
    def tls_verify(self) -> bool | str:
        """Return the TLS option used by both downloads and connection probes."""
        if not self.verify_tls:
            return False
        return str(Path(self.ca_bundle).expanduser()) if self.ca_bundle else True

    def validate(self, require_connection: bool = False) -> None:
        labels = {
            "base_url": "Sunucu adresi", "username": "Kullanıcı adı",
            "password": "Parola", "output_dir": "İndirme klasörü",
            "folder_id": "Klasör kimliği", "ca_bundle": "CA sertifika dosyası",
            "document_subfolder_format": "Klasör adı formatı",
        }
        for name, label in labels.items():
            value = getattr(self, name)
            if not isinstance(value, str):
                raise SettingsValidationError(name, f"{label} metin olmalıdır.")
            if "\x00" in value:
                raise SettingsValidationError(name, f"{label} NUL karakteri içeremez.")
            try:
                encoded = value.encode("utf-8")
            except UnicodeEncodeError:
                raise SettingsValidationError(name, f"{label} geçerli Unicode metni olmalıdır.") from None
            if len(encoded) > MAX_SECRET_BYTES:
                raise SettingsValidationError(name, f"{label} izin verilen boyutu aşıyor.")
        for name in ("verify_tls", "remember_password", "document_subfolder_enabled",
                     "download_related_forms", "download_related_attachments",
                     "manual_folder_hierarchy_enabled"):
            if type(getattr(self, name)) is not bool:
                raise SettingsValidationError(name, "Seçenek açık veya kapalı olmalıdır.")
        if isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)):
            raise SettingsValidationError("timeout", "Zaman aşımı saniye cinsinden bir sayı olmalıdır.")
        try:
            valid_timeout = math.isfinite(self.timeout) and 0 < self.timeout <= 3600
        except OverflowError:
            valid_timeout = False
        if not valid_timeout:
            raise SettingsValidationError("timeout", "Zaman aşımı sıfırdan büyük ve en fazla 3600 saniye olmalıdır.")
        base_url = self.base_url.strip()
        if base_url:
            try:
                parts = urlsplit(base_url)
                invalid = (
                    parts.scheme not in ("http", "https") or not parts.hostname
                    or parts.username is not None or parts.password is not None
                    or bool(parts.query) or bool(parts.fragment)
                    or "?" in base_url or "#" in base_url
                    or any(character.isspace() for character in base_url)
                    or any(ord(character) < 32 or ord(character) == 127 for character in base_url)
                    or "\\" in base_url
                )
                _ = parts.port  # Also rejects malformed and out-of-range ports.
            except ValueError:
                invalid = True
            if invalid:
                raise SettingsValidationError("base_url", "Sunucu adresi geçerli bir HTTP/HTTPS adresi olmalı; kullanıcı bilgisi, sorgu veya # içermemelidir.")
        if not self.output_dir.strip():
            raise SettingsValidationError("output_dir", "İndirme klasörünü seçin.")
        try:
            validate_filename_format(self.filename_format)
        except ValueError as error:
            raise SettingsValidationError("filename_format", str(error)) from None
        if self.document_subfolder_match not in ("exact", "contains"):
            raise SettingsValidationError("document_subfolder_match", "Klasör eşleşmesi birebir veya içerme olmalıdır.")
        if self.document_subfolder_enabled and self.manual_folder_hierarchy_enabled:
            raise SettingsValidationError("manual_folder_hierarchy_enabled", "Otomatik belge klasörü ve elle klasör hiyerarşisi aynı anda açılamaz.")
        if self.document_subfolder_enabled or self.manual_folder_hierarchy_enabled:
            try:
                validate_folder_format(self.document_subfolder_format)
            except ValueError as error:
                raise SettingsValidationError("document_subfolder_format", str(error)) from None
        self._validate_paths()
        if require_connection:
            for name, message in (("base_url", "Sunucu adresini girin."),
                                  ("username", "Kullanıcı adını girin."),
                                  ("password", "Parolayı girin.")):
                value = getattr(self, name)
                if not (value if name == "password" else value.strip()):
                    raise SettingsValidationError(name, message)

    def _validate_paths(self) -> None:
        try:
            output_path = Path(self.output_dir).expanduser()
            if output_path.exists() and not output_path.is_dir():
                raise SettingsValidationError("output_dir", "İndirme yolu bir klasör olmalıdır.")
        except (OSError, RuntimeError):
            raise SettingsValidationError("output_dir", "İndirme klasörü yolu okunamadı.") from None
        try:
            if self.verify_tls and self.ca_bundle.strip() and not Path(self.ca_bundle).expanduser().is_file():
                raise SettingsValidationError("ca_bundle", "CA sertifika dosyası bulunamadı veya bir dosya değil.")
        except (OSError, RuntimeError):
            raise SettingsValidationError("ca_bundle", "CA sertifika dosyası yolu okunamadı.") from None


_CONFIG_FIELDS = tuple(item.name for item in fields(AppSettings) if item.name != "password")


def _documents_digest(documents: list[str]) -> str:
    sequence = json.dumps(documents, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(sequence.encode("utf-8")).hexdigest()


def _serialize_hierarchy(documents: list[str], hierarchy: dict[str, str | None]) -> str:
    """Validate the complete structure before any registry or secret changes."""
    if not isinstance(hierarchy, dict) or len(hierarchy) > MAX_DOCUMENTS:
        raise ValueError("Belge hiyerarşisi geçerli bir eşleme olmalıdır.")
    positions = {number: index for index, number in enumerate(documents)}
    if any(number not in positions for number in hierarchy):
        raise ValueError("Hiyerarşi belge listesinde bulunmayan bir belge içeriyor.")
    entries = [HierarchyEntry(number, hierarchy.get(number)) for number in documents]
    validate_hierarchy(entries)
    parents = [positions[entry.parent_key] if entry.parent_key is not None else None for entry in entries]
    record = json.dumps({"version": 1, "documents_sha256": _documents_digest(documents),
                         "parents": parents}, ensure_ascii=False, separators=(",", ":"))
    if len(record) > MAX_CONFIG_CHARACTERS:
        raise ValueError("Belge hiyerarşisi izin verilen toplam boyutu aşıyor.")
    return record


def _credential_context(settings: AppSettings) -> dict[str, str]:
    return {"base_url": settings.base_url.strip().rstrip("/"), "username": settings.username.strip()}


def _saved_password_binding(config_value) -> dict:
    """Read additive credential metadata; legacy records retain their identity.

    A ciphertext digest detects partial registry saves without storing a hash of
    the plaintext password. Invalid/missing configuration never binds a secret
    to newly entered connection details.
    """
    try:
        if not isinstance(config_value, str) or len(config_value) > MAX_CONFIG_CHARACTERS:
            return {}
        config = json.loads(config_value)
        if not isinstance(config, dict):
            return {}
        if "password_binding" in config:
            binding = config["password_binding"]
            return binding if isinstance(binding, dict) else {}
        return _credential_context(AppSettings(
            base_url=config.get("base_url", ""), username=config.get("username", "")
        ))
    except (ValueError, RecursionError, AttributeError):
        return {}


class _WindowsRegistry:
    def __init__(self) -> None:
        import winreg
        self.winreg = winreg

    def read(self, name: str):
        with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, self.winreg.KEY_QUERY_VALUE) as key:
            return self.winreg.QueryValueEx(key, name)

    def write(self, name: str, value, kind: int) -> None:
        with self.winreg.CreateKeyEx(self.winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, self.winreg.KEY_SET_VALUE) as key:
            self.winreg.SetValueEx(key, name, 0, kind, value)

    def delete(self, name: str) -> None:
        try:
            with self.winreg.OpenKey(self.winreg.HKEY_CURRENT_USER, REGISTRY_PATH, 0, self.winreg.KEY_SET_VALUE) as key:
                self.winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


class RegistryStore:
    """Save settings under HKCU\\Software\\OTDesktop, without elevation.

    ``save_documents`` touches only the queue. When remembering is enabled, an
    empty password on a full save leaves any existing ciphertext intact. Supply
    a replacement password or explicitly disable remembering to change it.
    ``save(settings, None)`` changes configuration/secret only and preserves the
    document queue, including a saved queue that could not be read this session.
    """

    def __init__(self, registry=None, protector=None, *, platform: str | None = None) -> None:
        self._registry = registry
        self._protector = protector
        self._warnings: dict[str, str] = {}
        self._memory_settings = AppSettings()
        self._memory_documents: list[str] = []
        self._memory_hierarchy: str | None = None
        self._session_only = registry is None and (platform or sys.platform) != "win32"
        if self._session_only:
            self._warnings["platform"] = "Windows dışında çalışıyor: ayarlar, parola ve belge listesi yalnızca bu oturumda tutulur; uygulama kapanınca silinir."
        elif self._registry is None:
            self._registry = _WindowsRegistry()
        if not self._session_only and self._protector is None:
            try:
                self._protector = DPAPIProtector()
            except (OSError, RuntimeError):
                self._warnings["password"] = "Windows parola koruma hizmeti kullanılamıyor. Parola kalıcı olarak kaydedilemez."

    @property
    def warning(self) -> str:
        return " ".join(self._warnings.values())

    @property
    def persistent(self) -> bool:
        return not self._session_only

    def _read_value(self, name: str, expected_type: int, category: str, label: str):
        try:
            value, kind = self._registry.read(name)
        except FileNotFoundError:
            return _MISSING
        except (OSError, ValueError, TypeError):
            self._warnings[category] = f"Kayıtlı {label} okunamadı; diğer veriler kullanılabilir."
            return _MISSING
        if kind != expected_type:
            self._warnings[category] = f"Kayıtlı {label} türü geçersiz; mevcut kayıt değiştirilmedi."
            return _MISSING
        return value

    def _load_config(self, value) -> AppSettings:
        settings = AppSettings()
        if value is _MISSING:
            return settings
        try:
            if not isinstance(value, str) or len(value) > MAX_CONFIG_CHARACTERS:
                raise ValueError
            config = json.loads(value)
            if not isinstance(config, dict):
                raise ValueError
        except (ValueError, RecursionError):
            self._warnings["settings"] = "Kayıtlı ayarlar bozuk; varsayılan ayarlar açıldı. Belge listesi ve parola ayrı olarak okunur."
            return settings
        invalid_fields = "password" in config
        # Validate CA under saved TLS; load manual mode last so a conflicting
        # corrupt record preserves the existing automatic-subfolder behavior.
        delayed = ("verify_tls", "manual_folder_hierarchy_enabled")
        for name in ("verify_tls", *(key for key in _CONFIG_FIELDS if key not in delayed),
                     "manual_folder_hierarchy_enabled"):
            if name not in config:
                continue
            candidate = replace(settings, **{name: config[name]})
            try:
                candidate.validate()
            except ValueError:
                invalid_fields = True
            else:
                settings = candidate
        if invalid_fields:
            self._warnings["settings"] = "Kayıtlı ayarlardaki geçersiz alanlar varsayılana döndürüldü; geçerli alanlar korundu."
        return settings

    def _load_documents(self, value) -> list[str]:
        if value is _MISSING:
            return []
        if not isinstance(value, (list, tuple)):
            self._warnings["documents"] = "Kayıtlı belge listesi geçersiz; mevcut kayıt değiştirilmedi."
            return []
        recovered: list[str] = []
        seen: set[str] = set()
        total_characters = 0
        damaged = False
        for entry in value:
            try:
                normalized = merge_document_numbers([], [entry])
            except ValueError:
                damaged = True
                continue
            if not normalized or normalized[0] in seen:
                continue
            number = normalized[0]
            total_characters += len(number)
            if len(recovered) >= MAX_DOCUMENTS or total_characters > MAX_INPUT_CHARACTERS:
                damaged = True
                break
            seen.add(number)
            recovered.append(number)
        if damaged:
            self._warnings["documents"] = "Kayıtlı belge listesinde geçersiz veya sınırı aşan öğeler var; okunabilen belgeler kurtarıldı."
        return recovered

    def load(self) -> tuple[AppSettings, list[str]]:
        if self._session_only:
            return replace(self._memory_settings), list(self._memory_documents)
        self._warnings.clear()
        if self._protector is None:
            self._warnings["password"] = "Windows parola koruma hizmeti kullanılamıyor. Parola kalıcı olarak kaydedilemez."
        config_value = self._read_value(SETTINGS_VALUE, REG_SZ, "settings", "ayarlar")
        settings = self._load_config(config_value)
        binding = _saved_password_binding(config_value)
        document_value = self._read_value(DOCUMENTS_VALUE, REG_MULTI_SZ, "documents", "belge listesi")
        documents = self._load_documents(document_value)
        if settings.remember_password:
            protected = self._read_value(PASSWORD_VALUE, REG_BINARY, "password", "parola")
            if protected is not _MISSING:
                try:
                    if not isinstance(protected, bytes) or len(protected) > MAX_SECRET_BYTES or self._protector is None:
                        raise ValueError
                    if any(binding.get(key) != value for key, value in _credential_context(settings).items()):
                        raise ValueError
                    if "ciphertext_sha256" in binding and binding["ciphertext_sha256"] != hashlib.sha256(protected).hexdigest():
                        raise ValueError
                    password = self._protector.unprotect(protected).decode("utf-8")
                    candidate = replace(settings, password=password)
                    candidate.validate()
                    settings = candidate
                except (OSError, RuntimeError, ValueError, TypeError, AttributeError):
                    self._warnings["password"] = "Kayıtlı parola çözülemedi veya bağlantı bilgileriyle eşleşmiyor; parolayı yeniden girin. Şifreli kayıt korundu; yeni parola kaydedilene veya hatırlama kapatılana kadar değiştirilmez."
        return settings, documents

    def _save_error(self, message: str, *, category: str = "save_write") -> None:
        self._warnings[category] = message
        raise SettingsError(message) from None

    def load_hierarchy(self, documents: list[str]) -> dict[str, str | None]:
        """Read queue-bound metadata; damaged or stale records leave all roots.

        Recovery never rewrites the stored record. The document queue and the
        existing two-item ``load`` result remain independently compatible.
        """
        canonical = merge_document_numbers([], documents)
        roots = dict.fromkeys(canonical)
        self._warnings.pop("hierarchy", None)
        value = self._memory_hierarchy if self._session_only else self._read_value(
            HIERARCHY_VALUE, REG_SZ, "hierarchy", "belge hiyerarşisi")
        if value is _MISSING or (self._session_only and value is None):
            return roots
        try:
            if not isinstance(value, str) or len(value) > MAX_CONFIG_CHARACTERS:
                raise ValueError
            record = json.loads(value)
            if (not isinstance(record, dict) or type(record.get("version")) is not int
                    or record["version"] != 1 or record.get("documents_sha256") != _documents_digest(canonical)):
                raise ValueError
            parents = record.get("parents")
            if not isinstance(parents, list) or len(parents) != len(canonical) or len(parents) > MAX_DOCUMENTS:
                raise ValueError
            for index, parent in enumerate(parents):
                if parent is not None and (type(parent) is not int or not 0 <= parent < index):
                    raise ValueError
            entries = [HierarchyEntry(number, canonical[parent] if parent is not None else None)
                       for number, parent in zip(canonical, parents)]
            validate_hierarchy(entries)
            return {entry.key: entry.parent_key for entry in entries}
        except (ValueError, TypeError, RecursionError):
            self._warnings["hierarchy"] = "Kayıtlı belge hiyerarşisi geçersiz veya belge listesiyle eşleşmiyor; belgeler kökte açıldı. Mevcut kayıt değiştirilmedi."
            return roots

    def save_documents(self, documents: list[str], *, hierarchy: dict[str, str | None] | None = None) -> None:
        """Autosave queue/optional hierarchy without reading or changing secrets.

        Omitted hierarchy metadata and its recovery warning remain untouched.
        """
        canonical = merge_document_numbers([], documents)
        hierarchy_record = _serialize_hierarchy(canonical, hierarchy) if hierarchy is not None else None
        if self._session_only:
            self._memory_documents = list(canonical)
            if hierarchy_record is not None:
                self._memory_hierarchy = hierarchy_record
                self._warnings.pop("hierarchy", None)
            return
        try:
            self._registry.write(DOCUMENTS_VALUE, canonical, REG_MULTI_SZ)
            if hierarchy_record is not None:
                self._registry.write(HIERARCHY_VALUE, hierarchy_record, REG_SZ)
        except (OSError, ValueError, TypeError):
            self._save_error("Belge listesi Windows kayıt defterine kaydedilemedi. Liste bu oturumda kullanılabilir.", category="queue_write")
        self._warnings.pop("documents", None)
        self._warnings.pop("queue_write", None)
        if hierarchy_record is not None:
            self._warnings.pop("hierarchy", None)

    def save(self, settings: AppSettings, documents: list[str] | None = None, *,
             hierarchy: dict[str, str | None] | None = None) -> None:
        """Save configuration/secret and optionally replace the document queue.

        ``None`` (including an omitted argument) never reads or writes Documents.
        Pass an explicit list, including ``[]``, to replace the persisted queue.
        """
        settings.validate()
        if hierarchy is not None and documents is None:
            raise ValueError("Hiyerarşi kaydedilirken belge listesi de verilmelidir.")
        canonical = merge_document_numbers([], documents) if documents is not None else None
        hierarchy_record = _serialize_hierarchy(canonical, hierarchy) if hierarchy is not None else None
        config_values = {name: getattr(settings, name) for name in _CONFIG_FIELDS}
        config = json.dumps(config_values, ensure_ascii=False, allow_nan=False)
        if len(config) > MAX_CONFIG_CHARACTERS:
            raise ValueError("Ayarlar izin verilen toplam boyutu aşıyor.")
        if self._session_only:
            self._memory_settings = replace(settings)
            if canonical is not None:
                self._memory_documents = list(canonical)
            if hierarchy_record is not None:
                self._memory_hierarchy = hierarchy_record
                self._warnings.pop("hierarchy", None)
            return
        protected = None
        if settings.remember_password and settings.password:
            try:
                if self._protector is None:
                    raise ValueError
                protected = self._protector.protect(settings.password.encode("utf-8"))
                if not isinstance(protected, bytes) or not protected or len(protected) > MAX_SECRET_BYTES:
                    raise ValueError
            except (OSError, RuntimeError, ValueError, TypeError):
                self._save_error("Parola Windows DPAPI ile korunamadı. Hiçbir ayar kaydedilmedi; mevcut kayıtlar korundu.")
        if protected is not None:
            binding = {**_credential_context(settings), "ciphertext_sha256": hashlib.sha256(protected).hexdigest()}
        else:
            old_config = self._read_value(SETTINGS_VALUE, REG_SZ, "settings", "ayarlar")
            binding = _saved_password_binding(old_config)
        config_values["password_binding"] = binding
        config = json.dumps(config_values, ensure_ascii=False, allow_nan=False)
        if len(config) > MAX_CONFIG_CHARACTERS:
            raise ValueError("Ayarlar izin verilen toplam boyutu aşıyor.")
        # DPAPI is completed before registry changes. Secret changes are last,
        # so a configuration/queue write failure cannot remove a saved password.
        try:
            self._registry.write(SETTINGS_VALUE, config, REG_SZ)
            if canonical is not None:
                self._registry.write(DOCUMENTS_VALUE, canonical, REG_MULTI_SZ)
            if hierarchy_record is not None:
                self._registry.write(HIERARCHY_VALUE, hierarchy_record, REG_SZ)
            if not settings.remember_password:
                self._registry.delete(PASSWORD_VALUE)
            elif protected is not None:
                self._registry.write(PASSWORD_VALUE, protected, REG_BINARY)
        except (OSError, ValueError, TypeError):
            self._save_error("Ayarların tamamı Windows kayıt defterine kaydedilemedi. Alanlar bu oturumda kullanılabilir; kaydetmeyi yeniden deneyin.")
        for category in ("settings", "save_write"):
            self._warnings.pop(category, None)
        if canonical is not None:
            self._warnings.pop("documents", None)
            self._warnings.pop("queue_write", None)
        if hierarchy_record is not None:
            self._warnings.pop("hierarchy", None)
        if protected is not None or not settings.remember_password:
            self._warnings.pop("password", None)
