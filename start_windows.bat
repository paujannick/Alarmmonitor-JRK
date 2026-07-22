@echo off
setlocal
cd /d "%~dp0"

echo [Alarmmonitor] Starte Windows-Version ...

if not exist "venv\Scripts\python.exe" (
  echo [FEHLER] Virtuelle Umgebung nicht gefunden.
  echo Bitte zuerst install_windows.bat ausfuehren.
  goto error
)

if not exist "data" mkdir "data"

set "FLASK_APP=app.py"
set "FLASK_RUN_HOST=0.0.0.0"
set "FLASK_RUN_PORT=5000"

echo [Alarmmonitor] Adresse lokal: http://localhost:5000/
echo [Alarmmonitor] Zum Beenden dieses Fenster schliessen oder STRG+C druecken.
echo.
"venv\Scripts\python.exe" -m flask run --host=%FLASK_RUN_HOST% --port=%FLASK_RUN_PORT%
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo [FEHLER] Alarmmonitor wurde mit Fehlercode %EXIT_CODE% beendet.
  echo Die Fehlermeldung oben bleibt sichtbar, damit sie ausgelesen werden kann.
  goto error_with_code
)

echo.
echo [Alarmmonitor] Alarmmonitor wurde beendet.
pause
exit /b 0

:error
pause
exit /b 1

:error_with_code
pause
exit /b %EXIT_CODE%
