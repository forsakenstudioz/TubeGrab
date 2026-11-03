@echo off
chcp 65001 >nul
title TubeGrab
cd /d "%~dp0"

rem ---- find Python (the "py" launcher first, then python.exe) ----
set "PY="
set "PYW="
py -3 --version >nul 2>&1 && (set "PY=py -3" & set "PYW=pyw -3")
if not defined PY python --version >nul 2>&1 && (set "PY=python" & set "PYW=pythonw")
if not defined PY goto :need_python
%PY% -c "import sys; sys.exit(sys.version_info < (3, 11))" || goto :need_python
%PY% -c "import tkinter" >nul 2>&1 || goto :need_tk

rem ---- first run: install yt-dlp with its extras (includes the YouTube solver) ----
%PY% -c "import yt_dlp, yt_dlp_ejs" >nul 2>&1
if errorlevel 1 (
  echo Installing yt-dlp - this happens only once...
  %PY% -m pip install -U "yt-dlp[default]"
  if errorlevel 1 (
    echo Could not install yt-dlp. Check your internet connection and try again.
    pause
    exit /b 1
  )
)

rem ---- start the window without keeping this console open ----
start "" %PYW% tubegrab.py
exit /b 0

:need_python
echo Python 3.11 or newer is needed.
echo Install it with:  winget install Python.Python.3.12
echo   or from https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
pause
exit /b 1

:need_tk
echo Your Python is missing Tkinter ^(the window toolkit^).
echo Re-run the Python installer, choose "Modify" and tick "tcl/tk and IDLE".
pause
exit /b 1
