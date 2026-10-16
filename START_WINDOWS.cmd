@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto missing_python
if exist ".venv\Scripts\python.exe" goto install_dependencies
py -3 -m venv .venv
if errorlevel 1 goto failed
:install_dependencies
echo Installing the archive reader into this folder. Internet access is needed.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --no-input -r requirements-archive.txt
if errorlevel 1 goto failed
echo Choose the downloaded Brent Parquet file in the file dialog.
".venv\Scripts\python.exe" run_windows.py
if errorlevel 1 goto failed
pause
exit /b 0
:missing_python
echo Python launcher was not found.
echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
echo Include the Python launcher during installation, then run this file again.
pause
exit /b 1
:failed
echo The operation stopped. Read the error above; your source file was not changed.
pause
exit /b 1
