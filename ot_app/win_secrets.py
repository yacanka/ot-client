"""Small, typed Windows current-user DPAPI boundary; no file-based fallback."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

CRYPTPROTECT_UI_FORBIDDEN = 0x1
MAX_SECRET_BYTES = 1024 * 1024


class DPAPIError(RuntimeError):
    """Windows could not protect or recover a current-user secret."""


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class DPAPIProtector:
    """Encrypt/decrypt bytes with Windows' current-user DPAPI protection."""

    def __init__(self, *, crypt32=None, kernel32=None) -> None:
        if (crypt32 is None) != (kernel32 is None):
            raise ValueError("Her iki yerel DPAPI bağımlılığı birlikte sağlanmalıdır.")
        if crypt32 is None:
            if os.name != "nt":
                raise DPAPIError("Windows DPAPI bu işletim sisteminde kullanılamıyor.")
            crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._crypt32 = crypt32
        self._kernel32 = kernel32
        blob_pointer = ctypes.POINTER(_DataBlob)
        self._crypt32.CryptProtectData.argtypes = [
            blob_pointer,
            wintypes.LPCWSTR,
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            blob_pointer,
        ]
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.argtypes = [
            blob_pointer,
            ctypes.POINTER(wintypes.LPWSTR),
            blob_pointer,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            blob_pointer,
        ]
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        # HLOCAL is pointer-sized. Leaving the default c_int return/arguments
        # would truncate a 64-bit address when freeing DPAPI's allocated output.
        self._kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    def _transform(self, data: bytes, *, protect: bool) -> bytes:
        if not isinstance(data, bytes) or len(data) > MAX_SECRET_BYTES:
            raise DPAPIError("Parola verisi geçersiz veya izin verilen boyutu aşıyor.")
        buffer = (ctypes.c_ubyte * max(1, len(data)))()
        if data:
            ctypes.memmove(buffer, data, len(data))
        source = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
        destination = _DataBlob()
        # The local buffer must remain alive until the native call returns.
        try:
            if protect:
                success = self._crypt32.CryptProtectData(
                    ctypes.byref(source), "OT Desktop", None, None, None,
                    CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(destination),
                )
            else:
                success = self._crypt32.CryptUnprotectData(
                    ctypes.byref(source), None, None, None, None,
                    CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(destination),
                )
            if not success:
                code = ctypes.get_last_error()
                raise DPAPIError(f"Windows parola koruma işlemi başarısız (hata kodu: {code}).")
            if destination.cbData > MAX_SECRET_BYTES or (destination.cbData and not destination.pbData):
                raise DPAPIError("Windows geçersiz parola verisi döndürdü.")
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            if destination.pbData:
                self._kernel32.LocalFree(ctypes.cast(destination.pbData, ctypes.c_void_p))

    def protect(self, data: bytes) -> bytes:
        return self._transform(data, protect=True)

    def unprotect(self, data: bytes) -> bytes:
        return self._transform(data, protect=False)
