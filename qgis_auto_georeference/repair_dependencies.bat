@echo off
rem ---------------------------------------------------------------------------
rem  Auto Georeference - install / repair the Python libraries for QGIS (Windows)
rem  Authors: Radu Andrei & Claude - MIT License
rem
rem  Installs OpenCV into the Python of your QGIS, and repairs numpy if something
rem  replaced the numpy that QGIS's GDAL needs. Details: install_dependencies.py
rem
rem  Close QGIS first. Double-click this file and accept the administrator prompt
rem  (QGIS is installed in Program Files, so admin rights are needed to write there).
rem ---------------------------------------------------------------------------
setlocal

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Asking for administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set "QGISDIR="
for /d %%D in ("%ProgramFiles%\QGIS*") do if exist "%%D\bin\o4w_env.bat" (
    echo Found QGIS: "%%D"
    set "QGISDIR=%%D"
)
if not defined QGISDIR (
    echo Could not find QGIS in "%ProgramFiles%".
    echo Open the "OSGeo4W Shell" of your QGIS as administrator and run:
    echo     python "%~dp0install_dependencies.py"
    pause
    exit /b 1
)

echo.
echo Using QGIS in "%QGISDIR%"
echo Make sure QGIS is CLOSED, then press a key.
pause >nul

call "%QGISDIR%\bin\o4w_env.bat"
python "%~dp0install_dependencies.py"

echo.
echo If the last line above starts with "Done", start QGIS again.
pause
exit /b 0
