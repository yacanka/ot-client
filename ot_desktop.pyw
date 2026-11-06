"""Double-click entry point; keep startup failures visible without a console."""
import sys


def import_error_message(error):
    missing = (getattr(error, "name", None) or "").split(".")[0].casefold()
    if missing in {"otclient", "ot_app"}:
        return (
            "Uygulama dosyaları eksik veya farklı sürümlere ait. "
            "ot_desktop.pyw, otClient.py ve ot_app klasörünü aynı sürümden birlikte güncelleyin. "
            "ZIP kullanıyorsanız tamamını yeni bir klasöre çıkarın; yalnızca pyw dosyasını taşımayın."
        )
    return (
        "Gerekli bir Python bileşeni yüklenemedi. Önce Kurulum.cmd dosyasını çalıştırın, "
        "ardından Baslat.cmd ile açın. pyw dosyasına çift tıklamak farklı bir Python ortamı kullanabilir."
    )


def startup_error(message):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("OT Desktop", message, parent=root)
        root.destroy()
    except Exception:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "OT Desktop", 0x10)
        else:
            print(message, file=sys.stderr)


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        startup_error("Python 3.10 veya üzeri gerekiyor. Python 3.11+ kurduktan sonra Kurulum.cmd dosyasını çalıştırın.")
        sys.exit(1)
    try:
        from ot_app.app import main
    except ImportError as error:
        startup_error(import_error_message(error))
        sys.exit(1)
    try:
        main()
    except Exception as error:
        startup_error("Uygulama başlatılamadı. Dosyaların aynı klasörde ve Python kurulumunun eksiksiz olduğundan emin olun.\n\nHata türü: " + type(error).__name__)
        sys.exit(1)
