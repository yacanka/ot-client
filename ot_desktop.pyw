"""Double-click entry point; keep startup failures visible without a console."""
import sys


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
        startup_error("Gerekli bir Python bileşeni bulunamadı. Önce Kurulum.cmd dosyasını çalıştırın.\n\n" + str(error))
        sys.exit(1)
    try:
        main()
    except Exception as error:
        startup_error("Uygulama başlatılamadı. Dosyaların aynı klasörde ve Python kurulumunun eksiksiz olduğundan emin olun.\n\nHata türü: " + type(error).__name__)
        sys.exit(1)
