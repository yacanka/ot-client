@echo off
setlocal
cd /d "%~dp0"
echo OT Desktop kurulumu

echo Uygulama klasorunde yerel Python ortami hazirlaniyor...
if exist ".venv\Scripts\python.exe" goto install

py -3.11 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 (
    py -3.11 -m venv .venv
    goto checkenv
)
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv
    goto checkenv
)
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 (
    python -m venv .venv
    goto checkenv
)
echo [HATA] Python 3.10 veya uzeri bulunamadi. Python 3.11+ kurup tekrar deneyin.
echo Python kurulurken Tcl/Tk ve Python Launcher seceneklerini etkin birakin.
pause
exit /b 1

:checkenv
if not exist ".venv\Scripts\python.exe" (
    echo [HATA] Python ortami olusturulamadi. Bu klasore yazma izniniz oldugunu kontrol edin.
    pause
    exit /b 1
)

:install
".venv\Scripts\python.exe" -c "import sys, tkinter; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 (
    echo [HATA] Python 3.10+ ve Tcl/Tk gerekiyor. Mevcut .venv klasorunu kontrol edin.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [HATA] Paket kurulumu tamamlanamadi. Internet veya kurum paket deposu ayarlarini kontrol edin.
    echo Alternatif kurulum adimlari README.md dosyasindadir.
    pause
    exit /b 1
)
echo.
echo Kurulum tamamlandi. Uygulamayi Baslat.cmd ile acabilirsiniz.
pause
