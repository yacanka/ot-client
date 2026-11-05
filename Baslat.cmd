@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo [BILGI] Ilk kullanimdan once Kurulum.cmd dosyasini calistirin.
    echo Mevcut Python ortaminizi kullanmak icin: python ot_desktop.pyw
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -c "import requests, tkinter" >nul 2>&1
if errorlevel 1 (
    echo [HATA] Gerekli bilesenler bulunamadi. Kurulum.cmd dosyasini tekrar calistirin.
    pause
    exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0ot_desktop.pyw"
