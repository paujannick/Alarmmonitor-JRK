@echo off
setlocal
cd /d "%~dp0"

echo [Alarmmonitor] Windows-Installation wird gestartet ...

where py >nul 2>nul
if %errorlevel%==0 (
  set "PYTHON_CMD=py -3"
) else (
  where python >nul 2>nul
  if %errorlevel%==0 (
    set "PYTHON_CMD=python"
  ) else (
    echo [FEHLER] Python wurde nicht gefunden.
    echo Bitte Python 3 installieren und die Option "Add python.exe to PATH" aktivieren.
    goto error
  )
)

if not exist "venv\Scripts\python.exe" (
  echo [Alarmmonitor] Erstelle virtuelle Umgebung ...
  %PYTHON_CMD% -m venv venv
  if errorlevel 1 goto error
)

echo [Alarmmonitor] Aktualisiere pip ...
"venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto error

echo [Alarmmonitor] Installiere Abhaengigkeiten ...
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto error

echo.
echo [Alarmmonitor] Installation abgeschlossen.
echo Starte den Alarmmonitor zukuenftig mit start_windows.bat.
pause
exit /b 0

:error
echo.
echo [FEHLER] Die Installation wurde abgebrochen. Die Meldung oben bleibt sichtbar.
pause
exit /b 1
